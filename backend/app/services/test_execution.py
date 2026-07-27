import subprocess
import tempfile
import time
from pathlib import Path

from app.schemas.test_execution import (
    ExecutionTestCase,
    ExecutionTestResult,
    RunTestsResponse,
)
from app.services.compiler import (
    COMPILER_EXECUTABLE,
    COMPILE_TIMEOUT_SECONDS,
    CompilerServiceError,
)

TEST_TIMEOUT_SECONDS = 2
TEST_OUTPUT_LIMIT_BYTES = 64 * 1024
OUTPUT_LIMIT_MESSAGE = "\n[Output limited to 64 KiB.]"
FUNCTION_ONLY_MESSAGE = (
    "Test execution currently requires a complete runnable program with main()."
)


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


def _is_missing_main_error(stderr: str) -> bool:
    message = stderr.lower()
    return (
        "undefined reference to `main'" in message
        or "undefined reference to 'main'" in message
        or (
            "undefined symbols for architecture" in message
            and '"_main"' in message
        )
    )


def _run_test(
    executable: Path,
    working_directory: Path,
    test: ExecutionTestCase,
    *,
    timeout_seconds: float,
) -> ExecutionTestResult:
    stdin_path = working_directory / "test-input.txt"
    stdout_path = working_directory / "test-stdout.txt"
    stderr_path = working_directory / "test-stderr.txt"
    stdin_path.write_bytes(test.stdin.encode("utf-8"))

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
        actual_stdout, stdout_limited = _limit_bytes(
            stdout_file.read(TEST_OUTPUT_LIMIT_BYTES + 1)
        )
        stderr, stderr_limited = _limit_bytes(
            stderr_file.read(TEST_OUTPUT_LIMIT_BYTES + 1)
        )

    output_limited = output_limited or stdout_limited or stderr_limited
    match_type = _classify_output_match(
        test.expected_stdout,
        actual_stdout,
    )
    passed = (
        not timed_out
        and not output_limited
        and exit_code == 0
        and match_type != "mismatch"
    )
    return ExecutionTestResult(
        name=test.name,
        passed=passed,
        expected_stdout=test.expected_stdout,
        actual_stdout=actual_stdout,
        stderr=stderr,
        exit_code=None if timed_out else exit_code,
        timed_out=timed_out,
        output_limited=output_limited,
        match_type=match_type,
    )


def run_cpp_tests(
    code: str,
    tests: list[ExecutionTestCase],
    *,
    compiler: str = COMPILER_EXECUTABLE,
    compile_timeout_seconds: int = COMPILE_TIMEOUT_SECONDS,
    test_timeout_seconds: float = TEST_TIMEOUT_SECONDS,
) -> RunTestsResponse:
    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-tests-") as directory:
            working_directory = Path(directory)
            source_path = working_directory / "main.cpp"
            executable_path = working_directory / "program"
            source_path.write_bytes(code.encode("utf-8"))

            compile_command = [
                compiler,
                "-std=c++17",
                "main.cpp",
                "-o",
                "program",
            ]
            completed = subprocess.run(
                compile_command,
                cwd=working_directory,
                capture_output=True,
                timeout=compile_timeout_seconds,
                check=False,
                shell=False,
            )
            compile_stdout, _ = _limit_bytes(completed.stdout)
            compile_stderr, _ = _limit_bytes(completed.stderr)
            compiler_output = compile_stderr or compile_stdout

            if completed.returncode != 0:
                compile_error = (
                    FUNCTION_ONLY_MESSAGE
                    if _is_missing_main_error(compiler_output)
                    else compiler_output
                    or "The compiler failed without producing diagnostic output."
                )
                return RunTestsResponse(
                    success=False,
                    compile_error=compile_error,
                    tests=[],
                )

            results = [
                _run_test(
                    executable_path,
                    working_directory,
                    test,
                    timeout_seconds=test_timeout_seconds,
                )
                for test in tests
            ]
            return RunTestsResponse(
                success=all(result.passed for result in results),
                compile_error=None,
                tests=results,
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
