import asyncio
import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import compiler as compiler_service
from app.services.compiler import CompilerServiceError, compile_cpp
from app.services.compiler_diagnostics import parse_compiler_diagnostics
from app.services.execution_providers import DockerExecutionResult


async def api_request(payload: dict[str, str]):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/api/compile", json=payload)


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_valid_cpp_compiles_successfully():
    result = compile_cpp("int main() { return 0; }")
    assert result.success is True
    assert result.exit_code == 0
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_valid_function_without_main_compiles_successfully():
    result = compile_cpp(
        """
int findMax(int a, int b)
{
    int maxValue;
    if (a > b)
    {
        maxValue = b;
    }
    else
    {
        maxValue = a;
    }
    return maxValue;
}
""".strip()
    )

    assert result.success is True
    assert result.exit_code == 0
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_invalid_cpp_returns_normal_compiler_failure():
    result = compile_cpp("int main() {\n    return 0\n}")
    assert result.success is False
    assert result.exit_code != 0
    assert "error:" in result.stderr
    assert result.diagnostics
    assert result.diagnostics[0].severity == "error"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_function_without_main_and_with_syntax_error_returns_diagnostics():
    result = compile_cpp("int findMax(int a, int b) {\n    return a > b ? a : b\n}")

    assert result.success is False
    assert result.exit_code != 0
    assert result.diagnostics
    assert any(
        diagnostic.severity == "error" for diagnostic in result.diagnostics
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_undeclared_identifier_returns_diagnostics():
    result = compile_cpp("int findMax(int a, int b) { return maxValue; }")

    assert result.success is False
    assert result.exit_code != 0
    assert result.diagnostics
    assert any(
        diagnostic.severity == "error"
        and "maxValue" in diagnostic.message
        for diagnostic in result.diagnostics
    )


def test_empty_source_is_rejected_without_compiling(monkeypatch):
    invoked = False

    def unexpected_compile(_code: str):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr("app.api.compilation.compile_cpp", unexpected_compile)
    response = asyncio.run(api_request({"code": "   \n", "language": "cpp"}))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_source"
    assert invoked is False


def test_unsupported_language_is_rejected_clearly():
    response = asyncio.run(
        api_request({"code": "int main() {}", "language": "python"})
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_language"


def test_missing_compiler_is_an_infrastructure_error():
    with pytest.raises(CompilerServiceError) as caught:
        compile_cpp("int main() {}", compiler="inktocode-missing-compiler")
    assert caught.value.code == "compiler_unavailable"
    assert caught.value.status_code == 503


def test_compiler_timeout_is_handled(monkeypatch):
    class TimeoutProvider:
        def compile_source(self, *_args, **_kwargs):
            return DockerExecutionResult(compile_timed_out=True)

        def close(self):
            return None

    with pytest.raises(CompilerServiceError) as caught:
        compile_cpp("int main() {}", execution_provider=TimeoutProvider())
    assert caught.value.code == "compiler_timeout"
    assert caught.value.status_code == 504


@pytest.mark.parametrize(
    "source",
    ["int main() { return 0; }", "int main() { return 0 }"],
)
def test_temporary_directory_is_cleaned_after_compilation(
    source: str, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(compiler_service.tempfile, "tempdir", str(tmp_path))
    compile_cpp(source)
    assert list(tmp_path.iterdir()) == []


def test_compiler_uses_safe_argument_list_and_exact_source(monkeypatch):
    submitted = "int main() {\n\treturn 0;  \n}\n"
    invocation = {}

    class RecordingProvider:
        def compile_source(self, work_directory, *, timeout_seconds):
            invocation["source"] = (work_directory / "main.cpp").read_bytes()
            invocation["timeout"] = timeout_seconds
            return DockerExecutionResult(exit_code=0)

        def close(self):
            return None

    result = compile_cpp(submitted, execution_provider=RecordingProvider())

    assert result.success is True
    assert invocation["timeout"] == 10
    assert invocation["source"] == submitted.encode("utf-8")
    assert result.diagnostics == []


def test_compiler_diagnostics_preserve_order_locations_and_messages():
    stderr = "\n".join(
        [
            "main.cpp:3:5: warning: unused variable 'value' [-Wunused-variable]",
            "main.cpp:6:9: error: expected ';' before '}' token",
            "main.cpp:6:9: note: to match this '('",
            "main.cpp:8:1: fatal error: unexpected end of file",
        ]
    )

    diagnostics = parse_compiler_diagnostics(stderr)

    assert [diagnostic.model_dump() for diagnostic in diagnostics] == [
        {
            "line": 3,
            "column": 5,
            "severity": "warning",
            "message": "unused variable 'value' [-Wunused-variable]",
            "explanation": None,
        },
        {
            "line": 6,
            "column": 9,
            "severity": "error",
            "message": "expected ';' before '}' token",
            "explanation": "The compiler expected a semicolon near this location.",
        },
        {
            "line": 6,
            "column": 9,
            "severity": "note",
            "message": "to match this '('",
            "explanation": None,
        },
        {
            "line": 8,
            "column": 1,
            "severity": "error",
            "message": "unexpected end of file",
            "explanation": None,
        },
    ]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "use of undeclared identifier 'c'",
            (
                "`c` has not been declared or is not visible at this point in "
                "the program."
            ),
        ),
        (
            "expected expression",
            (
                "The compiler could not understand the syntax at this location. "
                "Check this line and the code immediately before it."
            ),
        ),
        (
            "expected '}'",
            (
                "A closing `}` is missing somewhere in the surrounding block "
                "structure."
            ),
        ),
        (
            "unknown type name 'retum'",
            "`retum` is not recognized as a type.",
        ),
        (
            "expected ';' after expression",
            "The compiler expected a semicolon near this location.",
        ),
        (
            "expected ')' after expression",
            "The compiler expected a closing `)` near this location.",
        ),
        (
            "expected ']'",
            "The compiler expected a closing `]` near this location.",
        ),
        (
            "invalid operands to binary expression",
            (
                "The values or expressions used with this operator are not "
                "compatible."
            ),
        ),
        (
            "redefinition of 'value'",
            (
                "This name has already been declared or defined in a "
                "conflicting way."
            ),
        ),
    ],
)
def test_supported_diagnostics_receive_conservative_explanations(
    message: str,
    expected: str,
):
    diagnostics = parse_compiler_diagnostics(
        f"main.cpp:4:3: error: {message}"
    )
    assert diagnostics[0].message == message
    assert diagnostics[0].explanation == expected


def test_expected_expression_explanation_does_not_claim_an_exact_cause():
    diagnostic = parse_compiler_diagnostics(
        "main.cpp:7:5: error: expected expression"
    )[0]
    assert diagnostic.explanation is not None
    assert "else" not in diagnostic.explanation.lower()
    assert "add" not in diagnostic.explanation.lower()


def test_matching_open_brace_note_enriches_only_the_related_brace_error():
    stderr = "\n".join(
        [
            "main.cpp:13:1: error: expected '}'",
            "main.cpp:2:12: note: to match this '{'",
        ]
    )
    diagnostics = parse_compiler_diagnostics(stderr)

    assert diagnostics[0].explanation == (
        "A closing `}` is missing somewhere in the surrounding block structure. "
        "The compiler is matching an opening `{` from line 2."
    )
    assert diagnostics[1].severity == "note"
    assert diagnostics[1].explanation is None


def test_unrelated_note_does_not_enrich_brace_explanation():
    stderr = "\n".join(
        [
            "main.cpp:13:1: error: expected '}'",
            "main.cpp:2:12: note: candidate function not viable",
        ]
    )
    diagnostic = parse_compiler_diagnostics(stderr)[0]
    assert diagnostic.explanation == (
        "A closing `}` is missing somewhere in the surrounding block structure."
    )


def test_unknown_type_explanation_does_not_infer_return_keyword():
    diagnostic = parse_compiler_diagnostics(
        "main.cpp:8:5: error: unknown type name 'retum'"
    )[0]
    assert diagnostic.explanation == "`retum` is not recognized as a type."
    assert "return" not in diagnostic.explanation


def test_unsupported_message_has_no_explanation():
    diagnostic = parse_compiler_diagnostics(
        "main.cpp:3:1: error: something unusual happened"
    )[0]
    assert diagnostic.explanation is None


def test_unrecognized_compiler_output_remains_available_as_raw_fallback(
    monkeypatch,
):
    raw_stderr = "The compiler stopped without a source location."

    class RawOutputProvider:
        def compile_source(self, *_args, **_kwargs):
            return DockerExecutionResult(exit_code=1, stderr=raw_stderr)

        def close(self):
            return None

    result = compile_cpp(
        "int main() {}", execution_provider=RawOutputProvider()
    )

    assert result.success is False
    assert result.stderr == raw_stderr
    assert result.diagnostics == []


def test_explanations_do_not_change_raw_compiler_stderr(monkeypatch):
    raw_stderr = "\n".join(
        [
            "main.cpp:13:1: error: expected '}'",
            "main.cpp:2:12: note: to match this '{'",
        ]
    )

    class DiagnosticProvider:
        def compile_source(self, *_args, **_kwargs):
            return DockerExecutionResult(exit_code=1, stderr=raw_stderr)

        def close(self):
            return None

    result = compile_cpp(
        "int main() {", execution_provider=DiagnosticProvider()
    )

    assert result.stderr == raw_stderr
    assert len(result.diagnostics) == 2
    assert result.diagnostics[1].severity == "note"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_compiler_error_is_http_200_not_internal_server_error():
    response = asyncio.run(
        api_request({"code": "int main() { return 0 }", "language": "cpp"})
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["stderr"]


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_sort_with_only_vector_fails():
    # Regression: on Apple libc++, <vector> used to transitively supply
    # std::sort.  The compile path now disables transitive includes so the
    # student gets the missing-header error naturally.
    result = compile_cpp(
        "#include <vector>\n"
        "void sortValues(std::vector<int>& values)\n"
        "{\n"
        "    std::sort(values.begin(), values.end());\n"
        "}\n"
    )
    assert result.success is False
    assert any(
        "sort" in d.message or "not declared" in d.message or "no member" in d.message
        for d in result.diagnostics
    ), f"expected sort-related diagnostic, got: {[d.message for d in result.diagnostics]}"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_sort_diagnostic_mentions_sort_or_not_declared():
    result = compile_cpp(
        "#include <vector>\n"
        "void f(std::vector<int>& v) { std::sort(v.begin(), v.end()); }\n"
    )
    assert result.success is False
    assert "sort" in result.stderr or "not declared" in result.stderr


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_sort_with_algorithm_header_passes():
    result = compile_cpp(
        "#include <algorithm>\n"
        "#include <vector>\n"
        "void sortValues(std::vector<int>& values)\n"
        "{\n"
        "    std::sort(values.begin(), values.end());\n"
        "}\n"
    )
    assert result.success is True
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_accumulate_without_numeric_fails():
    result = compile_cpp(
        "#include <vector>\n"
        "int f(const std::vector<int>& v) {\n"
        "    return std::accumulate(v.begin(), v.end(), 0);\n"
        "}\n"
    )
    assert result.success is False
    assert "accumulate" in result.stderr


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_accumulate_with_numeric_header_passes():
    result = compile_cpp(
        "#include <numeric>\n"
        "#include <vector>\n"
        "int f(const std::vector<int>& v) {\n"
        "    return std::accumulate(v.begin(), v.end(), 0);\n"
        "}\n"
    )
    assert result.success is True
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_simple_scalar_compilation_still_succeeds():
    result = compile_cpp(
        "int add(int a, int b) { return a + b; }\n"
    )
    assert result.success is True
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_iterator_harness_explicit_include_still_works():
    # Iterator test harnesses explicitly include <iterator>; that explicit
    # include must still compile correctly — the fix must not block it.
    result = compile_cpp(
        "#include <iterator>\n"
        "#include <vector>\n"
        "void f(std::vector<int>& v) {\n"
        "    auto it = v.begin();\n"
        "    std::advance(it, 1);\n"
        "}\n"
    )
    assert result.success is True
    assert result.diagnostics == []
