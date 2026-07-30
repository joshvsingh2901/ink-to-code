import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.services import execution_providers
from app.services.execution_providers import (
    DockerExecutionResult,
    DockerExecutionProvider,
    HostExecutionProvider,
    ProviderCapabilities,
    _docker_base_command,
    docker_capabilities,
    select_memory_provider,
)
from app.services.test_execution import _docker_process_output
from app.services.test_execution import _compile_executable
from app.services.compiler import CompilerServiceError


def settings(
    provider: str = "auto",
    *,
    compile_timeout: float = 30,
    run_timeout: float = 8,
    valgrind_timeout: float = 20,
) -> Settings:
    return Settings(
        "http://localhost:3000",
        None,
        "test-model",
        "test",
        cpp_execution_provider=provider,
        cpp_runner_image="inktocode-cpp-runner",
        cpp_runner_memory="256m",
        cpp_runner_cpus="1.0",
        cpp_runner_pids=32,
        cpp_runner_user="runner",
        cpp_docker_compile_timeout_seconds=compile_timeout,
        cpp_docker_run_timeout_seconds=run_timeout,
        cpp_docker_valgrind_timeout_seconds=valgrind_timeout,
    )


AVAILABLE = ProviderCapabilities(
    "docker", True, True, True, True, True, True, True
)
UNAVAILABLE = ProviderCapabilities(
    "docker",
    False,
    False,
    False,
    False,
    False,
    False,
    False,
    "Docker is unavailable.",
)


def test_auto_selects_docker_for_memory_when_available(monkeypatch):
    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: AVAILABLE
    )
    name, provider, error = select_memory_provider(settings("auto"))
    assert name == "docker"
    assert provider is not None
    assert error is None


def test_auto_falls_back_to_host_when_docker_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: UNAVAILABLE
    )
    name, provider, error = select_memory_provider(settings("auto"))
    assert name == "host"
    assert isinstance(provider, HostExecutionProvider)
    assert error == "Docker is unavailable."


def test_host_mode_never_checks_docker(monkeypatch):
    monkeypatch.setattr(
        DockerExecutionProvider,
        "capabilities",
        lambda self: pytest.fail("Docker should not be checked"),
    )
    name, provider, error = select_memory_provider(settings("host"))
    assert name == "host"
    assert isinstance(provider, HostExecutionProvider)
    assert error is None


def test_docker_required_never_silently_falls_back(monkeypatch):
    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: UNAVAILABLE
    )
    name, provider, error = select_memory_provider(settings("docker"))
    assert name == "docker"
    assert provider is None
    assert error == "Docker is unavailable."


def test_docker_command_has_strict_security_and_one_mount(tmp_path: Path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    command = _docker_base_command(
        tmp_path, "inktocode-test", settings("docker")
    )
    assert command[:2] == ["docker", "run"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert command[command.index("--user") + 1] == "runner"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--cpus") + 1] == "1.0"
    assert command[command.index("--pids-limit") + 1] == "32"
    assert "--read-only" in command
    mounts = [
        command[index + 1]
        for index, item in enumerate(command)
        if item == "--mount"
    ]
    assert mounts == [
        f"type=bind,source={tmp_path.resolve()},target=/work"
    ]
    joined = " ".join(command)
    assert ".env" not in joined
    assert ".git" not in joined
    assert "docker.sock" not in joined
    assert "int main" not in joined


def test_docker_subprocess_uses_shell_false_and_child_manifest(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "main.cpp").write_text("int main() {}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "runner-result.json").write_text(
            json.dumps({"memory_tool": "sanitizer"})
        )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: AVAILABLE
    )
    monkeypatch.setattr(execution_providers.subprocess, "run", fake_run)
    result = DockerExecutionProvider(
        settings("docker")
    ).compile_and_run(tmp_path, "private input", timeout_seconds=2)

    assert result.memory_tool == "sanitizer"
    command, kwargs = calls[0]
    assert kwargs["shell"] is False
    assert "private input" not in " ".join(command)
    manifest = json.loads(
        (tmp_path / "runner-request.json").read_text()
    )
    assert manifest["stdin"] == "private input"
    assert manifest["mode"] == "compile_and_run_sanitized"
    assert manifest["compile_timeout_seconds"] == 30
    assert manifest["run_timeout_seconds"] == 8
    assert manifest["valgrind_timeout_seconds"] == 20
    assert calls[0][1]["timeout"] == 13


def test_sanitizer_compile_uses_separate_larger_timeout(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "main.cpp").write_text("int main() {}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "runner-result.json").write_text(
            json.dumps({"memory_tool": "sanitizer"})
        )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: AVAILABLE
    )
    monkeypatch.setattr(execution_providers.subprocess, "run", fake_run)
    result = DockerExecutionProvider(
        settings("docker", compile_timeout=30, run_timeout=8)
    ).compile_and_run(
        tmp_path, "", timeout_seconds=2, compile_only=True
    )

    assert result.compile_timed_out is False
    assert calls[0][1]["timeout"] == 30
    manifest = json.loads((tmp_path / "runner-request.json").read_text())
    assert manifest["compile_only"] is True
    assert manifest["compile_timeout_seconds"] == 30
    assert manifest["run_timeout_seconds"] == 8


def test_compile_timeout_is_classified_and_container_removed(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "main.cpp").write_text("int main() {}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(
        DockerExecutionProvider, "capabilities", lambda self: AVAILABLE
    )
    monkeypatch.setattr(execution_providers.subprocess, "run", fake_run)
    result = DockerExecutionProvider(
        settings("docker")
    ).compile_and_run(
        tmp_path, "", timeout_seconds=2, compile_only=True
    )

    assert result.compile_timed_out is True
    assert result.timed_out is False
    assert result.infrastructure_error == (
        "The isolated runner could not finish compiling the test program "
        "in time."
    )
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_compile_timeout_uses_dedicated_service_error(
    tmp_path: Path, monkeypatch
):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = DockerExecutionProvider(settings("docker"))
    monkeypatch.setattr(
        provider,
        "compile_and_run",
        lambda *_args, **_kwargs: DockerExecutionResult(
            infrastructure_error=(
                "The isolated runner could not finish compiling the test "
                "program in time."
            ),
            compile_timed_out=True,
        ),
    )

    with pytest.raises(CompilerServiceError) as caught:
        _compile_executable(
            tmp_path,
            compiler="g++",
            timeout_seconds=10,
            run_memory_checks=True,
            docker_provider=provider,
        )

    assert caught.value.code == "memory_compile_timeout"
    assert caught.value.status_code == 504
    assert caught.value.message == (
        "The isolated runner could not finish compiling the test program "
        "in time."
    )


def test_timeout_removes_container(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["docker", "rm", "-f"]:
            return subprocess.CompletedProcess(command, 0, b"", b"")
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(execution_providers.subprocess, "run", fake_run)
    result = execution_providers._run_docker_command(
        ["docker", "run"], "inktocode-timeout", timeout_seconds=1
    )
    assert result is None
    assert calls[-1] == ["docker", "rm", "-f", "inktocode-timeout"]


def test_capability_cache_can_be_reset_and_is_cached(monkeypatch):
    docker_capabilities.cache_clear()
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, b"", b"")

    monkeypatch.setattr(execution_providers.subprocess, "run", fake_run)
    first = docker_capabilities(
        "image", "256m", "1.0", 32, "runner"
    )
    second = docker_capabilities(
        "image", "256m", "1.0", 32, "runner"
    )
    assert first is second
    assert calls == 1


def test_definite_valgrind_leak_is_confirmed_and_paths_are_redacted(
    tmp_path: Path,
):
    output = _docker_process_output(
        DockerExecutionResult(
            exit_code=97,
            memory_tool="sanitizer_and_valgrind",
            valgrind_diagnostics=(
                "solution at /work/main.cpp:7\n"
                "definitely lost: 4 bytes in 1 blocks"
            ),
            leak_kind="definite",
            leaked_bytes=4,
            leaked_allocations=1,
        ),
        AVAILABLE,
        tmp_path,
    )
    assert output.memory_status == "leak"
    assert output.leak_status == "failed"
    assert output.leaked_bytes == 4
    assert "/work/" not in (output.memory_diagnostics or "")
    assert "solution.cpp:7" in (output.memory_diagnostics or "")


def test_possible_valgrind_leak_is_warning_not_confirmed(tmp_path: Path):
    output = _docker_process_output(
        DockerExecutionResult(
            exit_code=97,
            memory_tool="sanitizer_and_valgrind",
            valgrind_diagnostics="possibly lost: 4 bytes in 1 blocks",
            leak_kind="possible",
            leaked_bytes=4,
            leaked_allocations=1,
        ),
        AVAILABLE,
        tmp_path,
    )
    assert output.memory_status == "partial"
    assert output.leak_status == "possible"


def test_non_leak_asan_and_ubsan_classifications_remain_specific(
    tmp_path: Path,
):
    address = _docker_process_output(
        DockerExecutionResult(
            stderr="AddressSanitizer: heap-buffer-overflow",
            exit_code=1,
            memory_tool="sanitizer",
        ),
        AVAILABLE,
        tmp_path,
    )
    undefined = _docker_process_output(
        DockerExecutionResult(
            stderr="runtime error: signed integer overflow",
            exit_code=1,
            memory_tool="sanitizer",
        ),
        AVAILABLE,
        tmp_path,
    )
    assert address.memory_status == "buffer_overflow"
    assert address.memory_access_status == "failed"
    assert undefined.memory_status == "undefined_behavior"
    assert undefined.undefined_behavior_status == "failed"


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker is not installed",
)
def test_docker_runner_capability_integration():
    docker_capabilities.cache_clear()
    capabilities = DockerExecutionProvider(
        settings("docker")
    ).capabilities()
    if not capabilities.image_available:
        pytest.skip("inktocode-cpp-runner image is not installed")
    assert capabilities.runtime_available is True
    assert capabilities.compiler_available is True
    assert capabilities.address_sanitizer_available is True
    assert capabilities.undefined_behavior_sanitizer_available is True
    assert (
        capabilities.leak_sanitizer_available
        or capabilities.valgrind_available
    )
