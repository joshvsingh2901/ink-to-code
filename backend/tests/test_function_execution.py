import asyncio
import json
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.test_execution import (
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "int first(int *arr) { return arr[0]; }",
            "not supported",
        ),
        (
            "int identity(int &value) { return value; }",
            "not supported",
        ),
        (
            "void printValue(int value) {}",
            "Void returns are unsupported",
        ),
    ],
)
def test_unsupported_or_ambiguous_signatures_are_rejected(
    source: str,
    expected: str,
):
    analysis = analyze_test_mode(source)

    assert analysis.mode == "unsupported"
    assert analysis.message
    assert expected in analysis.message


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
    assert response.json()["functions"] == [
        {
            "id": "findMax(int,int)->int",
            "name": "findMax",
            "return_type": "int",
            "return_type_metadata": {
                "kind": "scalar",
                "display_type": "int",
                "scalar_type": "int",
                "element_type": None,
                "passing": "value",
            },
            "parameters": [
                {
                    "name": "a",
                    "type": "int",
                    "type_metadata": {
                        "kind": "scalar",
                        "display_type": "int",
                        "scalar_type": "int",
                        "element_type": None,
                        "passing": "value",
                    },
                },
                {
                    "name": "b",
                    "type": "int",
                    "type_metadata": {
                        "kind": "scalar",
                        "display_type": "int",
                        "scalar_type": "int",
                        "element_type": None,
                        "passing": "value",
                    },
                },
            ],
            "display": "findMax(int a, int b)",
        }
    ]


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
            "int size(std::vector<std::vector<int>> values) { return 0; }",
            "Unsupported vector",
        ),
        (
            "int size(std::vector<int>& values) { return 0; }",
            "Non-const vector reference",
        ),
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
            "int size(std::string& value) { return value.size(); }",
            "Non-const string reference",
        ),
        (
            "int size(std::string* value) { return value->size(); }",
            "String pointer",
        ),
        (
            "int size(char* value) { return 0; }",
            "Unsupported type",
        ),
        (
            "int size(const char* value) { return 0; }",
            "Unsupported type",
        ),
        (
            "int size(char value[]) { return 0; }",
            "not supported",
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
