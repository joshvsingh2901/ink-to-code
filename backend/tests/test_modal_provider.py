"""Mocked unit suite for ModalExecutionProvider. Runs in normal CI: no
Modal account, no network, no real sandbox. modal.App.lookup,
modal.Image.from_registry, and modal.Sandbox.create are monkeypatched with
in-process fakes that record every call so the security-critical kwargs,
the fixed launch command, and the sandbox lifecycle can all be asserted
directly.
"""

import json

import pytest

import modal
import modal.exception

from app.config import Settings
from app.services import modal_provider as modal_provider_module
from app.services.execution_providers import ProviderCapabilities
from app.services.modal_provider import (
    ModalExecutionProvider,
    _LAUNCH_COMMAND,
    _READ_RESULT_COMMAND,
    _memory_mib,
    modal_capabilities,
)


def _settings(**overrides) -> Settings:
    defaults = dict(
        frontend_origin="http://localhost:3000",
        gemini_api_key=None,
        transcription_model="test-model",
        environment="test",
        cpp_execution_provider="modal",
        cpp_runner_memory="256m",
        cpp_runner_cpus="1.0",
        cpp_docker_compile_timeout_seconds=30,
        cpp_docker_run_timeout_seconds=8,
        cpp_docker_valgrind_timeout_seconds=20,
        modal_app_name="inktocode-cpp-runner-test",
        modal_runner_image="ghcr.io/example/inktocode-cpp-runner@sha256:deadbeef",
        modal_sandbox_timeout_seconds=600,
        modal_sandbox_idle_timeout_seconds=120,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# In-process fakes
# ---------------------------------------------------------------------------


class FakeStream:
    def __init__(self, text: str = ""):
        self._text = text

    def read(self) -> str:
        return self._text


class FakeProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = FakeStream(stdout)
        self.stderr = FakeStream(stderr)

    def wait(self) -> int:
        return self.returncode


class RaisingProcess:
    """A fake exec() return value whose .wait() raises."""

    def __init__(self, error: Exception):
        self._error = error
        self.stdout = FakeStream("")
        self.stderr = FakeStream("")

    def wait(self):
        raise self._error


class FakeFileHandle:
    def __init__(self, store: dict, path: str):
        self._store = store
        self._path = path
        self._chunks: list[bytes] = []

    def write(self, data) -> None:
        self._chunks.append(data if isinstance(data, bytes) else data.encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._store[self._path] = b"".join(self._chunks)
        return False


class FakeImage:
    """Records how the image was built; from_registry is a class-level
    call recorder, and any other builder method is a hard failure."""

    build_calls: list[tuple] = []
    entrypoint_calls: list[list] = []

    def __init__(self, tag: str):
        self.tag = tag

    @classmethod
    def from_registry(cls, tag, *args, **kwargs):
        cls.build_calls.append((tag, args, kwargs))
        return cls(tag)

    def entrypoint(self, entrypoint_commands: list):
        # Real modal.Image.entrypoint([]) clears the registry image's
        # baked-in ENTRYPOINT and returns a (new) chainable Image -- see
        # the matching comments in modal_provider.py. Recorded here so
        # tests can assert it was actually called with [].
        FakeImage.entrypoint_calls.append(entrypoint_commands)
        return self

    def run_commands(self, *args, **kwargs):
        raise AssertionError("Image.run_commands must never be called")

    def pip_install(self, *args, **kwargs):
        raise AssertionError("Image.pip_install must never be called")

    def apt_install(self, *args, **kwargs):
        raise AssertionError("Image.apt_install must never be called")


class FakeSandboxFilesystem:
    """Mirrors modal.Sandbox.filesystem (the current, non-deprecated
    write/remove API) against the same in-memory files dict the old
    .open()/.rm()-based fake used, so sandbox.files[...] assertions in
    other tests keep working unchanged."""

    def __init__(self, files: dict):
        self._files = files

    def write_bytes(self, data: bytes, remote_path: str) -> None:
        self._files[remote_path] = bytes(data)

    def write_text(self, data: str, remote_path: str) -> None:
        self._files[remote_path] = data.encode("utf-8")

    def remove(self, remote_path: str, *, recursive: bool = False) -> None:
        if remote_path not in self._files:
            raise modal.exception.SandboxFilesystemNotFoundError(remote_path)
        del self._files[remote_path]


class FakeApp:
    lookup_calls: list[tuple] = []

    def __init__(self, name: str):
        self.name = name

    @classmethod
    def lookup(cls, name, *, client=None, environment_name=None, create_if_missing=False):
        cls.lookup_calls.append((name, create_if_missing))
        return cls(name)


class FakeSandbox:
    """Records constructor kwargs and every exec()/open()/rm() call. Each
    instance is queued with exec responses in the order tests expect them
    to be consumed: [launch_response, read_result_response, ...]."""

    create_calls: list[dict] = []
    create_positional_calls: list[tuple] = []
    instances: list["FakeSandbox"] = []
    create_side_effect = None

    def __init__(self, *args, **kwargs):
        self.cmd_args = args
        self.kwargs = kwargs
        self.files: dict[str, bytes] = {}
        self.exec_calls: list[tuple] = []
        self.terminate_calls = 0
        self.exec_queue: list[object] = []
        self._filesystem = FakeSandboxFilesystem(self.files)

    @property
    def filesystem(self) -> FakeSandboxFilesystem:
        return self._filesystem

    @classmethod
    def create(cls, *args, **kwargs):
        # Real Sandbox.create(*args, ...) sets the sandbox's CMD -- our
        # code overrides it with ("sleep", "infinity") so the container
        # idles instead of auto-running the image's ENTRYPOINT. Recorded
        # separately from create_calls (kwargs only) so existing kwarg
        # assertions stay a plain dict lookup.
        cls.create_positional_calls.append(args)
        cls.create_calls.append(kwargs)
        if cls.create_side_effect is not None:
            raise cls.create_side_effect
        instance = cls(*args, **kwargs)
        cls.instances.append(instance)
        return instance

    def open(self, path: str, mode: str = "r"):
        return FakeFileHandle(self.files, path)

    def rm(self, path: str, recursive: bool = False) -> None:
        if path not in self.files:
            raise modal.exception.SandboxFilesystemNotFoundError(path)
        del self.files[path]

    def exec(self, *args, **kwargs):
        self.exec_calls.append((args, kwargs))
        if not self.exec_queue:
            return FakeProcess(returncode=0)
        response = self.exec_queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def terminate(self, *, wait: bool = False):
        self.terminate_calls += 1
        return 0


@pytest.fixture(autouse=True)
def _reset_fakes(monkeypatch):
    FakeSandbox.create_calls = []
    FakeSandbox.create_positional_calls = []
    FakeSandbox.instances = []
    FakeSandbox.create_side_effect = None
    FakeImage.build_calls = []
    FakeImage.entrypoint_calls = []
    FakeApp.lookup_calls = []
    monkeypatch.setattr(modal, "Sandbox", FakeSandbox)
    monkeypatch.setattr(modal, "Image", FakeImage)
    monkeypatch.setattr(modal, "App", FakeApp)
    yield


def _result_process(payload: dict) -> FakeProcess:
    return FakeProcess(returncode=0, stdout=json.dumps(payload))


# ---------------------------------------------------------------------------
# _memory_mib
# ---------------------------------------------------------------------------


def test_memory_mib_parses_megabyte_suffix():
    assert _memory_mib("256m") == 256


def test_memory_mib_parses_gigabyte_suffix():
    assert _memory_mib("1g") == 1024


def test_memory_mib_rejects_garbage():
    with pytest.raises(ValueError):
        _memory_mib("not-a-size")


# ---------------------------------------------------------------------------
# Sandbox.create kwargs (security-critical)
# ---------------------------------------------------------------------------


def test_sandbox_create_kwargs_are_security_critical_and_correct(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    FakeSandbox.instances_will_have_exec = True
    provider._ensure_sandbox(tmp_path)

    assert len(FakeSandbox.create_calls) == 1
    kwargs = FakeSandbox.create_calls[0]
    assert kwargs["block_network"] is True
    assert kwargs["volumes"] == {}
    assert kwargs["network_file_systems"] == {}
    assert "secrets" not in kwargs or not kwargs["secrets"]
    assert kwargs["include_oidc_identity_token"] is False
    for forbidden in (
        "encrypted_ports",
        "unencrypted_ports",
        "h2_ports",
        "proxy",
        "custom_domain",
        "outbound_cidr_allowlist",
        "outbound_domain_allowlist",
        "inbound_cidr_allowlist",
    ):
        assert forbidden not in kwargs
    assert kwargs["workdir"] == "/work"
    assert kwargs["cpu"] == (1.0, 1.0)
    assert kwargs["memory"] == (256, 256)
    assert kwargs["timeout"] == 600
    assert kwargs["idle_timeout"] == 120
    # CMD is overridden to idle rather than letting the image's baked-in
    # ENTRYPOINT auto-run the isolated runner before inputs are uploaded.
    assert FakeSandbox.create_positional_calls[0] == ("sleep", "infinity")


def test_image_built_only_via_from_registry_with_configured_digest(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(
        _settings(
            modal_runner_image="ghcr.io/example/inktocode-cpp-runner@sha256:deadbeef"
        )
    )
    provider._ensure_sandbox(tmp_path)

    assert len(FakeImage.build_calls) == 1
    tag, args, kwargs = FakeImage.build_calls[0]
    assert tag == "ghcr.io/example/inktocode-cpp-runner@sha256:deadbeef"
    # No further builder methods (run_commands/pip_install/apt_install) are
    # ever invoked -- FakeImage raises AssertionError if they are.
    # .entrypoint([]) clears the registry image's baked-in ENTRYPOINT at
    # the Modal image-object level -- this does not touch run_commands/
    # pip_install/apt_install and is not a build step against the registry.
    assert FakeImage.entrypoint_calls == [[]]


def test_app_lookup_uses_configured_app_name(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings(modal_app_name="my-app"))
    provider._ensure_sandbox(tmp_path)

    assert FakeApp.lookup_calls == [("my-app", True)]


# ---------------------------------------------------------------------------
# Exec launch line
# ---------------------------------------------------------------------------


def test_launch_command_is_the_exact_fixed_string_with_no_user_data(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        _result_process({"exit_code": 0, "stdout": "ok"}),
    ]

    provider.compile_and_run(tmp_path, "TOP SECRET STDIN", timeout_seconds=2)

    launch_args, launch_kwargs = sandbox.exec_calls[0]
    # bash, not the image's default /bin/sh (dash): dash's ulimit builtin
    # rejects -u (max-user-processes) outright, silently no-op'ing the
    # PID-limit line since the launch command has no `set -e`.
    assert launch_args == ("/bin/bash", "-c", _LAUNCH_COMMAND)
    assert "setpriv --reuid=10001" in _LAUNCH_COMMAND
    assert "--no-new-privs" in _LAUNCH_COMMAND
    assert "env -i" in _LAUNCH_COMMAND
    assert "ulimit -u 32" in _LAUNCH_COMMAND
    assert "TOP SECRET STDIN" not in _LAUNCH_COMMAND
    assert "int main" not in _LAUNCH_COMMAND
    assert launch_kwargs["workdir"] == "/work"

    read_args, _read_kwargs = sandbox.exec_calls[1]
    assert read_args == _READ_RESULT_COMMAND


def test_stdin_is_uploaded_via_manifest_not_the_launch_command(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        _result_process({"exit_code": 0}),
    ]

    provider.compile_and_run(tmp_path, "private input", timeout_seconds=2)

    manifest = json.loads(sandbox.files["/work/runner-request.json"])
    assert manifest["stdin"] == "private input"
    assert "private input" not in json.dumps(
        [call for call in sandbox.exec_calls]
    )


# ---------------------------------------------------------------------------
# Sandbox reuse / lifecycle
# ---------------------------------------------------------------------------


def test_one_sandbox_reused_across_compile_and_three_runs(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())

    def queue_ok(sandbox, payload):
        sandbox.exec_queue.extend(
            [FakeProcess(returncode=0), _result_process(payload)]
        )

    # compile_only=True
    sandbox = provider._ensure_sandbox(tmp_path)
    queue_ok(sandbox, {"memory_tool": "none"})
    provider.compile_and_run(tmp_path, "", timeout_seconds=2, compile_only=True)

    for _ in range(3):
        queue_ok(sandbox, {"exit_code": 0, "stdout": "ok"})
        provider.compile_and_run(tmp_path, "1\n", timeout_seconds=2)

    assert len(FakeSandbox.create_calls) == 1

    provider.close()
    assert sandbox.terminate_calls == 1
    provider.close()
    assert sandbox.terminate_calls == 1  # idempotent, no double-terminate


def test_terminate_runs_even_when_an_exec_raises(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [RaisingProcess(RuntimeError("boom"))]

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error is not None
    # close() was not implicitly called for a non-timeout failure; the
    # caller (compiler.py / test_execution.py) is responsible for closing
    # in its own finally. Explicitly closing here must still terminate.
    provider.close()
    assert sandbox.terminate_calls == 1


def test_second_different_work_directory_raises(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "main.cpp").write_text("int main() {}")
    (other / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    provider._ensure_sandbox(tmp_path)

    with pytest.raises(ValueError):
        provider._ensure_sandbox(other)


# ---------------------------------------------------------------------------
# Result retrieval never uses sb.open on the result path
# ---------------------------------------------------------------------------


def test_result_retrieval_never_opens_the_result_path_directly(tmp_path, monkeypatch):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        _result_process({"exit_code": 0}),
    ]

    opened_paths = []
    original_open = sandbox.open

    def tracking_open(path, mode="r"):
        opened_paths.append(path)
        return original_open(path, mode)

    monkeypatch.setattr(sandbox, "open", tracking_open)

    provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert "/work/runner-result.json" not in opened_paths


# ---------------------------------------------------------------------------
# Failure modes -> infrastructure_error
# ---------------------------------------------------------------------------


def test_create_failure_yields_infrastructure_error(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    FakeSandbox.create_side_effect = RuntimeError("no capacity")
    provider = ModalExecutionProvider(_settings())

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error == "The isolated runner could not start."


def test_exec_raises_yields_infrastructure_error(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [RaisingProcess(RuntimeError("connection reset"))]

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error == "The isolated runner could not start."


def test_exec_timeout_yields_infrastructure_error_and_terminates_sandbox(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        RaisingProcess(modal.exception.ExecTimeoutError("timed out"))
    ]

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error == (
        "The isolated runner did not complete the request."
    )
    assert result.timed_out is True
    assert sandbox.terminate_calls == 1


def test_compile_only_exec_timeout_sets_compile_timed_out(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        RaisingProcess(modal.exception.SandboxTimeoutError("timed out"))
    ]

    result = provider.compile_and_run(
        tmp_path, "", timeout_seconds=2, compile_only=True
    )

    assert result.compile_timed_out is True
    assert sandbox.terminate_calls == 1


def test_non_json_stdout_yields_invalid_result_error(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        FakeProcess(returncode=0, stdout="not json at all"),
    ]

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error == (
        "The isolated runner returned an invalid result."
    )


def test_empty_stdout_yields_could_not_start_error(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        FakeProcess(returncode=0, stdout=""),
    ]

    result = provider.compile_and_run(tmp_path, "", timeout_seconds=2)

    assert result.infrastructure_error == "The isolated runner could not start."


def test_compile_source_create_failure_yields_infrastructure_error(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    FakeSandbox.create_side_effect = RuntimeError("no capacity")
    provider = ModalExecutionProvider(_settings())

    result = provider.compile_source(tmp_path, timeout_seconds=10)

    assert result.infrastructure_error == "The isolated runner could not start."


def test_compile_source_success_round_trips_payload(tmp_path):
    (tmp_path / "main.cpp").write_text("int main() {}")
    provider = ModalExecutionProvider(_settings())
    sandbox = provider._ensure_sandbox(tmp_path)
    sandbox.exec_queue = [
        FakeProcess(returncode=0),
        _result_process({"stdout": "", "stderr": "", "exit_code": 0}),
    ]

    result = provider.compile_source(tmp_path, timeout_seconds=10)

    assert result.exit_code == 0
    assert result.infrastructure_error is None


# ---------------------------------------------------------------------------
# modal_capabilities
# ---------------------------------------------------------------------------


def test_modal_capabilities_absent_tokens_returns_generic_unavailable(monkeypatch):
    modal_capabilities.cache_clear()
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)

    capabilities = modal_capabilities("image", "1.0", "256m", 600)

    assert capabilities == ProviderCapabilities(
        "modal", False, False, False, False, False, False, False,
        "The isolated cloud runner is unavailable.",
    )


def test_modal_capabilities_is_lru_cached(monkeypatch):
    modal_capabilities.cache_clear()
    monkeypatch.delenv("MODAL_TOKEN_ID", raising=False)
    monkeypatch.delenv("MODAL_TOKEN_SECRET", raising=False)

    first = modal_capabilities("image", "1.0", "256m", 600)
    second = modal_capabilities("image", "1.0", "256m", 600)

    assert first is second


def test_modal_capabilities_with_tokens_runs_probe_and_terminates_sandbox(
    monkeypatch,
):
    modal_capabilities.cache_clear()
    monkeypatch.setenv("MODAL_TOKEN_ID", "id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "secret")

    probe_payload = {
        "compiler_available": True,
        "address_sanitizer_available": True,
        "undefined_behavior_sanitizer_available": True,
        "leak_sanitizer_available": True,
        "valgrind_available": True,
    }

    original_create = FakeSandbox.create

    def create_with_queue(*args, **kwargs):
        instance = original_create(*args, **kwargs)
        instance.exec_queue = [
            FakeProcess(returncode=0),
            _result_process(probe_payload),
        ]
        return instance

    monkeypatch.setattr(
        FakeSandbox, "create", classmethod(lambda cls, *a, **kw: create_with_queue(*a, **kw))
    )

    capabilities = modal_capabilities("image", "1.0", "256m", 600)

    assert capabilities.provider == "modal"
    assert capabilities.runtime_available is True
    assert capabilities.image_available is True
    assert capabilities.compiler_available is True
    assert FakeSandbox.instances[-1].terminate_calls == 1
