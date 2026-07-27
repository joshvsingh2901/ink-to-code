import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import compiler as compiler_service
from app.services.compiler import CompilerServiceError, compile_cpp
from app.services.compiler_diagnostics import parse_compiler_diagnostics


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
def test_invalid_cpp_returns_normal_compiler_failure():
    result = compile_cpp("int main() {\n    return 0\n}")
    assert result.success is False
    assert result.exit_code != 0
    assert "error:" in result.stderr
    assert result.diagnostics
    assert result.diagnostics[0].severity == "error"


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
    def timeout_runner(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="g++", timeout=10)

    monkeypatch.setattr(compiler_service.subprocess, "run", timeout_runner)
    with pytest.raises(CompilerServiceError) as caught:
        compile_cpp("int main() {}")
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

    def recording_runner(command, **kwargs):
        invocation["command"] = command
        invocation["kwargs"] = kwargs
        invocation["source"] = (Path(kwargs["cwd"]) / "main.cpp").read_bytes()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(compiler_service.subprocess, "run", recording_runner)
    result = compile_cpp(submitted)

    assert result.success is True
    assert invocation["command"] == [
        "g++",
        "-std=c++17",
        "main.cpp",
        "-o",
        "program",
    ]
    assert invocation["kwargs"]["shell"] is False
    assert submitted not in invocation["command"]
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
        },
        {
            "line": 6,
            "column": 9,
            "severity": "error",
            "message": "expected ';' before '}' token",
        },
        {
            "line": 6,
            "column": 9,
            "severity": "note",
            "message": "to match this '('",
        },
        {
            "line": 8,
            "column": 1,
            "severity": "error",
            "message": "unexpected end of file",
        },
    ]


def test_unrecognized_compiler_output_remains_available_as_raw_fallback(
    monkeypatch,
):
    raw_stderr = "The compiler stopped without a source location."

    def raw_output_runner(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=raw_stderr,
        )

    monkeypatch.setattr(compiler_service.subprocess, "run", raw_output_runner)
    result = compile_cpp("int main() {}")

    assert result.success is False
    assert result.stderr == raw_stderr
    assert result.diagnostics == []


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_compiler_error_is_http_200_not_internal_server_error():
    response = asyncio.run(
        api_request({"code": "int main() { return 0 }", "language": "cpp"})
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["stderr"]
