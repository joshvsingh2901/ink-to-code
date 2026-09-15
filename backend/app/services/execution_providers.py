import json
import logging
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

from app.config import Settings, get_settings


logger = logging.getLogger(__name__)

ProviderName = Literal["docker", "modal"]
MemoryTool = Literal[
    "none", "sanitizer", "valgrind", "sanitizer_and_valgrind"
]
_SAFE_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}")
_SAFE_RESOURCE = re.compile(r"[A-Za-z0-9.]+")
_OUTPUT_LIMIT = 64 * 1024
# The probe runs two compiles (one linking the ASan/UBSan runtime) plus a
# Valgrind pass on a trivial program. Measured local wall time is ~1-2s, but
# shared/throttled CI runners need more headroom than a single fixed compile
# or run timeout would give; this is a one-time, lru_cache'd check, not a
# per-request limit, so a generous bound here costs nothing in the hot path.
# Real per-request compile/run timeouts remain governed by
# Settings.cpp_docker_compile_timeout_seconds /
# cpp_docker_run_timeout_seconds and are unaffected by this constant.
_CAPABILITY_PROBE_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: ProviderName
    runtime_available: bool
    image_available: bool
    compiler_available: bool
    address_sanitizer_available: bool
    undefined_behavior_sanitizer_available: bool
    leak_sanitizer_available: bool
    valgrind_available: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class ExecutionResult:
    compile_error: str | None = None
    infrastructure_error: str | None = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    output_limited: bool = False
    function_stdout: str = ""
    result_metadata: str | None = None
    step_stdout: tuple[str, ...] = ()
    step_metadata: tuple[str | None, ...] = ()
    progress_index: int | None = None
    constructor_metadata: str | None = None
    memory_tool: MemoryTool = "none"
    valgrind_diagnostics: str | None = None
    leaked_bytes: int | None = None
    leaked_allocations: int | None = None
    leak_kind: str | None = None
    compile_timed_out: bool = False


# Back-compat alias: earlier code (and imports outside this module) referred
# to this dataclass as DockerExecutionResult before the provider surface
# became provider-neutral. Keep the old name usable without duplicating the
# definition.
DockerExecutionResult = ExecutionResult


class ExecutionProvider(Protocol):
    name: ProviderName

    def capabilities(self) -> ProviderCapabilities: ...

    def compile_source(
        self,
        work_directory: Path,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult: ...

    def compile_and_run(
        self,
        work_directory: Path,
        stdin: str,
        *,
        timeout_seconds: float,
        compile_only: bool = False,
        run_memory_checks: bool = False,
    ) -> ExecutionResult: ...

    def close(self) -> None: ...


def _validated_settings(settings: Settings) -> Settings:
    if settings.cpp_execution_provider not in {"auto", "docker", "modal"}:
        raise ValueError(
            "CPP_EXECUTION_PROVIDER must be docker or modal. Host execution "
            "is disabled."
        )
    is_modal = settings.cpp_execution_provider == "modal"
    if is_modal:
        if not settings.modal_runner_image:
            raise ValueError("MODAL_RUNNER_IMAGE is required when "
                              "CPP_EXECUTION_PROVIDER is modal.")
    else:
        if not _SAFE_IMAGE.fullmatch(settings.cpp_runner_image):
            raise ValueError("CPP_RUNNER_IMAGE is invalid.")
        if not _SAFE_RESOURCE.fullmatch(settings.cpp_runner_memory):
            raise ValueError("CPP_RUNNER_MEMORY is invalid.")
        if not _SAFE_RESOURCE.fullmatch(settings.cpp_runner_cpus):
            raise ValueError("CPP_RUNNER_CPUS is invalid.")
        if not 1 <= settings.cpp_runner_pids <= 256:
            raise ValueError("CPP_RUNNER_PIDS must be between 1 and 256.")
        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_-]{0,31}", settings.cpp_runner_user
        ):
            raise ValueError("CPP_RUNNER_USER is invalid.")
        if not 1 <= settings.cpp_docker_compile_timeout_seconds <= 120:
            raise ValueError("CPP_DOCKER_COMPILE_TIMEOUT_SECONDS is invalid.")
        if not 0.05 <= settings.cpp_docker_run_timeout_seconds <= 30:
            raise ValueError("CPP_DOCKER_RUN_TIMEOUT_SECONDS is invalid.")
        if not 1 <= settings.cpp_docker_valgrind_timeout_seconds <= 60:
            raise ValueError("CPP_DOCKER_VALGRIND_TIMEOUT_SECONDS is invalid.")
    return settings


def _docker_base_command(
    work_directory: Path,
    container_name: str,
    settings: Settings,
) -> list[str]:
    resolved = work_directory.resolve()
    if (
        not resolved.is_dir()
        or resolved == Path("/")
        or not (resolved / "main.cpp").is_file()
    ):
        raise ValueError("The Docker runner work directory is invalid.")
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--ipc",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(settings.cpp_runner_pids),
        "--ulimit",
        "core=0:0",
        "--ulimit",
        "fsize=67108864:67108864",
        "--ulimit",
        "nofile=64:64",
        "--memory",
        settings.cpp_runner_memory,
        "--memory-swap",
        settings.cpp_runner_memory,
        "--cpus",
        settings.cpp_runner_cpus,
        "--user",
        settings.cpp_runner_user,
        "--workdir",
        "/work",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--mount",
        (
            f"type=bind,source={resolved},target=/work,"
            "bind-propagation=rprivate"
        ),
        settings.cpp_runner_image,
    ]


def _is_regular_result_file(path: Path) -> bool:
    """True only for an ordinary file, never a symlink.

    The per-request work directory is chmod 0o777 on the host so the
    container's non-root user can write results back to it (see
    EXECUTION_SECURITY_PLAN.md's residual risks). A symlink planted at the
    expected result path — whether by the sandboxed process or a local
    host actor — must never be followed when reading results back.
    """
    return path.is_file() and not path.is_symlink()


def _run_docker_command(
    command: list[str],
    container_name: str,
    *,
    timeout_seconds: float,
) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=5,
                check=False,
                shell=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            pass
        return None


def build_run_manifest(
    *,
    stdin: str,
    compile_timeout_seconds: float,
    run_timeout_seconds: float,
    valgrind_timeout_seconds: float,
    compile_only: bool,
    run_memory_checks: bool,
    leak_sanitizer_available: bool,
    valgrind_available: bool,
) -> dict:
    """Build the exact runner-request.json payload for compile_and_run."""
    return {
        "mode": "compile_and_run",
        "stdin": stdin,
        "compile_timeout_seconds": compile_timeout_seconds,
        "run_timeout_seconds": run_timeout_seconds,
        "valgrind_timeout_seconds": valgrind_timeout_seconds,
        "output_limit_bytes": _OUTPUT_LIMIT,
        "compile_only": compile_only,
        "run_memory_checks": run_memory_checks,
        "leak_sanitizer_available": leak_sanitizer_available,
        "valgrind_available": valgrind_available,
    }


def build_compile_manifest(*, compile_timeout_seconds: float) -> dict:
    """Build the exact runner-request.json payload for compile_source."""
    return {
        "mode": "compile_source",
        "compile_timeout_seconds": compile_timeout_seconds,
        "output_limit_bytes": _OUTPUT_LIMIT,
    }


def clamped_timeouts(
    settings: Settings,
    timeout_seconds: float,
    *,
    compile_only: bool,
) -> tuple[float, float]:
    """Return (run_timeout, compile_timeout) clamped to configured bounds."""
    run_timeout = min(
        max(timeout_seconds, 0.05),
        settings.cpp_docker_run_timeout_seconds,
    )
    compile_timeout = (
        min(
            max(timeout_seconds, 1),
            settings.cpp_docker_compile_timeout_seconds,
        )
        if compile_only
        else settings.cpp_docker_compile_timeout_seconds
    )
    return run_timeout, compile_timeout


def execution_result_from_payload(payload: dict) -> ExecutionResult:
    """Convert a compile_and_run runner-result.json payload to a result."""
    if not isinstance(payload, dict):
        return ExecutionResult(
            infrastructure_error=(
                "The isolated runner returned an invalid result."
            )
        )
    return ExecutionResult(
        compile_error=_optional_string(payload.get("compile_error")),
        infrastructure_error=_optional_string(
            payload.get("infrastructure_error")
        ),
        stdout=_string(payload.get("stdout")),
        stderr=_string(payload.get("stderr")),
        exit_code=(
            payload.get("exit_code")
            if isinstance(payload.get("exit_code"), int)
            else None
        ),
        timed_out=bool(payload.get("timed_out")),
        output_limited=bool(payload.get("output_limited")),
        function_stdout=_string(payload.get("function_stdout")),
        result_metadata=_optional_string(
            payload.get("result_metadata")
        ),
        step_stdout=tuple(
            item if isinstance(item, str) else ""
            for item in payload.get("step_stdout", [])
        ),
        step_metadata=tuple(
            item if isinstance(item, str) else None
            for item in payload.get("step_metadata", [])
        ),
        progress_index=(
            payload.get("progress_index")
            if isinstance(payload.get("progress_index"), int)
            else None
        ),
        constructor_metadata=_optional_string(
            payload.get("constructor_metadata")
        ),
        memory_tool=(
            payload.get("memory_tool")
            if payload.get("memory_tool")
            in {
                "none",
                "sanitizer",
                "valgrind",
                "sanitizer_and_valgrind",
            }
            else "none"
        ),
        valgrind_diagnostics=_optional_string(
            payload.get("valgrind_diagnostics")
        ),
        leaked_bytes=_optional_int(payload.get("leaked_bytes")),
        leaked_allocations=_optional_int(
            payload.get("leaked_allocations")
        ),
        leak_kind=_optional_string(payload.get("leak_kind")),
        compile_timed_out=bool(payload.get("compile_timed_out")),
    )


def compile_result_from_payload(payload: dict) -> ExecutionResult:
    """Convert a compile_source runner-result.json payload to a result."""
    if not isinstance(payload, dict):
        return ExecutionResult(
            infrastructure_error=(
                "The isolated runner returned an invalid result."
            )
        )
    return ExecutionResult(
        stdout=_string(payload.get("stdout")),
        stderr=_string(payload.get("stderr")),
        exit_code=(
            payload.get("exit_code")
            if isinstance(payload.get("exit_code"), int)
            else None
        ),
        output_limited=bool(payload.get("output_limited")),
        compile_timed_out=bool(payload.get("compile_timed_out")),
        infrastructure_error=_optional_string(
            payload.get("infrastructure_error")
        ),
    )


def capabilities_from_probe_payload(
    provider: ProviderName, payload: dict
) -> ProviderCapabilities:
    """Convert a capability_probe runner-result.json payload to
    ProviderCapabilities for a runtime+image that are already known to be
    available (both are hardcoded True: getting here means the probe
    container/sandbox itself started and produced a result)."""
    return ProviderCapabilities(
        provider=provider,
        runtime_available=True,
        image_available=True,
        compiler_available=bool(payload.get("compiler_available")),
        address_sanitizer_available=bool(
            payload.get("address_sanitizer_available")
        ),
        undefined_behavior_sanitizer_available=bool(
            payload.get("undefined_behavior_sanitizer_available")
        ),
        leak_sanitizer_available=bool(
            payload.get("leak_sanitizer_available")
        ),
        valgrind_available=bool(payload.get("valgrind_available")),
        unavailable_reason=_optional_string(
            payload.get("unavailable_reason")
        ),
    )


def unavailable_capabilities(
    provider: ProviderName,
    *,
    runtime: bool,
    image: bool,
    reason: str,
) -> ProviderCapabilities:
    """Build a ProviderCapabilities for a provider that failed before, or
    without, being able to run any tool-detection probe."""
    return ProviderCapabilities(
        provider,
        runtime,
        image,
        False,
        False,
        False,
        False,
        False,
        reason,
    )


class DockerExecutionProvider:
    name: ProviderName = "docker"

    def __init__(self, settings: Settings | None = None):
        self.settings = _validated_settings(settings or get_settings())

    def capabilities(self) -> ProviderCapabilities:
        return docker_capabilities(
            self.settings.cpp_runner_image,
            self.settings.cpp_runner_memory,
            self.settings.cpp_runner_cpus,
            self.settings.cpp_runner_pids,
            self.settings.cpp_runner_user,
        )

    def close(self) -> None:
        """No-op: each Docker invocation is already a standalone `docker
        run --rm`, so there is no persistent per-instance resource to
        release. Present only to satisfy the ExecutionProvider protocol."""
        return None

    def compile_and_run(
        self,
        work_directory: Path,
        stdin: str,
        *,
        timeout_seconds: float,
        compile_only: bool = False,
        run_memory_checks: bool = False,
    ) -> ExecutionResult:
        run_timeout, compile_timeout = clamped_timeouts(
            self.settings, timeout_seconds, compile_only=compile_only
        )
        capabilities = self.capabilities() if run_memory_checks else None
        manifest = build_run_manifest(
            stdin=stdin,
            compile_timeout_seconds=compile_timeout,
            run_timeout_seconds=run_timeout,
            valgrind_timeout_seconds=(
                self.settings.cpp_docker_valgrind_timeout_seconds
            ),
            compile_only=compile_only,
            run_memory_checks=run_memory_checks,
            leak_sanitizer_available=(
                capabilities.leak_sanitizer_available
                if capabilities is not None
                else False
            ),
            valgrind_available=(
                capabilities.valgrind_available
                if capabilities is not None
                else False
            ),
        )
        manifest_path = work_directory / "runner-request.json"
        result_path = work_directory / "runner-result.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_path.chmod(0o644)
        (work_directory / "main.cpp").chmod(0o644)
        work_directory.chmod(0o777)
        result_path.unlink(missing_ok=True)
        container_name = f"inktocode-{uuid.uuid4().hex}"
        command = _docker_base_command(
            work_directory, container_name, self.settings
        )
        completed = _run_docker_command(
            command,
            container_name,
            timeout_seconds=(
                compile_timeout + 5
                if compile_only
                else run_timeout + 5
            ),
        )
        if completed is None:
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner could not finish compiling in time."
                    if compile_only
                    else "The isolated runner did not complete the request."
                ),
                timed_out=not compile_only,
                compile_timed_out=compile_only,
            )
        if not _is_regular_result_file(result_path):
            if completed.returncode in {137, -9} and not compile_only:
                return ExecutionResult(
                    stderr=(
                        "Execution was terminated after reaching an "
                        "isolation resource limit."
                    ),
                    exit_code=completed.returncode,
                )
            message = completed.stderr[:_OUTPUT_LIMIT].decode(
                "utf-8", errors="replace"
            )
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner could not start."
                    if not message
                    else "The isolated runner failed."
                )
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner returned an invalid result."
                )
            )
        return execution_result_from_payload(payload)

    def compile_source(
        self,
        work_directory: Path,
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        manifest_path = work_directory / "runner-request.json"
        result_path = work_directory / "runner-result.json"
        manifest_path.write_text(
            json.dumps(
                build_compile_manifest(compile_timeout_seconds=timeout_seconds)
            ),
            encoding="utf-8",
        )
        manifest_path.chmod(0o644)
        (work_directory / "main.cpp").chmod(0o644)
        work_directory.chmod(0o777)
        result_path.unlink(missing_ok=True)
        container_name = f"inktocode-{uuid.uuid4().hex}"
        completed = _run_docker_command(
            _docker_base_command(work_directory, container_name, self.settings),
            container_name,
            timeout_seconds=timeout_seconds + 5,
        )
        if completed is None:
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner did not complete the compile request."
                ),
                compile_timed_out=True,
            )
        if not _is_regular_result_file(result_path):
            return ExecutionResult(
                infrastructure_error="The isolated runner could not start."
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner returned an invalid result."
                )
            )
        return compile_result_from_payload(payload)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


@lru_cache(maxsize=4)
def docker_capabilities(
    image: str,
    memory: str,
    cpus: str,
    pids: int,
    user: str,
) -> ProviderCapabilities:
    try:
        runtime = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return ProviderCapabilities(
            "docker", False, False, False, False, False, False, False,
            "Docker is unavailable.",
        )
    if runtime.returncode != 0:
        return ProviderCapabilities(
            "docker", False, False, False, False, False, False, False,
            "Docker is unavailable.",
        )
    image_check = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        timeout=5,
        check=False,
        shell=False,
    )
    if image_check.returncode != 0:
        return ProviderCapabilities(
            "docker", True, False, False, False, False, False, False,
            "C++ memory runner image is not installed.",
        )
    settings = Settings(
        frontend_origin="",
        gemini_api_key=None,
        transcription_model="",
        environment="",
        cpp_execution_provider="docker",
        cpp_runner_image=image,
        cpp_runner_memory=memory,
        cpp_runner_cpus=cpus,
        cpp_runner_pids=pids,
        cpp_runner_user=user,
    )
    with tempfile.TemporaryDirectory(
        prefix="inktocode-runner-probe-"
    ) as directory:
        work = Path(directory)
        (work / "main.cpp").write_text("int main() { return 0; }\n")
        (work / "runner-request.json").write_text(
            json.dumps({"mode": "capability_probe"}),
            encoding="utf-8",
        )
        (work / "main.cpp").chmod(0o644)
        (work / "runner-request.json").chmod(0o644)
        work.chmod(0o777)
        container_name = f"inktocode-probe-{uuid.uuid4().hex}"
        probe_command = _docker_base_command(work, container_name, settings)
        completed = _run_docker_command(
            probe_command,
            container_name,
            timeout_seconds=_CAPABILITY_PROBE_TIMEOUT_SECONDS,
        )
        result_path = work / "runner-result.json"
        if completed is None or not _is_regular_result_file(result_path):
            # Diagnostic only: never surfaced to end users. The public
            # `unavailable_reason` below stays a fixed, generic string —
            # the same one `select_memory_provider()` forwards verbatim
            # into RunTestsResponse.memory_summary for real users, so it
            # must never carry raw stderr or host detail. This log line is
            # for operators/CI only; it does not run any user-submitted
            # source, only the probe's own fixed trivial program.
            if completed is None:
                logger.warning(
                    "C++ memory runner capability probe: docker run did "
                    "not complete within %ss (command=%r).",
                    _CAPABILITY_PROBE_TIMEOUT_SECONDS,
                    probe_command,
                )
            else:
                stderr_tail = completed.stderr[-2000:].decode(
                    "utf-8", errors="replace"
                )
                logger.warning(
                    "C++ memory runner capability probe: container exited "
                    "%s with no result file (command=%r). stderr tail: %s",
                    completed.returncode,
                    probe_command,
                    stderr_tail,
                )
            return ProviderCapabilities(
                "docker", True, True, False, False, False, False, False,
                "The C++ memory runner capability probe failed.",
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    return capabilities_from_probe_payload("docker", payload)


def select_execution_provider(
    settings: Settings | None = None,
) -> ExecutionProvider:
    selected = _validated_settings(settings or get_settings())
    if selected.cpp_execution_provider == "modal":
        # Imported lazily so Docker-only environments never import the
        # `modal` package (and never need it installed).
        from app.services.modal_provider import ModalExecutionProvider

        return ModalExecutionProvider(selected)
    return DockerExecutionProvider(selected)


def select_memory_provider(
    settings: Settings | None = None,
) -> tuple[ProviderName, ExecutionProvider | None, str | None]:
    """Compatibility wrapper that never falls back to host execution."""
    docker = select_execution_provider(settings)
    capabilities = docker.capabilities()
    if (
        capabilities.runtime_available
        and capabilities.image_available
        and capabilities.compiler_available
    ):
        return "docker", docker, None
    return "docker", None, (
        capabilities.unavailable_reason
        or "The isolated runner is unavailable."
    )
