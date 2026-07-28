import asyncio
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
            "parameters": [
                {"name": "a", "type": "int"},
                {"name": "b", "type": "int"},
            ],
            "display": "findMax(int a, int b)",
        }
    ]


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
