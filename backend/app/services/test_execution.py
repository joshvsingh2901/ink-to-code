import ctypes
import json
import math
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.schemas.test_execution import (
    FunctionResponse,
    ExceptionOutcomeResult,
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
    ExecutionResult,
    ExecutionProvider,
    ProviderCapabilities,
    select_execution_provider,
    select_memory_provider,
)
from app.services.function_analysis import (
    FunctionAnalysis,
    FunctionSignature,
    STRING_TYPE,
    TemplateArgument,
    ValueType,
    analyze_test_mode,
    instantiate_function_template,
)
from app.services.memory_classifier import classify_memory_findings
from app.services.memory_runtime_parser import parse_memory_runtime
from app.services.memory_source_analysis import analyze_memory_source
from app.services.object_analysis import (
    ObjectClass,
    ObjectConstructor,
    ObjectMethod,
    ObjectOperator,
    ObjectSpecialMember,
    analyze_object_scenarios,
    instantiate_object_template,
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
    function_stdout: str = ""
    result_metadata: str | None = None
    step_stdout: tuple[str, ...] = ()
    step_metadata: tuple[str | None, ...] = ()
    progress_index: int | None = None
    constructor_metadata: str | None = None
    memory_status: str = "not_run"
    memory_summary: str | None = None
    memory_diagnostics: str | None = None
    address_sanitizer_available: bool | None = None
    undefined_behavior_sanitizer_available: bool | None = None
    leak_sanitizer_available: bool | None = None
    memory_access_status: str = "not_run"
    undefined_behavior_status: str = "not_run"
    leak_status: str = "not_run"
    execution_provider: str = "docker"
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
    constructor: ObjectConstructor | None = None
    constructor_class: ObjectClass | None = None
    static_class_id: str | None = None
    runtime_class_id: str | None = None
    ownership_mode: str | None = None
    source_expression_id: str | None = None
    cast_target_class_id: str | None = None
    cast_mode: str | None = None
    expected_cast_result: str | None = None
    virtual_destructor: bool | None = None


@dataclass(frozen=True)
class PreparedScenarioObject:
    object_id: str
    name: str
    object_class: ObjectClass
    constructor: ObjectConstructor
    constructor_arguments: tuple[HarnessArgument, ...]
    expected_outcome: str = "return_void"


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
            element_const=getattr(value_type, "element_const", False),
            container_family=value_type.container_family,
            container_name=value_type.container_name,
            key_type=value_type.key_type,
            mapped_type=value_type.mapped_type,
            fixed_size=value_type.fixed_size,
            nested_depth=value_type.nested_depth,
            ordered=value_type.ordered,
            associative=value_type.associative,
            unordered=value_type.unordered,
            adapter=value_type.adapter,
            supported=getattr(value_type, "supported", True),
            unsupported_reason=getattr(value_type, "unsupported_reason", None),
            iterator_container=value_type.iterator_container,
            iterator_const=value_type.iterator_const,
            iterator_role=value_type.iterator_role,
            iterator_group_index=value_type.iterator_group_index,
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
        template_kind=signature.template_kind,
        template_parameters=[
            {
                "name": parameter.name,
                "kind": parameter.kind,
                "non_type_type": parameter.non_type_type,
                "default_argument": parameter.default_argument,
                "deducible": any(
                    parameter.name in raw_type
                    for raw_type in signature.raw_parameter_types
                ),
            }
            for parameter in signature.template_parameters
        ],
        template_argument_mode=signature.template_argument_mode,
        effective_template_arguments=[
            {
                "parameter_name": argument.parameter_name,
                "kind": argument.kind,
                "value": argument.value,
                "used_default": argument.used_default,
            }
            for argument in signature.effective_template_arguments
        ],
        concrete_instantiation=signature.concrete_instantiation,
        specialization_selected=(
            signature.specialization_selected
        ),
        explicit_specializations=[
            {
                "primary_template_name": specialization.primary_template_name,
                "effective_template_arguments": list(
                    specialization.effective_template_arguments
                ),
                "return_type": specialization.return_type,
                "parameter_types": list(specialization.parameter_types),
                "source_line": specialization.source_line,
            }
            for specialization in signature.explicit_specializations
        ],
        source_line=(
            signature.source_line
            if signature.template_kind != "none"
            else None
        ),
    )


def _run_process(
    executable: Path,
    working_directory: Path,
    stdin: str,
    *,
    timeout_seconds: float,
    run_memory_checks: bool = False,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    provider: ExecutionProvider | None = None,
    capabilities: ProviderCapabilities | None = None,
) -> ProcessOutput:
    if provider is None:
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        )
    result = provider.compile_and_run(
        working_directory,
        stdin,
        timeout_seconds=timeout_seconds,
        run_memory_checks=run_memory_checks,
    )
    if result.infrastructure_error and not run_memory_checks:
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        )
    resolved_capabilities = capabilities or ProviderCapabilities(
        "docker", True, True, True, False, False, False, False
    )
    return _provider_process_output(
        result,
        resolved_capabilities,
        working_directory,
        run_memory_checks=run_memory_checks,
    )


def _provider_process_output(
    result: ExecutionResult,
    capabilities: ProviderCapabilities,
    working_directory: Path,
    *,
    run_memory_checks: bool = True,
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
            execution_provider=capabilities.provider,
            container_runtime_available=True,
            infrastructure_error=result.infrastructure_error,
        )
    sanitizer_status, summary, diagnostics = (
        _classify_memory_diagnostics(
            result.stderr,
            working_directory,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
        )
        if run_memory_checks
        else ("not_run", None, None)
    )
    leak_status = (
        "clean"
        if capabilities.leak_sanitizer_available
        or capabilities.valgrind_available
        else "unavailable"
    ) if run_memory_checks else "not_run"
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
            run_memory_checks,
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
        constructor_metadata=result.constructor_metadata,
        memory_status=sanitizer_status,
        memory_summary=summary,
        memory_diagnostics=(
            _redact_container_paths(diagnostics) if diagnostics else None
        ),
        address_sanitizer_available=(
            capabilities.address_sanitizer_available
            if run_memory_checks
            else None
        ),
        undefined_behavior_sanitizer_available=(
            capabilities.undefined_behavior_sanitizer_available
            if run_memory_checks
            else None
        ),
        leak_sanitizer_available=(
            capabilities.leak_sanitizer_available
            or capabilities.valgrind_available
        ) if run_memory_checks else None,
        memory_access_status=access_status,
        undefined_behavior_status=undefined_status,
        leak_status=classified_leak_status,
        execution_provider=capabilities.provider,
        memory_tool=result.memory_tool,
        container_runtime_available=True,
        leaked_bytes=result.leaked_bytes,
        leaked_allocations=result.leaked_allocations,
        leak_kind=result.leak_kind,
        infrastructure_error=result.infrastructure_error,
    )


# Back-compat alias: earlier code (and tests) referred to this function as
# _docker_process_output before it became provider-neutral.
_docker_process_output = _provider_process_output


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
    findings = parse_memory_runtime(stderr)
    if findings:
        category = findings[0].category
        status, summary = {
            "double_free": ("double_free", "Double free detected."),
            "invalid_free": ("invalid_free", "Invalid free detected."),
            "use_after_free": (
                "use_after_free",
                "Heap use-after-free detected.",
            ),
            "lifetime_error": (
                "use_after_free",
                "Invalid lifetime access detected.",
            ),
            "heap_buffer_overflow": (
                "buffer_overflow",
                "Buffer overflow detected.",
            ),
            "stack_buffer_overflow": (
                "buffer_overflow",
                "Buffer overflow detected.",
            ),
            "global_buffer_overflow": (
                "buffer_overflow",
                "Buffer overflow detected.",
            ),
            "out_of_bounds_read": (
                "buffer_overflow",
                "Out-of-bounds read detected.",
            ),
            "out_of_bounds_write": (
                "buffer_overflow",
                "Out-of-bounds write detected.",
            ),
            "memory_leak": ("leak", "Memory leak detected."),
            "undefined_behaviour": (
                "undefined_behavior",
                "Undefined behaviour detected.",
            ),
            "null_pointer_access": (
                "undefined_behavior",
                "Null pointer access detected.",
            ),
            "invalid_pointer_arithmetic": (
                "undefined_behavior",
                "Invalid pointer arithmetic detected.",
            ),
            "unknown_memory_failure": (
                "runtime_error",
                "Runtime memory error detected.",
            ),
            "mismatched_allocation_deallocation": (
                "invalid_free",
                "Mismatched memory cleanup detected.",
            ),
        }.get(
            category,
            ("runtime_error", "Runtime memory error detected."),
        )
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


def _memory_result_fields(
    output: ProcessOutput,
    enabled: bool,
    source: str = "",
    *,
    exception_active: bool = False,
    operation_context: str = "unknown",
    related_operation: str | None = None,
) -> dict[str, object]:
    findings = (
        parse_memory_runtime(
            output.memory_diagnostics or output.stderr,
            provider=output.execution_provider,
        )
        if enabled
        else []
    )
    diagnoses = classify_memory_findings(
        findings + (
            analyze_memory_source(source)
            if enabled and output.memory_status in {"partial", "unavailable"}
            else []
        ),
        source,
        exception_active=exception_active,
        operation_context=operation_context,
        related_operation=related_operation,
    )
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
        "memory_diagnoses": [
            {
                "category": diagnosis.category,
                "title": diagnosis.title,
                "confidence": diagnosis.confidence,
                "summary": diagnosis.summary,
                "likely_cause": diagnosis.likely_cause,
                "source_range": (
                    {
                        "start_line": diagnosis.location.start_line,
                        "end_line": diagnosis.location.end_line,
                        "excerpt": diagnosis.location.excerpt,
                        "label": diagnosis.location.label,
                        "confidence": diagnosis.location.confidence,
                    }
                    if diagnosis.location
                    else None
                ),
                "suggested_direction": diagnosis.suggested_direction,
                "related_operation": diagnosis.related_operation,
                "confirmed_by": list(diagnosis.confirmed_by),
                "technical_details": list(diagnosis.technical_details),
                "supporting_findings": list(
                    diagnosis.supporting_findings
                ),
            }
            for diagnosis in diagnoses
        ],
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


def _compile_executable(
    working_directory: Path,
    *,
    compiler: str,
    timeout_seconds: int,
    run_memory_checks: bool = False,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    provider: ExecutionProvider | None = None,
) -> tuple[str | None, bool]:
    del compiler, sanitizer_capabilities
    if provider is None:
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        )
    result = provider.compile_and_run(
        working_directory,
        "",
        timeout_seconds=timeout_seconds,
        compile_only=True,
        run_memory_checks=run_memory_checks,
    )
    if result.compile_timed_out:
        raise CompilerServiceError(
            "compiler_timeout",
            "Compiling the runnable test program exceeded the time limit.",
            504,
        )
    if result.infrastructure_error:
        if run_memory_checks:
            return result.infrastructure_error, True
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        )
    return result.compile_error, False


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

    if type_name in {"float", "double"}:
        if not _DOUBLE_VALUE.fullmatch(value):
            raise ValueError(
                f"{label} must be a finite decimal {type_name} value."
            )
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(
                f"{label} must be a finite decimal {type_name} value."
            )
        literal = repr(parsed)
        if "." not in literal and "e" not in literal.lower():
            literal += ".0"
        return f"{literal}f" if type_name == "float" else literal

    if type_name == "char":
        if len(raw_value) != 1:
            raise ValueError(f"{label} must contain exactly one character.")
        escaped = {
            "\\": "\\\\",
            "'": "\\'",
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }.get(raw_value, raw_value)
        if ord(raw_value) < 32 and raw_value not in {"\n", "\r", "\t"}:
            raise ValueError(f"{label} contains an unsupported character.")
        return f"'{escaped}'"

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


def _container_literal(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> str:
    c_name = value_type.container_name or ("vector" if value_type.kind == "vector" else "array")

    if value_type.key_type is not None and value_type.mapped_type is not None:
        key_t = value_type.key_type
        val_t = value_type.mapped_type
        entries: list[tuple[object, object]] = []
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, dict):
                entries = list(parsed.items())
            elif isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict) and "key" in item and "value" in item:
                        entries.append((item["key"], item["value"]))
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        entries.append((item[0], item[1]))
                    else:
                        raise ValueError()
            else:
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            pairs = _split_vector_input(raw_value, label, collection_name="map")
            for pair in pairs:
                if "=" in pair:
                    k, v = pair.split("=", 1)
                elif ":" in pair:
                    k, v = pair.split(":", 1)
                else:
                    raise ValueError(f"{label} map entries must be key=value or key:value.")
                entries.append((k.strip(), v.strip()))

        if len(entries) > 50:
            raise ValueError(f"{label} exceeds maximum allowed container elements limit of 50.")

        pair_literals = []
        for idx, (k_val, v_val) in enumerate(entries):
            k_lit = _literal_from_typed_value(key_t, k_val, f"{label} entry {idx+1} key")
            v_lit = _literal_from_typed_value(val_t, v_val, f"{label} entry {idx+1} value")
            pair_literals.append(f"{{{k_lit}, {v_lit}}}")

        container_type_cpp = f"std::{c_name}<{key_t}, {val_t}>"
        return f"{container_type_cpp}{{{', '.join(pair_literals)}}}"

    element_type = value_type.element_type or "int"

    if (value_type.nested_depth and value_type.nested_depth >= 2) or value_type.vector_depth == 2:
        rows = _typed_nested_vector_values(value_type, raw_value, label)
        if len(rows) > 50:
            raise ValueError(f"{label} exceeds maximum allowed container elements limit of 50.")
        row_literals = []
        for row_index, row in enumerate(rows):
            if len(row) > 50:
                raise ValueError(f"{label} row {row_index+1} exceeds maximum allowed container elements limit of 50.")
            lits = [
                _literal_from_typed_value(element_type, element, f"{label} row {row_index+1} element {elem_idx+1}")
                for elem_idx, element in enumerate(row)
            ]
            row_literals.append("{" + ", ".join(lits) + "}")

        base_cpp = f"std::vector<{element_type}>"
        depth = value_type.nested_depth or value_type.vector_depth or 2
        if depth == 3:
            container_type_cpp = f"std::vector<std::vector<{base_cpp}>>"
        else:
            container_type_cpp = f"std::vector<{base_cpp}>"
        return f"{container_type_cpp}{{{', '.join(row_literals)}}}"

    elements = (
        _parse_string_vector(raw_value, label)
        if element_type == STRING_TYPE
        else _split_vector_input(raw_value, label)
    )
    if len(elements) > 50:
        raise ValueError(f"{label} exceeds maximum allowed container elements limit of 50.")

    if value_type.fixed_size is not None:
        if len(elements) != value_type.fixed_size:
            raise ValueError(f"{label} requires exactly {value_type.fixed_size} elements for std::array.")

    literals = [
        _safe_literal(element_type, element, f"{label} element {index + 1}")
        for index, element in enumerate(elements)
    ]

    if c_name == "array":
        size = value_type.fixed_size if value_type.fixed_size is not None else len(literals)
        return f"std::array<{element_type}, {size}>{{{', '.join(literals)}}}"
    elif c_name == "stack":
        return f"std::stack<{element_type}>(std::deque<{element_type}>{{{', '.join(literals)}}})"
    elif c_name == "queue":
        return f"std::queue<{element_type}>(std::deque<{element_type}>{{{', '.join(literals)}}})"
    elif c_name == "priority_queue":
        elems = ", ".join(literals)
        return (
            f"([]() {{ std::vector<{element_type}> __v{{{elems}}};"
            f" return std::priority_queue<{element_type}>(__v.begin(), __v.end()); }}())"
        )
    elif c_name in {"vector", "deque", "list", "set", "multiset", "unordered_set", "unordered_multiset"}:
        return f"std::{c_name}<{element_type}>{{{', '.join(literals)}}}"

    return f"std::vector<{element_type}>{{{', '.join(literals)}}}"


def _vector_literal(
    value_type: ValueType,
    raw_value: str,
    label: str,
) -> str:
    return _container_literal(value_type, raw_value, label)


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
    if value_type.kind in {"container", "vector", "array"} or value_type.container_name:
        return _container_literal(value_type, raw_value, label)
    if value_type.scalar_type is None:
        raise ValueError(f"{label} uses an unsupported scalar type.")
    return _safe_literal(value_type.scalar_type, raw_value, label)


def _parse_iterator_argument(
    raw: str,
    value_type: ValueType,
    label: str,
    *,
    is_tail: bool,
    head_container_payload: list | None = None,
) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"{label} must be an iterator position object.")
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an iterator position object.")
    if is_tail:
        if "container" in payload:
            raise ValueError(
                f"{label} must not carry its own container; the range start owns it."
            )
        container_data = head_container_payload
    else:
        if "container" not in payload:
            raise ValueError(f"{label} must include a container array.")
        container_data = payload["container"]
        if not isinstance(container_data, list):
            raise ValueError(f"{label} container must be a JSON array.")
    element_count = len(container_data) if container_data is not None else 0
    position_raw = payload.get("position")
    if not isinstance(position_raw, int):
        raise ValueError(f"{label} position must be an integer.")
    if position_raw < 0:
        raise ValueError(f"{label} position cannot be negative.")
    if position_raw > element_count:
        raise ValueError(
            f"{label} position {position_raw} exceeds container size {element_count}."
        )
    return {"container": container_data, "position": position_raw}


def _iterator_cpp_type(value_type: ValueType) -> str:
    c = value_type.iterator_container
    e = value_type.element_type or "int"
    if c == "array":
        return f"std::array<{e}, {value_type.fixed_size}>"
    if c == "vector":
        return f"std::vector<{e}>"
    if c == "deque":
        return f"std::deque<{e}>"
    if c == "list":
        return f"std::list<{e}>"
    return f"std::vector<{e}>"


def _iterator_expression(storage: str, position: int, *, is_const: bool) -> str:
    begin = "cbegin()" if is_const else "begin()"
    return f"std::next({storage}.{begin}, {position})"


def _prepare_iterator_arguments(
    function: FunctionSignature,
    raw_arguments: list[str],
    test_index: int,
) -> dict[int, HarnessArgument]:
    result: dict[int, HarnessArgument] = {}
    visited_groups: set[int] = set()
    for param_index, parameter in enumerate(function.parameters):
        vt = parameter.value_type
        if vt.kind != "iterator":
            continue
        if vt.iterator_role == "range_end":
            continue
        group_index = vt.iterator_group_index
        if group_index is None or group_index in visited_groups:
            continue
        visited_groups.add(group_index)
        label = f"argument {parameter.name}"
        head_payload = _parse_iterator_argument(
            raw_arguments[param_index],
            vt,
            label,
            is_tail=False,
        )
        container_data = head_payload["container"]
        head_position = head_payload["position"]
        synthetic_vt = ValueType(
            kind="vector" if vt.iterator_container == "vector" else "container",
            display_type=f"std::{vt.iterator_container}<{vt.element_type}>",
            element_type=vt.element_type,
            fixed_size=vt.fixed_size,
            passing="value",
            container_name=vt.iterator_container,
            container_family="sequence",
            ordered=True,
            associative=False,
            unordered=False,
            adapter=False,
        )
        literal = _container_literal(
            synthetic_vt,
            json.dumps(container_data),
            label,
        )
        cpp_type = _iterator_cpp_type(vt)
        storage = f"inktocode_iterbase_{test_index}_{group_index}"
        decl = f"{cpp_type} {storage} = {literal};"
        result[param_index] = HarnessArgument(
            expression=_iterator_expression(
                storage, head_position, is_const=bool(vt.iterator_const)
            ),
            declarations=(decl,),
            mutation_expression=storage,
        )
        if vt.iterator_role == "range_begin":
            tail_index = next(
                (
                    i
                    for i in range(param_index + 1, len(function.parameters))
                    if function.parameters[i].value_type.iterator_group_index == group_index
                ),
                None,
            )
            if tail_index is not None:
                tail_vt = function.parameters[tail_index].value_type
                tail_label = f"argument {function.parameters[tail_index].name}"
                tail_payload = _parse_iterator_argument(
                    raw_arguments[tail_index],
                    tail_vt,
                    tail_label,
                    is_tail=True,
                    head_container_payload=container_data,
                )
                tail_position = tail_payload["position"]
                if head_position > tail_position:
                    raise ValueError(
                        f"{label} range start must not be after range end."
                    )
                result[tail_index] = HarnessArgument(
                    expression=_iterator_expression(
                        storage,
                        tail_position,
                        is_const=bool(tail_vt.iterator_const),
                    ),
                )
    return result


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
        if value_type.kind in {"container", "vector", "array"} or value_type.container_name:
            literal = _container_literal(value_type, raw_value, label)
            storage_type = value_type.display_type
            if storage_type.startswith("const "):
                storage_type = storage_type[6:]
            if storage_type.endswith("&"):
                storage_type = storage_type[:-1].rstrip()
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
    if value_type.kind != "array" or value_type.container_name == "array":
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


_MAP_CONTAINERS = {"map", "multimap", "unordered_map", "unordered_multimap"}
_SET_CONTAINERS = {"set", "unordered_set"}
_MULTISET_CONTAINERS = {"multiset", "unordered_multiset"}
_SEQUENCE_CONTAINERS = {"deque", "list"}
_ADAPTER_CONTAINERS = {"stack", "queue", "priority_queue"}


def _canonical_map_entries(
    parsed: object,
) -> list[tuple[object, object]] | None:
    if isinstance(parsed, dict):
        return list(parsed.items())
    if not isinstance(parsed, list):
        return None
    entries: list[tuple[object, object]] = []
    for item in parsed:
        if isinstance(item, dict) and "key" in item and "value" in item:
            entries.append((item["key"], item["value"]))
        elif isinstance(item, list) and len(item) == 2:
            entries.append((item[0], item[1]))
        else:
            return None
    return entries


def _canonical_tokens(values: list[object]) -> list[str]:
    return [
        json.dumps(value, sort_keys=True, ensure_ascii=False) for value in values
    ]


def _classify_container_match(
    value_type: ValueType,
    expected: str,
    actual: str,
) -> str:
    try:
        exp = json.loads(expected)
        act = json.loads(actual)
    except (json.JSONDecodeError, ValueError):
        return "mismatch"

    name = value_type.container_name

    if name in _MAP_CONTAINERS:
        exp_entries = _canonical_map_entries(exp)
        act_entries = _canonical_map_entries(act)
        if exp_entries is None or act_entries is None:
            return "mismatch"
        exp_tokens = _canonical_tokens([list(e) for e in exp_entries])
        act_tokens = _canonical_tokens([list(e) for e in act_entries])
        return "exact" if Counter(exp_tokens) == Counter(act_tokens) else "mismatch"

    if not isinstance(exp, list) or not isinstance(act, list):
        return "mismatch"

    if name in _SEQUENCE_CONTAINERS or name in _ADAPTER_CONTAINERS:
        return "exact" if exp == act else "mismatch"

    if name in _SET_CONTAINERS:
        return (
            "exact"
            if set(_canonical_tokens(exp)) == set(_canonical_tokens(act))
            else "mismatch"
        )

    if name in _MULTISET_CONTAINERS:
        return (
            "exact"
            if Counter(_canonical_tokens(exp)) == Counter(_canonical_tokens(act))
            else "mismatch"
        )

    return "exact" if expected == actual else "mismatch"


def _container_mismatch_detail(
    value_type: ValueType,
    expected: str,
    actual: str,
) -> str | None:
    try:
        exp = json.loads(expected)
        act = json.loads(actual)
    except (json.JSONDecodeError, ValueError):
        return None

    name = value_type.container_name

    if (name in _SEQUENCE_CONTAINERS or name in _ADAPTER_CONTAINERS) and isinstance(exp, list) and isinstance(act, list):
        if len(exp) != len(act):
            return f"Expected {len(exp)} element(s), actual {len(act)}."
        for index, (exp_item, act_item) in enumerate(zip(exp, act)):
            if exp_item != act_item:
                if name == "stack":
                    return f"First mismatch at position {index} from top."
                if name == "queue":
                    return f"First mismatch at position {index} from front."
                if name == "priority_queue":
                    return f"First mismatch at pop position {index}."
                return f"First mismatch at index {index}."
        return None

    if name in _MAP_CONTAINERS:
        exp_entries = _canonical_map_entries(exp)
        act_entries = _canonical_map_entries(act)
        if exp_entries is None or act_entries is None:
            return None
        exp_counts = Counter(_canonical_tokens([list(e) for e in exp_entries]))
        act_counts = Counter(_canonical_tokens([list(e) for e in act_entries]))
    elif (
        name in _SET_CONTAINERS or name in _MULTISET_CONTAINERS
    ) and isinstance(exp, list) and isinstance(act, list):
        exp_counts = Counter(_canonical_tokens(exp))
        act_counts = Counter(_canonical_tokens(act))
    else:
        return None

    missing = sorted((exp_counts - act_counts).elements())
    unexpected = sorted((act_counts - exp_counts).elements())
    parts: list[str] = []
    if missing:
        parts.append(f"Missing: {', '.join(missing[:3])}.")
    if unexpected:
        parts.append(f"Unexpected: {', '.join(unexpected[:3])}.")
    return " ".join(parts) if parts else None


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


_EXCEPTION_CATCH_TYPES = (
    "std::invalid_argument",
    "std::domain_error",
    "std::length_error",
    "std::out_of_range",
    "std::logic_error",
    "std::overflow_error",
    "std::underflow_error",
    "std::range_error",
    "std::runtime_error",
    "std::bad_alloc",
    "std::bad_cast",
    "std::bad_typeid",
    "std::bad_function_call",
)


def _exception_support_source() -> str:
    return """
static void inktocode_write_json_string(
    std::ostream& output, const std::string& value)
{
    output << '"';
    for (unsigned char character : value)
    {
        switch (character)
        {
            case '\\\\': output << "\\\\\\\\"; break;
            case '"': output << "\\\\\\""; break;
            case '\\n': output << "\\\\n"; break;
            case '\\r': output << "\\\\r"; break;
            case '\\t': output << "\\\\t"; break;
            default:
                if (character < 0x20) output << '?';
                else output << static_cast<char>(character);
        }
    }
    output << '"';
}

static void inktocode_write_exception(
    const char* path,
    const char* type,
    const char* message,
    bool standard)
{
    std::string temporary_path = std::string(path) + ".tmp";
    std::ofstream output(
        temporary_path, std::ios::binary | std::ios::trunc);
    output << "{\\"outcome\\":\\""
           << (standard ? "threw_standard" : "threw_non_standard")
           << "\\",\\"exception_type\\":";
    inktocode_write_json_string(output, type);
    output << ",\\"exception_message\\":";
    inktocode_write_json_string(output, message ? message : "");
    output << ",\\"process_completed\\":true}";
    output.flush();
    output.close();
    std::rename(temporary_path.c_str(), path);
}
""".strip()


def _exception_catches(
    metadata_path: str,
    *,
    before_write: str = "",
) -> str:
    catches = [
        (
            f"catch (const {exception_type}& inktocode_exception) {{ "
            f"{before_write} "
            f'inktocode_write_exception("{metadata_path}", '
            f'"{exception_type}", inktocode_exception.what(), true); '
            "return 0; }"
        )
        for exception_type in _EXCEPTION_CATCH_TYPES
    ]
    catches.append(
        "catch (const std::exception& inktocode_exception) { "
        f"{before_write} "
        "const char* inktocode_type = "
        "typeid(inktocode_exception) == typeid(std::exception) "
        '? "std::exception" : "other std::exception"; '
        f'inktocode_write_exception("{metadata_path}", inktocode_type, '
        "inktocode_exception.what(), true); return 0; }"
    )
    catches.append(
        "catch (...) { "
        f"{before_write} "
        f'inktocode_write_exception("{metadata_path}", '
        '"non-standard", "", false); return 0; }'
    )
    return " ".join(catches)


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
            f"{function.invocation_name or function.name}("
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
            elif parameter.value_type.kind == "iterator":
                backing_vt = ValueType(
                    kind="vector" if parameter.value_type.iterator_container == "vector" else "container",
                    display_type=f"std::{parameter.value_type.iterator_container}<{parameter.value_type.element_type}>",
                    element_type=parameter.value_type.element_type,
                    fixed_size=parameter.value_type.fixed_size,
                    passing="value",
                    container_name=parameter.value_type.iterator_container,
                    container_family="sequence",
                    ordered=True,
                    associative=False,
                    unordered=False,
                    adapter=False,
                )
                serialized_value = _serialized_value_output(
                    mutable_expression, backing_vt
                )
            elif parameter.value_type.kind == "container":
                serialized_value = _serialized_value_output(
                    mutable_expression, parameter.value_type
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
            elif function.return_value_type.kind == "iterator":
                backing_index = function.return_value_type.iterator_group_index
                if backing_index is not None and backing_index < len(arguments):
                    iter_base = arguments[backing_index].mutation_expression or ""
                else:
                    iter_base = ""
                if iter_base:
                    serialized_return = (
                        f'if (inktocode_return_value == {iter_base}.end()) '
                        f'{{ std::cout << "\\"end\\""; }} '
                        f'else {{ std::cout << std::distance({iter_base}.begin(), '
                        f'inktocode_return_value); }}'
                    )
                else:
                    serialized_return = 'std::cout << "null";'
            elif function.return_value_type.kind == "container":
                serialized_return = _serialized_value_output(
                    "inktocode_return_value", function.return_value_type
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
                "try {",
                call_statement,
                "std::cout.rdbuf(inktocode_original_output);",
                "inktocode_user_output.close();",
                'std::ofstream inktocode_metadata("function-result.json.tmp", '
                "std::ios::binary | std::ios::trunc);",
                "std::streambuf* inktocode_original_metadata = "
                "std::cout.rdbuf(inktocode_metadata.rdbuf());",
                'std::cout << "{\\"outcome\\":\\"returned\\",\\"return\\":";',
                serialized_return,
                'std::cout << ",\\"mutations\\":{";',
                " ".join(serialized_mutations),
                'std::cout << "},\\"process_completed\\":true}";',
                "std::cout.rdbuf(inktocode_original_metadata);",
                "inktocode_metadata.close();",
                'std::rename("function-result.json.tmp", '
                '"function-result.json");',
                "}",
                _exception_catches(
                    "function-result.json",
                    before_write=(
                        "std::cout.rdbuf(inktocode_original_output); "
                        "inktocode_user_output.close();"
                    ),
                ),
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
        "#include <functional>\n"
        "#include <iomanip>\n"
        "#include <iostream>\n"
        "#include <iterator>\n\n"
        "#include <new>\n"
        "#include <queue>\n"
        "#include <stack>\n"
        "#include <stdexcept>\n"
        "#include <string>\n"
        "#include <typeinfo>\n"
        "#include <utility>\n"
        "#include <vector>\n\n"
        f"{code}\n\n"
        f"{_string_serializer_source()}\n\n"
        f"{_container_serializer_source()}\n\n"
        f"{_exception_support_source()}\n\n"
        f"{generated_main}\n"
    )


def _container_serializer_source() -> str:
    return "\n".join(
        [
            "inline void inktocode_serialize(int val) { std::cout << val; }",
            "inline void inktocode_serialize(long val) { std::cout << val; }",
            "inline void inktocode_serialize(long long val) { std::cout << val; }",
            "inline void inktocode_serialize(float val) { std::cout << std::setprecision(17) << val; }",
            "inline void inktocode_serialize(double val) { std::cout << std::setprecision(17) << val; }",
            "inline void inktocode_serialize(bool val) { std::cout << (val ? \"true\" : \"false\"); }",
            "inline void inktocode_serialize(char val) { std::cout << '\\'' << val << '\\''; }",
            "inline void inktocode_serialize(const std::string& val) { inktocode_write_quoted_string(val); }",
            "template <typename K, typename V>",
            "inline void inktocode_serialize(const std::pair<K, V>& p) {",
            "    std::cout << \"{\\\"key\\\": \";",
            "    inktocode_serialize(p.first);",
            "    std::cout << \", \\\"value\\\": \";",
            "    inktocode_serialize(p.second);",
            "    std::cout << \"}\";",
            "}",
            "template <typename Container>",
            "auto inktocode_serialize_container(const Container& c, int) -> decltype(c.begin(), void()) {",
            "    std::cout << \"[\";",
            "    bool first = true;",
            "    for (const auto& item : c) {",
            "        if (!first) std::cout << \", \";",
            "        first = false;",
            "        inktocode_serialize(item);",
            "    }",
            "    std::cout << \"]\";",
            "}",
            "template <typename T, typename Container>",
            "inline void inktocode_serialize_adapter(std::stack<T, Container> adp) {",
            "    std::vector<T> items;",
            "    while (!adp.empty()) { items.push_back(adp.top()); adp.pop(); }",
            "    inktocode_serialize_container(items, 0);",
            "}",
            "template <typename T, typename Container>",
            "inline void inktocode_serialize_adapter(std::queue<T, Container> adp) {",
            "    std::vector<T> items;",
            "    while (!adp.empty()) { items.push_back(adp.front()); adp.pop(); }",
            "    inktocode_serialize_container(items, 0);",
            "}",
            "template <typename T, typename Container, typename Compare>",
            "inline void inktocode_serialize_adapter(std::priority_queue<T, Container, Compare> adp) {",
            "    std::vector<T> items;",
            "    while (!adp.empty()) { items.push_back(adp.top()); adp.pop(); }",
            "    inktocode_serialize_container(items, 0);",
            "}",
            "template <typename T>",
            "inline void inktocode_serialize(const T& val) {",
            "    inktocode_serialize_container(val, 0);",
            "}",
        ]
    )


def _serialized_value_output(
    expression: str,
    value_type: ValueType,
) -> str:
    if value_type.container_name in _ADAPTER_CONTAINERS:
        return f"inktocode_serialize_adapter({expression});"
    if value_type.kind in {"container", "vector", "array"} or value_type.container_name:
        return f"inktocode_serialize({expression});"
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
            *[
                (
                    f"std::optional<{scenario_object.object_class.name}> "
                    f"inktocode_object_{object_index};"
                )
                for object_index, scenario_object in enumerate(
                    scenario.objects
                )
            ],
            _progress_statement(-1),
            (
                'std::ofstream inktocode_constructor_output('
                '"object-constructor-stdout.txt", '
                "std::ios::binary | std::ios::trunc);"
            ),
            "std::streambuf* inktocode_constructor_original = "
            "std::cout.rdbuf(inktocode_constructor_output.rdbuf());",
            "try {",
            *[
                (
                    f"{_progress_statement(-100 - object_index)} "
                    f"inktocode_object_{object_index}.emplace("
                    + ", ".join(
                        argument.expression
                        for argument in scenario_object.constructor_arguments
                    )
                    + ");"
                )
                for object_index, scenario_object in enumerate(
                    scenario.objects
                )
            ],
            "std::cout.rdbuf(inktocode_constructor_original);",
            "inktocode_constructor_output.close();",
            (
                'std::ofstream inktocode_constructor_metadata('
                '"object-constructor-result.json", '
                "std::ios::binary | std::ios::trunc); "
                'inktocode_constructor_metadata << '
                '"{\\"outcome\\":\\"returned\\"}";'
            ),
            "}",
            _exception_catches(
                "object-constructor-result.json",
                before_write=(
                    "std::cout.rdbuf(inktocode_constructor_original); "
                    "inktocode_constructor_output.close();"
                ),
            ),
        ]
        object_variables = {
            scenario_object.object_id: f"(*inktocode_object_{index})"
            for index, scenario_object in enumerate(scenario.objects)
        }
        pointer_variables: dict[str, str] = {}
        for step_index, step in enumerate(scenario.steps):
            persistent_declaration = ""
            declarations = " ".join(
                declaration
                for argument in step.arguments
                for declaration in argument.declarations
            )
            expressions = ", ".join(
                argument.expression for argument in step.arguments
            )
            target = object_variables.get(step.target_object_id, "")
            if step.step_type in {
                "create_base_reference",
                "create_base_pointer",
            }:
                source = object_variables[step.source_object_id or ""]
                result_variable = f"inktocode_result_{step_index}"
                persistent_declaration = (
                    f"{step.static_class_id}* {result_variable} = nullptr;"
                )
                call_statement = f"{result_variable} = &({source});"
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
                    pointer_variables[step.result_object_id] = result_variable
                return_type = None
                object_result_type = step.static_class_id
                suppress_return = True
            elif step.step_type == "slice_object":
                source = object_variables[step.source_object_id or ""]
                result_variable = f"inktocode_result_{step_index}"
                persistent_declaration = (
                    f"std::optional<{step.static_class_id}> "
                    f"{result_variable};"
                )
                call_statement = f"{result_variable}.emplace({source});"
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
                return_type = None
                object_result_type = step.static_class_id
                suppress_return = True
            elif (
                step.step_type == "create_owned_base_pointer"
                and step.constructor is not None
                and step.constructor_class is not None
            ):
                result_variable = f"inktocode_result_{step_index}"
                persistent_declaration = (
                    f"{step.static_class_id}* {result_variable} = nullptr;"
                )
                call_statement = (
                    f"{result_variable} = new {step.constructor_class.name}"
                    f"({expressions});"
                )
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
                    pointer_variables[step.result_object_id] = result_variable
                return_type = None
                object_result_type = step.runtime_class_id
                suppress_return = True
            elif step.step_type == "delete_base_pointer":
                pointer = pointer_variables.get(step.target_object_id)
                if pointer is None:
                    raise ValueError(
                        "Prepared deletion step has no owned pointer."
                    )
                call_statement = f"delete {pointer}; {pointer} = nullptr;"
                return_type = None
                object_result_type = None
                suppress_return = True
            elif step.step_type == "dynamic_cast":
                source = object_variables[step.target_object_id]
                target_type = step.cast_target_class_id
                result_name = f"inktocode_step_{step_index}_result"
                if step.cast_mode == "pointer":
                    source_pointer = pointer_variables.get(
                        step.target_object_id,
                        f"&({source})",
                    )
                    call = (
                        f"(dynamic_cast<{target_type}*>({source_pointer}) "
                        "!= nullptr)"
                    )
                else:
                    call = (
                        f"(static_cast<void>(dynamic_cast<{target_type}&>"
                        f"({source})), true)"
                    )
                return_type = ValueType(
                    kind="scalar",
                    display_type="bool",
                    scalar_type="bool",
                )
                object_result_type = None
                suppress_return = False
            elif step.constructor is not None and step.constructor_class is not None:
                result_variable = f"inktocode_result_{step_index}"
                persistent_declaration = (
                    f"std::optional<{step.constructor_class.name}> "
                    f"{result_variable};"
                )
                call_statement = (
                    f"{result_variable}.emplace({expressions});"
                )
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
                return_type = None
                object_result_type = step.constructor_class.name
                suppress_return = True
            elif step.special_member is not None:
                source = (
                    object_variables[step.source_object_id]
                    if step.source_object_id
                    else target
                )
                result_variable = f"inktocode_result_{step_index}"
                if step.step_type == "copy_construct":
                    persistent_declaration = (
                        f"std::optional<{step.result_object_class_id}> "
                        f"{result_variable};"
                    )
                    call_statement = (
                        f"{result_variable}.emplace({source});"
                    )
                elif step.step_type == "move_construct":
                    persistent_declaration = (
                        f"std::optional<{step.result_object_class_id}> "
                        f"{result_variable};"
                    )
                    call_statement = (
                        f"{result_variable}.emplace(std::move({source}));"
                    )
                elif step.step_type == "copy_assign":
                    call_statement = f"{target} = {source};"
                elif step.step_type == "move_assign":
                    call_statement = f"{target} = std::move({source});"
                else:
                    call_statement = f"{target} = {target};"
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
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
                object_result_type = (
                    step.result_object_class_id
                    or operator.return_object_class_id
                )
                suppress_return = operator.return_kind in {
                    "mutation_reference",
                    "stream_reference",
                }
            result_name = f"inktocode_step_{step_index}_result"
            if (
                step.special_member is not None
                or step.constructor is not None
                or step.step_type
                in {
                    "create_base_reference",
                    "create_base_pointer",
                    "slice_object",
                    "delete_base_pointer",
                }
            ):
                pass
            elif object_result_type:
                result_variable = f"inktocode_result_{step_index}"
                persistent_declaration = (
                    f"std::optional<{object_result_type}> {result_variable};"
                )
                call_statement = (
                    f"{result_variable}.emplace({call});"
                )
                if step.result_object_id:
                    object_variables[step.result_object_id] = (
                        f"(*{result_variable})"
                    )
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
                    persistent_declaration,
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
                    "try {",
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
                    'std::cout << "{\\"outcome\\":\\"returned\\",\\"return\\":";',
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
                    "}",
                    _exception_catches(
                        f"object-step-{step_index}-result.json",
                        before_write=(
                            "std::cout.rdbuf("
                            f"inktocode_step_original_{step_index}); "
                            f"inktocode_step_output_{step_index}.close();"
                        ),
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
        "#include <functional>\n"
        "#include <iomanip>\n"
        "#include <iostream>\n"
        "#include <new>\n"
        "#include <optional>\n"
        "#include <queue>\n"
        "#include <stack>\n"
        "#include <stdexcept>\n"
        "#include <string>\n"
        "#include <typeinfo>\n"
        "#include <utility>\n"
        "#include <vector>\n\n"
        f"{code}\n\n"
        f"{_string_serializer_source()}\n\n"
        f"{_container_serializer_source()}\n\n"
        f"{_exception_support_source()}\n\n"
        f"{generated_main}\n"
    )


def _program_results(
    executable: Path,
    working_directory: Path,
    request: ProgramRunTestsRequest,
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    provider: ExecutionProvider | None = None,
    capabilities: ProviderCapabilities | None = None,
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
            provider=provider,
            capabilities=capabilities,
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
                **_memory_result_fields(
                    output, request.run_memory_checks, request.code
                ),
            )
        )
    return results


def _metadata_value(value_type: ValueType, value: object) -> str:
    if value_type.kind == "iterator":
        if value == "end":
            return "end"
        if isinstance(value, int):
            return str(value)
        return ""
    if value_type.kind in {"vector", "array", "container"}:
        return (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (list, dict))
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
    if value_type.kind == "iterator":
        return "exact" if expected.strip() == actual.strip() else "mismatch"
    if value_type.kind in {"vector", "array"}:
        return (
            "mismatch"
            if _classify_vector_match(value_type, expected, actual)
            == "mismatch"
            else "exact"
        )
    if value_type.kind == "container":
        return _classify_container_match(value_type, expected, actual)
    return "exact" if expected == actual else "mismatch"


def _typed_mismatch_detail(
    value_type: ValueType,
    expected: str,
    actual: str,
) -> str | None:
    if value_type.kind == "iterator":
        e_label = "end()" if expected.strip() == "end" else f"position {expected.strip()}"
        a_label = "end()" if actual.strip() == "end" else f"position {actual.strip()}"
        return f"Expected {e_label}, actual {a_label}."
    if value_type.kind == "container":
        return _container_mismatch_detail(value_type, expected, actual)
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


def _exception_outcome_result(
    *,
    expected_outcome: str,
    expected_exception_type: str | None,
    message_rule: str,
    expected_message: str | None,
    metadata: dict[str, object] | None,
    timed_out: bool,
    exit_code: int | None,
    execution_continued: bool,
) -> ExceptionOutcomeResult:
    raw_outcome = metadata.get("outcome") if metadata else None
    actual_outcome = (
        raw_outcome
        if raw_outcome
        in {"returned", "threw_standard", "threw_non_standard"}
        else "timed_out"
        if timed_out
        else "crashed"
        if exit_code not in {0, None}
        else "crashed"
    )
    actual_type = (
        metadata.get("exception_type")
        if metadata
        and isinstance(metadata.get("exception_type"), str)
        else None
    )
    actual_message = (
        metadata.get("exception_message")
        if metadata
        and isinstance(metadata.get("exception_message"), str)
        else None
    )
    type_matched: bool | None = None
    message_matched: bool | None = None
    if expected_outcome == "throws":
        type_matched = (
            actual_outcome == "threw_standard"
            and (
                expected_exception_type == "any_std_exception"
                or actual_type == expected_exception_type
            )
        )
        message_matched = (
            True
            if message_rule == "ignore"
            else actual_message == expected_message
            if message_rule == "exact"
            else (
                expected_message in actual_message
                if expected_message is not None and actual_message is not None
                else False
            )
        )
        expectation_passed = bool(type_matched and message_matched)
    else:
        expectation_passed = actual_outcome == "returned"
    return ExceptionOutcomeResult(
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome,
        expected_exception_type=expected_exception_type,
        actual_exception_type=actual_type,
        expected_message_rule=message_rule,
        expected_message=expected_message,
        actual_message=actual_message,
        type_matched=type_matched,
        message_matched=message_matched,
        expectation_passed=expectation_passed,
        execution_continued=execution_continued,
    )


def _backing_value_type_for_iterator(vt: ValueType) -> ValueType:
    """Return the container ValueType that represents an iterator's backing store."""
    return ValueType(
        kind="vector" if vt.iterator_container == "vector" else "container",
        display_type=f"std::{vt.iterator_container}<{vt.element_type}>",
        element_type=vt.element_type,
        fixed_size=vt.fixed_size,
        passing="value",
        container_name=vt.iterator_container,
        container_family="sequence",
        ordered=True,
        associative=False,
        unordered=False,
        adapter=False,
    )


def _function_results(
    executable: Path,
    working_directory: Path,
    request: FunctionRunTestsRequest,
    function: FunctionSignature,
    mutation_parameter_names: tuple[str, ...],
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    provider: ExecutionProvider | None = None,
    capabilities: ProviderCapabilities | None = None,
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
            provider=provider,
            capabilities=capabilities,
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
        exception_result = _exception_outcome_result(
            expected_outcome=test.expected_outcome or (
                "return_value"
                if function.return_value_type.kind != "void"
                else "return_void"
            ),
            expected_exception_type=test.expected_exception_type,
            message_rule=test.exception_message_rule,
            expected_message=test.expected_exception_message,
            metadata=metadata,
            timed_out=output.timed_out,
            exit_code=output.exit_code,
            execution_continued=False,
        )
        if test.expected_outcome == "throws":
            passed = (
                exception_result.expectation_passed
                and not output.output_limited
                and _memory_is_clean(output, request.run_memory_checks)
            )
            results.append(
                FunctionCombinedTestResult(
                    name=test.name,
                    passed=passed,
                    arguments=test.arguments,
                    return_result=None,
                    stdout_result=None,
                    mutation_results=[],
                    stderr=stderr,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    output_limited=output.output_limited,
                    match_type="exact" if passed else "mismatch",
                    exception_result=exception_result,
                    **_memory_result_fields(
                        output, request.run_memory_checks, request.code,
                        exception_active=True,
                        operation_context=(
                            "template_specialization"
                            if function.specialization_selected
                            else "function_template_call"
                            if function.template_kind == "function_template"
                            else "exception_exit"
                        ),
                    ),
                )
            )
            continue

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
            cmp_vt = (
                _backing_value_type_for_iterator(parameter.value_type)
                if parameter.value_type.kind == "iterator"
                else parameter.value_type
            )
            actual_value = _metadata_value(cmp_vt, raw_value)
            mutation_passed = (
                _typed_match(
                    cmp_vt,
                    expected_values[parameter.name],
                    actual_value,
                )
                != "mismatch"
            )
            mutation_detail = (
                None
                if mutation_passed
                else _typed_mismatch_detail(
                    cmp_vt,
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
            and exception_result.expectation_passed
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
                    exception_result=exception_result,
                    **_memory_result_fields(
                        output,
                        request.run_memory_checks,
                        request.code,
                        operation_context=(
                            "function_template_call"
                            if function.template_kind == "function_template"
                            else "normal_return"
                        ),
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
                    exception_result=exception_result,
                    **_memory_result_fields(
                        output,
                        request.run_memory_checks,
                        request.code,
                        operation_context=(
                            "function_template_call"
                            if function.template_kind == "function_template"
                            else "normal_return"
                        ),
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
                    exception_result=exception_result,
                    **_memory_result_fields(
                        output,
                        request.run_memory_checks,
                        request.code,
                        operation_context=(
                            "function_template_call"
                            if function.template_kind == "function_template"
                            else "normal_return"
                        ),
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
                exception_result=exception_result,
                **_memory_result_fields(
                    output,
                    request.run_memory_checks,
                    request.code,
                    operation_context=(
                        "function_template_call"
                        if function.template_kind == "function_template"
                        else "normal_return"
                    ),
                ),
            )
        )
    if function.template_kind == "function_template":
        specialization_selected = function.specialization_selected
        updates = {
            "template_kind": (
                "explicit_specialization"
                if specialization_selected
                else "function_template"
            ),
            "template_name": function.name,
            "template_argument_mode": function.template_argument_mode,
            "effective_template_arguments": [
                {
                    "parameter_name": argument.parameter_name,
                    "kind": argument.kind,
                    "value": argument.value,
                    "used_default": argument.used_default,
                }
                for argument in function.effective_template_arguments
            ],
            "concrete_instantiation": function.concrete_instantiation,
            "specialization_selected": specialization_selected,
            "specialization_kind": (
                "explicit_specialization"
                if specialization_selected
                else "primary"
            ),
        }
        return [result.model_copy(update=updates) for result in results]
    return results


def _object_results(
    executable: Path,
    working_directory: Path,
    request: ObjectScenarioRunTestsRequest,
    scenarios: list[PreparedObjectScenario],
    *,
    timeout_seconds: float,
    sanitizer_capabilities: SanitizerCapabilities | None = None,
    provider: ExecutionProvider | None = None,
    capabilities: ProviderCapabilities | None = None,
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
            provider=provider,
            capabilities=capabilities,
        )
        constructor_metadata: dict[str, object] | None = None
        if output.constructor_metadata is not None:
            try:
                decoded_constructor = json.loads(
                    output.constructor_metadata
                )
            except json.JSONDecodeError:
                decoded_constructor = None
            if isinstance(decoded_constructor, dict):
                constructor_metadata = decoded_constructor
        failed_constructor_index = (
            -output.progress_index - 100
            if output.progress_index is not None
            and output.progress_index <= -100
            else None
        )
        requested_objects = test.objects or []
        constructor_expectation = (
            requested_objects[failed_constructor_index]
            if failed_constructor_index is not None
            and failed_constructor_index < len(requested_objects)
            else next(
                (
                    item
                    for item in requested_objects
                    if item.expected_outcome == "throws"
                ),
                requested_objects[0] if requested_objects else None,
            )
        )
        constructor_exception_result = (
            _exception_outcome_result(
                expected_outcome=constructor_expectation.expected_outcome,
                expected_exception_type=(
                    constructor_expectation.expected_exception_type
                ),
                message_rule=constructor_expectation.exception_message_rule,
                expected_message=(
                    constructor_expectation.expected_exception_message
                ),
                metadata=constructor_metadata,
                timed_out=output.timed_out,
                exit_code=output.exit_code,
                execution_continued=False,
            )
            if constructor_expectation is not None
            else None
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
                failed_exception_result = (
                    _exception_outcome_result(
                        expected_outcome=(
                            step_request.expected_outcome or "return_void"
                        ),
                        expected_exception_type=(
                            step_request.expected_exception_type
                        ),
                        message_rule=step_request.exception_message_rule,
                        expected_message=(
                            step_request.expected_exception_message
                        ),
                        metadata=None,
                        timed_out=output.timed_out,
                        exit_code=output.exit_code,
                        execution_continued=False,
                    )
                    if status == "failed"
                    else None
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
                            if prepared_step.special_member
                            else prepared_step.constructor.display
                            if prepared_step.constructor
                            else "Create object"
                        ),
                        expression=prepared_step.expression,
                        result_object_name=prepared_step.result_name,
                        status=status,
                        passed=False,
                        exception_result=failed_exception_result,
                        static_type=prepared_step.static_class_id,
                        runtime_type=prepared_step.runtime_class_id,
                        ownership_mode=prepared_step.ownership_mode,
                        dispatch_kind=(
                            "virtual"
                            if prepared_step.method
                            and prepared_step.method.is_virtual
                            else "non_virtual"
                            if prepared_step.method
                            else None
                        ),
                        slicing_occurred=(
                            prepared_step.step_type == "slice_object"
                        ),
                        virtual_destructor=(
                            prepared_step.virtual_destructor
                        ),
                    )
                )
                continue

            exception_result = _exception_outcome_result(
                expected_outcome=step_request.expected_outcome or "return_void",
                expected_exception_type=step_request.expected_exception_type,
                message_rule=step_request.exception_message_rule,
                expected_message=step_request.expected_exception_message,
                metadata=metadata,
                timed_out=output.timed_out,
                exit_code=output.exit_code,
                execution_continued=(
                    metadata.get("outcome") == "returned"
                ),
            )

            return_result: FunctionChannelResult | None = None
            result_type = (
                prepared_step.method.return_value_type
                if prepared_step.method
                else prepared_step.operator.return_value_type
                if prepared_step.operator
                and prepared_step.operator.return_kind == "value"
                else None
            )
            if prepared_step.step_type == "dynamic_cast":
                result_type = ValueType(
                    kind="scalar",
                    display_type="bool",
                    scalar_type="bool",
                )
            if (
                result_type is not None
                and result_type.kind != "void"
                and step_request.expected_outcome != "throws"
            ):
                expected_return = (
                    "false"
                    if prepared_step.expected_cast_result == "returns_null"
                    else "true"
                    if prepared_step.step_type == "dynamic_cast"
                    else step_request.expected_return or ""
                )
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
            passed = (
                exception_result.expectation_passed
                and all(channel.passed for channel in channels)
            )
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
                        if prepared_step.special_member
                        else prepared_step.constructor.display
                        if prepared_step.constructor
                        else "Create object"
                    ),
                    expression=prepared_step.expression,
                    result_object_name=prepared_step.result_name,
                    status="completed",
                    passed=passed,
                    return_result=return_result,
                    stdout_result=stdout_result,
                    exception_result=exception_result,
                    static_type=prepared_step.static_class_id,
                    runtime_type=prepared_step.runtime_class_id,
                    ownership_mode=prepared_step.ownership_mode,
                    dispatch_kind=(
                        "virtual"
                        if prepared_step.method
                        and prepared_step.method.is_virtual
                        else "non_virtual"
                        if prepared_step.method
                        else None
                    ),
                    selected_implementation=(
                        (
                            prepared_step.runtime_class_id
                            if prepared_step.method.is_virtual
                            else prepared_step.static_class_id
                        )
                        + f"::{prepared_step.method.name}"
                        if prepared_step.method
                        and prepared_step.static_class_id
                        and prepared_step.runtime_class_id
                        else None
                    ),
                    slicing_occurred=(
                        prepared_step.step_type == "slice_object"
                    ),
                    cast_result=(
                        "null"
                        if prepared_step.step_type == "dynamic_cast"
                        and metadata.get("return") is False
                        else "succeeded"
                        if prepared_step.step_type == "dynamic_cast"
                        and metadata.get("outcome") == "returned"
                        else "threw_bad_cast"
                        if prepared_step.step_type == "dynamic_cast"
                        and metadata.get("outcome") == "threw_standard"
                        else None
                    ),
                    virtual_destructor=prepared_step.virtual_destructor,
                )
            )

        expected_constructor_throw = any(
            item.expected_outcome == "throws" for item in requested_objects
        )
        constructor_behavior_passed = (
            constructor_exception_result.expectation_passed
            if constructor_exception_result is not None
            else constructor_completed
        )
        expected_stop_after_constructor = (
            expected_constructor_throw
            and constructor_exception_result is not None
            and constructor_exception_result.expectation_passed
        )
        expected_stop_after_step = any(
            step.exception_result is not None
            and step.exception_result.expected_outcome == "throws"
            and step.exception_result.expectation_passed
            for step in step_results
        )
        runtime_ok = (
            not output.timed_out
            and not output.output_limited
            and output.exit_code == 0
            and constructor_behavior_passed
            and (
                output.progress_index == len(prepared.steps)
                or expected_stop_after_constructor
                or expected_stop_after_step
            )
            and _memory_is_clean(output, request.run_memory_checks)
        )
        passed = runtime_ok and all(
            step.passed
            for step in step_results
            if step.status != "not_executed"
        ) and not any(
            step.status == "not_executed"
            for step in step_results
            if not expected_stop_after_step
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
                class_name=(
                    prepared.objects[0].object_class.name
                    if prepared.objects
                    else next(
                        (
                            step.constructor_class.name
                            for step in prepared.steps
                            if step.constructor_class is not None
                        ),
                        "Object scenario",
                    )
                ),
                constructor=(
                    prepared.objects[0].constructor.display
                    if prepared.objects
                    else "No setup constructor"
                ),
                constructor_arguments=(
                    test.constructor_arguments
                    if test.constructor_arguments is not None
                    else test.objects[0].arguments
                    if test.objects
                    else []
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
                            if test.objects is not None
                            else [
                                type(
                                "LegacyObject",
                                (),
                                {"arguments": test.constructor_arguments or []},
                            )()
                        ],
                        strict=True,
                    )
                    if failed_constructor_index is None
                    or prepared.objects.index(item) < failed_constructor_index
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
                constructor_exception_result=constructor_exception_result,
                **_memory_result_fields(
                    output,
                    request.run_memory_checks,
                    request.code,
                    exception_active=any(
                        (
                            item.expected_outcome == "throws"
                            for item in (
                                list(test.objects or []) + list(test.steps)
                            )
                        )
                    ),
                    operation_context=next(
                        (
                            {
                                "delete_base_pointer": "base_pointer_deletion",
                                "polymorphic_method": "polymorphic_call",
                                "slice_object": "object_slicing",
                                "dynamic_cast": "dynamic_cast",
                            }.get(step.step_type, step.step_type)
                            for step in reversed(test.steps)
                            if step.step_type
                            in {
                                "copy_construct",
                                "copy_assign",
                                "move_construct",
                                "move_assign",
                                "delete_base_pointer",
                                "polymorphic_method",
                                "slice_object",
                                "dynamic_cast",
                            }
                        ),
                        "scenario_cleanup",
                    ).replace("copy_assign", "copy_assignment").replace(
                        "move_assign", "move_assignment"
                    ).replace(
                        "copy_construct", "copy_constructor"
                    ).replace(
                        "move_construct", "move_constructor"
                    ),
                    related_operation=next(
                        (
                            step.step_type
                            for step in reversed(test.steps)
                            if step.step_type
                            in {
                                "copy_construct",
                                "copy_assign",
                                "move_construct",
                                "move_assign",
                            }
                        ),
                        None,
                    ),
                ),
            )
        diagnosis = diagnose_big_five(request.code, test, scenario_result)
        template_class = next(
            (
                item.object_class
                for item in prepared.objects
                if item.object_class.template_kind == "class_template"
            ),
            next(
                (
                    step.constructor_class
                    for step in prepared.steps
                    if step.constructor_class is not None
                    and step.constructor_class.template_kind
                    == "class_template"
                ),
                None,
            ),
        )
        template_updates = (
            {
                "template_kind": "class_template",
                "template_name": template_class.id,
                "template_argument_mode": "explicit",
                "effective_template_arguments": [
                    {
                        "parameter_name": argument.parameter_name,
                        "kind": argument.kind,
                        "value": argument.value,
                        "used_default": argument.used_default,
                    }
                    for argument in template_class.effective_template_arguments
                ],
                "concrete_instantiation": template_class.concrete_type,
            }
            if template_class is not None
            else {}
        )
        results.append(
            scenario_result.model_copy(
                update={
                    "big_five_diagnosis": diagnosis,
                    **template_updates,
                }
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
    unqualified_types_allowed = bool(
        re.search(r"\busing\s+namespace\s+std\s*;", request.code)
    )

    def resolve_class(
        class_id: str | None,
        raw_arguments,
    ) -> tuple[ObjectClass | None, ObjectClass | None]:
        definition = next(
            (
                candidate
                for candidate in analysis.classes
                if candidate.id == class_id
            ),
            None,
        )
        if definition is None:
            return None, None
        supplied = tuple(
            TemplateArgument(
                parameter_name=argument.parameter_name,
                kind=argument.kind,
                value=argument.value,
                used_default=argument.use_default,
            )
            for argument in raw_arguments
        )
        return (
            definition,
            instantiate_object_template(
                definition,
                supplied,
                unqualified_types_allowed=unqualified_types_allowed,
            ),
        )
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
                        "expected_outcome": "return_void",
                        "expected_exception_type": None,
                        "exception_message_rule": "ignore",
                        "expected_exception_message": None,
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
        concrete_classes_by_object_id: dict[str, ObjectClass] = {}
        # static type, display name, runtime type, ownership mode
        available_objects: dict[str, tuple[str, str, str, str]] = {}
        used_names = {item.name for item in requested_objects}
        for object_index, item in enumerate(requested_objects):
            object_definition, object_class = resolve_class(
                item.class_id,
                getattr(item, "template_arguments", ()),
            )
            if object_class is None:
                raise ValueError(
                    f"{test.name} selected a class that is no longer available."
                )
            if object_class.is_abstract:
                raise ValueError(
                    f"{test.name} cannot construct abstract class "
                    f"{object_class.name} directly."
                )
            constructor = next(
                (
                    candidate
                    for candidate in object_class.constructors
                    if candidate.id == item.constructor_id
                ),
                None,
            )
            if constructor is None and object_definition is not None:
                definition_index = next(
                    (
                        index
                        for index, candidate in enumerate(
                            object_definition.constructors
                        )
                        if candidate.id == item.constructor_id
                    ),
                    None,
                )
                if (
                    definition_index is not None
                    and definition_index < len(object_class.constructors)
                ):
                    constructor = object_class.constructors[definition_index]
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
                    expected_outcome=item.expected_outcome,
                )
            )
            concrete_classes_by_object_id[item.object_id] = object_class
            if item.expected_outcome != "throws":
                available_objects[item.object_id] = (
                    object_class.id,
                    item.name,
                    object_class.id,
                    "value",
                )
        prepared_steps: list[PreparedObjectStep] = []
        moved_from: set[str] = set()
        deleted_owned_pointers: set[str] = set()
        for step_index, step in enumerate(test.steps):
            if step.step_type == "create_object":
                object_definition, object_class = resolve_class(
                    step.class_id,
                    step.template_arguments,
                )
                if object_class is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected an "
                        "unsupported class."
                    )
                if object_class.is_abstract:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} cannot construct "
                        f"abstract class {object_class.name} directly."
                    )
                constructor = next(
                    (
                        candidate
                        for candidate in object_class.constructors
                        if candidate.id == step.constructor_id
                    ),
                    None,
                )
                if constructor is None and object_definition is not None:
                    definition_index = next(
                        (
                            index
                            for index, candidate in enumerate(
                                object_definition.constructors
                            )
                            if candidate.id == step.constructor_id
                        ),
                        None,
                    )
                    if (
                        definition_index is not None
                        and definition_index < len(object_class.constructors)
                    ):
                        constructor = object_class.constructors[definition_index]
                if constructor is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected a stale "
                        "or wrong-class constructor."
                    )
                if (
                    step.result_object_id in available_objects
                    or step.result_name in used_names
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} object name and "
                        "identifier must be unique."
                    )
                if len(step.arguments) != len(constructor.parameters):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} constructor "
                        f"requires {len(constructor.parameters)} argument(s)."
                    )
                arguments = tuple(
                    _prepare_argument(
                        parameter.value_type,
                        argument,
                        (
                            f"{test.name} step {step_index + 1} constructor "
                            f"argument {parameter.name}"
                        ),
                        test_index=scenario_index,
                        parameter_index=(
                            (len(requested_objects) + step_index) * 20
                            + parameter_index
                        ),
                    )
                    for parameter_index, (parameter, argument) in enumerate(
                        zip(
                            constructor.parameters,
                            step.arguments,
                            strict=True,
                        )
                    )
                )
                if step.expected_outcome != "throws":
                    available_objects[step.result_object_id or ""] = (
                        object_class.id,
                        step.result_name or "",
                        object_class.id,
                        "value",
                    )
                    used_names.add(step.result_name or "")
                    concrete_classes_by_object_id[
                        step.result_object_id or ""
                    ] = object_class
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=arguments,
                        target_object_id=step.result_object_id or "",
                        result_object_id=step.result_object_id,
                        result_name=step.result_name,
                        expression=(
                            f"Create {step.result_name} with "
                            f"{constructor.display}"
                        ),
                        step_type="create_object",
                        result_object_class_id=object_class.id,
                        constructor=constructor,
                        constructor_class=object_class,
                        static_class_id=object_class.name,
                        runtime_class_id=object_class.name,
                        ownership_mode="value",
                    )
                )
                continue
            if step.step_type in {
                "create_base_reference",
                "create_base_pointer",
                "slice_object",
            }:
                source = available_objects.get(step.source_object_id or "")
                if source is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} references an "
                        "unavailable source object."
                    )
                source_class = next(
                    item for item in analysis.classes if item.id == source[2]
                )
                if (
                    not source_class.inheritance_supported
                    or source_class.base_class_id != step.base_class_id
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected unrelated "
                        "or unsupported base and derived classes."
                    )
                if (
                    step.result_object_id in available_objects
                    or step.result_name in used_names
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} result name and "
                        "identifier must be unique."
                    )
                ownership = {
                    "create_base_reference": "reference",
                    "create_base_pointer": "non_owning_pointer",
                    "slice_object": "value",
                }[step.step_type]
                runtime_type = (
                    step.base_class_id
                    if step.step_type == "slice_object"
                    else source[2]
                )
                available_objects[step.result_object_id or ""] = (
                    step.base_class_id or "",
                    step.result_name or "",
                    runtime_type or "",
                    ownership,
                )
                used_names.add(step.result_name or "")
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=(),
                        target_object_id=step.result_object_id or "",
                        source_object_id=step.source_object_id,
                        result_object_id=step.result_object_id,
                        result_name=step.result_name,
                        result_object_class_id=step.base_class_id,
                        expression=(
                            f"Create {step.result_name} as "
                            f"{step.base_class_id}"
                        ),
                        step_type=step.step_type,
                        static_class_id=step.base_class_id,
                        runtime_class_id=runtime_type,
                        ownership_mode=ownership,
                    )
                )
                continue
            if step.step_type == "create_owned_base_pointer":
                base_class = next(
                    (
                        item
                        for item in analysis.classes
                        if item.id == step.base_class_id
                    ),
                    None,
                )
                derived_class = next(
                    (
                        item
                        for item in analysis.classes
                        if item.id == step.derived_class_id
                    ),
                    None,
                )
                if (
                    base_class is None
                    or derived_class is None
                    or not derived_class.inheritance_supported
                    or derived_class.base_class_id != base_class.id
                    or derived_class.is_abstract
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected an invalid "
                        "owned base-pointer relationship."
                    )
                constructor = next(
                    (
                        item
                        for item in derived_class.constructors
                        if item.id == step.constructor_id
                    ),
                    None,
                )
                if constructor is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected a stale "
                        "derived constructor."
                    )
                if len(step.arguments) != len(constructor.parameters):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} constructor "
                        f"requires {len(constructor.parameters)} argument(s)."
                    )
                arguments = tuple(
                    _prepare_argument(
                        parameter.value_type,
                        argument,
                        f"{test.name} step {step_index + 1} argument",
                        test_index=scenario_index,
                        parameter_index=step_index * 20 + index,
                    )
                    for index, (parameter, argument) in enumerate(
                        zip(constructor.parameters, step.arguments, strict=True)
                    )
                )
                if (
                    step.result_object_id in available_objects
                    or step.result_name in used_names
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} pointer name and "
                        "identifier must be unique."
                    )
                if step.expected_outcome != "throws":
                    available_objects[step.result_object_id or ""] = (
                        base_class.id,
                        step.result_name or "",
                        derived_class.id,
                        "owned_pointer",
                    )
                    used_names.add(step.result_name or "")
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=arguments,
                        target_object_id=step.result_object_id or "",
                        result_object_id=step.result_object_id,
                        result_name=step.result_name,
                        expression=(
                            f"Create {step.result_name} owning "
                            f"{derived_class.name} as {base_class.name} pointer"
                        ),
                        step_type=step.step_type,
                        static_class_id=base_class.id,
                        runtime_class_id=derived_class.id,
                        ownership_mode="owned_pointer",
                        constructor=constructor,
                        constructor_class=derived_class,
                        virtual_destructor=base_class.has_virtual_destructor,
                    )
                )
                continue
            if step.step_type == "delete_base_pointer":
                target = available_objects.get(step.target_object_id or "")
                if target is None or target[3] != "owned_pointer":
                    raise ValueError(
                        f"{test.name} step {step_index + 1} can delete only "
                        "an available owned base pointer."
                    )
                if step.target_object_id in deleted_owned_pointers:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} repeats deletion."
                    )
                base_class = next(
                    item for item in analysis.classes if item.id == target[0]
                )
                deleted_owned_pointers.add(step.target_object_id or "")
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=(),
                        target_object_id=step.target_object_id or "",
                        expression=f"Delete {target[1]} through {target[0]}*",
                        step_type=step.step_type,
                        static_class_id=target[0],
                        runtime_class_id=target[2],
                        ownership_mode=target[3],
                        virtual_destructor=base_class.has_virtual_destructor,
                    )
                )
                continue
            if step.step_type == "dynamic_cast":
                source = available_objects.get(step.source_object_id or "")
                target_class = next(
                    (
                        item
                        for item in analysis.classes
                        if item.id == step.cast_target_class_id
                    ),
                    None,
                )
                static_class = next(
                    (
                        item
                        for item in analysis.classes
                        if source and item.id == source[0]
                    ),
                    None,
                )
                if (
                    source is None
                    or target_class is None
                    or static_class is None
                    or not any(
                        method.is_virtual for method in static_class.methods
                    )
                    and not static_class.has_virtual_destructor
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} has an invalid "
                        "dynamic-cast source or target."
                    )
                related_ids = {
                    source[0],
                    source[2],
                    static_class.base_class_id,
                    *static_class.derived_class_ids,
                }
                if target_class.id not in related_ids:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} selected an "
                        "unrelated dynamic-cast target."
                    )
                prepared_steps.append(
                    PreparedObjectStep(
                        method=None,
                        arguments=(),
                        target_object_id=step.source_object_id or "",
                        expression=(
                            f"Cast {source[1]} to {target_class.name}"
                        ),
                        step_type=step.step_type,
                        static_class_id=source[0],
                        runtime_class_id=source[2],
                        ownership_mode=source[3],
                        cast_target_class_id=target_class.id,
                        cast_mode=step.cast_mode,
                        expected_cast_result=step.expected_cast_result,
                    )
                )
                continue
            target_id = step.target_object_id or (
                requested_objects[0].object_id
                if requested_objects
                else ""
            )
            target = available_objects.get(target_id)
            if target is None:
                raise ValueError(
                    f"{test.name} step {step_index + 1} references an "
                    "unavailable object. Objects expected to fail "
                    "construction cannot be used later."
                )
            if target_id in deleted_owned_pointers:
                raise ValueError(
                    f"{test.name} step {step_index + 1} cannot use a deleted "
                    "base pointer."
                )
            target_class = concrete_classes_by_object_id.get(target_id) or next(
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
                if creates_object and step.expected_outcome != "throws":
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
                        source[2],
                        "value",
                    )
                    concrete_classes_by_object_id[
                        step.result_object_id
                    ] = target_class
                    used_names.add(step.result_name)
                if step.step_type in {"move_construct", "move_assign"}:
                    moved_from.add(source_id)
                if step.step_type in {"copy_assign", "move_assign"}:
                    moved_from.discard(target_id)
                readable = {
                    "copy_construct": (
                        f"Copy constructed {step.result_name} from {source[1]}"
                        if step.result_name
                        else f"Copy construction from {source[1]}"
                    ),
                    "copy_assign": f"{target[1]} = {source[1]}",
                    "self_assign": f"{target[1]} = {target[1]}",
                    "move_construct": (
                        f"Move constructed {step.result_name} from {source[1]}"
                        if step.result_name
                        else f"Move construction from {source[1]}"
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
                            target_class.name if creates_object else None
                        ),
                    )
                )
                continue
            if target_id in moved_from:
                raise ValueError(
                    f"{test.name} step {step_index + 1} cannot use a moved-from object."
                )
            if step.step_type in {
                "method",
                "observer",
                "polymorphic_method",
            }:
                method = next(
                    (
                        candidate
                        for candidate in target_class.methods
                        if candidate.id == step.method_id
                    ),
                    None,
                )
                if (
                    method is None
                    and target_class.template_kind == "class_template"
                ):
                    definition = next(
                        (
                            item
                            for item in analysis.classes
                            if item.id == target_class.id
                        ),
                        None,
                    )
                    definition_index = next(
                        (
                            index
                            for index, candidate in enumerate(
                                definition.methods if definition else ()
                            )
                            if candidate.id == step.method_id
                        ),
                        None,
                    )
                    if (
                        definition_index is not None
                        and definition_index < len(target_class.methods)
                    ):
                        method = target_class.methods[definition_index]
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
                if (
                    step.expected_outcome != "throws"
                    and is_void == (step.expected_return is not None)
                ):
                    raise ValueError(
                        f"{test.name} step {step_index + 1} has an invalid "
                        "expected return."
                    )
                if not is_void and step.expected_outcome != "throws":
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
                        static_class_id=target[0],
                        runtime_class_id=target[2],
                        ownership_mode=target[3],
                    )
                )
                continue
            operator = None
            if target_class.template_kind == "class_template":
                definition = next(
                    (
                        item
                        for item in analysis.classes
                        if item.id == target_class.id
                    ),
                    None,
                )
                definition_index = next(
                    (
                        index
                        for index, candidate in enumerate(
                            definition.operators if definition else ()
                        )
                        if candidate.id == step.operator_id
                    ),
                    None,
                )
                if (
                    definition_index is not None
                    and definition_index < len(target_class.operators)
                ):
                    operator = target_class.operators[definition_index]
            if operator is None:
                operator = next(
                    (
                        candidate
                        for object_class in (
                            tuple(concrete_classes_by_object_id.values())
                            + analysis.classes
                        )
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
            if (
                operator.return_kind == "value"
                and step.expected_outcome != "throws"
            ):
                if step.expected_return is None or operator.return_value_type is None:
                    raise ValueError(
                        f"{test.name} step {step_index + 1} requires an expected value."
                    )
                _safe_value_literal(
                    operator.return_value_type,
                    step.expected_return,
                    f"{test.name} step {step_index + 1} expected return",
                )
            elif (
                operator.return_kind == "object_value"
                and step.expected_outcome != "throws"
            ):
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
                    operator.return_object_class_id or "",
                    "value",
                )
                concrete_classes_by_object_id[
                    step.result_object_id
                ] = target_class
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
                    result_object_class_id=(
                        target_class.name
                        if operator.return_kind == "object_value"
                        else None
                    ),
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
        if function.template_kind == "function_template":
            mode = request.template_argument_mode or (
                "deduced"
                if function.template_argument_mode == "deduced"
                else "explicit"
            )
            supplied = tuple(
                TemplateArgument(
                    parameter_name=argument.parameter_name,
                    kind=argument.kind,
                    value=argument.value,
                    used_default=argument.use_default,
                )
                for argument in request.template_arguments
            )
            try:
                function = instantiate_function_template(
                    function,
                    supplied,
                    argument_mode=mode,
                    call_arguments=tuple(request.tests[0].arguments),
                    unqualified_vector_allowed=bool(
                        re.search(
                            r"\busing\s+namespace\s+std\s*;",
                            request.code,
                        )
                    ),
                )
            except ValueError as error:
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=str(error),
                    function=_function_response(function),
                    tests=[],
                )
        elif request.template_argument_mode or request.template_arguments:
            return RunTestsResponse(
                mode="function",
                success=False,
                input_error=(
                    "Template settings cannot be used with a non-template "
                    "function."
                ),
                function=_function_response(function),
                tests=[],
            )
        mutation_capable_parameters = [
            parameter
            for parameter in function.parameters
            if parameter.value_type.passing in {"mutable_reference", "scalar_pointer"}
            or (
                parameter.value_type.passing == "array_pointer"
                and not parameter.value_type.element_const
            )
            or (
                parameter.value_type.kind == "iterator"
                and parameter.value_type.iterator_const is False
                and parameter.value_type.iterator_role in {"single", "range_begin"}
            )
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
            # Required: non-iterator mutable params must always be present.
            # Optional: non-const mutable iterator groups may be omitted.
            _required_mutation_names = {
                parameter.name
                for parameter in mutation_capable_parameters
                if parameter.value_type.passing
                in {"mutable_reference", "scalar_pointer", "array_pointer"}
            }
            _optional_mutation_names = {
                parameter.name
                for parameter in mutation_capable_parameters
            } - _required_mutation_names
            _all_mutation_capable_names = (
                _required_mutation_names | _optional_mutation_names
            )
            if any(
                not _required_mutation_names.issubset(set(expectations))
                or not set(expectations).issubset(_all_mutation_capable_names)
                for expectations in expectation_maps
            ):
                return RunTestsResponse(
                    mode="function",
                    success=False,
                    input_error=(
                        "Every mutable parameter must have an expected "
                        "final value; iterator groups are optional. "
                        "Immutable parameters cannot have mutation "
                        "expectations."
                    ),
                    function=_function_response(function),
                    tests=[],
                )
            # Only capture/compare iterators that the caller explicitly opted in to.
            _active_optional_names = set().union(
                *(set(exp) & _optional_mutation_names for exp in expectation_maps)
            )
            mutation_parameter_names = tuple(
                parameter.name
                for parameter in mutation_capable_parameters
                if parameter.name
                in (_required_mutation_names | _active_optional_names)
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
                _iter_return_backing_idx: int | None = (
                    function.return_value_type.iterator_group_index
                    if (
                        function.return_value_type.kind == "iterator"
                        and function.return_value_type.supported
                    )
                    else None
                )
                required_mutable_parameters = [
                    parameter
                    for param_idx, parameter in enumerate(function.parameters)
                    if parameter.value_type.passing
                    in {"mutable_reference", "scalar_pointer"}
                    and param_idx != _iter_return_backing_idx
                ]
                if (
                    test.expected_outcome != "throws"
                    and
                    required_mutable_parameters
                    and not mutation_parameter_names
                ):
                    raise ValueError(
                        f"{test.name} must provide expected final values for "
                        "every mutable parameter."
                    )
                if (
                    test.expected_outcome != "throws"
                    and
                    not mutation_parameter_names
                    and is_void
                    and test.expected_stdout is None
                ):
                    raise ValueError(
                        f"{test.name} must provide expected output for "
                        "the selected void function."
                    )
                if (
                    test.expected_outcome != "throws"
                    and
                    not is_void
                    and test.expected_return is None
                ):
                    raise ValueError(
                        f"{test.name} must provide an expected return value "
                        "for the selected non-void function."
                    )
                if is_void and test.expected_outcome == "return_value":
                    raise ValueError(
                        f"{test.name} cannot expect a return value from a "
                        "void function."
                    )
                if not is_void and test.expected_outcome == "return_void":
                    raise ValueError(
                        f"{test.name} cannot expect void completion from a "
                        "non-void function."
                    )
                iterator_args = _prepare_iterator_arguments(
                    function,
                    list(test.arguments),
                    test_index,
                )
                prepared_arguments = [
                    iterator_args[parameter_index]
                    if parameter_index in iterator_args
                    else _prepare_argument(
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
                        if mutable_parameter.value_type.kind == "iterator":
                            pass
                        elif mutable_parameter.value_type.kind in {
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
                if (
                    not is_void
                    and test.expected_outcome != "throws"
                    and function.return_value_type.kind != "iterator"
                ):
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

    try:
        provider = select_execution_provider()
    except ValueError as error:
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        ) from error
    provider_name = provider.name
    provider_unavailable: str | None = None
    provider_capabilities: ProviderCapabilities | None = None
    if request.run_memory_checks:
        provider_name, selected_provider, provider_unavailable = (
            select_memory_provider()
        )
        provider = selected_provider if selected_provider else None
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
        provider_capabilities = provider.capabilities()

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
            sanitizer_capabilities = (
                SanitizerCapabilities(
                    provider_capabilities.address_sanitizer_available,
                    provider_capabilities.undefined_behavior_sanitizer_available,
                    provider_capabilities.leak_sanitizer_available
                    or provider_capabilities.valgrind_available,
                )
                if provider_capabilities is not None
                else None
            )
            compile_error, sanitizer_unavailable = _compile_executable(
                working_directory,
                compiler=compiler,
                timeout_seconds=compile_timeout_seconds,
                run_memory_checks=request.run_memory_checks,
                sanitizer_capabilities=sanitizer_capabilities,
                provider=provider,
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
                            if provider is not None
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
                            provider_capabilities.runtime_available
                            if provider_capabilities
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
                        provider_capabilities.runtime_available
                        if provider_capabilities
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
                    provider=provider,
                    capabilities=provider_capabilities,
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
                        provider_capabilities.runtime_available
                        if provider_capabilities
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
                    provider=provider,
                    capabilities=provider_capabilities,
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
                        provider_capabilities.runtime_available
                        if provider_capabilities
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
                provider=provider,
                capabilities=provider_capabilities,
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
                    provider_capabilities.runtime_available
                    if provider_capabilities
                    else None
                ),
                function=_function_response(function),
                tests=function_results,
            )
    except CompilerServiceError:
        raise
    except (OSError, ValueError) as error:
        raise CompilerServiceError(
            "test_execution_failed",
            "The isolated C++ runner could not compile or run the tests.",
            503,
        ) from error
    finally:
        if provider is not None:
            provider.close()


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
