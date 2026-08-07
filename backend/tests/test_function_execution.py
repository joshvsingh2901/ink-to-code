import asyncio
import json
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.test_execution import (
    FunctionMutationExpectation,
    FunctionRunTestsRequest,
    FunctionTestCase,
    ProgramRunTestsRequest,
    ProgramTestCase,
)
from app.services import test_execution
from app.services.function_analysis import analyze_test_mode
from app.services.test_execution import run_test_request


def function_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert len(analysis.functions) == 1
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[0].id,
        tests=[
            FunctionTestCase(
                name="Test 1",
                arguments=arguments,
                expected_return=expected_return,
            )
        ],
    )


def mutation_request(
    code: str,
    *,
    arguments: list[str],
    expected_final_arguments: dict[str, str],
    target_index: int = 0,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.functions
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[target_index].id,
        tests=[
            FunctionTestCase(
                name="Test 1",
                arguments=arguments,
                expected_final_arguments=expected_final_arguments,
            )
        ],
    )


def multiple_mutation_request(
    code: str,
    *,
    arguments: list[str],
    expected_mutations: list[tuple[str, str]],
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert len(analysis.functions) == 1
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[0].id,
        tests=[
            FunctionTestCase(
                name="Test 1",
                arguments=arguments,
                expected_mutations=[
                    FunctionMutationExpectation(
                        parameter_id=parameter_id,
                        expected_final_value=expected_value,
                    )
                    for parameter_id, expected_value in expected_mutations
                ],
            )
        ],
    )


def combined_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str | None = None,
    expected_stdout: str | None = None,
    check_stdout: bool = False,
    expected_mutations: list[tuple[str, str]] | None = None,
    comparison_mode: str = "whitespace_tolerant",
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert len(analysis.functions) == 1
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[0].id,
        comparison_mode=comparison_mode,
        tests=[
            FunctionTestCase(
                name="Combined test",
                arguments=arguments,
                expected_return=expected_return,
                expected_stdout=expected_stdout,
                check_stdout=check_stdout,
                expected_mutations=(
                    [
                        FunctionMutationExpectation(
                            parameter_id=name,
                            expected_final_value=value,
                        )
                        for name, value in expected_mutations
                    ]
                    if expected_mutations is not None
                    else None
                ),
            )
        ],
    )


async def api_request(path: str, payload: object):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(path, json=payload)


def test_detects_supported_function_and_parameters():
    analysis = analyze_test_mode(
        "int findMax(int a, int b) { return a > b ? a : b; }"
    )

    assert analysis.mode == "function"
    assert len(analysis.functions) == 1
    assert analysis.functions[0].display == "findMax(int a, int b)"
    assert [
        (parameter.name, parameter.type)
        for parameter in analysis.functions[0].parameters
    ] == [("a", "int"), ("b", "int")]


MULTI_FUNCTION_SOURCE = """
int square(int value) { return value * value; }
int add(int left, int right) { return left + right; }
int solve(int value) { return add(square(value), 1); }
""".strip()


def test_detects_multiple_supported_functions_in_source_order():
    analysis = analyze_test_mode(MULTI_FUNCTION_SOURCE)

    assert analysis.mode == "function"
    assert [function.id for function in analysis.functions] == [
        "square(int)->int",
        "add(int,int)->int",
        "solve(int)->int",
    ]


def test_unsupported_functions_are_excluded_when_supported_targets_exist():
    analysis = analyze_test_mode(
        "int pointerValue(int *value) { return *value; }\n"
        "int identity(int value) { return value; }"
    )

    assert analysis.mode == "function"
    assert [function.id for function in analysis.functions] == [
        "pointerValue(int*)->int",
        "identity(int)->int"
    ]


def test_overloaded_function_names_are_rejected():
    analysis = analyze_test_mode(
        "int value(int input) { return input; }\n"
        "double value(double input) { return input; }"
    )

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert "Overloaded function" in analysis.message


def multi_function_request(
    target_function: str,
    *,
    arguments: list[str],
    expected_return: str,
) -> FunctionRunTestsRequest:
    return FunctionRunTestsRequest(
        mode="function",
        code=MULTI_FUNCTION_SOURCE,
        language="cpp",
        target_function=target_function,
        tests=[
            FunctionTestCase(
                name="Selected target",
                arguments=arguments,
                expected_return=expected_return,
            )
        ],
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("target", "arguments", "expected"),
    [
        ("square(int)->int", ["4"], "16"),
        ("add(int,int)->int", ["4", "5"], "9"),
        ("solve(int)->int", ["3"], "10"),
    ],
)
def test_selected_function_alone_is_called(
    target: str,
    arguments: list[str],
    expected: str,
):
    result = run_test_request(
        multi_function_request(
            target,
            arguments=arguments,
            expected_return=expected,
        )
    )

    assert result.success is True
    assert result.function is not None
    assert result.function.id == target
    assert result.tests[0].passed is True


def test_invalid_target_is_rejected_before_compilation(monkeypatch):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        multi_function_request(
            "missing(int)->int",
            arguments=["1"],
            expected_return="1",
        )
    )

    assert result.success is False
    assert result.input_error
    assert "no longer available" in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("code", "arguments", "expected"),
    [
        (
            "int findMax(int a, int b) { return a > b ? a : b; }",
            ["1", "2"],
            "2",
        ),
        ("long add(long a, long b) { return a + b; }", ["10", "25"], "35"),
        (
            "long long add(long long a, long long b) { return a + b; }",
            ["3000000000", "4"],
            "3000000004",
        ),
        ("bool isPositive(int x) { return x > 0; }", ["-3"], "false"),
        ("double square(double x) { return x * x; }", ["2.5"], "6.25"),
        ("int answer() { return 42; }", [], "42"),
    ],
)
def test_supported_function_types_execute(
    code: str,
    arguments: list[str],
    expected: str,
):
    result = run_test_request(
        function_request(
            code,
            arguments=arguments,
            expected_return=expected,
        )
    )

    assert result.mode == "function"
    assert result.success is True
    assert result.function is not None
    assert result.tests[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_parameters_are_passed_in_declared_order():
    result = run_test_request(
        function_request(
            "int digits(int hundreds, int tens, int ones) "
            "{ return hundreds * 100 + tens * 10 + ones; }",
            arguments=["1", "2", "3"],
            expected_return="123",
        )
    )

    assert result.success is True
    assert result.tests[0].arguments == ["1", "2", "3"]


def test_invalid_argument_count_is_rejected_before_compilation(monkeypatch):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        function_request(
            "int add(int a, int b) { return a + b; }",
            arguments=["1"],
            expected_return="1",
        )
    )

    assert result.input_error
    assert "requires 2 argument" in result.input_error
    assert invoked is False


@pytest.mark.parametrize(
    ("code", "arguments", "expected_message"),
    [
        (
            "int identity(int value) { return value; }",
            ["1 + 2"],
            "signed decimal int",
        ),
        (
            "double identity(double value) { return value; }",
            ["not-a-number"],
            "finite decimal double",
        ),
        (
            "bool identity(bool value) { return value; }",
            ["1"],
            "true or false",
        ),
    ],
)
def test_invalid_argument_values_are_rejected(
    code: str,
    arguments: list[str],
    expected_message: str,
):
    result = run_test_request(
        function_request(
            code,
            arguments=arguments,
            expected_return="0" if "bool" not in code else "false",
        )
    )

    assert result.success is False
    assert result.input_error
    assert expected_message in result.input_error
    assert result.tests == []


def test_source_with_main_remains_program_mode():
    source = "int helper() { return 1; }\nint main() { return helper(); }"
    analysis = analyze_test_mode(source)

    assert analysis.mode == "program"


def test_mode_endpoint_returns_function_metadata():
    response = asyncio.run(
        api_request(
            "/api/test-mode",
            {
                "code": "int findMax(int a, int b) { return a > b ? a : b; }",
                "language": "cpp",
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "function"
    functions = response.json()["functions"]
    assert len(functions) == 1
    fn = functions[0]
    assert fn["id"] == "findMax(int,int)->int"
    assert fn["name"] == "findMax"
    assert fn["return_type"] == "int"
    assert fn["display"] == "findMax(int a, int b)"
    # Verify scalar metadata core fields; container extension fields are None for scalars
    for metadata in [fn["return_type_metadata"]] + [p["type_metadata"] for p in fn["parameters"]]:
        assert metadata["kind"] == "scalar"
        assert metadata["display_type"] == "int"
        assert metadata["scalar_type"] == "int"
        assert metadata["element_type"] is None
        assert metadata["vector_depth"] is None
        assert metadata["passing"] == "value"
        assert metadata["size_parameter_name"] is None
        assert metadata.get("container_name") is None
        assert metadata.get("container_family") is None


def vector_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str,
    target_index: int = 0,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.mode == "function"
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[target_index].id,
        tests=[
            FunctionTestCase(
                name="Vector test",
                arguments=arguments,
                expected_return=expected_return,
            )
        ],
    )


def void_request(
    code: str,
    *,
    arguments: list[str],
    expected_stdout: str,
    comparison_mode: str = "whitespace_tolerant",
    target_index: int = 0,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.mode == "function"
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[target_index].id,
        comparison_mode=comparison_mode,
        tests=[
            FunctionTestCase(
                name="Void output test",
                arguments=arguments,
                expected_stdout=expected_stdout,
            )
        ],
    )


@pytest.mark.parametrize(
    ("declaration", "passing"),
    [
        ("std::vector<int> values", "value"),
        ("const std::vector<int>& values", "const_reference"),
        ("std::vector<int> const& values", "const_reference"),
    ],
)
def test_vector_parameter_metadata_is_structured(
    declaration: str,
    passing: str,
):
    analysis = analyze_test_mode(
        f"#include <vector>\nint size({declaration}) "
        "{ return static_cast<int>(values.size()); }"
    )

    assert analysis.mode == "function"
    metadata = analysis.functions[0].parameters[0].value_type
    assert metadata.kind == "vector"
    assert metadata.element_type == "int"
    assert metadata.passing == passing


def test_unqualified_vector_is_supported_with_using_namespace_std():
    analysis = analyze_test_mode(
        "#include <vector>\nusing namespace std;\n"
        "int size(vector<int> values) { return values.size(); }"
    )

    assert analysis.mode == "function"
    assert analysis.functions[0].parameters[0].type == "std::vector<int>"


def test_unqualified_vector_without_namespace_is_rejected():
    analysis = analyze_test_mode(
        "int size(vector<int> values) { return values.size(); }"
    )

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert "using namespace std" in analysis.message


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("element_type", "values", "expected"),
    [
        ("int", "[1, 2, 3, 4]", "10"),
        ("long", "-2, 5, 10", "13"),
        ("long long", "-3000000000 3000000004", "4"),
        ("double", "[1.5, -2e0, 3.25]", "2.75"),
        ("bool", "[true, false, true]", "2"),
    ],
)
def test_supported_vector_parameters_execute(
    element_type: str,
    values: str,
    expected: str,
):
    source = (
        "#include <vector>\n"
        f"{'double' if element_type == 'double' else 'long long'} "
        f"sum(std::vector<{element_type}> values) {{\n"
        f"    {'double' if element_type == 'double' else 'long long'} total = 0;\n"
        "    for (auto value : values) total += value;\n"
        "    return total;\n"
        "}"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[values],
            expected_return=expected,
        )
    )

    assert result.success is True
    assert result.tests[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_empty_vector_and_mixed_scalar_vector_parameters_execute():
    source = """
#include <vector>
bool contains(std::vector<int> values, int target)
{
    for (int value : values) if (value == target) return true;
    return false;
}
""".strip()
    empty_result = run_test_request(
        vector_request(
            source,
            arguments=["[]", "7"],
            expected_return="false",
        )
    )
    populated_result = run_test_request(
        vector_request(
            source,
            arguments=["3 7 9", "7"],
            expected_return="true",
        )
    )

    assert empty_result.success is True
    assert populated_result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("element_type", "body", "values", "expected", "actual"),
    [
        (
            "int",
            "for (int &value : values) value *= 2;",
            "[1, 2, 3]",
            "2 4 6",
            "[2, 4, 6]",
        ),
        ("int", "values.clear();", "[1]", "[]", "[]"),
        (
            "double",
            "for (double &value : values) value /= 2;",
            "[1, 2.5]",
            "[0.5, 1.25]",
            "[0.5, 1.25]",
        ),
        (
            "bool",
            "for (std::size_t i = 0; i < values.size(); ++i) "
            "values[i] = !values[i];",
            "[true, false]",
            "[false, true]",
            "[false, true]",
        ),
    ],
)
def test_vector_returns_are_serialized_and_compared_structurally(
    element_type: str,
    body: str,
    values: str,
    expected: str,
    actual: str,
):
    source = (
        "#include <vector>\n"
        f"std::vector<{element_type}> transform("
        f"std::vector<{element_type}> values) {{ {body} return values; }}"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[values],
            expected_return=expected,
        )
    )

    assert result.success is True
    assert result.tests[0].actual_return == actual
    assert result.tests[0].match_type in {"exact", "whitespace_normalized"}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize("expected", ["[2, 6, 4]", "[2, 4]"])
def test_vector_result_order_and_length_must_match(expected: str):
    source = (
        "#include <vector>\n"
        "std::vector<int> doubled(std::vector<int> values) "
        "{ for (int &value : values) value *= 2; return values; }"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=["[1, 2, 3]"],
            expected_return=expected,
        )
    )

    assert result.success is False
    assert result.tests[0].match_type == "mismatch"
    assert result.tests[0].actual_return == "[2, 4, 6]"


@pytest.mark.parametrize(
    ("element_type", "value", "message"),
    [
        ("int", "[1,,2]", "empty vector element"),
        ("int", "", "use [] for empty"),
        ("int", "[1, 2.5]", "signed decimal int"),
        ("int", "{foo()}", "not C++ expressions"),
        ("int", "std::vector<int>(3)", "not C++ expressions"),
        ("bool", "[true, maybe]", "true or false"),
    ],
)
def test_invalid_vector_input_is_rejected_before_compilation(
    element_type: str,
    value: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            f"int sum(std::vector<{element_type}> values) "
            "{ return values.size(); }",
            arguments=[value],
            expected_return="0",
        )
    )

    assert result.success is False
    assert result.input_error
    assert message in result.input_error
    assert invoked is False


def test_invalid_expected_vector_is_rejected_before_compilation(monkeypatch):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            "std::vector<int> identity(std::vector<int> values) "
            "{ return values; }",
            arguments=["[1, 2]"],
            expected_return="[1, nope]",
        )
    )

    assert result.input_error
    assert "expected return element 2" in result.input_error
    assert invoked is False


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "int size(std::vector<int>* values) { return 0; }",
            "Vector pointer",
        ),
        (
            "std::vector<float> values() { return {}; }",
            "Unsupported vector element",
        ),
    ],
)
def test_unsupported_vector_signatures_have_clear_messages(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert message in analysis.message


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_vector_target_can_call_vector_helper():
    source = """
#include <vector>
int sum(std::vector<int> values)
{
    int total = 0;
    for (int value : values) total += value;
    return total;
}
int averageRounded(std::vector<int> values)
{
    return sum(values) / static_cast<int>(values.size());
}
""".strip()
    analysis = analyze_test_mode(source)
    assert [function.name for function in analysis.functions] == [
        "sum",
        "averageRounded",
    ]
    result = run_test_request(
        vector_request(
            source,
            arguments=["[2, 4, 6]"],
            expected_return="4",
            target_index=1,
        )
    )

    assert result.success is True


@pytest.mark.parametrize(
    ("declaration", "passing"),
    [
        ("std::string text", "value"),
        ("const std::string& text", "const_reference"),
        ("std::string const& text", "const_reference"),
    ],
)
def test_string_parameter_metadata_is_structured(
    declaration: str,
    passing: str,
):
    analysis = analyze_test_mode(
        f"#include <string>\nstd::string identity({declaration}) "
        "{ return text; }"
    )

    assert analysis.mode == "function"
    parameter = analysis.functions[0].parameters[0].value_type
    assert parameter.kind == "scalar"
    assert parameter.scalar_type == "std::string"
    assert parameter.passing == passing
    assert analysis.functions[0].return_value_type.scalar_type == "std::string"


@pytest.mark.parametrize(
    ("declaration", "passing"),
    [
        ("std::vector<std::string> words", "value"),
        ("const std::vector<std::string>& words", "const_reference"),
        ("std::vector<std::string> const& words", "const_reference"),
    ],
)
def test_string_vector_parameter_metadata_is_structured(
    declaration: str,
    passing: str,
):
    analysis = analyze_test_mode(
        "#include <string>\n#include <vector>\n"
        f"std::vector<std::string> identity({declaration}) "
        "{ return words; }"
    )

    assert analysis.mode == "function"
    parameter = analysis.functions[0].parameters[0].value_type
    assert parameter.kind == "vector"
    assert parameter.element_type == "std::string"
    assert parameter.passing == passing


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    "value",
    [
        "Josh Singh",
        "",
        'He said "hello"',
        "path\\name",
        "first\nsecond\tvalue\rcarriage",
    ],
)
def test_string_parameter_and_return_preserve_exact_contents(value: str):
    source = (
        "#include <string>\n"
        "std::string identity(std::string value) { return value; }"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[value],
            expected_return=value,
        )
    )

    assert result.success is True
    assert result.tests[0].actual_return == value
    assert result.tests[0].match_type == "exact"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("argument", "expected", "actual"),
    [
        (
            '["hello", "world"]',
            '["hello", "world"]',
            '["hello", "world"]',
        ),
        ("[]", "[]", "[]"),
        (
            '["hello world", "second,value"]',
            '["hello world", "second,value"]',
            '["hello world", "second,value"]',
        ),
        (
            r'["a quote: \"hello\"", "path\\name"]',
            r'["a quote: \"hello\"", "path\\name"]',
            r'["a quote: \"hello\"", "path\\name"]',
        ),
    ],
)
def test_string_vector_parameter_and_return_use_canonical_serialization(
    argument: str,
    expected: str,
    actual: str,
):
    source = (
        "#include <string>\n#include <vector>\n"
        "std::vector<std::string> identity("
        "std::vector<std::string> words) { return words; }"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[argument],
            expected_return=expected,
        )
    )

    assert result.success is True
    assert result.tests[0].actual_return == actual


@pytest.mark.parametrize(
    "value",
    [
        "[hello, world]",
        '["hello",]',
        '["unterminated]',
        '["a" "b"]',
        '"hello"',
        "[1, 2]",
    ],
)
def test_malformed_string_vector_is_rejected_before_compilation(
    value: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        vector_request(
            "#include <string>\n#include <vector>\n"
            "std::vector<std::string> identity("
            "std::vector<std::string> words) { return words; }",
            arguments=[value],
            expected_return="[]",
        )
    )

    assert result.input_error
    assert "quoted" in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("hello  world", "hello world"),
        ("Hello", "hello"),
        ("hello!", "hello."),
    ],
)
def test_scalar_string_comparison_is_exact(expected: str, actual: str):
    source = (
        "#include <string>\n"
        f"std::string value() {{ return {json.dumps(actual)}; }}"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[],
            expected_return=expected,
        )
    )

    assert result.success is False
    assert result.tests[0].match_type == "mismatch"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    "expected",
    [
        '["world", "hello"]',
        '["hello"]',
        '["hello  world"]',
    ],
)
def test_string_vector_order_length_and_internal_spaces_matter(expected: str):
    source = (
        "#include <string>\n#include <vector>\n"
        "std::vector<std::string> values() "
        '{ return {"hello world", "world"}; }'
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[],
            expected_return=expected,
        )
    )

    assert result.success is False
    assert result.tests[0].match_type == "mismatch"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mixed_string_and_scalar_parameters_execute():
    source = """
#include <string>
std::string repeat(std::string value, int count)
{
    std::string result;
    for (int index = 0; index < count; ++index) result += value;
    return result;
}
""".strip()
    result = run_test_request(
        vector_request(
            source,
            arguments=["ab", "3"],
            expected_return="ababab",
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_string_functions_and_helper_calls_remain_supported():
    source = """
#include <string>
std::string greet(std::string name) { return "Hello, " + name; }
std::string shout(std::string text) { return text + "!"; }
std::string welcome(std::string name) { return shout(greet(name)); }
""".strip()
    analysis = analyze_test_mode(source)
    assert [function.name for function in analysis.functions] == [
        "greet",
        "shout",
        "welcome",
    ]
    result = run_test_request(
        vector_request(
            source,
            arguments=["Josh"],
            expected_return="Hello, Josh!",
            target_index=2,
        )
    )

    assert result.success is True


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "int size(char* value) { return 0; }",
            "Character arrays and pointers",
        ),
        (
            "int size(const char* value) { return 0; }",
            "Unsupported type",
        ),
        (
            "int size(char value[]) { return 0; }",
            "Character arrays and pointers",
        ),
    ],
)
def test_unsupported_string_signatures_are_rejected(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert message in analysis.message


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_string_function_runtime_timeout_is_preserved():
    result = run_test_request(
        vector_request(
            "#include <string>\n"
            "std::string spin(std::string value) "
            "{ while (true) {} return value; }",
            arguments=["value"],
            expected_return="value",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_string_function_output_limit_is_preserved():
    result = run_test_request(
        vector_request(
            "#include <string>\n"
            "std::string huge() { return std::string(100000, 'x'); }",
            arguments=[],
            expected_return="",
        )
    )

    assert result.tests[0].output_limited is True


def test_void_function_metadata_is_detected():
    analysis = analyze_test_mode(
        "void printDouble(int value) { (void)value; }"
    )

    assert analysis.mode == "function"
    assert analysis.functions[0].return_type == "void"
    assert analysis.functions[0].return_value_type.kind == "void"
    assert analysis.functions[0].id == "printDouble(int)->void"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("source", "arguments", "expected"),
    [
        (
            "#include <iostream>\n"
            "void printDouble(int value) { std::cout << value * 2; }",
            ["5"],
            "10",
        ),
        (
            "#include <iostream>\n#include <string>\n"
            "void greet(std::string name) "
            '{ std::cout << "Hello, " << name; }',
            ["Josh Singh"],
            "Hello, Josh Singh",
        ),
        (
            "#include <iostream>\n"
            "void values(int first, int second) "
            "{ std::cout << first << ' ' << second; }",
            ["2", "3"],
            "2 3",
        ),
        (
            "#include <iostream>\n"
            "void lines() { std::cout << \"one\\ntwo\\n\"; }",
            [],
            "one\ntwo\n",
        ),
        (
            "void silent() {}",
            [],
            "",
        ),
    ],
)
def test_void_functions_capture_stdout(
    source: str,
    arguments: list[str],
    expected: str,
):
    result = run_test_request(
        void_request(
            source,
            arguments=arguments,
            expected_stdout=expected,
        )
    )

    assert result.success is True
    assert result.tests[0].passed is True
    assert result.tests[0].actual_stdout == expected


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_output_whitespace_tolerant_comparison():
    result = run_test_request(
        void_request(
            "#include <iostream>\n"
            "void printValues() { std::cout << \"1  2\\n3 \"; }",
            arguments=[],
            expected_stdout="1 2 3",
        )
    )

    assert result.success is True
    assert result.tests[0].match_type == "whitespace_normalized"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_output_exact_comparison_and_formatting_mismatch():
    source = (
        "#include <iostream>\n"
        "void printValue() { std::cout << \"value\\n\"; }"
    )
    exact = run_test_request(
        void_request(
            source,
            arguments=[],
            expected_stdout="value\n",
            comparison_mode="exact",
        )
    )
    formatting_mismatch = run_test_request(
        void_request(
            source,
            arguments=[],
            expected_stdout="value",
            comparison_mode="exact",
        )
    )

    assert exact.success is True
    assert exact.tests[0].match_type == "exact"
    assert formatting_mismatch.success is False
    assert formatting_mismatch.tests[0].match_type == "formatting_mismatch"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_function_preserves_stderr_separately():
    result = run_test_request(
        void_request(
            "#include <iostream>\n"
            "void report() { std::cerr << \"warning\"; }",
            arguments=[],
            expected_stdout="",
        )
    )

    assert result.success is True
    assert result.tests[0].actual_stdout == ""
    assert result.tests[0].stderr == "warning"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_function_nonzero_exit_is_reported():
    result = run_test_request(
        void_request(
            "#include <cstdlib>\nvoid stop() { std::exit(7); }",
            arguments=[],
            expected_stdout="",
        )
    )

    assert result.success is False
    assert result.tests[0].exit_code == 7


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("source", "argument", "expected"),
    [
        (
            "#include <iostream>\n#include <vector>\n"
            "void printValues(const std::vector<int>& values) "
            "{ for (int value : values) std::cout << value << ' '; }",
            "[1, 2, 3]",
            "1 2 3",
        ),
        (
            "#include <iostream>\n#include <string>\n#include <vector>\n"
            "void printWords(const std::vector<std::string>& words) "
            "{ for (const auto& word : words) std::cout << word << '\\n'; }",
            '["hello world", "second"]',
            "hello world\nsecond",
        ),
    ],
)
def test_void_functions_accept_supported_vector_arguments(
    source: str,
    argument: str,
    expected: str,
):
    result = run_test_request(
        void_request(
            source,
            arguments=[argument],
            expected_stdout=expected,
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_and_non_void_targets_remain_selectable_with_helpers():
    source = """
#include <iostream>
int add(int left, int right) { return left + right; }
void printSum(int left, int right) { std::cout << add(left, right); }
""".strip()
    analysis = analyze_test_mode(source)
    assert [function.name for function in analysis.functions] == [
        "add",
        "printSum",
    ]
    result = run_test_request(
        void_request(
            source,
            arguments=["2", "3"],
            expected_stdout="5",
            target_index=1,
        )
    )

    assert result.success is True


def test_expected_return_is_rejected_for_void_target():
    source = "void printValue(int value) { (void)value; }"
    analysis = analyze_test_mode(source)
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=analysis.functions[0].id,
            tests=[
                FunctionTestCase(
                    name="Wrong shape",
                    arguments=["1"],
                    expected_return="",
                )
            ],
        )
    )

    assert result.input_error
    assert "expected output" in result.input_error


def test_expected_stdout_is_rejected_for_non_void_target():
    source = "int value() { return 1; }"
    analysis = analyze_test_mode(source)
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=analysis.functions[0].id,
            tests=[
                FunctionTestCase(
                    name="Wrong shape",
                    arguments=[],
                    expected_stdout="1",
                )
            ],
        )
    )

    assert result.input_error
    assert "expected return" in result.input_error


def test_void_function_test_requires_an_expected_field():
    response = asyncio.run(
        api_request(
            "/api/run-tests",
            {
                "mode": "function",
                "code": "void silent() {}",
                "language": "cpp",
                "target_function": "silent()->void",
                "tests": [{"name": "Missing output", "arguments": []}],
            },
        )
    )

    assert response.status_code == 422


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_run_tests_endpoint_returns_void_function_output_shape():
    response = asyncio.run(
        api_request(
            "/api/run-tests",
            {
                "mode": "function",
                "code": (
                    "#include <iostream>\n"
                    "void printValue(int value) { std::cout << value; }"
                ),
                "language": "cpp",
                "target_function": "printValue(int)->void",
                "comparison_mode": "exact",
                "tests": [
                    {
                        "name": "Print",
                        "arguments": ["5"],
                        "expected_stdout": "5",
                    }
                ],
            },
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["function"]["return_type_metadata"]["kind"] == "void"
    assert body["tests"][0]["arguments"] == ["5"]
    assert body["tests"][0]["expected_stdout"] == "5"
    assert body["tests"][0]["actual_stdout"] == "5"
    assert "expected_return" not in body["tests"][0]


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_function_runtime_timeout_is_preserved():
    result = run_test_request(
        void_request(
            "void spin() { while (true) {} }",
            arguments=[],
            expected_stdout="",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_function_output_limit_is_preserved():
    result = run_test_request(
        void_request(
            "#include <iostream>\n"
            "void noisy() { while (true) std::cout << "
            "\"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"; }",
            arguments=[],
            expected_stdout="",
        )
    )

    assert result.tests[0].output_limited is True


@pytest.mark.parametrize(
    "declaration",
    [
        "int values[]",
        "int values []",
        "int* values",
        "int *values",
    ],
)
def test_array_parameter_metadata_links_explicit_size(
    declaration: str,
):
    analysis = analyze_test_mode(
        f"int sum({declaration}, int size) {{ return size; }}"
    )

    assert analysis.mode == "function"
    array_type = analysis.functions[0].parameters[0].value_type
    assert array_type.kind == "array"
    assert array_type.display_type == "int[]"
    assert array_type.element_type == "int"
    assert array_type.passing == "array_pointer"
    assert array_type.size_parameter_name == "size"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("element_type", "values", "size", "expected"),
    [
        ("int", "[1, 2, 3, 4]", "4", "10"),
        ("long", "-2, 5, 10", "3", "13"),
        ("long long", "-3000000000 3000000004", "2", "4"),
        ("double", "[1.5, -2e0, 3.25]", "3", "2.75"),
        ("bool", "[true, false, true]", "3", "2"),
    ],
)
def test_supported_numeric_array_types_execute(
    element_type: str,
    values: str,
    size: str,
    expected: str,
):
    accumulator_type = "double" if element_type == "double" else "long long"
    source = (
        f"{accumulator_type} sum({element_type} values[], int size) {{\n"
        f"    {accumulator_type} total = 0;\n"
        "    for (int index = 0; index < size; ++index) total += values[index];\n"
        "    return total;\n"
        "}"
    )
    result = run_test_request(
        vector_request(
            source,
            arguments=[values, size],
            expected_return=expected,
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_pointer_spelling_executes_with_local_array_storage():
    result = run_test_request(
        vector_request(
            "int maximum(int* values, int count) "
            "{ int result = values[0]; "
            "for (int i = 1; i < count; ++i) "
            "if (values[i] > result) result = values[i]; return result; }",
            arguments=["[4, 9, 2]", "3"],
            expected_return="9",
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("values", "size", "expected"),
    [
        ("[]", "0", "0"),
        ("[1, 2, 3, 4]", "3", "6"),
        ("[1, 2, 3, 4]", "4", "10"),
    ],
)
def test_array_size_zero_smaller_and_equal_are_supported(
    values: str,
    size: str,
    expected: str,
):
    result = run_test_request(
        vector_request(
            "int sum(int values[], int size) "
            "{ int total = 0; for (int i = 0; i < size; ++i) "
            "total += values[i]; return total; }",
            arguments=[values, size],
            expected_return=expected,
        )
    )

    assert result.success is True


@pytest.mark.parametrize(
    ("values", "size", "message"),
    [
        ("[1, 2]", "5", "cannot exceed"),
        ("[1, 2]", "-1", "cannot be negative"),
        ("[1,,2]", "2", "empty array element"),
        ("[1, 2.5]", "2", "signed decimal int"),
        ("[foo()]", "1", "not C++ expressions"),
        ("[1 + dangerousCall()]", "1", "not C++ expressions"),
    ],
)
def test_invalid_array_values_and_sizes_are_rejected_before_compilation(
    values: str,
    size: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        vector_request(
            "int sum(int values[], int size) { return size; }",
            arguments=[values, size],
            expected_return="0",
        )
    )

    assert result.input_error
    assert message in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_array_with_additional_scalar_parameter_executes():
    result = run_test_request(
        vector_request(
            "bool contains(int values[], int length, int target) "
            "{ for (int i = 0; i < length; ++i) "
            "if (values[i] == target) return true; return false; }",
            arguments=["[3, 7, 9]", "3", "7"],
            expected_return="true",
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_void_array_function_captures_stdout():
    result = run_test_request(
        void_request(
            "#include <iostream>\n"
            "void printValues(int values[], int size) "
            "{ for (int i = 0; i < size; ++i) "
            "std::cout << values[i] << ' '; }",
            arguments=["[1, 2, 3]", "3"],
            expected_stdout="1 2 3",
        )
    )

    assert result.success is True
    assert result.tests[0].match_type == "whitespace_normalized"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_array_targets_and_helpers_remain_supported():
    source = """
int sum(int values[], int size)
{
    int total = 0;
    for (int index = 0; index < size; ++index) total += values[index];
    return total;
}
int average(int values[], int size)
{
    return sum(values, size) / size;
}
""".strip()
    analysis = analyze_test_mode(source)
    assert [function.name for function in analysis.functions] == [
        "sum",
        "average",
    ]
    result = run_test_request(
        vector_request(
            source,
            arguments=["[2, 4, 6]", "3"],
            expected_return="4",
            target_index=1,
        )
    )

    assert result.success is True


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "int sum(int values[]) { return 0; }",
            "requires a later integral size parameter",
        ),
        (
            "int f(int* values, int size, long count) { return 0; }",
            "ambiguous size parameter",
        ),
        (
            "int f(int** values, int size) { return 0; }",
            "Pointer-to-pointer",
        ),
        (
            "int f(int values[][], int size) { return 0; }",
            "Multidimensional",
        ),
        (
            "int f(char values[], int size) { return 0; }",
            "Character arrays",
        ),
        (
            "int* values() { return nullptr; }",
            "Pointer return",
        ),
    ],
)
def test_unsupported_array_signatures_have_clear_messages(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert message in analysis.message


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_array_function_runtime_timeout_is_preserved():
    result = run_test_request(
        vector_request(
            "int spin(int values[], int size) "
            "{ while (true) {} return values[size]; }",
            arguments=["[]", "0"],
            expected_return="0",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_array_void_function_output_limit_is_preserved():
    result = run_test_request(
        void_request(
            "#include <iostream>\n"
            "void noisy(int values[], int size) "
            "{ while (true) std::cout << values[0]; }",
            arguments=["[1]", "1"],
            expected_stdout="",
        )
    )

    assert result.tests[0].output_limited is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_vector_function_runtime_timeout_is_preserved():
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            "std::vector<int> spin(std::vector<int> values) "
            "{ while (true) {} return values; }",
            arguments=["[]"],
            expected_return="[]",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True
    assert result.tests[0].passed is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_vector_function_output_limit_is_preserved():
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            "std::vector<int> huge(std::vector<int> values) "
            "{ return std::vector<int>(100000, 1); }",
            arguments=["[]"],
            expected_return="[]",
        )
    )

    assert result.tests[0].output_limited is True
    assert result.tests[0].passed is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_run_tests_endpoint_accepts_function_mode():
    response = asyncio.run(
        api_request(
            "/api/run-tests",
            {
                "mode": "function",
                "code": "int add(int a, int b) { return a + b; }",
                "language": "cpp",
                "target_function": "add(int,int)->int",
                "tests": [
                    {
                        "name": "Add",
                        "arguments": ["2", "3"],
                        "expected_return": "5",
                    }
                ],
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "function"
    assert response.json()["tests"][0]["passed"] is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_user_function_compilation_error_is_returned():
    result = run_test_request(
        function_request(
            "int broken(int value) { return value + ; }",
            arguments=["1"],
            expected_return="1",
        )
    )

    assert result.success is False
    assert result.compile_error
    assert result.tests == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_function_runtime_timeout_is_preserved():
    result = run_test_request(
        function_request(
            "int spin() { while (true) {} return 0; }",
            arguments=[],
            expected_return="0",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True
    assert result.tests[0].passed is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_function_output_limit_is_preserved():
    result = run_test_request(
        function_request(
            """
#include <iostream>
int noisy()
{
    while (true) {
        std::cout << "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    }
    return 0;
}
""".strip(),
            arguments=[],
            expected_return="0",
        )
    )

    assert result.tests[0].output_limited is True
    assert result.tests[0].passed is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_function_harness_temporary_files_are_cleaned(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(test_execution.tempfile, "tempdir", str(tmp_path))

    run_test_request(
        function_request(
            "int answer() { return 42; }",
            arguments=[],
            expected_return="42",
        )
    )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_existing_program_mode_still_uses_stdin_and_stdout():
    request = ProgramRunTestsRequest(
        mode="program",
        code=(
            "#include <iostream>\n"
            "int main() { int x; std::cin >> x; std::cout << x * 2 << '\\n'; }"
        ),
        language="cpp",
        tests=[
            ProgramTestCase(
                name="Program test",
                stdin="5\n",
                expected_stdout="10",
            )
        ],
    )

    result = run_test_request(request)

    assert result.mode == "program"
    assert result.success is True
    assert result.tests[0].passed is True


@pytest.mark.parametrize(
    "declaration",
    ["int& value", "int &value", "int & value"],
)
def test_mutable_reference_metadata_is_structured(declaration: str):
    analysis = analyze_test_mode(
        f"void doubleValue({declaration}) {{ value *= 2; }}"
    )

    assert analysis.mode == "function"
    metadata = analysis.functions[0].parameters[0].value_type
    assert metadata.kind == "scalar"
    assert metadata.scalar_type == "int"
    assert metadata.passing == "mutable_reference"
    assert metadata.display_type == "int&"


@pytest.mark.parametrize(
    "declaration",
    ["const int& value", "int const& value"],
)
def test_const_scalar_reference_remains_read_only(declaration: str):
    analysis = analyze_test_mode(
        f"int identity({declaration}) {{ return value; }}"
    )

    assert analysis.mode == "function"
    metadata = analysis.functions[0].parameters[0].value_type
    assert metadata.passing == "const_reference"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("type_name", "body", "initial", "expected"),
    [
        ("int", "value *= 2;", "5", "10"),
        ("long", "value -= 3;", "10", "7"),
        ("long long", "value += 3000000000LL;", "2", "3000000002"),
        ("double", "value *= 2.0;", "1.25", "2.5"),
        ("bool", "value = !value;", "true", "false"),
    ],
)
def test_supported_scalar_reference_mutations_execute(
    type_name: str,
    body: str,
    initial: str,
    expected: str,
):
    result = run_test_request(
        mutation_request(
            f"void change({type_name}& value) {{ {body} }}",
            arguments=[initial],
            expected_final_arguments={"value": expected},
        )
    )

    assert result.success is True
    assert result.tests[0].passed is True
    assert result.tests[0].actual_final_arguments == {"value": expected}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mutable_reference_failure_reports_actual_final_value():
    result = run_test_request(
        mutation_request(
            "void doubleValue(int& value) { value *= 2; }",
            arguments=["5"],
            expected_final_arguments={"value": "9"},
        )
    )

    assert result.success is False
    assert result.tests[0].initial_arguments == {"value": "5"}
    assert result.tests[0].expected_final_arguments == {"value": "9"}
    assert result.tests[0].actual_final_arguments == {"value": "10"}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_string_reference_mutation_preserves_spaces_and_quotes():
    result = run_test_request(
        mutation_request(
            "#include <string>\n"
            "void addSuffix(std::string& text, std::string suffix) "
            "{ text += suffix; }",
            arguments=["hello", ' \"world\"'],
            expected_final_arguments={"text": 'hello \"world\"'},
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "text": 'hello \"world\"'
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mutable_reference_with_scalar_and_helper_executes():
    result = run_test_request(
        mutation_request(
            "int amount(int value) { return value * 2; }\n"
            "void addAmount(int& value, int input) "
            "{ value += amount(input); }",
            arguments=["5", "3"],
            expected_final_arguments={"value": "11"},
            target_index=1,
        )
    )

    assert result.success is True


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "void change(int*& value) {}",
            "References to pointers",
        ),
        (
            "void change(int&& value) {}",
            "Rvalue reference",
        ),
        (
            "#include <string>\nvoid change(std::string&& value) {}",
            "Rvalue reference",
        ),
        (
            "int& value(int input) { static int result; return result; }",
            "reference return",
        ),
    ],
)
def test_unsupported_reference_signatures_are_clear(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert message.lower() in analysis.message.lower()


@pytest.mark.parametrize(
    ("initial", "expected", "message"),
    [
        ("1.5", "2", "signed decimal int"),
        ("1", "false", "signed decimal int"),
    ],
)
def test_invalid_reference_values_are_rejected_before_compilation(
    initial: str,
    expected: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        mutation_request(
            "void change(int& value) { ++value; }",
            arguments=[initial],
            expected_final_arguments={"value": expected},
        )
    )

    assert result.input_error
    assert message in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mutable_reference_stdout_is_ignored_when_output_check_is_disabled():
    result = run_test_request(
        mutation_request(
            "#include <iostream>\n"
            "void change(int& value) { ++value; std::cout << value; }",
            arguments=["1"],
            expected_final_arguments={"value": "2"},
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mutable_reference_timeout_and_output_limits_are_preserved():
    timeout_result = run_test_request(
        mutation_request(
            "void spin(int& value) { while (true) {} }",
            arguments=["1"],
            expected_final_arguments={"value": "1"},
        ),
        test_timeout_seconds=0.05,
    )
    output_result = run_test_request(
        mutation_request(
            "#include <iostream>\n"
            "void noisy(int& value) { while (true) std::cout << value; }",
            arguments=["1"],
            expected_final_arguments={"value": "1"},
        )
    )

    assert timeout_result.tests[0].timed_out is True
    assert output_result.tests[0].output_limited is True


@pytest.mark.parametrize(
    ("declaration", "element_type"),
    [
        ("std::vector<int>& values", "int"),
        ("vector<long>& values", "long"),
        ("std::vector<long long>& values", "long long"),
        ("std::vector<double>& values", "double"),
        ("std::vector<bool>& values", "bool"),
        ("std::vector<std::string>& values", "std::string"),
    ],
)
def test_mutable_vector_metadata_is_structured(
    declaration: str,
    element_type: str,
):
    namespace = (
        "using namespace std;\n"
        if declaration.startswith("vector")
        else ""
    )
    analysis = analyze_test_mode(
        "#include <string>\n#include <vector>\n"
        f"{namespace}void change({declaration}) {{}}"
    )

    assert analysis.mode == "function"
    metadata = analysis.functions[0].parameters[0].value_type
    assert metadata.kind == "vector"
    assert metadata.element_type == element_type
    assert metadata.passing == "mutable_reference"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("initial", "expected"),
    [
        ("[1, 2, 3]", "[2, 4, 6]"),
        ("[]", "[]"),
    ],
)
def test_numeric_vector_mutation_executes(initial: str, expected: str):
    result = run_test_request(
        mutation_request(
            "#include <vector>\n"
            "void doubleValues(std::vector<int>& values) "
            "{ for (int& value : values) value *= 2; }",
            arguments=[initial],
            expected_final_arguments={"values": expected},
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {"values": expected}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_string_vector_mutation_uses_canonical_serialization():
    result = run_test_request(
        mutation_request(
            "#include <string>\n#include <vector>\n"
            "void addPrefix(std::vector<std::string>& words) "
            '{ for (std::string& word : words) word = "item-" + word; }',
            arguments=['["one", "two"]'],
            expected_final_arguments={
                "words": '["item-one", "item-two"]'
            },
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "words": '["item-one", "item-two"]'
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_vector_mutation_with_ordinary_scalar_parameter_executes():
    result = run_test_request(
        mutation_request(
            "#include <vector>\n"
            "void addAmount(std::vector<int>& values, int amount) "
            "{ for (int& value : values) value += amount; }",
            arguments=["[1, 2]", "3"],
            expected_final_arguments={"values": "[4, 5]"},
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize("declaration", ["int values[]", "int* values"])
def test_array_mutation_and_pointer_spelling_execute(declaration: str):
    result = run_test_request(
        mutation_request(
            f"void reverseArray({declaration}, int size) "
            "{ for (int i = 0; i < size / 2; ++i) "
            "{ int temp = values[i]; values[i] = values[size - 1 - i]; "
            "values[size - 1 - i] = temp; } }",
            arguments=["[1, 2, 3, 4]", "4"],
            expected_final_arguments={"values": "[4, 3, 2, 1]"},
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("initial", "size", "expected"),
    [
        ("[1, 2, 3, 99]", "3", "[3, 2, 1]"),
        ("[]", "0", "[]"),
    ],
)
def test_array_mutation_compares_only_the_explicit_size(
    initial: str,
    size: str,
    expected: str,
):
    result = run_test_request(
        mutation_request(
            "void reverseArray(int values[], int size) "
            "{ for (int i = 0; i < size / 2; ++i) "
            "{ int temp = values[i]; values[i] = values[size - 1 - i]; "
            "values[size - 1 - i] = temp; } }",
            arguments=[initial, size],
            expected_final_arguments={"values": expected},
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {"values": expected}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_incorrect_expected_collection_mutation_fails():
    result = run_test_request(
        mutation_request(
            "#include <vector>\n"
            "void doubleValues(std::vector<int>& values) "
            "{ for (int& value : values) value *= 2; }",
            arguments=["[1, 2]"],
            expected_final_arguments={"values": "[2, 5]"},
        )
    )

    assert result.success is False
    assert result.tests[0].actual_final_arguments == {"values": "[2, 4]"}


@pytest.mark.parametrize(
    ("source", "arguments", "expected", "message"),
    [
        (
            "#include <vector>\n"
            "void change(std::vector<int>& values) {}",
            ["[1, 2]"],
            "[1,,2]",
            "empty vector element",
        ),
        (
            "void change(int values[], int size) {}",
            ["[1, 2]", "2"],
            "[one]",
            "signed decimal int",
        ),
    ],
)
def test_malformed_expected_collection_mutation_is_rejected_before_compile(
    source: str,
    arguments: list[str],
    expected: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        mutation_request(
            source,
            arguments=arguments,
            expected_final_arguments={
                analyze_test_mode(source).functions[0].parameters[0].name:
                    expected
            },
        )
    )

    assert result.input_error
    assert message in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_two_scalar_mutations_are_captured_and_compared():
    result = run_test_request(
        multiple_mutation_request(
            "void swapValues(int& left, int& right) "
            "{ int temporary = left; left = right; right = temporary; }",
            arguments=["4", "9"],
            expected_mutations=[("left", "9"), ("right", "4")],
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "left": "9",
        "right": "4",
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_three_scalar_mutations_with_ordinary_inputs_execute():
    result = run_test_request(
        multiple_mutation_request(
            "void divideValues(int value, int divisor, int& quotient, "
            "int& remainder, bool& exact) "
            "{ quotient = value / divisor; remainder = value % divisor; "
            "exact = remainder == 0; }",
            arguments=["17", "5", "0", "0", "true"],
            expected_mutations=[
                ("quotient", "3"),
                ("remainder", "2"),
                ("exact", "false"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_scalar_and_string_mutations_execute_together():
    result = run_test_request(
        multiple_mutation_request(
            "#include <string>\n"
            "void updateUser(int& score, std::string& label) "
            '{ score += 5; label += "-updated"; }',
            arguments=["10", "user"],
            expected_mutations=[
                ("score", "15"),
                ("label", "user-updated"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_two_vector_mutations_execute_together():
    result = run_test_request(
        multiple_mutation_request(
            "#include <vector>\n"
            "void swapVectors(std::vector<int>& first, "
            "std::vector<int>& second) { first.swap(second); }",
            arguments=["[1, 2]", "[3, 4]"],
            expected_mutations=[
                ("first", "[3, 4]"),
                ("second", "[1, 2]"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_scalar_and_vector_mutations_execute_together():
    result = run_test_request(
        multiple_mutation_request(
            "#include <vector>\n"
            "void update(int& count, std::vector<int>& values) "
            "{ ++count; for (int& value : values) ++value; }",
            arguments=["2", "[1, 2]"],
            expected_mutations=[
                ("count", "3"),
                ("values", "[2, 3]"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_two_arrays_use_their_unambiguous_adjacent_sizes():
    source = (
        "void swapFirst(int first[], int size, int second[], int count) "
        "{ int temporary = first[0]; first[0] = second[0]; "
        "second[0] = temporary; }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    assert [
        parameter.value_type.size_parameter_name
        for parameter in analysis.functions[0].parameters
        if parameter.value_type.kind == "array"
    ] == ["size", "count"]

    result = run_test_request(
        multiple_mutation_request(
            source,
            arguments=["[1, 2]", "2", "[8, 9, 10]", "2"],
            expected_mutations=[
                ("first", "[8, 2]"),
                ("second", "[1, 9]"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_one_mutation_mismatch_fails_the_whole_test():
    result = run_test_request(
        multiple_mutation_request(
            "void swapValues(int& left, int& right) "
            "{ int temporary = left; left = right; right = temporary; }",
            arguments=["4", "9"],
            expected_mutations=[("left", "9"), ("right", "5")],
        )
    )

    assert result.success is False
    assert result.tests[0].actual_final_arguments == {
        "left": "9",
        "right": "4",
    }


@pytest.mark.parametrize(
    ("expectations", "message"),
    [
        ([("left", "2")], "Every mutable parameter"),
        (
            [("left", "2"), ("right", "1"), ("value", "3")],
            "Every mutable parameter",
        ),
        (
            [("left", "2"), ("right", "1"), ("stale", "3")],
            "Every mutable parameter",
        ),
        (
            [("left", "2"), ("left", "2"), ("right", "1")],
            "duplicate mutation parameter",
        ),
    ],
)
def test_invalid_multiple_mutation_identifiers_are_rejected_before_compile(
    expectations: list[tuple[str, str]],
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        multiple_mutation_request(
            "void swapValues(int& left, int& right, int value) {}",
            arguments=["1", "2", "3"],
            expected_mutations=expectations,
        )
    )

    assert result.input_error
    assert message in result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("expected_return", "expected_mutation", "success"),
    [("12", "6", True), ("11", "6", False), ("12", "7", False)],
)
def test_return_and_mutation_channels(
    expected_return: str,
    expected_mutation: str,
    success: bool,
):
    result = run_test_request(
        combined_request(
            "int increase(int& value) { ++value; return value * 2; }",
            arguments=["5"],
            expected_return=expected_return,
            expected_mutations=[("value", expected_mutation)],
        )
    )

    assert result.success is success
    combined = result.tests[0]
    assert combined.return_result.passed is (expected_return == "12")
    assert combined.mutation_results[0].passed is (
        expected_mutation == "6"
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_stdout_and_mutation_channels_pass():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "void updateAndPrint(int& value) "
            "{ ++value; std::cout << value; }",
            arguments=["5"],
            expected_stdout="6",
            check_stdout=True,
            expected_mutations=[("value", "6")],
        )
    )

    assert result.success is True
    assert result.tests[0].stdout_result.passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_return_and_stdout_channels_are_isolated():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "int calculate(int value) "
            '{ std::cout << "__INKTOCODE_MUTATION_RESULT__"; '
            "return value * 2; }",
            arguments=["5"],
            expected_return="10",
            expected_stdout="__INKTOCODE_MUTATION_RESULT__",
            check_stdout=True,
        )
    )

    assert result.success is True
    assert result.tests[0].return_result.actual == "10"
    assert result.tests[0].stdout_result.actual == (
        "__INKTOCODE_MUTATION_RESULT__"
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_all_three_channels_report_independent_failures():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "int process(int& value) "
            "{ value += 2; std::cout << value; return value * 3; }",
            arguments=["4"],
            expected_return="18",
            expected_stdout="7",
            check_stdout=True,
            expected_mutations=[("value", "6")],
        )
    )

    combined = result.tests[0]
    assert result.success is False
    assert combined.return_result.passed is True
    assert combined.stdout_result.passed is False
    assert combined.mutation_results[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_all_three_channels_pass():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "int process(int& value) "
            "{ value += 2; std::cout << value; return value * 3; }",
            arguments=["4"],
            expected_return="18",
            expected_stdout="6",
            check_stdout=True,
            expected_mutations=[("value", "6")],
        )
    )

    combined = result.tests[0]
    assert result.success is True
    assert combined.return_result.passed is True
    assert combined.stdout_result.passed is True
    assert combined.mutation_results[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_return_failure_does_not_hide_passing_stdout():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            'int calculate() { std::cout << "ready"; return 10; }',
            arguments=[],
            expected_return="11",
            expected_stdout="ready",
            check_stdout=True,
        )
    )

    combined = result.tests[0]
    assert result.success is False
    assert combined.return_result.passed is False
    assert combined.stdout_result.passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_mutations_can_be_combined_with_return():
    result = run_test_request(
        combined_request(
            "int adjust(int& left, int& right) "
            "{ ++left; right += 2; return left + right; }",
            arguments=["1", "2"],
            expected_return="6",
            expected_mutations=[("left", "2"), ("right", "4")],
        )
    )

    combined = result.tests[0]
    assert result.success is True
    assert combined.return_result.passed is True
    assert [item.parameter for item in combined.mutation_results] == [
        "left",
        "right",
    ]
    assert all(item.passed for item in combined.mutation_results)


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_mutations_can_be_combined_with_stdout():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "void adjust(int& left, int& right) "
            "{ ++left; right += 2; std::cout << left + right; }",
            arguments=["1", "2"],
            expected_stdout="6",
            check_stdout=True,
            expected_mutations=[("left", "2"), ("right", "4")],
        )
    )

    combined = result.tests[0]
    assert result.success is True
    assert combined.stdout_result.passed is True
    assert all(item.passed for item in combined.mutation_results)


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("comparison_mode", "expected", "passed"),
    [
        ("whitespace_tolerant", "hello world", True),
        ("exact", "hello world", False),
    ],
)
def test_combined_stdout_uses_selected_comparison_mode(
    comparison_mode: str,
    expected: str,
    passed: bool,
):
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            'int output() { std::cout << "hello  world\\n"; return 1; }',
            arguments=[],
            expected_return="1",
            expected_stdout=expected,
            check_stdout=True,
            comparison_mode=comparison_mode,
        )
    )

    assert result.tests[0].stdout_result.passed is passed


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_disabled_output_check_captures_but_ignores_stdout():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            'int output() { std::cout << "ignored"; return 1; }',
            arguments=[],
            expected_return="1",
            check_stdout=False,
        )
    )

    assert result.success is True


def test_void_expected_return_and_missing_nonvoid_return_are_rejected():
    void_result = run_test_request(
        combined_request(
            "void output() {}",
            arguments=[],
            expected_return="1",
        )
    )
    nonvoid_result = run_test_request(
        combined_request(
            'int output() { return 1; }',
            arguments=[],
            expected_stdout="",
            check_stdout=True,
        )
    )

    assert "void function" in (void_result.input_error or "")
    assert "expected return" in (nonvoid_result.input_error or "")


def test_output_check_requires_stdout_only_when_enabled():
    disabled = FunctionTestCase(
        name="Disabled output check",
        arguments=[],
        expected_return="1",
        check_stdout=False,
    )

    assert disabled.expected_stdout is None
    with pytest.raises(
        ValueError,
        match="Function-output checking requires expected stdout",
    ):
        FunctionTestCase(
            name="Enabled output check",
            arguments=[],
            expected_return="1",
            check_stdout=True,
        )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_timeout_before_metadata_completion_is_reported():
    result = run_test_request(
        combined_request(
            "int spin() { while (true) {} return 1; }",
            arguments=[],
            expected_return="1",
        ),
        test_timeout_seconds=0.05,
    )

    assert result.tests[0].timed_out is True
    assert "metadata was incomplete" in result.tests[0].stderr


def test_scalar_pointer_metadata_and_whitespace_spellings():
    analysis = analyze_test_mode(
        "#include <string>\n"
        "void update(int * score, long long* total, "
        "std::string * label) {}"
    )

    assert analysis.mode == "function"
    parameters = analysis.functions[0].parameters
    assert [
        (
            parameter.value_type.kind,
            parameter.value_type.display_type,
            parameter.value_type.scalar_type,
            parameter.value_type.passing,
        )
        for parameter in parameters
    ] == [
        ("scalar", "int*", "int", "scalar_pointer"),
        ("scalar", "long long*", "long long", "scalar_pointer"),
        ("scalar", "std::string*", "std::string", "scalar_pointer"),
    ]


def test_unqualified_string_pointer_requires_valid_namespace_use():
    supported = analyze_test_mode(
        "#include <string>\nusing namespace std;\n"
        "void update(string* value) {}"
    )
    unsupported = analyze_test_mode(
        "#include <string>\nvoid update(string* value) {}"
    )

    assert supported.mode == "function"
    assert (
        supported.functions[0].parameters[0].value_type.scalar_type
        == "std::string"
    )
    assert unsupported.mode == "unsupported"
    assert "using namespace std" in (unsupported.message or "")


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("source", "initial", "expected"),
    [
        ("void update(int* value) { ++*value; }", "5", "6"),
        (
            "void update(long long* value) { *value += 2; }",
            "9223372036854775800",
            "9223372036854775802",
        ),
        ("void update(double* value) { *value *= 2; }", "1.25", "2.5"),
        ("void update(bool* value) { *value = !*value; }", "false", "true"),
    ],
)
def test_numeric_scalar_pointer_mutations(
    source: str,
    initial: str,
    expected: str,
):
    result = run_test_request(
        combined_request(
            source,
            arguments=[initial],
            expected_mutations=[("value", expected)],
        )
    )

    assert result.success is True
    mutation = result.tests[0]
    assert mutation.actual_final_arguments == {"value": expected}


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_string_scalar_pointer_mutation():
    result = run_test_request(
        combined_request(
            "#include <string>\n"
            'void update(std::string* value) { *value += "-updated"; }',
            arguments=["user"],
            expected_mutations=[("value", "user-updated")],
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "value": "user-updated"
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_scalar_pointer_with_ordinary_parameter_and_two_pointers():
    result = run_test_request(
        combined_request(
            "void calculate(int amount, int* quotient, int* remainder) "
            "{ *quotient += amount; *remainder -= amount; }",
            arguments=["3", "7", "5"],
            expected_mutations=[("quotient", "10"), ("remainder", "2")],
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "quotient": "10",
        "remainder": "2",
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_scalar_pointer_combines_with_reference_and_vector_mutations():
    result = run_test_request(
        combined_request(
            "#include <vector>\n"
            "void update(int* pointer, int& reference, "
            "std::vector<int>& values) "
            "{ ++*pointer; reference += 2; values.push_back(3); }",
            arguments=["1", "2", "[1, 2]"],
            expected_mutations=[
                ("pointer", "2"),
                ("reference", "4"),
                ("values", "[1, 2, 3]"),
            ],
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "pointer": "2",
        "reference": "4",
        "values": "[1, 2, 3]",
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_scalar_pointer_combines_with_return_and_checked_stdout():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n"
            "int update(int* value) "
            "{ *value += 2; std::cout << *value; return *value * 3; }",
            arguments=["4"],
            expected_return="18",
            expected_stdout="6",
            check_stdout=True,
            expected_mutations=[("value", "6")],
        )
    )

    combined = result.tests[0]
    assert result.success is True
    assert combined.return_result.passed is True
    assert combined.stdout_result.passed is True
    assert combined.mutation_results[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_incorrect_scalar_pointer_mutation_fails():
    result = run_test_request(
        combined_request(
            "void update(int* value) { ++*value; }",
            arguments=["5"],
            expected_mutations=[("value", "7")],
        )
    )

    assert result.success is False
    assert result.tests[0].actual_final_arguments == {"value": "6"}


@pytest.mark.parametrize(
    ("initial", "expected", "message"),
    [
        ("", "6", "must be a signed decimal int value"),
        ("5", "", "must be a signed decimal int value"),
        ("nullptr", "6", "must be a signed decimal int value"),
    ],
)
def test_invalid_scalar_pointer_values_are_rejected_before_compilation(
    initial: str,
    expected: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        combined_request(
            "void update(int* value) {}",
            arguments=[initial],
            expected_mutations=[("value", expected)],
        )
    )

    assert message in (result.input_error or "")
    assert invoked is False


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("void update(int** value) {}", "Pointer-to-pointer"),
        ("void update(int*& value) {}", "References to pointers"),
        ("void update(const int* value) {}", "Const scalar pointer"),
        ("void update(int const* value) {}", "Const scalar pointer"),
        (
            "#include <string>\nvoid update(const std::string* value) {}",
            "Const scalar pointer",
        ),
        ("void update(Custom* value) {}", "Unsupported type"),
        ("void update(int* value) { value++; }", "pointer arithmetic"),
        ("void update(int* value) { value[0] = 1; }", "pointer arithmetic"),
        ("int* update(int* value) { return value; }", "Pointer return"),
    ],
)
def test_unsupported_scalar_pointer_signatures_are_clear(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert message in (analysis.message or "")


def test_numeric_pointer_with_size_remains_array_backed():
    analysis = analyze_test_mode(
        "void reverseArray(int* values, int size) {}"
    )

    assert analysis.mode == "function"
    value_type = analysis.functions[0].parameters[0].value_type
    assert value_type.kind == "array"
    assert value_type.passing == "array_pointer"
    assert value_type.size_parameter_name == "size"


def test_nested_vector_metadata_distinguishes_two_dimensions():
    analysis = analyze_test_mode(
        "#include <vector>\n"
        "std::vector<std::vector<int>> transform("
        "const std::vector<std::vector<int>>& grid) { return grid; }"
    )

    assert analysis.mode == "function"
    function = analysis.functions[0]
    assert function.return_value_type.vector_depth == 2
    assert function.return_value_type.element_type == "int"
    assert function.return_value_type.display_type == (
        "std::vector<std::vector<int>>"
    )
    parameter = function.parameters[0].value_type
    assert parameter.vector_depth == 2
    assert parameter.passing == "const_reference"
    assert function.id == (
        "transform(const std::vector<std::vector<int>>&)"
        "->std::vector<std::vector<int>>"
    )


def test_unqualified_nested_vectors_require_namespace_use():
    supported = analyze_test_mode(
        "#include <vector>\nusing namespace std;\n"
        "int count(vector<vector<int>> values) { return values.size(); }"
    )
    unsupported = analyze_test_mode(
        "#include <vector>\n"
        "int count(vector<vector<int>> values) { return values.size(); }"
    )

    assert supported.mode == "function"
    assert supported.functions[0].parameters[0].value_type.vector_depth == 2
    assert unsupported.mode == "unsupported"
    assert "using namespace std" in (unsupported.message or "")


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("source", "argument", "expected"),
    [
        (
            "#include <vector>\n"
            "int sum(std::vector<std::vector<int>> grid) "
            "{ int result = 0; for (auto row : grid) "
            "for (int value : row) result += value; return result; }",
            "[[1, 2], [3, 4]]",
            "10",
        ),
        (
            "#include <vector>\n"
            "int count(std::vector<std::vector<int>> grid) "
            "{ int result = 0; for (auto row : grid) "
            "result += row.size(); return result; }",
            "[[1], [2, 3], []]",
            "3",
        ),
        (
            "#include <vector>\n"
            "int count(std::vector<std::vector<int>> grid) "
            "{ return grid.size(); }",
            "[]",
            "0",
        ),
        (
            "#include <vector>\n"
            "int count(std::vector<std::vector<int>> grid) "
            "{ return grid[0].size() + grid[1].size(); }",
            "[[], [1, 2]]",
            "2",
        ),
    ],
)
def test_nested_vector_inputs_support_jagged_and_empty_shapes(
    source: str,
    argument: str,
    expected: str,
):
    result = run_test_request(
        vector_request(
            source,
            arguments=[argument],
            expected_return=expected,
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("source", "argument", "expected"),
    [
        (
            "#include <vector>\n"
            "std::vector<std::vector<int>> identity("
            "std::vector<std::vector<int>> value) { return value; }",
            "[[1, 2], [3]]",
            "[[1, 2], [3]]",
        ),
        (
            "#include <string>\n#include <vector>\n"
            "std::vector<std::vector<std::string>> identity("
            "std::vector<std::vector<std::string>> value) { return value; }",
            '[["one", "two"], ["three"]]',
            '[["one", "two"], ["three"]]',
        ),
        (
            "#include <vector>\n"
            "std::vector<std::vector<double>> identity("
            "std::vector<std::vector<double>> value) { return value; }",
            "[[1.5], [2, 3.25]]",
            "[[1.5], [2, 3.25]]",
        ),
        (
            "#include <vector>\n"
            "std::vector<std::vector<bool>> identity("
            "std::vector<std::vector<bool>> value) { return value; }",
            "[[true, false], []]",
            "[[true, false], []]",
        ),
    ],
)
def test_nested_vector_returns_are_structural(
    source: str,
    argument: str,
    expected: str,
):
    result = run_test_request(
        vector_request(
            source,
            arguments=[argument],
            expected_return=expected,
        )
    )

    assert result.success is True
    assert result.tests[0].actual_return == expected


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_mutable_nested_vector_and_ordinary_scalar():
    result = run_test_request(
        combined_request(
            "#include <vector>\n"
            "void add(std::vector<std::vector<int>>& grid, int amount) "
            "{ for (auto& row : grid) for (int& value : row) "
            "value += amount; }",
            arguments=["[[1, 2], [3]]", "2"],
            expected_mutations=[("grid", "[[3, 4], [5]]")],
        )
    )

    assert result.success is True
    assert result.tests[0].actual_final_arguments == {
        "grid": "[[3, 4], [5]]"
    }


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_two_mutable_nested_vectors():
    result = run_test_request(
        combined_request(
            "#include <utility>\n#include <vector>\n"
            "void swapGrids(std::vector<std::vector<int>>& first, "
            "std::vector<std::vector<int>>& second) "
            "{ std::swap(first, second); }",
            arguments=["[[1], [2]]", "[[3, 4]]"],
            expected_mutations=[
                ("first", "[[3, 4]]"),
                ("second", "[[1], [2]]"),
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_nested_mutation_combines_with_return_and_stdout():
    result = run_test_request(
        combined_request(
            "#include <iostream>\n#include <vector>\n"
            "int update(std::vector<std::vector<int>>& grid) "
            "{ grid[0][0] += 1; std::cout << grid[0][0]; "
            "return grid.size(); }",
            arguments=["[[1, 2], [3]]"],
            expected_return="2",
            expected_stdout="2",
            check_stdout=True,
            expected_mutations=[("grid", "[[2, 2], [3]]")],
        )
    )

    combined = result.tests[0]
    assert result.success is True
    assert combined.return_result.passed is True
    assert combined.stdout_result.passed is True
    assert combined.mutation_results[0].passed is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("expected", "detail"),
    [
        ("[[1], [2]]", "Expected 2 row(s), actual 1"),
        ("[[1, 2, 3]]", "Row 1: expected length 3, actual length 2"),
        ("[[1, 9]]", "row 1, element 2"),
    ],
)
def test_nested_return_mismatch_has_structural_detail(
    expected: str,
    detail: str,
):
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            "std::vector<std::vector<int>> value() { return {{1, 2}}; }",
            arguments=[],
            expected_return=expected,
        )
    )

    assert result.success is False
    assert result.tests[0].match_type == "mismatch"
    assert detail in (result.tests[0].mismatch_detail or "")


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_nested_mutation_mismatch_has_structural_detail():
    result = run_test_request(
        combined_request(
            "#include <vector>\n"
            "void update(std::vector<std::vector<int>>& grid) "
            "{ grid[0].push_back(3); }",
            arguments=["[[1, 2]]"],
            expected_mutations=[("grid", "[[1, 2]]")],
        )
    )

    assert result.success is False
    assert "Row 1: expected length 2, actual length 3" in (
        result.tests[0].mismatch_details["grid"]
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("[1, 2]", "row 1 must be a list"),
        ("[[1], 2]", "row 2 must be a list"),
        ("[[1, true]]", "signed decimal int"),
        ("[[1], [bad]]", "nested list"),
        ("[[1], [2]", "nested list"),
    ],
)
def test_malformed_nested_literals_are_rejected_before_compile(
    value: str,
    message: str,
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    result = run_test_request(
        vector_request(
            "#include <vector>\n"
            "int count(std::vector<std::vector<int>> value) { return 0; }",
            arguments=[value],
            expected_return="0",
        )
    )

    assert message in (result.input_error or "")
    assert invoked is False


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "#include <vector>\n"
            "int f(std::vector<std::vector<std::vector<int>>> value) "
            "{ return 0; }",
            "deeper than two",
        ),
        (
            "#include <vector>\n"
            "int f(std::vector<std::vector<Custom>> value) { return 0; }",
            "Unsupported vector element type",
        ),
        (
            "#include <vector>\n"
            "int f(std::vector<std::vector<int*>> value) { return 0; }",
            "Unsupported vector element type",
        ),
    ],
)
def test_unsupported_nested_vector_types_are_clear(
    source: str,
    message: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert message in (analysis.message or "")
