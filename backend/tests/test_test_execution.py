import asyncio
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.test_execution import ProgramTestCase
from app.services import test_execution
from app.services import execution_providers
from app.services.test_execution import (
    TEST_OUTPUT_LIMIT_BYTES,
    _classify_output_match,
    _classify_program_output_match,
    run_cpp_tests,
)

RUNNABLE_PROGRAM = """
#include <iostream>
#include <string>

int main()
{
    std::string value;
    std::getline(std::cin, value);
    std::cout << value << "\\n";
    return 0;
}
""".strip()


async def api_request(payload: object):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/run-tests", json=payload)


def make_test_case(
    *,
    name: str = "Test 1",
    stdin: str = "",
    expected_stdout: str = "",
) -> ProgramTestCase:
    return ProgramTestCase(
        name=name,
        stdin=stdin,
        expected_stdout=expected_stdout,
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_valid_program_passes_and_receives_stdin():
    result = run_cpp_tests(
        RUNNABLE_PROGRAM,
        [make_test_case(stdin="hello\n", expected_stdout="hello\n")],
    )

    assert result.success is True
    assert result.compile_error is None
    assert result.tests[0].passed is True
    assert result.tests[0].actual_stdout == "hello\n"
    assert result.tests[0].match_type == "exact"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_expected_output_mismatch_fails():
    result = run_cpp_tests(
        RUNNABLE_PROGRAM,
        [make_test_case(stdin="actual\n", expected_stdout="expected\n")],
    )

    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].actual_stdout == "actual\n"
    assert result.tests[0].match_type == "mismatch"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_multiple_tests_execute_in_request_order():
    result = run_cpp_tests(
        RUNNABLE_PROGRAM,
        [
            make_test_case(name="First", stdin="one\n", expected_stdout="one\n"),
            make_test_case(name="Second", stdin="two\n", expected_stdout="two\n"),
        ],
    )

    assert [item.name for item in result.tests] == ["First", "Second"]
    assert [item.actual_stdout for item in result.tests] == ["one\n", "two\n"]
    assert all(item.passed for item in result.tests)


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_runtime_stderr_and_nonzero_exit_are_reported():
    result = run_cpp_tests(
        '#include <iostream>\nint main() { std::cerr << "problem"; return 7; }',
        [make_test_case()],
    )

    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].stderr == "problem"
    assert result.tests[0].exit_code == 7
    assert result.tests[0].timed_out is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_infinite_loop_times_out():
    result = run_cpp_tests(
        "int main() { while (true) {} }",
        [make_test_case()],
        test_timeout_seconds=0.05,
    )

    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].timed_out is True
    assert result.tests[0].exit_code is None


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_compile_failure_prevents_execution():
    result = run_cpp_tests(
        "int main() { return missing; }",
        [make_test_case()],
    )

    assert result.success is False
    assert result.compile_error
    assert result.tests == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_temporary_files_are_cleaned(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(test_execution.tempfile, "tempdir", str(tmp_path))

    run_cpp_tests(RUNNABLE_PROGRAM, [make_test_case()])

    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_compiler_and_program_never_use_shell_true(monkeypatch):
    original_run = execution_providers.subprocess.run
    invocations: list[tuple[list[str], bool | None]] = []

    def recording_run(command, **kwargs):
        invocations.append((command, kwargs.get("shell")))
        return original_run(command, **kwargs)

    monkeypatch.setattr(execution_providers.subprocess, "run", recording_run)

    result = run_cpp_tests(RUNNABLE_PROGRAM, [make_test_case()])

    assert result.tests
    assert len(invocations) >= 2
    assert all(command[0] == "docker" for command, _ in invocations)
    assert all(shell is False for _, shell in invocations)


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_whitespace_only_difference_passes_and_preserves_raw_output():
    result = run_cpp_tests(
        '#include <iostream>\nint main() { std::cout << "15 \\n"; }',
        [make_test_case(expected_stdout="15\n")],
    )

    assert result.tests[0].passed is True
    assert result.tests[0].match_type == "whitespace_normalized"
    assert result.tests[0].expected_stdout == "15\n"
    assert result.tests[0].actual_stdout == "15 \n"


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("2", "2\n"),
        ("2", "   2"),
        ("2 3", "2    3"),
        ("hello\tworld", "hello world"),
        ("2 3", "2\n3\n"),
        ("one\r\ntwo\r\n", "one\ntwo\n"),
    ],
)
def test_whitespace_variants_are_normalized(expected: str, actual: str):
    assert _classify_output_match(expected, actual) == "whitespace_normalized"


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("2", "3"),
        ("2 3", "3 2"),
        ("hello world", "hello there"),
        ("value.", "value"),
        ("Hello", "hello"),
    ],
)
def test_meaningful_token_differences_remain_mismatches(
    expected: str,
    actual: str,
):
    assert _classify_output_match(expected, actual) == "mismatch"


def test_identical_output_is_classified_as_exact():
    assert _classify_output_match("hello world\n", "hello world\n") == "exact"


def test_exact_mode_normalizes_crlf_only():
    assert (
        _classify_program_output_match(
            "hello\r\nworld\r\n",
            "hello\nworld\n",
            "exact",
        )
        == "exact"
    )


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        ("2", "2\n"),
        ("2 3", "2   3"),
        ("hello world", "hello\tworld"),
    ],
)
def test_exact_mode_identifies_formatting_only_mismatches(
    expected: str,
    actual: str,
):
    assert (
        _classify_program_output_match(expected, actual, "exact")
        == "formatting_mismatch"
    )


def test_exact_mode_preserves_real_value_mismatches():
    assert (
        _classify_program_output_match("2\n", "3\n", "exact")
        == "mismatch"
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_exact_mode_fails_on_trailing_newline_and_preserves_raw_output():
    result = run_cpp_tests(
        '#include <iostream>\nint main() { std::cout << "2\\n"; }',
        [make_test_case(expected_stdout="2")],
        comparison_mode="exact",
    )

    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].match_type == "formatting_mismatch"
    assert result.tests[0].expected_stdout == "2"
    assert result.tests[0].actual_stdout == "2\n"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_output_limit_stops_large_output():
    result = run_cpp_tests(
        """
#include <iostream>
int main()
{
    while (true) {
        std::cout << "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    }
}
""".strip(),
        [make_test_case()],
    )

    assert result.tests[0].passed is False
    assert result.tests[0].output_limited is True
    assert len(result.tests[0].actual_stdout.encode("utf-8")) <= (
        TEST_OUTPUT_LIMIT_BYTES + 64
    )


def test_empty_test_list_is_rejected():
    response = asyncio.run(
        api_request(
            {
                "code": "int main() {}",
                "language": "cpp",
                "tests": [],
            }
        )
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_malformed_test_is_rejected():
    response = asyncio.run(
        api_request(
            {
                "code": "int main() {}",
                "language": "cpp",
                "tests": [{"name": "", "stdin": ""}],
            }
        )
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_invalid_comparison_mode_is_rejected():
    response = asyncio.run(
        api_request(
            {
                "mode": "program",
                "code": "int main() {}",
                "language": "cpp",
                "comparison_mode": "close_enough",
                "tests": [
                    {
                        "name": "Test 1",
                        "stdin": "",
                        "expected_stdout": "",
                    }
                ],
            }
        )
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_test_service_has_no_host_process_launcher():
    assert not hasattr(test_execution, "subprocess")
    assert not hasattr(test_execution, "os")
