import ctypes
import json
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.schemas.test_execution import (
    FunctionResponse,
    FunctionChannelResult,
    FunctionCombinedTestResult,
    FunctionMutationChannelResult,
    FunctionRunTestsRequest,
    FunctionTestCase,
    FunctionMutationTestResult,
    ObjectScenarioRunTestsRequest,
    ObjectScenarioStepResult,
    ObjectScenarioTestResult,
    FunctionOutputTestResult,
    FunctionTestResult,
    FunctionTypeResponse,
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
from app.services.big_five_diagnosis import diagnose_big_five
from app.services.execution_providers import (
    DockerExecutionResult,
    DockerExecutionProvider,
    ProviderCapabilities,
    select_memory_provider,
)
from app.services.function_analysis import (
    FunctionAnalysis,
    FunctionSignature,
    STRING_TYPE,
    ValueType,
    analyze_test_mode,
)
from app.services.object_analysis import (
    ObjectClass,
    ObjectConstructor,
    ObjectMethod,
    ObjectOperator,
    ObjectSpecialMember,
    analyze_object_scenarios,
)

TEST_TIMEOUT_SECONDS = 2
TEST_OUTPUT_LIMIT_BYTES = 64 * 1024
OUTPUT_LIMIT_MESSAGE = "\n[Output limited to 64 KiB.]"
SANITIZER_COMPILE_FLAGS = (
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
    "-g",
)
SANITIZER_ENVIRONMENT = {
    "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
}
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
    function_stdout: str = ""
    result_metadata: str | None = None
    step_stdout: tuple[str, ...] = ()
    step_metadata: tuple[str | None, ...] = ()
    progress_index: int | None = None
    memory_status: str = "not_run"
    memory_summary: str | None = None
    memory_diagnostics: str | None = None
    address_sanitizer_available: bool | None = None
    undefined_behavior_sanitizer_available: bool | None = None
    leak_sanitizer_available: bool | None = None
    memory_access_status: str = "not_run"
    undefined_behavior_status: str = "not_run"
    leak_status: str = "not_run"
    execution_provider: str = "host"
    memory_tool: str = "none"
    container_runtime_available: bool | None = None
    leaked_bytes: int | None = None
    leaked_allocations: int | None = None
    leak_kind: str | None = None
    infrastructure_error: str | None = None


@dataclass(frozen=True)
class SanitizerCapabilities:
    address_sanitizer_available: bool
    undefined_behavior_sanitizer_available: bool
    leak_sanitizer_available: bool


@dataclass(frozen=True)
class HarnessArgument:
    expression: str
    declarations: tuple[str, ...] = ()
    array_element_count: int | None = None
    mutation_expression: str | None = None


@dataclass(frozen=True)
class PreparedObjectStep:
    method: ObjectMethod | None
    arguments: tuple[HarnessArgument, ...]
    target_object_id: str
    operator: ObjectOperator | None = None
    operand_expressions: tuple[str, ...] = ()
    result_object_id: str | None = None
    result_name: str | None = None
    expression: str = ""
    special_member: ObjectSpecialMember | None = None
    source_object_id: str | None = None
    step_type: str = "method"
    result_object_class_id: str | None = None


@dataclass(frozen=True)
class PreparedScenarioObject:
    object_id: str
    name: str
    object_class: ObjectClass
    constructor: ObjectConstructor
    constructor_arguments: tuple[HarnessArgument, ...]


@dataclass(frozen=True)
class PreparedObjectScenario:
    objects: tuple[PreparedScenarioObject, ...]
    steps: tuple[PreparedObjectStep, ...]


def _limit_bytes(output: bytes) -> tuple[str, bool]:
    limited = len(output) > TEST_OUTPUT_LIMIT_BYTES
    content = output[:TEST_OUTPUT_LIMIT_BYTES].decode("utf-8", errors="replace")
    return (
        content + OUTPUT_LIMIT_MESSAGE if limited else content,
        limited,
    )


def _file_exceeds_limit(path: Path) -> bool:
    try:
        return path.stat().st_size > TEST_OUTPUT_LIMIT_BYTES
    except FileNotFoundError:
        return False


def _classify_output_match(expected: str, actual: str) -> str:
    if expected == actual:
        return "exact"
    if expected.split() == actual.split():
        return "whitespace_normalized"
    return "mismatch"


def _classify_program_output_match(
    expected: str,
    actual: str,
    comparison_mode: str,
) -> str:
    if comparison_mode == "whitespace_tolerant":
        return _classify_output_match(expected, actual)

    normalized_expected = expected.replace("\r\n", "\n")
    normalized_actual = actual.replace("\r\n", "\n")
    if normalized_expected == normalized_actual:
        return "exact"
    if normalized_expected.split() == normalized_actual.split():
        return "formatting_mismatch"
    return "mismatch"


def _expected_mutations(test: FunctionTestCase) -> dict[str, str] | None:
    if test.expected_mutations is not None:
        names = [
            expectation.parameter_id
            for expectation in test.expected_mutations
        ]
        if len(names) != len(set(names)):
            raise ValueError(
                f"{test.name} contains a duplicate mutation parameter."
            )
        return {
            expectation.parameter_id: expectation.expected_final_value
            for expectation in test.expected_mutations
        }
    return test.expected_final_arguments


def _function_response(signature: FunctionSignature) -> FunctionResponse:
    def type_response(value_type: ValueType) -> FunctionTypeResponse:
        return FunctionTypeResponse(
            kind=value_type.kind,
            display_type=value_type.display_type,
            scalar_type=value_type.scalar_type,
            element_type=value_type.element_type,
            vector_depth=value_type.vector_depth,
            passing=value_type.passing,
            size_parameter_name=value_type.size_parameter_name,
        )

    return FunctionResponse(
        id=signature.id,
        name=signature.name,
        return_type=signature.return_type,
        parameters=[
            {
                "name": parameter.name,
                "type": parameter.type,
                "type_metadata": type_response(parameter.value_type),
            }
            for parameter in signature.parameters
        ],
        display=signature.display,
        return_type_metadata=type_response(signature.return_value_type),
    )


def _run_process(
    executable: Path,
    working_directory: Path,
    stdin: str,
    *,
    timeout_seconds: float,
    run_memory_checks: bool = False,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    docker_provider: DockerExecutionProvider | None = None,
) -> ProcessOutput:
    stdin_path = working_directory / "test-input.txt"
    stdout_path = working_directory / "test-stdout.txt"
    stderr_path = working_directory / "test-stderr.txt"
    function_stdout_path = working_directory / "function-stdout.txt"
    result_path = working_directory / "function-result.json"
    result_temp_path = working_directory / "function-result.json.tmp"
    object_progress_path = working_directory / "object-progress.txt"
    object_constructor_stdout_path = (
        working_directory / "object-constructor-stdout.txt"
    )
    object_step_stdout_paths = tuple(
        working_directory / f"object-step-{index}-stdout.txt"
        for index in range(20)
    )
    object_step_result_paths = tuple(
        working_directory / f"object-step-{index}-result.json"
        for index in range(20)
    )
    result_path.unlink(missing_ok=True)
    function_stdout_path.unlink(missing_ok=True)
    object_progress_path.unlink(missing_ok=True)
    object_constructor_stdout_path.unlink(missing_ok=True)
    for path in (*object_step_stdout_paths, *object_step_result_paths):
        path.unlink(missing_ok=True)
    if docker_provider is not None:
        docker_result = docker_provider.compile_and_run(
            working_directory,
            stdin,
            timeout_seconds=timeout_seconds,
        )
        return _docker_process_output(
            docker_result,
            docker_provider.capabilities(),
            working_directory,
        )
    stdin_path.write_bytes(stdin.encode("utf-8"))
    timed_out = False
    output_limited = False

    with (
        stdin_path.open("rb") as stdin_file,
        stdout_path.open("w+b") as stdout_file,
        stderr_path.open("w+b") as stderr_file,
    ):
        child_environment = None
        if run_memory_checks:
            child_environment = os.environ.copy()
            child_environment.update(
                _sanitizer_environment(
                    leak_detection_enabled=bool(
                        sanitizer_capabilities
                        and sanitizer_capabilities.leak_sanitizer_available
                    )
                )
            )
        process = subprocess.Popen(
            [str(executable)],
            cwd=working_directory,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            env=child_environment,
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
                or (
                    _file_exceeds_limit(function_stdout_path)
                )
                or (
                    _file_exceeds_limit(result_temp_path)
                )
                or (
                    _file_exceeds_limit(result_path)
                )
                or _file_exceeds_limit(object_constructor_stdout_path)
                or any(
                    _file_exceeds_limit(path)
                    for path in (
                        *object_step_stdout_paths,
                        *object_step_result_paths,
                    )
                )
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

    function_stdout = ""
    if function_stdout_path.exists():
        function_stdout, function_limited = _limit_bytes(
            function_stdout_path.read_bytes()[: TEST_OUTPUT_LIMIT_BYTES + 1]
        )
        output_limited = output_limited or function_limited
    metadata_limited = (
        (result_path.exists() and result_path.stat().st_size > TEST_OUTPUT_LIMIT_BYTES)
        or (
            result_temp_path.exists()
            and result_temp_path.stat().st_size > TEST_OUTPUT_LIMIT_BYTES
        )
    )
    output_limited = output_limited or metadata_limited
    step_stdout = tuple(
        (
            _limit_bytes(
                path.read_bytes()[: TEST_OUTPUT_LIMIT_BYTES + 1]
            )[0]
            if path.exists()
            else ""
        )
        for path in object_step_stdout_paths
    )
    step_metadata = tuple(
        (
            path.read_text(encoding="utf-8", errors="replace")
            if path.exists() and not _file_exceeds_limit(path)
            else None
        )
        for path in object_step_result_paths
    )
    progress_index = None
    if object_progress_path.exists():
        try:
            progress_index = int(
                object_progress_path.read_text(encoding="utf-8").strip()
            )
        except ValueError:
            progress_index = None
    memory_status, memory_summary, memory_diagnostics = (
        _classify_memory_diagnostics(
            stderr,
            working_directory,
            exit_code=None if timed_out else exit_code,
            timed_out=timed_out,
        )
        if run_memory_checks
        else ("not_run", None, None)
    )
    (
        memory_access_status,
        undefined_behavior_status,
        leak_status,
    ) = _sanitizer_channel_statuses(
        memory_status,
        sanitizer_capabilities,
        run_memory_checks,
    )
    if (
        run_memory_checks
        and memory_status == "clean"
        and leak_status == "unavailable"
    ):
        memory_status = "partial"
        memory_summary = (
            "Memory access and undefined-behaviour checks passed, but "
            "leaks could not be checked with the current compiler runtime."
        )
    return ProcessOutput(
        stdout=stdout,
        stderr=stderr,
        exit_code=None if timed_out else exit_code,
        timed_out=timed_out,
        output_limited=output_limited or stdout_limited or stderr_limited,
        function_stdout=function_stdout,
        result_metadata=(
            result_path.read_text(encoding="utf-8", errors="replace")
            if result_path.exists() and not metadata_limited
            else None
        ),
        step_stdout=step_stdout,
        step_metadata=step_metadata,
        progress_index=progress_index,
        memory_status=memory_status,
        memory_summary=memory_summary,
        memory_diagnostics=memory_diagnostics,
        address_sanitizer_available=(
            sanitizer_capabilities.address_sanitizer_available
            if sanitizer_capabilities
            else None
        ),
        undefined_behavior_sanitizer_available=(
            sanitizer_capabilities.undefined_behavior_sanitizer_available
            if sanitizer_capabilities
            else None
        ),
        leak_sanitizer_available=(
            sanitizer_capabilities.leak_sanitizer_available
            if sanitizer_capabilities
            else None
        ),
        memory_access_status=memory_access_status,
        undefined_behavior_status=undefined_behavior_status,
        leak_status=leak_status,
        execution_provider="host",
        memory_tool="sanitizer" if run_memory_checks else "none",
        container_runtime_available=False if run_memory_checks else None,
    )


def _docker_process_output(
    result: DockerExecutionResult,
    capabilities: ProviderCapabilities,
    working_directory: Path,
) -> ProcessOutput:
    if result.infrastructure_error:
        return ProcessOutput(
            stdout="",
            stderr="",
            exit_code=None,
            timed_out=result.timed_out,
            output_limited=False,
            memory_status="unavailable",
            memory_summary=result.infrastructure_error,
            address_sanitizer_available=(
                capabilities.address_sanitizer_available
            ),
            undefined_behavior_sanitizer_available=(
                capabilities.undefined_behavior_sanitizer_available
            ),
            leak_sanitizer_available=(
                capabilities.leak_sanitizer_available
                or capabilities.valgrind_available
            ),
            memory_access_status="unavailable",
            undefined_behavior_status="unavailable",
            leak_status="unavailable",
            execution_provider="docker",
            container_runtime_available=True,
            infrastructure_error=result.infrastructure_error,
        )
    sanitizer_status, summary, diagnostics = _classify_memory_diagnostics(
        result.stderr,
        working_directory,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
    )
    leak_status = (
        "clean"
        if capabilities.leak_sanitizer_available
        or capabilities.valgrind_available
        else "unavailable"
    )
    if result.leak_kind in {"definite", "indirect"}:
        sanitizer_status = "leak"
        leak_status = "failed"
        summary = "Memory leak detected."
        diagnostics = _clean_memory_diagnostics(
            result.valgrind_diagnostics or result.stderr,
            working_directory,
        )
    elif result.leak_kind == "possible":
        sanitizer_status = "partial"
        leak_status = "possible"
        summary = (
            "Valgrind reported a possible leak that could not be confirmed."
        )
        diagnostics = _clean_memory_diagnostics(
            result.valgrind_diagnostics or "",
            working_directory,
        )
    elif result.leak_kind == "invalid_memory":
        sanitizer_status = "runtime_error"
        summary = "Valgrind detected invalid memory access."
        diagnostics = _clean_memory_diagnostics(
            result.valgrind_diagnostics or "",
            working_directory,
        )
    access_status, undefined_status, classified_leak_status = (
        _sanitizer_channel_statuses(
            sanitizer_status,
            SanitizerCapabilities(
                capabilities.address_sanitizer_available,
                capabilities.undefined_behavior_sanitizer_available,
                capabilities.leak_sanitizer_available
                or capabilities.valgrind_available,
            ),
            True,
        )
    )
    if result.leak_kind is not None:
        classified_leak_status = leak_status
    elif leak_status == "unavailable":
        classified_leak_status = "unavailable"
        if sanitizer_status == "clean":
            sanitizer_status = "partial"
            summary = (
                "Memory access and undefined-behaviour checks passed, but "
                "leaks could not be checked in the isolated runner."
            )
    return ProcessOutput(
        stdout=_redact_container_paths(result.stdout),
        stderr=_redact_container_paths(result.stderr),
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        output_limited=result.output_limited,
        function_stdout=result.function_stdout,
        result_metadata=result.result_metadata,
        step_stdout=result.step_stdout,
        step_metadata=result.step_metadata,
        progress_index=result.progress_index,
        memory_status=sanitizer_status,
        memory_summary=summary,
        memory_diagnostics=(
            _redact_container_paths(diagnostics) if diagnostics else None
        ),
        address_sanitizer_available=(
            capabilities.address_sanitizer_available
        ),
        undefined_behavior_sanitizer_available=(
            capabilities.undefined_behavior_sanitizer_available
        ),
        leak_sanitizer_available=(
            capabilities.leak_sanitizer_available
            or capabilities.valgrind_available
        ),
        memory_access_status=access_status,
        undefined_behavior_status=undefined_status,
        leak_status=classified_leak_status,
        execution_provider="docker",
        memory_tool=result.memory_tool,
        container_runtime_available=True,
        leaked_bytes=result.leaked_bytes,
        leaked_allocations=result.leaked_allocations,
        leak_kind=result.leak_kind,
        infrastructure_error=result.infrastructure_error,
    )


def _redact_container_paths(value: str) -> str:
    return value.replace("/work/main.cpp", "solution.cpp").replace(
        "/work/program", "program"
    ).replace("/work/", "")


def _clean_memory_diagnostics(
    diagnostics: str,
    working_directory: Path,
) -> str:
    cleaned = diagnostics.replace(str(working_directory), "<temporary>")
    cleaned = re.sub(
        r"/(?:private/)?(?:var|tmp)/[^\\s:]+/inktocode-tests-[^\\s:]*",
        "<temporary>",
        cleaned,
    )
    encoded = cleaned.encode("utf-8")
    return _limit_bytes(encoded)[0]


def _classify_memory_diagnostics(
    stderr: str,
    working_directory: Path,
    *,
    exit_code: int | None = 0,
    timed_out: bool = False,
) -> tuple[str, str, str | None]:
    if timed_out:
        return (
            "runtime_error",
            "Execution timed out before memory checks completed.",
            (
                _clean_memory_diagnostics(stderr, working_directory)
                if stderr.strip()
                else None
            ),
        )
    if not stderr.strip() and exit_code == 0:
        return "clean", "No memory issues detected.", None

    lowered = stderr.lower()
    if "detect_leaks is not supported on this platform" in lowered:
        return (
            "unavailable",
            "Memory diagnostics are unavailable with the current compiler.",
            _clean_memory_diagnostics(stderr, working_directory),
        )
    classifications = (
        (
            "double_free",
            "Double free detected.",
            ("attempting double-free", "double free"),
        ),
        (
            "invalid_free",
            "Invalid free detected.",
            (
                "attempting free on address which was not malloc()-ed",
                "bad-free",
                "invalid free",
            ),
        ),
        (
            "use_after_free",
            "Heap use-after-free detected.",
            (
                "heap-use-after-free",
                "stack-use-after-return",
                "stack-use-after-scope",
            ),
        ),
        (
            "buffer_overflow",
            "Buffer overflow detected.",
            (
                "heap-buffer-overflow",
                "stack-buffer-overflow",
                "global-buffer-overflow",
            ),
        ),
        (
            "leak",
            "Memory leak detected.",
            ("detected memory leaks", "leaksanitizer"),
        ),
        (
            "undefined_behavior",
            "Undefined behaviour detected.",
            (
                "runtime error:",
                "signed integer overflow",
                "null pointer",
                "misaligned address",
                "division by zero",
                "shift exponent",
                "shift-base",
                "out of bounds",
                "out-of-bounds",
            ),
        ),
        (
            "runtime_error",
            "Runtime memory error detected.",
            (
                "addresssanitizer: deadlysignal",
                "addresssanitizer:deadlysignal",
                "addresssanitizer: segv",
                "undefinedbehaviorsanitizer: deadlysignal",
            ),
        ),
    )
    for status, summary, patterns in classifications:
        if any(pattern in lowered for pattern in patterns):
            return (
                status,
                summary,
                _clean_memory_diagnostics(stderr, working_directory),
            )
    if exit_code == 0:
        return "clean", "No memory issues detected.", None
    return (
        "unknown_memory_error",
        "The checked program exited with an unclassified runtime error.",
        (
            _clean_memory_diagnostics(stderr, working_directory)
            if stderr.strip()
            else None
        ),
    )


def _sanitizer_channel_statuses(
    memory_status: str,
    capabilities: SanitizerCapabilities | None,
    enabled: bool,
) -> tuple[str, str, str]:
    if not enabled or capabilities is None:
        return "not_run", "not_run", "not_run"
    access_status = (
        "clean"
        if capabilities.address_sanitizer_available
        else "unavailable"
    )
    undefined_status = (
        "clean"
        if capabilities.undefined_behavior_sanitizer_available
        else "unavailable"
    )
    leak_status = (
        "clean" if capabilities.leak_sanitizer_available else "unavailable"
    )
    if memory_status in {
        "use_after_free",
        "double_free",
        "invalid_free",
        "buffer_overflow",
        "runtime_error",
        "unknown_memory_error",
    }:
        access_status = "failed"
    elif memory_status == "undefined_behavior":
        undefined_status = "failed"
    elif memory_status == "leak":
        leak_status = "failed"
    return access_status, undefined_status, leak_status


def _sanitizer_environment(
    *,
    leak_detection_enabled: bool,
) -> dict[str, str]:
    environment = dict(SANITIZER_ENVIRONMENT)
    if not leak_detection_enabled:
        environment["ASAN_OPTIONS"] = (
            "detect_leaks=0:halt_on_error=1:abort_on_error=1"
        )
    return environment


def _memory_result_fields(
    output: ProcessOutput,
    enabled: bool,
) -> dict[str, object]:
    return {
        "memory_check_enabled": enabled,
        "memory_status": output.memory_status,
        "memory_summary": output.memory_summary,
        "memory_diagnostics": output.memory_diagnostics,
        "address_sanitizer_available": (
            output.address_sanitizer_available
        ),
        "undefined_behavior_sanitizer_available": (
            output.undefined_behavior_sanitizer_available
        ),
        "leak_sanitizer_available": output.leak_sanitizer_available,
        "memory_access_status": output.memory_access_status,
        "undefined_behavior_status": output.undefined_behavior_status,
        "leak_status": output.leak_status,
        "execution_provider": output.execution_provider,
        "memory_tool": output.memory_tool,
        "container_runtime_available": (
            output.container_runtime_available
        ),
        "leaked_bytes": output.leaked_bytes,
        "leaked_allocations": output.leaked_allocations,
        "leak_kind": output.leak_kind,
    }


def _memory_is_clean(output: ProcessOutput, enabled: bool) -> bool:
    return not enabled or output.memory_status in {"clean", "partial"}


def _aggregate_memory_status(
    results: list[
        ProgramTestResult
        | FunctionTestResult
        | FunctionOutputTestResult
        | FunctionMutationTestResult
        | FunctionCombinedTestResult
        | ObjectScenarioTestResult
    ],
    enabled: bool,
) -> str:
    if not enabled:
        return "not_run"
    return next(
        (
            result.memory_status
            for result in results
            if result.memory_status != "clean"
        ),
        "clean",
    )


def _memory_infrastructure_failure(
    results: list[
        ProgramTestResult
        | FunctionTestResult
        | FunctionOutputTestResult
        | FunctionMutationTestResult
        | FunctionCombinedTestResult
        | ObjectScenarioTestResult
    ],
) -> str | None:
    return next(
        (
            result.memory_summary
            for result in results
            if result.memory_status == "unavailable"
        ),
        None,
    )


def _sanitizer_unavailable(compiler_output: str) -> bool:
    lowered = compiler_output.lower()
    return any(
        marker in lowered
        for marker in (
            "unrecognized command-line option",
            "unsupported option",
            "unsupported argument",
            "invalid argument '-fsanitize",
            "cannot find -lasan",
            "cannot find -lubsan",
            "library not found for -lasan",
            "library not found for -lubsan",
        )
    )


def _probe_compile_and_run(
    compiler: str,
    source: str,
    sanitizer_flag: str,
    *,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        with tempfile.TemporaryDirectory(
            prefix="inktocode-sanitizer-probe-"
        ) as directory:
            working_directory = Path(directory)
            (working_directory / "probe.cpp").write_text(
                source, encoding="utf-8"
            )
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    sanitizer_flag,
                    "-fno-omit-frame-pointer",
                    "-g",
                    "probe.cpp",
                    "-o",
                    "probe",
                ],
                cwd=working_directory,
                capture_output=True,
                timeout=COMPILE_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
            if compile_result.returncode != 0:
                return None
            return subprocess.run(
                [str(working_directory / "probe")],
                cwd=working_directory,
                capture_output=True,
                timeout=TEST_TIMEOUT_SECONDS,
                check=False,
                shell=False,
                env=environment,
            )
    except (
        FileNotFoundError,
        OSError,
        subprocess.SubprocessError,
        subprocess.TimeoutExpired,
    ):
        return None


@lru_cache(maxsize=8)
def _probe_sanitizer_capabilities(
    compiler: str,
) -> SanitizerCapabilities:
    base_environment = os.environ.copy()
    base_environment.update(
        _sanitizer_environment(leak_detection_enabled=False)
    )
    clean_source = "int main() { return 0; }\n"
    address_result = _probe_compile_and_run(
        compiler,
        clean_source,
        "-fsanitize=address",
        environment=base_environment,
    )
    undefined_result = _probe_compile_and_run(
        compiler,
        clean_source,
        "-fsanitize=undefined",
        environment=base_environment,
    )
    address_available = bool(
        address_result is not None and address_result.returncode == 0
    )
    undefined_available = bool(
        undefined_result is not None and undefined_result.returncode == 0
    )

    leak_available = False
    if address_available:
        leak_environment = os.environ.copy()
        leak_environment.update(
            _sanitizer_environment(leak_detection_enabled=True)
        )
        leak_result = _probe_compile_and_run(
            compiler,
            (
                "int main() { "
                "volatile int* leaked = new int(7); "
                "(void)leaked; return 0; }\n"
            ),
            (
                "-fsanitize=address,undefined"
                if undefined_available
                else "-fsanitize=address"
            ),
            environment=leak_environment,
        )
        if leak_result is not None:
            leak_output = (
                leak_result.stderr + b"\n" + leak_result.stdout
            ).decode("utf-8", errors="replace").lower()
            leak_available = (
                "leaksanitizer" in leak_output
                or "detected memory leaks" in leak_output
            )
    return SanitizerCapabilities(
        address_sanitizer_available=address_available,
        undefined_behavior_sanitizer_available=undefined_available,
        leak_sanitizer_available=leak_available,
    )


def _sanitizer_compile_flags(
    capabilities: SanitizerCapabilities,
) -> tuple[str, ...]:
    sanitizers = []
    if capabilities.address_sanitizer_available:
        sanitizers.append("address")
    if capabilities.undefined_behavior_sanitizer_available:
        sanitizers.append("undefined")
    if not sanitizers:
        return ()
    return (
        f"-fsanitize={','.join(sanitizers)}",
        "-fno-omit-frame-pointer",
        "-g",
    )


def _compile_executable(
    working_directory: Path,
    *,
    compiler: str,
    timeout_seconds: int,
    run_memory_checks: bool = False,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    docker_provider: DockerExecutionProvider | None = None,
) -> tuple[str | None, bool]:
    if docker_provider is not None:
        result = docker_provider.compile_and_run(
            working_directory,
            "",
            timeout_seconds=timeout_seconds,
            compile_only=True,
        )
        if result.compile_timed_out:
            raise CompilerServiceError(
                "memory_compile_timeout",
                "The isolated runner could not finish compiling the test "
                "program in time.",
                504,
            )
        if result.infrastructure_error:
            return result.infrastructure_error, True
        return result.compile_error, False
    command = [compiler, "-std=c++17", "main.cpp", "-o", "program"]
    if run_memory_checks:
        capabilities = (
            sanitizer_capabilities
            or _probe_sanitizer_capabilities(compiler)
        )
        flags = _sanitizer_compile_flags(capabilities)
        if not flags:
            return (
                "Memory diagnostics are unavailable with the current compiler.",
                True,
            )
        command[2:2] = flags
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
        return None, False
    diagnostic = (
        stderr or stdout or "The compiler failed without diagnostic output."
    )
    return diagnostic, run_memory_checks and _sanitizer_unavailable(diagnostic)


def _integer_bounds(c_type: type[ctypes._SimpleCData]) -> tuple[int, int]:
    bits = ctypes.sizeof(c_type) * 8
    return -(2 ** (bits - 1)), 2 ** (bits - 1) - 1


def _safe_literal(type_name: str, raw_value: str, label: str) -> str:
    if type_name == STRING_TYPE:
        return _cpp_string_literal(raw_value)

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


def _cpp_string_literal(value: str) -> str:
    escaped: list[str] = []
    replacements = {
        "\\": "\\\\",
        '"': '\\"',
        "\n": "\\n",
        "\t": "\\t",
        "\r": "\\r",
    }
    for character in value:
        if character in replacements:
            escaped.append(replacements[character])
        elif ord(character) < 32 or ord(character) == 127:
            escaped.append(f"\\{ord(character):03o}")
        else:
            escaped.append(character)
    return f'"{"".join(escaped)}"'


def _parse_string_vector(raw_value: str, label: str) -> list[str]:
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError(
            f'{label} must be a quoted list such as ["hello", "world"].'
        ) from error
    if not isinstance(parsed, list) or not all(
        isinstance(element, str) for element in parsed
    ):
        raise ValueError(
            f'{label} must contain only quoted strings, such as ["hello", "world"].'
        )
    return parsed


def _split_vector_input(
    raw_value: str,
    label: str,
    *,
    collection_name: str = "vector",
) -> list[str]:
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{label} must contain values or use [] for empty.")
    if value == "[]":
        return []
    if value.startswith("[") or value.endswith("]"):
        if not (value.startswith("[") and value.endswith("]")):
            raise ValueError(
                f"{label} must use matching square brackets."
            )
        value = value[1:-1].strip()
        if not value:
            return []
    if any(character in value for character in "{}()"):
        raise ValueError(
            f"{label} must contain data values, not C++ expressions."
        )
    if "," in value:
        elements = [element.strip() for element in value.split(",")]
        if any(not element for element in elements):
            raise ValueError(
                f"{label} contains an empty {collection_name} element."
            )
        return elements
    return value.split()


def _vector_literal(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> str:
    element_type = value_type.element_type
    if element_type is None:
        raise ValueError(f"{label} uses an unsupported vector type.")
    if value_type.vector_depth == 2:
        rows = _typed_nested_vector_values(value_type, raw_value, label)
        row_literals = [
            "{" + ", ".join(
                _literal_from_typed_value(
                    element_type,
                    element,
                    f"{label} row {row_index + 1} "
                    f"element {element_index + 1}",
                )
                for element_index, element in enumerate(row)
            ) + "}"
            for row_index, row in enumerate(rows)
        ]
        return (
            f"std::vector<std::vector<{element_type}>>"
            f"{{{', '.join(row_literals)}}}"
        )
    elements = (
        _parse_string_vector(raw_value, label)
        if element_type == STRING_TYPE
        else _split_vector_input(raw_value, label)
    )
    literals = [
        _safe_literal(element_type, element, f"{label} element {index + 1}")
        for index, element in enumerate(elements)
    ]
    return f"std::vector<{element_type}>{{{', '.join(literals)}}}"


def _literal_from_typed_value(
    element_type: str,
    value: int | float | bool | str,
    label: str,
) -> str:
    if element_type == STRING_TYPE:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string.")
        raw_value = value
    elif element_type == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be true or false.")
        raw_value = "true" if value else "false"
    elif element_type == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a finite decimal double value.")
        raw_value = repr(value)
    else:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{label} must be a signed decimal {element_type} value."
            )
        raw_value = str(value)
    return _safe_literal(element_type, raw_value, label)


def _typed_nested_vector_values(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> list[list[int | float | bool | str]]:
    element_type = value_type.element_type
    if element_type is None:
        raise ValueError(f"{label} uses an unsupported nested-vector type.")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{label} must be a nested list such as [[1, 2], [3, 4]]."
        ) from error
    if not isinstance(parsed, list):
        raise ValueError(f"{label} must be an outer list of row lists.")

    rows: list[list[int | float | bool | str]] = []
    for row_index, row in enumerate(parsed):
        if not isinstance(row, list):
            raise ValueError(
                f"{label} row {row_index + 1} must be a list."
            )
        validated_row: list[int | float | bool | str] = []
        for element_index, value in enumerate(row):
            element_label = (
                f"{label} row {row_index + 1} "
                f"element {element_index + 1}"
            )
            _literal_from_typed_value(
                element_type,
                value,
                element_label,
            )
            validated_row.append(value)
        rows.append(validated_row)
    return rows


def _safe_value_literal(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> str:
    if value_type.kind == "vector":
        return _vector_literal(value_type, raw_value, label)
    if value_type.scalar_type is None:
        raise ValueError(f"{label} uses an unsupported scalar type.")
    return _safe_literal(value_type.scalar_type, raw_value, label)


def _prepare_argument(
    value_type: ValueType,
    raw_value: str,
    label: str,
    *,
    test_index: int,
    parameter_index: int,
) -> HarnessArgument:
    if value_type.passing in {"mutable_reference", "scalar_pointer"}:
        storage_name = (
            f"inktocode_mutable_{test_index}_{parameter_index}_storage"
        )
        if value_type.kind == "vector":
            literal = _vector_literal(value_type, raw_value, label)
            storage_type = f"std::vector<{value_type.element_type}>"
            if value_type.vector_depth == 2:
                storage_type = f"std::vector<{storage_type}>"
        else:
            if value_type.scalar_type is None:
                raise ValueError(f"{label} uses an unsupported mutable type.")
            literal = _safe_literal(value_type.scalar_type, raw_value, label)
            storage_type = value_type.scalar_type
        return HarnessArgument(
            expression=(
                f"&{storage_name}"
                if value_type.passing == "scalar_pointer"
                else storage_name
            ),
            declarations=(
                f"{storage_type} {storage_name} = {literal};",
            ),
            mutation_expression=storage_name,
        )
    if value_type.kind != "array":
        return HarnessArgument(
            expression=_safe_value_literal(value_type, raw_value, label)
        )

    element_type = value_type.element_type
    if element_type is None:
        raise ValueError(f"{label} uses an unsupported array type.")
    elements = _split_vector_input(
        raw_value,
        label,
        collection_name="array",
    )
    literals = [
        _safe_literal(element_type, element, f"{label} element {index + 1}")
        for index, element in enumerate(elements)
    ]
    storage_name = (
        f"inktocode_array_{test_index}_{parameter_index}_storage"
    )
    declaration = (
        f"{element_type} {storage_name}[] = "
        f"{{{', '.join(literals)}}};"
        if literals
        else f"{element_type} {storage_name}[1] = {{}};"
    )
    return HarnessArgument(
        expression=storage_name,
        declarations=(declaration,),
        array_element_count=len(elements),
        mutation_expression=storage_name,
    )


def _typed_vector_values(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> (
    list[int | float | bool | str]
    | list[list[int | float | bool | str]]
):
    element_type = value_type.element_type
    if element_type is None:
        raise ValueError(f"{label} uses an unsupported vector type.")
    if value_type.vector_depth == 2:
        return _typed_nested_vector_values(value_type, raw_value, label)
    values: list[int | float | bool | str] = []
    elements = (
        _parse_string_vector(raw_value, label)
        if element_type == STRING_TYPE
        else _split_vector_input(raw_value, label)
    )
    for index, element in enumerate(elements):
        _safe_literal(element_type, element, f"{label} element {index + 1}")
        if element_type == STRING_TYPE:
            values.append(element)
        elif element_type == "bool":
            values.append(element.strip() == "true")
        elif element_type == "double":
            values.append(float(element.strip()))
        else:
            values.append(int(element.strip()))
    return values


def _classify_vector_match(
    value_type: ValueType,
    expected: str,
    actual: str,
) -> str:
    try:
        expected_values = _typed_vector_values(
            value_type, expected, "Expected return"
        )
        actual_values = _typed_vector_values(
            value_type, actual, "Actual return"
        )
    except ValueError:
        return "mismatch"
    if expected_values != actual_values:
        return "mismatch"
    return "exact" if expected == actual else "whitespace_normalized"


def _vector_output(function: FunctionSignature, call: str) -> str:
    element_type = function.return_value_type.element_type
    value_output = "inktocode_result[inktocode_index]"
    if element_type == STRING_TYPE:
        value_output = (
            "inktocode_write_quoted_string("
            "inktocode_result[inktocode_index])"
        )
    elif element_type == "bool":
        value_output = f"std::boolalpha << {value_output}"
    elif element_type == "double":
        value_output = (
            f"std::setprecision({DOUBLE_OUTPUT_PRECISION}) << {value_output}"
        )
    return " ".join(
        [
            f"auto inktocode_result = {call};",
            'std::cout << "[";',
            "for (std::size_t inktocode_index = 0;",
            "inktocode_index < inktocode_result.size();",
            "++inktocode_index) {",
            'if (inktocode_index != 0) std::cout << ", ";',
            (
                f"{value_output};"
                if element_type == STRING_TYPE
                else f"std::cout << {value_output};"
            ),
            "}",
            'std::cout << "]";',
        ]
    )


def _collection_output(
    expression: str,
    element_type: str,
    length_expression: str,
) -> str:
    value_expression = f"{expression}[inktocode_index]"
    if element_type == STRING_TYPE:
        value_output = (
            f"inktocode_write_quoted_string({value_expression});"
        )
    elif element_type == "bool":
        value_output = (
            f"std::cout << std::boolalpha << {value_expression};"
        )
    elif element_type == "double":
        value_output = (
            "std::cout << std::setprecision"
            f"({DOUBLE_OUTPUT_PRECISION}) << {value_expression};"
        )
    else:
        value_output = f"std::cout << {value_expression};"
    return " ".join(
        [
            'std::cout << "[";',
            "for (std::size_t inktocode_index = 0;",
            f"inktocode_index < static_cast<std::size_t>({length_expression});",
            "++inktocode_index) {",
            'if (inktocode_index != 0) std::cout << ", ";',
            value_output,
            "}",
            'std::cout << "]";',
        ]
    )


def _nested_collection_output(
    expression: str,
    element_type: str,
) -> str:
    value_expression = (
        f"{expression}[inktocode_row_index][inktocode_element_index]"
    )
    if element_type == STRING_TYPE:
        value_output = (
            f"inktocode_write_quoted_string({value_expression});"
        )
    elif element_type == "bool":
        value_output = (
            f"std::cout << std::boolalpha << {value_expression};"
        )
    elif element_type == "double":
        value_output = (
            "std::cout << std::setprecision"
            f"({DOUBLE_OUTPUT_PRECISION}) << {value_expression};"
        )
    else:
        value_output = f"std::cout << {value_expression};"
    return " ".join(
        [
            'std::cout << "[";',
            "for (std::size_t inktocode_row_index = 0;",
            f"inktocode_row_index < {expression}.size();",
            "++inktocode_row_index) {",
            'if (inktocode_row_index != 0) std::cout << ", ";',
            'std::cout << "[";',
            "for (std::size_t inktocode_element_index = 0;",
            "inktocode_element_index < "
            f"{expression}[inktocode_row_index].size();",
            "++inktocode_element_index) {",
            'if (inktocode_element_index != 0) std::cout << ", ";',
            value_output,
            "}",
            'std::cout << "]";',
            "}",
            'std::cout << "]";',
        ]
    )


def _string_serializer_source() -> str:
    return "\n".join(
        [
            "static void inktocode_write_quoted_string("
            "const std::string& inktocode_value)",
            "{",
            "    std::cout << '\"';",
            "    for (char inktocode_character : inktocode_value)",
            "    {",
            "        switch (inktocode_character)",
            "        {",
            "            case '\\\\': std::cout << \"\\\\\\\\\"; break;",
            "            case '\"': std::cout << \"\\\\\\\"\"; break;",
            "            case '\\n': std::cout << \"\\\\n\"; break;",
            "            case '\\t': std::cout << \"\\\\t\"; break;",
            "            case '\\r': std::cout << \"\\\\r\"; break;",
            "            default: std::cout << inktocode_character; break;",
            "        }",
            "    }",
            "    std::cout << '\"';",
            "}",
        ]
    )


def _build_function_harness(
    code: str,
    function: FunctionSignature,
    arguments_by_test: list[list[HarnessArgument]],
    mutation_parameter_names: tuple[str, ...],
) -> str:
    cases: list[str] = []
    mutable_parameters = [
        (parameter_index, parameter)
        for parameter_index, parameter in enumerate(function.parameters)
        if parameter.name in mutation_parameter_names
    ]
    for index, arguments in enumerate(arguments_by_test):
        declarations = " ".join(
            declaration
            for argument in arguments
            for declaration in argument.declarations
        )
        call = (
            f"{function.name}("
            f"{', '.join(argument.expression for argument in arguments)})"
        )
        serialized_mutations: list[str] = []
        for mutation_index, (mutable_index, parameter) in enumerate(
            mutable_parameters
        ):
            mutable_expression = (
                arguments[mutable_index].mutation_expression
                or arguments[mutable_index].expression
            )
            if parameter.value_type.kind in {"vector", "array"}:
                element_type = parameter.value_type.element_type
                if element_type is None:
                    raise ValueError(
                        f"Mutable parameter {parameter.name} "
                        "has no element type."
                    )
                if parameter.value_type.kind == "vector":
                    length_expression = f"{mutable_expression}.size()"
                else:
                    size_name = parameter.value_type.size_parameter_name
                    size_index = next(
                        (
                            candidate_index
                            for candidate_index, candidate in enumerate(
                                function.parameters
                            )
                            if candidate.name == size_name
                        ),
                        None,
                    )
                    if size_index is None:
                        raise ValueError(
                            f"Mutable array {parameter.name} has no size."
                        )
                    length_expression = arguments[size_index].expression
                serialized_value = (
                    _nested_collection_output(
                        mutable_expression,
                        element_type,
                    )
                    if (
                        parameter.value_type.kind == "vector"
                        and parameter.value_type.vector_depth == 2
                    )
                    else _collection_output(
                        mutable_expression,
                        element_type,
                        length_expression,
                    )
                )
            elif parameter.value_type.scalar_type == STRING_TYPE:
                serialized_value = (
                    "inktocode_write_quoted_string"
                    f"({mutable_expression});"
                )
            elif parameter.value_type.scalar_type == "bool":
                serialized_value = (
                    "std::cout << std::boolalpha "
                    f"<< {mutable_expression};"
                )
            elif parameter.value_type.scalar_type == "double":
                serialized_value = (
                    "std::cout << std::setprecision"
                    f"({DOUBLE_OUTPUT_PRECISION}) "
                    f"<< {mutable_expression};"
                )
            else:
                serialized_value = (
                    f"std::cout << {mutable_expression};"
                )
            separator = (
                'std::cout << ","; ' if mutation_index else ""
            )
            serialized_mutations.append(
                f'{separator}std::cout << "\\"{parameter.name}\\":"; '
                f"{serialized_value}"
            )
        if function.return_value_type.kind == "void":
            call_statement = f"{call};"
            serialized_return = 'std::cout << "null";'
        else:
            call_statement = f"auto inktocode_return_value = {call};"
            if function.return_value_type.kind == "vector":
                element_type = function.return_value_type.element_type
                if element_type is None:
                    raise ValueError("Return vector has no element type.")
                serialized_return = (
                    _nested_collection_output(
                        "inktocode_return_value",
                        element_type,
                    )
                    if function.return_value_type.vector_depth == 2
                    else _collection_output(
                        "inktocode_return_value",
                        element_type,
                        "inktocode_return_value.size()",
                    )
                )
            elif function.return_value_type.scalar_type == STRING_TYPE:
                serialized_return = (
                    "inktocode_write_quoted_string"
                    "(inktocode_return_value);"
                )
            elif function.return_value_type.scalar_type == "bool":
                serialized_return = (
                    "std::cout << std::boolalpha "
                    "<< inktocode_return_value;"
                )
            elif function.return_value_type.scalar_type == "double":
                serialized_return = (
                    "std::cout << std::setprecision"
                    f"({DOUBLE_OUTPUT_PRECISION}) "
                    "<< inktocode_return_value;"
                )
            else:
                serialized_return = (
                    "std::cout << inktocode_return_value;"
                )
        output = " ".join(
            [
                'std::ofstream inktocode_user_output("function-stdout.txt", '
                "std::ios::binary | std::ios::trunc);",
                "std::streambuf* inktocode_original_output = "
                "std::cout.rdbuf(inktocode_user_output.rdbuf());",
                call_statement,
                "std::cout.rdbuf(inktocode_original_output);",
                "inktocode_user_output.close();",
                'std::ofstream inktocode_metadata("function-result.json.tmp", '
                "std::ios::binary | std::ios::trunc);",
                "std::streambuf* inktocode_original_metadata = "
                "std::cout.rdbuf(inktocode_metadata.rdbuf());",
                'std::cout << "{\\"return\\":";',
                serialized_return,
                'std::cout << ",\\"mutations\\":{";',
                " ".join(serialized_mutations),
                'std::cout << "}}";',
                "std::cout.rdbuf(inktocode_original_metadata);",
                "inktocode_metadata.close();",
                'std::rename("function-result.json.tmp", '
                '"function-result.json");',
            ]
        )
        cases.append(
            f"case {index}: {{ {declarations} {output} return 0; }}"
        )

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
        "#include <cstdio>\n"
        "#include <fstream>\n"
        "#include <iomanip>\n"
        "#include <iostream>\n\n"
        "#include <string>\n"
        "#include <vector>\n\n"
        f"{code}\n\n"
        f"{_string_serializer_source()}\n\n"
        f"{generated_main}\n"
    )


def _serialized_value_output(
    expression: str,
    value_type: ValueType,
) -> str:
    if value_type.kind == "vector":
        element_type = value_type.element_type
        if element_type is None:
            raise ValueError("Vector result has no element type.")
        if value_type.vector_depth == 2:
            return _nested_collection_output(expression, element_type)
        return _collection_output(
            expression,
            element_type,
            f"{expression}.size()",
        )
    if value_type.scalar_type == STRING_TYPE:
        return f"inktocode_write_quoted_string({expression});"
    if value_type.scalar_type == "bool":
        return f"std::cout << std::boolalpha << {expression};"
    if value_type.scalar_type == "double":
        return (
            "std::cout << std::setprecision"
            f"({DOUBLE_OUTPUT_PRECISION}) << {expression};"
        )
    return f"std::cout << {expression};"


def _progress_statement(index: int) -> str:
    return " ".join(
        [
            '{ std::ofstream inktocode_progress("object-progress.txt",',
            "std::ios::trunc);",
            f"inktocode_progress << {index};",
            "}",
        ]
    )


def _build_object_harness(
    code: str,
    scenarios: list[PreparedObjectScenario],
) -> str:
    cases: list[str] = []
    for scenario_index, scenario in enumerate(scenarios):
        constructor_declarations = " ".join(
            declaration
            for scenario_object in scenario.objects
            for argument in scenario_object.constructor_arguments
            for declaration in argument.declarations
        )
        statements = [
            constructor_declarations,
            _progress_statement(-1),
            (
                'std::ofstream inktocode_constructor_output('
                '"object-constructor-stdout.txt", '
                "std::ios::binary | std::ios::trunc);"
            ),
            "std::streambuf* inktocode_constructor_original = "
            "std::cout.rdbuf(inktocode_constructor_output.rdbuf());",
            *[
                (
                    f"{scenario_object.object_class.name} "
                    f"inktocode_object_{object_index}{{"
                    + ", ".join(
                        argument.expression
                        for argument in scenario_object.constructor_arguments
                    )
                    + "};"
                )
                for object_index, scenario_object in enumerate(
                    scenario.objects
                )
            ],
            "std::cout.rdbuf(inktocode_constructor_original);",
            "inktocode_constructor_output.close();",
        ]
        object_variables = {
            scenario_object.object_id: f"inktocode_object_{index}"
            for index, scenario_object in enumerate(scenario.objects)
        }
        for step_index, step in enumerate(scenario.steps):
            declarations = " ".join(
                declaration
                for argument in step.arguments
                for declaration in argument.declarations
            )
            expressions = ", ".join(
                argument.expression for argument in step.arguments
            )
            target = object_variables[step.target_object_id]
            if step.special_member is not None:
                source = (
                    object_variables[step.source_object_id]
                    if step.source_object_id
                    else target
                )
                result_variable = f"inktocode_result_{step_index}"
                if step.step_type == "copy_construct":
                    call_statement = (
                        f"{step.result_object_class_id} {result_variable}"
                        f"{{{source}}};"
                    )
                elif step.step_type == "move_construct":
                    call_statement = (
                        f"{step.result_object_class_id} {result_variable}"
                        f"{{std::move({source})}};"
                    )
                elif step.step_type == "copy_assign":
                    call_statement = f"{target} = {source};"
                elif step.step_type == "move_assign":
                    call_statement = f"{target} = std::move({source});"
                else:
                    call_statement = f"{target} = {target};"
                if step.result_object_id:
                    object_variables[step.result_object_id] = result_variable
                return_type = None
                object_result_type = step.result_object_class_id
                suppress_return = True
            elif step.method is not None:
                call = f"{target}.{step.method.name}({expressions})"
                return_type = step.method.return_value_type
                object_result_type = None
                suppress_return = return_type.kind == "void"
            else:
                operator = step.operator
                if operator is None:
                    raise ValueError("Prepared operator step has no operator.")
                operands = [
                    object_variables.get(operand, operand)
                    for operand in step.operand_expressions
                ]
                if operator.symbol == "<<":
                    call = f"std::cout << {operands[-1]}"
                elif operator.kind == "member":
                    operand_text = ", ".join(operands)
                    if operator.symbol == "[]":
                        call = f"{target}[{operand_text}]"
                    elif operator.symbol == "()":
                        call = f"{target}({operand_text})"
                    else:
                        call = f"{target} {operator.symbol} {operands[0]}"
                else:
                    call = (
                        f" {operator.symbol} ".join(operands)
                        if len(operands) == 2
                        else f"operator{operator.symbol}({', '.join(operands)})"
                    )
                return_type = operator.return_value_type
                object_result_type = operator.return_object_class_id
                suppress_return = operator.return_kind in {
                    "mutation_reference",
                    "stream_reference",
                }
            result_name = f"inktocode_step_{step_index}_result"
            if step.special_member is not None:
                pass
            elif object_result_type:
                result_variable = f"inktocode_result_{step_index}"
                call_statement = (
                    f"{object_result_type} {result_variable} = {call};"
                )
                if step.result_object_id:
                    object_variables[step.result_object_id] = result_variable
            else:
                call_statement = (
                    f"{call};"
                    if suppress_return
                    else f"auto {result_name} = {call};"
                )
            serialized_return = (
                'std::cout << "null";'
                if suppress_return or object_result_type
                else _serialized_value_output(result_name, return_type)
            )
            statements.extend(
                [
                    declarations,
                    _progress_statement(step_index),
                    (
                        f'std::ofstream inktocode_step_output_{step_index}('
                        f'"object-step-{step_index}-stdout.txt", '
                        "std::ios::binary | std::ios::trunc);"
                    ),
                    (
                        f"std::streambuf* inktocode_step_original_{step_index} "
                        "= std::cout.rdbuf("
                        f"inktocode_step_output_{step_index}.rdbuf());"
                    ),
                    call_statement,
                    (
                        "std::cout.rdbuf("
                        f"inktocode_step_original_{step_index});"
                    ),
                    f"inktocode_step_output_{step_index}.close();",
                    (
                        f'std::ofstream inktocode_step_metadata_{step_index}('
                        f'"object-step-{step_index}-result.json.tmp", '
                        "std::ios::binary | std::ios::trunc);"
                    ),
                    (
                        f"std::streambuf* inktocode_metadata_original_"
                        f"{step_index} = std::cout.rdbuf("
                        f"inktocode_step_metadata_{step_index}.rdbuf());"
                    ),
                    'std::cout << "{\\"return\\":";',
                    serialized_return,
                    'std::cout << "}";',
                    (
                        "std::cout.rdbuf("
                        f"inktocode_metadata_original_{step_index});"
                    ),
                    f"inktocode_step_metadata_{step_index}.close();",
                    (
                        f'std::rename("object-step-{step_index}-result.json.tmp", '
                        f'"object-step-{step_index}-result.json");'
                    ),
                ]
            )
        statements.append(_progress_statement(len(scenario.steps)))
        cases.append(
            f"case {scenario_index}: {{ {' '.join(statements)} return 0; }}"
        )

    generated_main = "\n".join(
        [
            "int main()",
            "{",
            "    int inktocode_scenario_index = -1;",
            "    if (!(std::cin >> inktocode_scenario_index)) return 2;",
            "    switch (inktocode_scenario_index)",
            "    {",
            *[f"        {case}" for case in cases],
            "        default: return 3;",
            "    }",
            "}",
        ]
    )
    return (
        "#include <cstdio>\n"
        "#include <fstream>\n"
        "#include <iomanip>\n"
        "#include <iostream>\n"
        "#include <string>\n"
        "#include <utility>\n"
        "#include <vector>\n\n"
        f"{code}\n\n"
        f"{_string_serializer_source()}\n\n"
        f"{generated_main}\n"
    )


def _program_results(
    executable: Path,
    working_directory: Path,
    request: ProgramRunTestsRequest,
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    docker_provider: DockerExecutionProvider | None = None,
) -> list[ProgramTestResult]:
    results: list[ProgramTestResult] = []
    for test in request.tests:
        output = _run_process(
            executable,
            working_directory,
            test.stdin,
            timeout_seconds=timeout_seconds,
            run_memory_checks=request.run_memory_checks,
            sanitizer_capabilities=sanitizer_capabilities,
            docker_provider=docker_provider,
        )
        match_type = _classify_program_output_match(
            test.expected_stdout,
            output.stdout,
            request.comparison_mode,
        )
        passed = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and match_type not in {"formatting_mismatch", "mismatch"}
            and _memory_is_clean(output, request.run_memory_checks)
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
                **_memory_result_fields(output, request.run_memory_checks),
            )
        )
    return results


def _metadata_value(value_type: ValueType, value: object) -> str:
    if value_type.kind in {"vector", "array"}:
        return (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, list)
            else ""
        )
    if value_type.scalar_type == STRING_TYPE:
        return value if isinstance(value, str) else ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _typed_match(value_type: ValueType, expected: str, actual: str) -> str:
    if value_type.kind in {"vector", "array"}:
        return (
            "mismatch"
            if _classify_vector_match(value_type, expected, actual)
            == "mismatch"
            else "exact"
        )
    return "exact" if expected == actual else "mismatch"


def _typed_mismatch_detail(
    value_type: ValueType,
    expected: str,
    actual: str,
) -> str | None:
    if value_type.kind != "vector" or value_type.vector_depth != 2:
        return None
    try:
        expected_rows = _typed_nested_vector_values(
            value_type,
            expected,
            "Expected value",
        )
        actual_rows = _typed_nested_vector_values(
            value_type,
            actual,
            "Actual value",
        )
    except ValueError:
        return "The nested-vector result could not be compared structurally."
    if len(expected_rows) != len(actual_rows):
        return (
            f"Expected {len(expected_rows)} row(s), "
            f"actual {len(actual_rows)}."
        )
    for row_index, (expected_row, actual_row) in enumerate(
        zip(expected_rows, actual_rows, strict=True)
    ):
        if len(expected_row) != len(actual_row):
            return (
                f"Row {row_index + 1}: expected length "
                f"{len(expected_row)}, actual length {len(actual_row)}."
            )
        for element_index, (expected_value, actual_value) in enumerate(
            zip(expected_row, actual_row, strict=True)
        ):
            if expected_value != actual_value:
                return (
                    f"First mismatch at row {row_index + 1}, "
                    f"element {element_index + 1}."
                )
    return None


def _function_results(
    executable: Path,
    working_directory: Path,
    request: FunctionRunTestsRequest,
    function: FunctionSignature,
    mutation_parameter_names: tuple[str, ...],
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    docker_provider: DockerExecutionProvider | None = None,
) -> list[
    FunctionTestResult
    | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
]:
    results: list[
        FunctionTestResult
        | FunctionOutputTestResult
        | FunctionMutationTestResult
        | FunctionCombinedTestResult
    ] = []
    mutable_parameters = [
        parameter
        for parameter in function.parameters
        if parameter.name in mutation_parameter_names
    ]
    for index, test in enumerate(request.tests):
        output = _run_process(
            executable,
            working_directory,
            f"{index}\n",
            timeout_seconds=timeout_seconds,
            run_memory_checks=request.run_memory_checks,
            sanitizer_capabilities=sanitizer_capabilities,
            docker_provider=docker_provider,
        )
        metadata: dict[str, object] | None = None
        if output.result_metadata is not None:
            try:
                decoded_metadata = json.loads(output.result_metadata)
            except json.JSONDecodeError:
                decoded_metadata = None
            if isinstance(decoded_metadata, dict):
                metadata = decoded_metadata
        stderr = output.stderr
        if metadata is None:
            stderr = (
                f"{stderr}\n" if stderr else ""
            ) + "Function result metadata was incomplete."

        supplied_expected_values = _expected_mutations(test) or {}
        expected_values = {
            parameter.name: supplied_expected_values.get(parameter.name, "")
            for parameter in mutable_parameters
        }
        raw_mutations = (
            metadata.get("mutations") if metadata is not None else None
        )
        actual_values: dict[str, str] = {}
        mutation_channel_results: list[
            FunctionMutationChannelResult
        ] = []
        mutation_mismatch_details: dict[str, str] = {}
        for parameter in mutable_parameters:
            raw_value = (
                raw_mutations.get(parameter.name)
                if isinstance(raw_mutations, dict)
                else None
            )
            actual_value = _metadata_value(parameter.value_type, raw_value)
            mutation_passed = (
                _typed_match(
                    parameter.value_type,
                    expected_values[parameter.name],
                    actual_value,
                )
                != "mismatch"
            )
            mutation_detail = (
                None
                if mutation_passed
                else _typed_mismatch_detail(
                    parameter.value_type,
                    expected_values[parameter.name],
                    actual_value,
                )
            )
            if mutation_detail is not None:
                mutation_mismatch_details[parameter.name] = mutation_detail
            parameter_index = next(
                parameter_index
                for parameter_index, candidate in enumerate(
                    function.parameters
                )
                if candidate.name == parameter.name
            )
            actual_values[parameter.name] = actual_value
            mutation_channel_results.append(
                FunctionMutationChannelResult(
                    parameter=parameter.name,
                    initial=test.arguments[parameter_index],
                    expected_final=expected_values[parameter.name],
                    actual_final=actual_value,
                    passed=mutation_passed,
                    mismatch_detail=mutation_detail,
                )
            )

        return_channel: FunctionChannelResult | None = None
        if test.expected_return is not None:
            actual_return = _metadata_value(
                function.return_value_type,
                metadata.get("return") if metadata is not None else None,
            )
            return_match = _typed_match(
                function.return_value_type,
                test.expected_return,
                actual_return,
            )
            return_channel = FunctionChannelResult(
                expected=test.expected_return,
                actual=actual_return,
                passed=return_match != "mismatch",
                match_type=return_match,
                mismatch_detail=(
                    None
                    if return_match != "mismatch"
                    else _typed_mismatch_detail(
                        function.return_value_type,
                        test.expected_return,
                        actual_return,
                    )
                ),
            )

        check_stdout = (
            test.check_stdout
            if test.check_stdout is not None
            else test.expected_stdout is not None
        )
        stdout_channel: FunctionChannelResult | None = None
        if check_stdout and test.expected_stdout is not None:
            stdout_match = _classify_program_output_match(
                test.expected_stdout,
                output.function_stdout,
                request.comparison_mode,
            )
            stdout_channel = FunctionChannelResult(
                expected=test.expected_stdout,
                actual=output.function_stdout,
                passed=stdout_match
                not in {"formatting_mismatch", "mismatch"},
                match_type=stdout_match,
            )

        runtime_ok = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and metadata is not None
            and _memory_is_clean(output, request.run_memory_checks)
        )
        active_channels = sum(
            (
                return_channel is not None,
                stdout_channel is not None,
                bool(mutation_channel_results),
            )
        )
        if active_channels > 1:
            all_channels_pass = all(
                channel.passed
                for channel in (return_channel, stdout_channel)
                if channel is not None
            ) and all(
                channel.passed for channel in mutation_channel_results
            )
            passed = runtime_ok and all_channels_pass
            results.append(
                FunctionCombinedTestResult(
                    name=test.name,
                    passed=passed,
                    arguments=test.arguments,
                    return_result=return_channel,
                    stdout_result=stdout_channel,
                    mutation_results=mutation_channel_results,
                    stderr=stderr,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    output_limited=output.output_limited,
                    match_type="exact" if passed else "mismatch",
                    **_memory_result_fields(
                        output, request.run_memory_checks
                    ),
                )
            )
            continue
        if mutable_parameters:
            if not supplied_expected_values:
                raise ValueError(
                    "Mutation tests require expected final values."
                )
            match_type = (
                "exact"
                if all(
                    channel.passed
                    for channel in mutation_channel_results
                )
                else "mismatch"
            )
            passed = runtime_ok and match_type == "exact"
            results.append(
                FunctionMutationTestResult(
                    name=test.name,
                    passed=passed,
                    initial_arguments={
                        parameter.name: argument
                        for parameter, argument in zip(
                            function.parameters,
                            test.arguments,
                            strict=True,
                        )
                    },
                    expected_final_arguments=expected_values,
                    actual_final_arguments=actual_values,
                    mismatch_details=mutation_mismatch_details,
                    stderr=stderr,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    output_limited=output.output_limited,
                    match_type=match_type,
                    **_memory_result_fields(
                        output, request.run_memory_checks
                    ),
                )
            )
            continue
        if function.return_value_type.kind == "void":
            expected_stdout = test.expected_stdout
            if expected_stdout is None:
                raise ValueError("Void function tests require expected_stdout.")
            match_type = _classify_program_output_match(
                expected_stdout,
                output.function_stdout,
                request.comparison_mode,
            )
            passed = (
                runtime_ok
                and match_type not in {"formatting_mismatch", "mismatch"}
            )
            results.append(
                FunctionOutputTestResult(
                    name=test.name,
                    passed=passed,
                    arguments=test.arguments,
                    expected_stdout=expected_stdout,
                    actual_stdout=output.function_stdout,
                    stderr=stderr,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    output_limited=output.output_limited,
                    match_type=match_type,
                    **_memory_result_fields(
                        output, request.run_memory_checks
                    ),
                )
            )
            continue

        expected_return = test.expected_return
        if expected_return is None:
            raise ValueError("Non-void function tests require expected_return.")
        actual_return = (
            return_channel.actual if return_channel is not None else ""
        )
        match_type = (
            return_channel.match_type
            if return_channel is not None
            else "mismatch"
        )
        passed = runtime_ok and match_type != "mismatch"
        results.append(
            FunctionTestResult(
                name=test.name,
                passed=passed,
                arguments=test.arguments,
                expected_return=expected_return,
                actual_return=actual_return,
                mismatch_detail=(
                    return_channel.mismatch_detail
                    if return_channel is not None
                    else None
                ),
                stderr=stderr,
                exit_code=output.exit_code,
                timed_out=output.timed_out,
                output_limited=output.output_limited,
                match_type=match_type,
                **_memory_result_fields(output, request.run_memory_checks),
            )
        )
    return results


def _object_results(
    executable: Path,
    working_directory: Path,
    request: ObjectScenarioRunTestsRequest,
    scenarios: list[PreparedObjectScenario],
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    docker_provider: DockerExecutionProvider | None = None,
) -> list[ObjectScenarioTestResult]:
    results: list[ObjectScenarioTestResult] = []
    for scenario_index, (test, prepared) in enumerate(
        zip(request.tests, scenarios, strict=True)
    ):
        output = _run_process(
            executable,
            working_directory,
            f"{scenario_index}\n",
            timeout_seconds=timeout_seconds,
            run_memory_checks=request.run_memory_checks,
            sanitizer_capabilities=sanitizer_capabilities,
            docker_provider=docker_provider,
        )
        constructor_completed = (
            output.progress_index is not None
            and output.progress_index >= 0
        )
        failed_step_index = (
            output.progress_index
            if constructor_completed
            and output.progress_index is not None
            and output.progress_index < len(prepared.steps)
            else None
        )
        step_results: list[ObjectScenarioStepResult] = []
        for step_index, (step_request, prepared_step) in enumerate(
            zip(test.steps, prepared.steps, strict=True)
        ):
            metadata: dict[str, object] | None = None
            raw_metadata = output.step_metadata[step_index]
            if raw_metadata is not None:
                try:
                    decoded = json.loads(raw_metadata)
                except json.JSONDecodeError:
                    decoded = None
                if isinstance(decoded, dict):
                    metadata = decoded

            if metadata is None:
                status = (
                    "failed"
                    if failed_step_index == step_index
                    else "not_executed"
                )
                step_results.append(
                    ObjectScenarioStepResult(
                        index=step_index,
                        step_type=step_request.step_type,
                        method_id=(
                            prepared_step.method.id
                            if prepared_step.method
                            else None
                        ),
                        operator_id=(
                            prepared_step.operator.id
                            if prepared_step.operator
                            else None
                        ),
                        method=(
                            prepared_step.method.display
                            if prepared_step.method
                            else prepared_step.operator.display
                            if prepared_step.operator
                            else prepared_step.special_member.display
                        ),
                        expression=prepared_step.expression,
                        result_object_name=prepared_step.result_name,
                        status=status,
                        passed=False,
                    )
                )
                continue

            return_result: FunctionChannelResult | None = None
            result_type = (
                prepared_step.method.return_value_type
                if prepared_step.method
                else prepared_step.operator.return_value_type
                if prepared_step.operator
                and prepared_step.operator.return_kind == "value"
                else None
            )
            if result_type is not None and result_type.kind != "void":
                expected_return = step_request.expected_return or ""
                actual_return = _metadata_value(
                    result_type,
                    metadata.get("return"),
                )
                return_match = _typed_match(
                    result_type,
                    expected_return,
                    actual_return,
                )
                return_result = FunctionChannelResult(
                    expected=expected_return,
                    actual=actual_return,
                    passed=return_match != "mismatch",
                    match_type=return_match,
                    mismatch_detail=(
                        None
                        if return_match != "mismatch"
                        else _typed_mismatch_detail(
                            result_type,
                            expected_return,
                            actual_return,
                        )
                    ),
                )

            stdout_result: FunctionChannelResult | None = None
            if step_request.check_stdout:
                expected_stdout = step_request.expected_stdout or ""
                actual_stdout = output.step_stdout[step_index]
                stdout_match = _classify_program_output_match(
                    expected_stdout,
                    actual_stdout,
                    request.comparison_mode,
                )
                stdout_result = FunctionChannelResult(
                    expected=expected_stdout,
                    actual=actual_stdout,
                    passed=stdout_match
                    not in {"formatting_mismatch", "mismatch"},
                    match_type=stdout_match,
                )

            channels = [
                channel
                for channel in (return_result, stdout_result)
                if channel is not None
            ]
            passed = all(channel.passed for channel in channels)
            step_results.append(
                ObjectScenarioStepResult(
                    index=step_index,
                    step_type=step_request.step_type,
                    method_id=(
                        prepared_step.method.id if prepared_step.method else None
                    ),
                    operator_id=(
                        prepared_step.operator.id
                        if prepared_step.operator
                        else None
                    ),
                    method=(
                        prepared_step.method.display
                        if prepared_step.method
                        else prepared_step.operator.display
                        if prepared_step.operator
                        else prepared_step.special_member.display
                    ),
                    expression=prepared_step.expression,
                    result_object_name=prepared_step.result_name,
                    status="completed",
                    passed=passed,
                    return_result=return_result,
                    stdout_result=stdout_result,
                )
            )

        runtime_ok = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and constructor_completed
            and output.progress_index == len(prepared.steps)
            and _memory_is_clean(output, request.run_memory_checks)
        )
        passed = runtime_ok and all(
            step.passed for step in step_results
        )
        object_names = {
            item.object_id: item.name for item in prepared.objects
        }
        moved_ids: set[str] = set()
        for step in prepared.steps:
            if step.result_object_id and step.result_name:
                object_names[step.result_object_id] = step.result_name
            if step.step_type in {"move_construct", "move_assign"}:
                moved_ids.add(step.source_object_id or "")
            if step.step_type in {"copy_assign", "move_assign"}:
                moved_ids.discard(step.target_object_id)
        destruction_failed = (
            output.progress_index == len(prepared.steps)
            and output.exit_code not in {0, None}
            and not output.timed_out
            and not output.output_limited
        )
        scenario_result = ObjectScenarioTestResult(
                name=test.name,
                passed=passed,
                class_name=prepared.objects[0].object_class.name,
                constructor=prepared.objects[0].constructor.display,
                constructor_arguments=(
                    test.constructor_arguments
                    if test.constructor_arguments is not None
                    else test.objects[0].arguments
                ),
                constructor_completed=constructor_completed,
                constructed_objects=[
                    (
                        f"{item.name} = {item.constructor.display}"
                        f"({', '.join(requested.arguments)})"
                    )
                    for item, requested in zip(
                        prepared.objects,
                        test.objects
                        or [
                            type(
                                "LegacyObject",
                                (),
                                {"arguments": test.constructor_arguments or []},
                            )()
                        ],
                        strict=True,
                    )
                ],
                moved_from_objects=[
                    object_names[object_id]
                    for object_id in moved_ids
                    if object_id in object_names
                ],
                destruction_failed=destruction_failed,
                failed_step_index=failed_step_index,
                steps=step_results,
                stderr=output.stderr,
                exit_code=output.exit_code,
                timed_out=output.timed_out,
                output_limited=output.output_limited,
                match_type="exact" if passed else "mismatch",
                **_memory_result_fields(output, request.run_memory_checks),
            )
        diagnosis = diagnose_big_five(request.code, test, scenario_result)
        results.append(
            scenario_result.model_copy(
                update={"big_five_diagnosis": diagnosis}
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


def _prepare_object_scenarios(
    request: ObjectScenarioRunTestsRequest,
) -> list[PreparedObjectScenario]:
    analysis = analyze_object_scenarios(request.code)
    prepared_scenarios: list[PreparedObjectScenario] = []
    for scenario_index, test in enumerate(request.tests):
        requested_objects = test.objects
        if requested_objects is None:
            requested_objects = [
                type(
                    "LegacyObject",
                    (),
                    {
                        "object_id": "legacy-object",
                        "name": "object",
                        "class_id": test.class_id,
                        "constructor_id": test.constructor_id,
                        "arguments": test.constructor_arguments,
                    },
                )()
            ]
        if len({item.object_id for item in requested_objects}) != len(
            requested_objects
        ):
            raise ValueError(f"{test.name} has duplicate object identifiers.")
        if len({item.name for item in requested_objects}) != len(
            requested_objects
        ):
            raise ValueError(f"{test.name} object names must be unique.")
        prepared_objects: list[PreparedScenarioObject] = []
        available_objects: dict[str, tuple[str, str]] = {}
        used_names = {item.name for item in requested_objects}
        for object_index, item in enumerate(requested_objects):
            object_class = next(
                (
                    candidate
                    for candidate in analysis.classes
                    if candidate.id == item.class_id
                ),
                None,
            )
            if object_class is None:
                raise ValueError(
                    f"{test.name} selected a class that is no longer available."
                )
            constructor = next(
                (
                    candidate
                    for candidate in object_class.constructors
                    if candidate.id == item.constructor_id
                ),
                None,
            )
            if constructor is None:
                raise ValueError(
                    f"{test.name} selected a stale or wrong-class constructor."
                )
            if len(item.arguments) != len(constructor.parameters):
                raise ValueError(
                    f"{test.name} object {item.name} constructor requires "
                    f"{len(constructor.parameters)} argument(s)."
                )
            arguments = tuple(
                _prepare_argument(
                    parameter.value_type,
                    argument,
                    f"{test.name} constructor argument {parameter.name}",
                    test_index=scenario_index,
                    parameter_index=object_index * 20 + parameter_index,
                )
                for parameter_index, (parameter, argument) in enumerate(
                    zip(constructor.parameters, item.arguments, strict=True)
                )
            )
            prepared_objects.append(
                PreparedScenarioObject(
                    object_id=item.object_id,
                    name=item.name,
                    object_class=object_class,
                    constructor=constructor,
                    constructor_arguments=arguments,
                )
            )
            available_objects[item.object_id] = (object_class.id, item.name)
        prepared_steps: list[PreparedObjectStep] = []
        moved_from: set[str] = set()
        for step_index, step in enumerate(test.steps):
            target_id = step.target_object_id or requested_objects[0].object_id
            target = available_objects.get(target_id)
            if target is None:
                raise ValueError(
                    f"{test.name} step {step_index + 1} references a stale object."
                )
            target_class = next(
                item for item in analysis.classes if item.id == target[0]
            )
            special_kinds = {
                "copy_construct": "copy_constructor",
                "copy_assign": "copy_assignment",
                "self_assign": "copy_assignment",
                "move_construct": "move_constructor",
                "move_assign": "move_assignment",
            }
            if step.step_type in special_kinds:
                source_id = (
                    target_id
                    if step.step_type == "self_assign"
                    else step.source_object_id
                )
                source = (
                    available_objects.get(source_id)
                    if source_id is not None
                    else None
                )
                if source is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} references a stale source object."
                    )
                if source_id in moved_from:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} cannot use a moved-from source."
                    )
                if source[0] != target[0]:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} requires matching object types."
                    )
                special_member = next(
                    (
                        member
                        for member in target_class.special_members
                        if member.id == step.special_member_id
                        and member.kind == special_kinds[step.step_type]
                    ),
                    None,
                )
                if special_member is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected a stale or wrong special member."
                    )
                creates_object = step.step_type in {
                    "copy_construct",
                    "move_construct",
                }
                if creates_object:
                    if not step.result_object_id or not step.result_name:
                        raise ValueError(
                            "Copy/move construction requires a named result object."
                        )
                    if (
                        step.result_object_id in available_objects
                        or step.result_name in used_names
                    ):
                        raise ValueError(
                            "Special-member result identifiers and names must be unique."
                        )
                    available_objects[step.result_object_id] = (
                        source[0],
                        step.result_name,
                    )
                    used_names.add(step.result_name)
                if step.step_type in {"move_construct", "move_assign"}:
                    moved_from.add(source_id)
                if step.step_type in {"copy_assign", "move_assign"}:
                    moved_from.discard(target_id)
                readable = {
                    "copy_construct": (
                        f"Copy constructed {step.result_name} from {source[1]}"
                    ),
                    "copy_assign": f"{target[1]} = {source[1]}",
                    "self_assign": f"{target[1]} = {target[1]}",
                    "move_construct": (
                        f"Move constructed {step.result_name} from {source[1]}"
                    ),
                    "move_assign": (
                        f"{target[1]} = move({source[1]})"
                    ),
                }[step.step_type]
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=(),
                        target_object_id=target_id,
                        special_member=special_member,
                        source_object_id=source_id,
                        result_object_id=step.result_object_id,
                        result_name=step.result_name,
                        expression=readable,
                        step_type=step.step_type,
                        result_object_class_id=(
                            source[0] if creates_object else None
                        ),
                    )
                )
                continue
            if target_id in moved_from:
                raise ValueError(
                    f"{test.name} step {step_index + 1} cannot use a moved-from object."
                )
            if step.step_type in {"method", "observer"}:
                method = next(
                    (
                        candidate
                        for candidate in target_class.methods
                        if candidate.id == step.method_id
                    ),
                    None,
                )
                if method is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected a stale "
                        "or wrong-class method."
                    )
                if len(step.arguments) != len(method.parameters):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} requires "
                        f"{len(method.parameters)} argument(s)."
                    )
                is_void = method.return_value_type.kind == "void"
                if is_void == (step.expected_return is not None):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} has an invalid "
                        "expected return."
                    )
                if not is_void:
                    _safe_value_literal(
                        method.return_value_type,
                        step.expected_return or "",
                        f"{test.name} step {step_index + 1} expected return",
                    )
                arguments = tuple(
                    _prepare_argument(
                        parameter.value_type,
                        argument,
                        f"{test.name} step {step_index + 1} argument",
                        test_index=scenario_index,
                        parameter_index=step_index * 20 + parameter_index,
                    )
                    for parameter_index, (parameter, argument) in enumerate(
                        zip(method.parameters, step.arguments, strict=True)
                    )
                )
                prepared_steps.append(
                    PreparedObjectStep(
                        method=method,
                        arguments=arguments,
                        target_object_id=target_id,
                        expression=f"{target[1]}.{method.name}()",
                        step_type=step.step_type,
                    )
                )
                continue
            operator = next(
                (
                    candidate
                    for object_class in analysis.classes
                    for candidate in object_class.operators
                    if candidate.id == step.operator_id
                ),
                None,
            )
            if operator is None:
                raise ValueError(
                    f"{test.name} step {step_index + 1} selected a stale operator."
                )
            if (
                operator.kind == "member"
                and operator.declaring_class_id != target_class.id
            ):
                raise ValueError(
                    f"{test.name} step {step_index + 1} has the wrong target type."
                )
            editable_parameters = [
                parameter
                for parameter in operator.parameters
                if not parameter.is_stream
            ]
            supplied = step.operands
            if operator.kind == "member":
                expected_count = len(editable_parameters)
            else:
                expected_count = len(editable_parameters)
            if len(supplied) != expected_count:
                raise ValueError(
                    f"{test.name} step {step_index + 1} requires "
                    f"{expected_count} operand(s)."
                )
            operand_expressions: list[str] = []
            declarations: list[HarnessArgument] = []
            for operand_index, (parameter, supplied_value) in enumerate(
                zip(editable_parameters, supplied, strict=True)
            ):
                if parameter.object_class_id:
                    referenced = available_objects.get(supplied_value)
                    if referenced is None:
                        raise ValueError(
                            f"{test.name} step {step_index + 1} references "
                            "an unavailable object operand."
                        )
                    if referenced[0] != parameter.object_class_id:
                        raise ValueError(
                            f"{test.name} step {step_index + 1} has the wrong "
                            "object operand type."
                        )
                    if supplied_value in moved_from:
                        raise ValueError(
                            f"{test.name} step {step_index + 1} cannot use a moved-from operand."
                        )
                    operand_expressions.append(supplied_value)
                elif parameter.value_type:
                    prepared_argument = _prepare_argument(
                        parameter.value_type,
                        supplied_value,
                        f"{test.name} step {step_index + 1} operand",
                        test_index=scenario_index,
                        parameter_index=step_index * 20 + operand_index,
                    )
                    declarations.append(prepared_argument)
                    operand_expressions.append(prepared_argument.expression)
            if operator.kind == "standalone" and operator.symbol != "<<":
                participating = [
                    available_objects.get(value)
                    for value in operand_expressions
                    if value in available_objects
                ]
                if not participating:
                    raise ValueError("Standalone operator has no object operand.")
            if operator.return_kind == "value":
                if step.expected_return is None or operator.return_value_type is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} requires an expected value."
                    )
                _safe_value_literal(
                    operator.return_value_type,
                    step.expected_return,
                    f"{test.name} step {step_index + 1} expected return",
                )
            elif operator.return_kind == "object_value":
                if step.expected_return is not None:
                    raise ValueError(
                        "Object-valued operator results must use observers."
                    )
                if not step.result_object_id or not step.result_name:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} must name its object result."
                    )
                if (
                    step.result_object_id in available_objects
                    or step.result_name in used_names
                ):
                    raise ValueError("Object result identifiers and names must be unique.")
                available_objects[step.result_object_id] = (
                    operator.return_object_class_id or "",
                    step.result_name,
                )
                used_names.add(step.result_name)
            elif step.expected_return is not None:
                raise ValueError("Reference and stream operator returns are not values.")
            if operator.symbol == "<<" and not step.check_stdout:
                raise ValueError("Stream-output operators require expected output.")
            readable_operands = [
                available_objects[value][1]
                if value in available_objects
                else supplied_value
                for value, supplied_value in zip(
                    operand_expressions, supplied, strict=True
                )
            ]
            if operator.symbol == "<<":
                readable_expression = f"print {readable_operands[-1]}"
            elif operator.kind == "member":
                if operator.symbol == "[]":
                    readable_expression = (
                        f"{target[1]}[{', '.join(readable_operands)}]"
                    )
                elif operator.symbol == "()":
                    readable_expression = (
                        f"{target[1]}({', '.join(readable_operands)})"
                    )
                else:
                    readable_expression = (
                        f"{target[1]} {operator.symbol} "
                        f"{readable_operands[0]}"
                    )
            else:
                readable_expression = (
                    f" {operator.symbol} ".join(readable_operands)
                )
            if step.result_name:
                readable_expression = (
                    f"{step.result_name} = {readable_expression}"
                )
            prepared_steps.append(
                PreparedObjectStep(
                    method=None,
                    arguments=tuple(declarations),
                    target_object_id=target_id,
                    operator=operator,
                    operand_expressions=tuple(operand_expressions),
                    result_object_id=step.result_object_id,
                    result_name=step.result_name,
                    expression=readable_expression,
                    step_type="operator",
                )
            )
        prepared_scenarios.append(
            PreparedObjectScenario(
                objects=tuple(prepared_objects),
                steps=tuple(prepared_steps),
            )
        )
    return prepared_scenarios


def run_test_request(
    request: RunTestsRequest,
    *,
    compiler: str = COMPILER_EXECUTABLE,
    compile_timeout_seconds: int = COMPILE_TIMEOUT_SECONDS,
    test_timeout_seconds: float = TEST_TIMEOUT_SECONDS,
) -> RunTestsResponse:
    object_scenarios: list[PreparedObjectScenario] = []
    analysis = analyze_test_mode(request.code)
    if isinstance(request, ObjectScenarioRunTestsRequest):
        try:
            object_scenarios = _prepare_object_scenarios(request)
        except ValueError as error:
            return RunTestsResponse(
                mode="object",
                success=False,
                input_error=str(error),
                tests=[],
            )
    else:
        if analysis.mode == "unsupported":
            return _unsupported_response(analysis)
        if request.mode != analysis.mode:
            return RunTestsResponse(
                mode=analysis.mode,
                success=False,
                input_error=(
                    "The source execution mode changed. "
                    "Review the tests and retry."
                ),
                tests=[],
            )

    arguments_by_test: list[list[HarnessArgument]] = []
    function = None
    mutation_parameter_names: tuple[str, ...] = ()
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
        mutation_capable_parameters = [
            parameter
            for parameter in function.parameters
            if parameter.value_type.passing
            in {"mutable_reference", "scalar_pointer", "array_pointer"}
        ]
        mutation_tests = [
            test
            for test in request.tests
            if (
                test.expected_final_arguments is not None
                or test.expected_mutations is not None
            )
        ]
        if mutation_tests:
            if len(mutation_tests) != len(request.tests):
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=(
                        "All tests for a selected function must use the same "
                        "expected result channel."
                    ),
                    function=_function_response(function),
                    tests=[],
                )
            try:
                expectation_maps = [
                    _expected_mutations(test) or {}
                    for test in mutation_tests
                ]
            except ValueError as error:
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=str(error),
                    function=_function_response(function),
                    tests=[],
                )
            mutable_names = {
                parameter.name
                for parameter in mutation_capable_parameters
            }
            if any(
                set(expectations) != mutable_names
                for expectations in expectation_maps
            ):
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=(
                        "Every mutable parameter must have exactly one "
                        "expected final value, and immutable parameters "
                        "cannot have mutation expectations."
                    ),
                    function=_function_response(function),
                    tests=[],
                )
            mutation_parameter_names = tuple(
                parameter.name
                for parameter in mutation_capable_parameters
            )
        for test_index, test in enumerate(request.tests):
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
                is_void = function.return_value_type.kind == "void"
                required_mutable_parameters = [
                    parameter
                    for parameter in function.parameters
                    if parameter.value_type.passing
                    in {"mutable_reference", "scalar_pointer"}
                ]
                if (
                    required_mutable_parameters
                    and not mutation_parameter_names
                ):
                    raise ValueError(
                        f"{test.name} must provide expected final values for "
                        "every mutable parameter."
                    )
                if (
                    not mutation_parameter_names
                    and is_void
                    and test.expected_stdout is None
                ):
                    raise ValueError(
                        f"{test.name} must provide expected output for "
                        "the selected void function."
                    )
                if (
                    not is_void
                    and test.expected_return is None
                ):
                    raise ValueError(
                        f"{test.name} must provide an expected return value "
                        "for the selected non-void function."
                    )
                if is_void and test.expected_return is not None:
                    raise ValueError(
                        f"{test.name} cannot provide an expected return "
                        "for a void function."
                    )
                prepared_arguments = [
                    _prepare_argument(
                        parameter.value_type,
                        argument,
                        f"{test.name} argument {parameter.name}",
                        test_index=test_index,
                        parameter_index=parameter_index,
                    )
                    for parameter_index, (parameter, argument) in enumerate(
                        zip(
                            function.parameters,
                            test.arguments,
                            strict=True,
                        )
                    )
                ]
                if mutation_parameter_names:
                    expected_values = _expected_mutations(test) or {}
                    mutable_parameters = [
                        parameter
                        for parameter in function.parameters
                        if parameter.name in mutation_parameter_names
                    ]
                    for mutable_parameter in mutable_parameters:
                        expected_value = expected_values[
                            mutable_parameter.name
                        ]
                        label = (
                            f"{test.name} expected final "
                            f"{mutable_parameter.name}"
                        )
                        if mutable_parameter.value_type.kind in {
                            "vector",
                            "array",
                        }:
                            _typed_vector_values(
                                mutable_parameter.value_type,
                                expected_value,
                                label,
                            )
                        else:
                            _safe_value_literal(
                                mutable_parameter.value_type,
                                expected_value,
                                label,
                            )
                parameter_indexes = {
                    parameter.name: index
                    for index, parameter in enumerate(function.parameters)
                }
                for parameter_index, parameter in enumerate(function.parameters):
                    if parameter.value_type.kind != "array":
                        continue
                    size_name = parameter.value_type.size_parameter_name
                    size_index = (
                        parameter_indexes.get(size_name)
                        if size_name is not None
                        else None
                    )
                    if size_index is None:
                        raise ValueError(
                            f"{test.name} array {parameter.name} has no "
                            "validated size parameter."
                        )
                    size_value = int(test.arguments[size_index].strip())
                    if size_value < 0:
                        raise ValueError(
                            f"{test.name} size parameter {size_name} "
                            "cannot be negative."
                        )
                    element_count = prepared_arguments[
                        parameter_index
                    ].array_element_count
                    if (
                        element_count is None
                        or size_value > element_count
                    ):
                        raise ValueError(
                            f"{test.name} size parameter {size_name} "
                            f"cannot exceed the {element_count or 0} "
                            f"provided element(s) for {parameter.name}."
                        )
                if not is_void:
                    _safe_value_literal(
                        function.return_value_type,
                        test.expected_return or "",
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
            arguments_by_test.append(prepared_arguments)

    docker_provider: DockerExecutionProvider | None = None
    provider_name = "host"
    provider_unavailable: str | None = None
    if request.run_memory_checks:
        provider_name, selected_provider, provider_unavailable = (
            select_memory_provider()
        )
        docker_provider = (
            selected_provider
            if isinstance(selected_provider, DockerExecutionProvider)
            else None
        )
        if provider_name == "docker" and selected_provider is None:
            return RunTestsResponse(
                mode=request.mode,
                success=False,
                memory_check_enabled=True,
                memory_status="unavailable",
                memory_summary=(
                    provider_unavailable
                    or "The isolated memory-checking environment is unavailable."
                ),
                execution_provider="docker",
                container_runtime_available=False,
                function=(
                    _function_response(function)
                    if function is not None
                    else None
                ),
                tests=[],
            )

    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-tests-") as directory:
            working_directory = Path(directory)
            executable = working_directory / "program"
            source = (
                _build_object_harness(request.code, object_scenarios)
                if isinstance(request, ObjectScenarioRunTestsRequest)
                else _build_function_harness(
                    request.code,
                    function,
                    arguments_by_test,
                    mutation_parameter_names,
                )
                if isinstance(request, FunctionRunTestsRequest)
                and function is not None
                else request.code
            )
            (working_directory / "main.cpp").write_bytes(source.encode("utf-8"))
            docker_capabilities = (
                docker_provider.capabilities()
                if docker_provider is not None
                else None
            )
            sanitizer_capabilities = (
                SanitizerCapabilities(
                    docker_capabilities.address_sanitizer_available,
                    docker_capabilities.undefined_behavior_sanitizer_available,
                    docker_capabilities.leak_sanitizer_available
                    or docker_capabilities.valgrind_available,
                )
                if docker_capabilities is not None
                else _probe_sanitizer_capabilities(compiler)
                if request.run_memory_checks
                else None
            )
            compile_error, sanitizer_unavailable = _compile_executable(
                working_directory,
                compiler=compiler,
                timeout_seconds=compile_timeout_seconds,
                run_memory_checks=request.run_memory_checks,
                sanitizer_capabilities=sanitizer_capabilities,
                docker_provider=docker_provider,
            )
            if compile_error is not None:
                if sanitizer_unavailable:
                    return RunTestsResponse(
                        mode=request.mode,
                        success=False,
                        memory_check_enabled=True,
                        memory_status="unavailable",
                        memory_summary=(
                            compile_error
                            if docker_provider is not None
                            else (
                                "Memory diagnostics are unavailable with the "
                                "current compiler."
                            )
                        ),
                        address_sanitizer_available=(
                            sanitizer_capabilities.address_sanitizer_available
                            if sanitizer_capabilities
                            else False
                        ),
                        undefined_behavior_sanitizer_available=(
                            sanitizer_capabilities.undefined_behavior_sanitizer_available
                            if sanitizer_capabilities
                            else False
                        ),
                        leak_sanitizer_available=(
                            sanitizer_capabilities.leak_sanitizer_available
                            if sanitizer_capabilities
                            else False
                        ),
                        execution_provider=provider_name,
                        container_runtime_available=(
                            docker_capabilities.runtime_available
                            if docker_capabilities
                            else False
                        ),
                        function=(
                            _function_response(function)
                            if function is not None
                            else None
                        ),
                        tests=[],
                    )
                return RunTestsResponse(
                    mode=request.mode,
                    success=False,
                    compile_error=compile_error,
                    memory_check_enabled=request.run_memory_checks,
                    memory_status=(
                        "unknown_memory_error"
                        if request.run_memory_checks
                        else "not_run"
                    ),
                    address_sanitizer_available=(
                        sanitizer_capabilities.address_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    undefined_behavior_sanitizer_available=(
                        sanitizer_capabilities.undefined_behavior_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    leak_sanitizer_available=(
                        sanitizer_capabilities.leak_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    execution_provider=provider_name,
                    container_runtime_available=(
                        docker_capabilities.runtime_available
                        if docker_capabilities
                        else None
                    ),
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
                    sanitizer_capabilities=sanitizer_capabilities,
                    docker_provider=docker_provider,
                )
                infrastructure_failure = _memory_infrastructure_failure(
                    results
                )
                if infrastructure_failure:
                    return RunTestsResponse(
                        mode="program",
                        success=False,
                        memory_check_enabled=True,
                        memory_status="unavailable",
                        memory_summary=infrastructure_failure,
                        execution_provider=provider_name,
                        container_runtime_available=True,
                        tests=[],
                    )
                return RunTestsResponse(
                    mode="program",
                    success=all(result.passed for result in results),
                    memory_check_enabled=request.run_memory_checks,
                    memory_status=_aggregate_memory_status(
                        results, request.run_memory_checks
                    ),
                    address_sanitizer_available=(
                        sanitizer_capabilities.address_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    undefined_behavior_sanitizer_available=(
                        sanitizer_capabilities.undefined_behavior_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    leak_sanitizer_available=(
                        sanitizer_capabilities.leak_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    execution_provider=provider_name,
                    memory_tool=(
                        results[0].memory_tool if results else "none"
                    ),
                    container_runtime_available=(
                        docker_capabilities.runtime_available
                        if docker_capabilities
                        else None
                    ),
                    tests=results,
                )

            if isinstance(request, ObjectScenarioRunTestsRequest):
                object_results = _object_results(
                    executable,
                    working_directory,
                    request,
                    object_scenarios,
                    timeout_seconds=test_timeout_seconds,
                    sanitizer_capabilities=sanitizer_capabilities,
                    docker_provider=docker_provider,
                )
                infrastructure_failure = _memory_infrastructure_failure(
                    object_results
                )
                if infrastructure_failure:
                    return RunTestsResponse(
                        mode="object",
                        success=False,
                        memory_check_enabled=True,
                        memory_status="unavailable",
                        memory_summary=infrastructure_failure,
                        execution_provider=provider_name,
                        container_runtime_available=True,
                        tests=[],
                    )
                return RunTestsResponse(
                    mode="object",
                    success=all(result.passed for result in object_results),
                    memory_check_enabled=request.run_memory_checks,
                    memory_status=_aggregate_memory_status(
                        object_results, request.run_memory_checks
                    ),
                    address_sanitizer_available=(
                        sanitizer_capabilities.address_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    undefined_behavior_sanitizer_available=(
                        sanitizer_capabilities.undefined_behavior_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    leak_sanitizer_available=(
                        sanitizer_capabilities.leak_sanitizer_available
                        if sanitizer_capabilities
                        else None
                    ),
                    execution_provider=provider_name,
                    memory_tool=(
                        object_results[0].memory_tool
                        if object_results
                        else "none"
                    ),
                    container_runtime_available=(
                        docker_capabilities.runtime_available
                        if docker_capabilities
                        else None
                    ),
                    tests=object_results,
                )

            function_results = _function_results(
                executable,
                working_directory,
                request,
                function,
                mutation_parameter_names,
                timeout_seconds=test_timeout_seconds,
                sanitizer_capabilities=sanitizer_capabilities,
                docker_provider=docker_provider,
            )
            infrastructure_failure = _memory_infrastructure_failure(
                function_results
            )
            if infrastructure_failure:
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    memory_check_enabled=True,
                    memory_status="unavailable",
                    memory_summary=infrastructure_failure,
                    execution_provider=provider_name,
                    container_runtime_available=True,
                    function=_function_response(function),
                    tests=[],
                )
            return RunTestsResponse(
                mode="function",
                success=all(result.passed for result in function_results),
                memory_check_enabled=request.run_memory_checks,
                memory_status=_aggregate_memory_status(
                    function_results, request.run_memory_checks
                ),
                address_sanitizer_available=(
                    sanitizer_capabilities.address_sanitizer_available
                    if sanitizer_capabilities
                    else None
                ),
                undefined_behavior_sanitizer_available=(
                    sanitizer_capabilities.undefined_behavior_sanitizer_available
                    if sanitizer_capabilities
                    else None
                ),
                leak_sanitizer_available=(
                    sanitizer_capabilities.leak_sanitizer_available
                    if sanitizer_capabilities
                    else None
                ),
                execution_provider=provider_name,
                memory_tool=(
                    function_results[0].memory_tool
                    if function_results
                    else "none"
                ),
                container_runtime_available=(
                    docker_capabilities.runtime_available
                    if docker_capabilities
                    else None
                ),
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
    comparison_mode: str = "whitespace_tolerant",
    run_memory_checks: bool = False,
) -> RunTestsResponse:
    return run_test_request(
        ProgramRunTestsRequest(
            mode="program",
            code=code,
            language="cpp",
            comparison_mode=comparison_mode,
            run_memory_checks=run_memory_checks,
            tests=tests,
        ),
        compiler=compiler,
        compile_timeout_seconds=compile_timeout_seconds,
        test_timeout_seconds=test_timeout_seconds,
    )
