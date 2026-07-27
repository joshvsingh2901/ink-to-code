import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import compiler as compiler_service
from app.services.compiler import CompilerServiceError, compile_cpp


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


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_invalid_cpp_returns_normal_compiler_failure():
    result = compile_cpp("int main() {\n    return 0\n}")
    assert result.success is False
    assert result.exit_code != 0
    assert "error:" in result.stderr


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


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_compiler_error_is_http_200_not_internal_server_error():
    response = asyncio.run(
        api_request({"code": "int main() { return 0 }", "language": "cpp"})
    )
    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["stderr"]
