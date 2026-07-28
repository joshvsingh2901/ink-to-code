import ctypes
import json
import math
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.schemas.test_execution import (
    FunctionResponse,
    FunctionChannelResult,
    FunctionCombinedTestResult,
    FunctionMutationChannelResult,
    FunctionRunTestsRequest,
    FunctionTestCase,
    FunctionMutationTestResult,
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
from app.services.function_analysis import (
    FunctionAnalysis,
    FunctionSignature,
    STRING_TYPE,
    ValueType,
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
    function_stdout: str = ""
    result_metadata: str | None = None


@dataclass(frozen=True)
class HarnessArgument:
    expression: str
    declarations: tuple[str, ...] = ()
    array_element_count: int | None = None
    mutation_expression: str | None = None


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
) -> ProcessOutput:
    stdin_path = working_directory / "test-input.txt"
    stdout_path = working_directory / "test-stdout.txt"
    stderr_path = working_directory / "test-stderr.txt"
    function_stdout_path = working_directory / "function-stdout.txt"
    result_path = working_directory / "function-result.json"
    result_temp_path = working_directory / "function-result.json.tmp"
    result_path.unlink(missing_ok=True)
    function_stdout_path.unlink(missing_ok=True)
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
                or (
                    _file_exceeds_limit(function_stdout_path)
                )
                or (
                    _file_exceeds_limit(result_temp_path)
                )
                or (
                    _file_exceeds_limit(result_path)
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
) -> list[int | float | bool | str]:
    element_type = value_type.element_type
    if element_type is None:
        raise ValueError(f"{label} uses an unsupported vector type.")
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
                serialized_value = _collection_output(
                    mutable_expression,
                    element_type,
                    length_expression,
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
                serialized_return = _collection_output(
                    "inktocode_return_value",
                    element_type,
                    "inktocode_return_value.size()",
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


def _function_results(
    executable: Path,
    working_directory: Path,
    request: FunctionRunTestsRequest,
    function: FunctionSignature,
    mutation_parameter_names: tuple[str, ...],
    *,
    timeout_seconds: float,
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
                    stderr=stderr,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    output_limited=output.output_limited,
                    match_type=match_type,
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
                stderr=stderr,
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

    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-tests-") as directory:
            working_directory = Path(directory)
            executable = working_directory / "program"
            source = (
                _build_function_harness(
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
                function,
                mutation_parameter_names,
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
    comparison_mode: str = "whitespace_tolerant",
) -> RunTestsResponse:
    return run_test_request(
        ProgramRunTestsRequest(
            mode="program",
            code=code,
            language="cpp",
            comparison_mode=comparison_mode,
            tests=tests,
        ),
        compiler=compiler,
        compile_timeout_seconds=compile_timeout_seconds,
        test_timeout_seconds=test_timeout_seconds,
    )
