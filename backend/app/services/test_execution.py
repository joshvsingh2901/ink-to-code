import ctypes
import math
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.schemas.test_execution import (
    FunctionResponse,
    FunctionRunTestsRequest,
    FunctionTestResult,
    ProgramRunTestsRequest,
    ProgramTestCase,
    ProgramTestResult,
    RunTestsRequest,
    RunTestsResponse,
)
from app.services.compiler import (
    COMPILER_EXECUTABLE,
    COMPILE_TIMEOUT_SECONDS,
    CompilerServiceError,
)
from app.services.function_analysis import (
    FunctionAnalysis,
    FunctionSignature,
    analyze_test_mode,
)

TEST_TIMEOUT_SECONDS = 2
TEST_OUTPUT_LIMIT_BYTES = 64 * 1024
OUTPUT_LIMIT_MESSAGE = "\n[Output limited to 64 KiB.]"
DOUBLE_OUTPUT_PRECISION = 17
_INTEGER_VALUE = re.compile(r"[+-]?\d+")
_DOUBLE_VALUE = re.compile(
    r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?"
)


@dataclass(frozen=True)
class ProcessOutput:
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool


def _limit_bytes(output: bytes) -> tuple[str, bool]:
    limited = len(output) > TEST_OUTPUT_LIMIT_BYTES
    content = output[:TEST_OUTPUT_LIMIT_BYTES].decode("utf-8", errors="replace")
    return (
        content + OUTPUT_LIMIT_MESSAGE if limited else content,
        limited,
    )


def _classify_output_match(expected: str, actual: str) -> str:
    if expected == actual:
        return "exact"
    if expected.split() == actual.split():
        return "whitespace_normalized"
    return "mismatch"


def _function_response(signature: FunctionSignature) -> FunctionResponse:
    return FunctionResponse(
        id=signature.id,
        name=signature.name,
        return_type=signature.return_type,
        parameters=[
            {"name": parameter.name, "type": parameter.type}
            for parameter in signature.parameters
        ],
        display=signature.display,
    )


def _run_process(
    executable: Path,
    working_directory: Path,
    stdin: str,
    *,
    timeout_seconds: float,
) -> ProcessOutput:
    stdin_path = working_directory / "test-input.txt"
    stdout_path = working_directory / "test-stdout.txt"
    stderr_path = working_directory / "test-stderr.txt"
    stdin_path.write_bytes(stdin.encode("utf-8"))
    timed_out = False
    output_limited = False

    with (
        stdin_path.open("rb") as stdin_file,
        stdout_path.open("w+b") as stdout_file,
        stderr_path.open("w+b") as stderr_file,
    ):
        process = subprocess.Popen(
            [str(executable)],
            cwd=working_directory,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
        )
        deadline = time.monotonic() + timeout_seconds

        while process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                break
            if (
                stdout_path.stat().st_size > TEST_OUTPUT_LIMIT_BYTES
                or stderr_path.stat().st_size > TEST_OUTPUT_LIMIT_BYTES
            ):
                output_limited = True
                process.kill()
                break
            time.sleep(0.01)

        exit_code = process.wait()
        stdout_file.flush()
        stderr_file.flush()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout, stdout_limited = _limit_bytes(
            stdout_file.read(TEST_OUTPUT_LIMIT_BYTES + 1)
        )
        stderr, stderr_limited = _limit_bytes(
            stderr_file.read(TEST_OUTPUT_LIMIT_BYTES + 1)
        )

    return ProcessOutput(
        stdout=stdout,
        stderr=stderr,
        exit_code=None if timed_out else exit_code,
        timed_out=timed_out,
        output_limited=output_limited or stdout_limited or stderr_limited,
    )


def _compile_executable(
    working_directory: Path,
    *,
    compiler: str,
    timeout_seconds: int,
) -> str | None:
    command = [compiler, "-std=c++17", "main.cpp", "-o", "program"]
    completed = subprocess.run(
        command,
        cwd=working_directory,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    stdout, _ = _limit_bytes(completed.stdout)
    stderr, _ = _limit_bytes(completed.stderr)
    if completed.returncode == 0:
        return None
    return stderr or stdout or "The compiler failed without diagnostic output."


def _integer_bounds(c_type: type[ctypes._SimpleCData]) -> tuple[int, int]:
    bits = ctypes.sizeof(c_type) * 8
    return -(2 ** (bits - 1)), 2 ** (bits - 1) - 1


def _safe_literal(type_name: str, raw_value: str, label: str) -> str:
    value = raw_value.strip()
    if type_name == "bool":
        if value not in {"true", "false"}:
            raise ValueError(f"{label} must be true or false.")
        return value

    if type_name in {"int", "long", "long long"}:
        if not _INTEGER_VALUE.fullmatch(value):
            raise ValueError(f"{label} must be a signed decimal {type_name} value.")
        parsed = int(value)
        c_type = {
            "int": ctypes.c_int,
            "long": ctypes.c_long,
            "long long": ctypes.c_longlong,
        }[type_name]
        minimum, maximum = _integer_bounds(c_type)
        if not minimum <= parsed <= maximum:
            raise ValueError(f"{label} is outside the supported {type_name} range.")
        suffix = {"int": "", "long": "L", "long long": "LL"}[type_name]
        if parsed == minimum:
            return f"(-{maximum}{suffix} - 1{suffix})"
        return f"{parsed}{suffix}"

    if type_name == "double":
        if not _DOUBLE_VALUE.fullmatch(value):
            raise ValueError(f"{label} must be a finite decimal double value.")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"{label} must be a finite decimal double value.")
        literal = repr(parsed)
        if "." not in literal and "e" not in literal.lower():
            literal += ".0"
        return literal

    raise ValueError(f"{label} uses an unsupported type.")


def _build_function_harness(
    code: str,
    function: FunctionSignature,
    argument_literals: list[list[str]],
) -> str:
    cases: list[str] = []
    for index, literals in enumerate(argument_literals):
        call = f"{function.name}({', '.join(literals)})"
        if function.return_type == "bool":
            output = f"std::cout << std::boolalpha << {call};"
        elif function.return_type == "double":
            output = (
                f"std::cout << std::setprecision({DOUBLE_OUTPUT_PRECISION}) "
                f"<< {call};"
            )
        else:
            output = f"std::cout << {call};"
        cases.append(f"case {index}: {{ {output} return 0; }}")

    generated_main = "\n".join(
        [
            "int main()",
            "{",
            "    int inktocode_test_index = -1;",
            "    if (!(std::cin >> inktocode_test_index)) return 2;",
            "    switch (inktocode_test_index)",
            "    {",
            *[f"        {case}" for case in cases],
            "        default: return 3;",
            "    }",
            "}",
        ]
    )
    return (
        "#include <iomanip>\n"
        "#include <iostream>\n\n"
        f"{code}\n\n"
        f"{generated_main}\n"
    )


def _program_results(
    executable: Path,
    working_directory: Path,
    request: ProgramRunTestsRequest,
    *,
    timeout_seconds: float,
) -> list[ProgramTestResult]:
    results: list[ProgramTestResult] = []
    for test in request.tests:
        output = _run_process(
            executable,
            working_directory,
            test.stdin,
            timeout_seconds=timeout_seconds,
        )
        match_type = _classify_output_match(
            test.expected_stdout,
            output.stdout,
        )
        passed = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and match_type != "mismatch"
        )
        results.append(
            ProgramTestResult(
                name=test.name,
                passed=passed,
                expected_stdout=test.expected_stdout,
                actual_stdout=output.stdout,
                stderr=output.stderr,
                exit_code=output.exit_code,
                timed_out=output.timed_out,
                output_limited=output.output_limited,
                match_type=match_type,
            )
        )
    return results


def _function_results(
    executable: Path,
    working_directory: Path,
    request: FunctionRunTestsRequest,
    *,
    timeout_seconds: float,
) -> list[FunctionTestResult]:
    results: list[FunctionTestResult] = []
    for index, test in enumerate(request.tests):
        output = _run_process(
            executable,
            working_directory,
            f"{index}\n",
            timeout_seconds=timeout_seconds,
        )
        match_type = _classify_output_match(
            test.expected_return,
            output.stdout,
        )
        passed = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and match_type != "mismatch"
        )
        results.append(
            FunctionTestResult(
                name=test.name,
                passed=passed,
                arguments=test.arguments,
                expected_return=test.expected_return,
                actual_return=output.stdout,
                stderr=output.stderr,
                exit_code=output.exit_code,
                timed_out=output.timed_out,
                output_limited=output.output_limited,
                match_type=match_type,
            )
        )
    return results


def _unsupported_response(analysis: FunctionAnalysis) -> RunTestsResponse:
    return RunTestsResponse(
        mode="unsupported",
        success=False,
        unsupported_error=analysis.message
        or "Function testing is unavailable for this source.",
        tests=[],
    )


def run_test_request(
    request: RunTestsRequest,
    *,
    compiler: str = COMPILER_EXECUTABLE,
    compile_timeout_seconds: int = COMPILE_TIMEOUT_SECONDS,
    test_timeout_seconds: float = TEST_TIMEOUT_SECONDS,
) -> RunTestsResponse:
    analysis = analyze_test_mode(request.code)
    if analysis.mode == "unsupported":
        return _unsupported_response(analysis)
    if request.mode != analysis.mode:
        return RunTestsResponse(
            mode=analysis.mode,
            success=False,
            input_error="The source execution mode changed. Review the tests and retry.",
            tests=[],
        )

    argument_literals: list[list[str]] = []
    function = None
    if isinstance(request, FunctionRunTestsRequest):
        function = next(
            (
                candidate
                for candidate in analysis.functions
                if candidate.id == request.target_function
            ),
            None,
        )
        if function is None:
            return RunTestsResponse(
                mode="function",
                success=False,
                input_error=(
                    "The selected function is no longer available. "
                    "Choose a detected function and retry."
                ),
                tests=[],
            )
        for test in request.tests:
            if len(test.arguments) != len(function.parameters):
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=(
                        f"{test.name} requires {len(function.parameters)} "
                        f"argument(s), but {len(test.arguments)} were provided."
                    ),
                    function=_function_response(function),
                    tests=[],
                )
            try:
                literals = [
                    _safe_literal(
                        parameter.type,
                        argument,
                        f"{test.name} argument {parameter.name}",
                    )
                    for parameter, argument in zip(
                        function.parameters,
                        test.arguments,
                        strict=True,
                    )
                ]
                _safe_literal(
                    function.return_type,
                    test.expected_return,
                    f"{test.name} expected return",
                )
            except ValueError as error:
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=str(error),
                    function=_function_response(function),
                    tests=[],
                )
            argument_literals.append(literals)

    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-tests-") as directory:
            working_directory = Path(directory)
            executable = working_directory / "program"
            source = (
                _build_function_harness(request.code, function, argument_literals)
                if isinstance(request, FunctionRunTestsRequest)
                and function is not None
                else request.code
            )
            (working_directory / "main.cpp").write_bytes(source.encode("utf-8"))
            compile_error = _compile_executable(
                working_directory,
                compiler=compiler,
                timeout_seconds=compile_timeout_seconds,
            )
            if compile_error is not None:
                return RunTestsResponse(
                    mode=request.mode,
                    success=False,
                    compile_error=compile_error,
                    function=(
                        _function_response(function)
                        if function is not None
                        else None
                    ),
                    tests=[],
                )

            if isinstance(request, ProgramRunTestsRequest):
                results = _program_results(
                    executable,
                    working_directory,
                    request,
                    timeout_seconds=test_timeout_seconds,
                )
                return RunTestsResponse(
                    mode="program",
                    success=all(result.passed for result in results),
                    tests=results,
                )

            function_results = _function_results(
                executable,
                working_directory,
                request,
                timeout_seconds=test_timeout_seconds,
            )
            return RunTestsResponse(
                mode="function",
                success=all(result.passed for result in function_results),
                function=_function_response(function),
                tests=function_results,
            )
    except FileNotFoundError as error:
        raise CompilerServiceError(
            "compiler_unavailable",
            "The C++ compiler is unavailable on the backend.",
            503,
        ) from error
    except subprocess.TimeoutExpired as error:
        raise CompilerServiceError(
            "compiler_timeout",
            "Compiling the runnable test program exceeded the time limit.",
            504,
        ) from error
    except (OSError, subprocess.SubprocessError) as error:
        raise CompilerServiceError(
            "test_execution_failed",
            "The backend could not compile or run the tests.",
            500,
        ) from error


def run_cpp_tests(
    code: str,
    tests: list[ProgramTestCase],
    *,
    compiler: str = COMPILER_EXECUTABLE,
    compile_timeout_seconds: int = COMPILE_TIMEOUT_SECONDS,
    test_timeout_seconds: float = TEST_TIMEOUT_SECONDS,
) -> RunTestsResponse:
    return run_test_request(
        ProgramRunTestsRequest(
            mode="program",
            code=code,
            language="cpp",
            tests=tests,
        ),
        compiler=compiler,
        compile_timeout_seconds=compile_timeout_seconds,
        test_timeout_seconds=test_timeout_seconds,
    )
