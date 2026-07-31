import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

from app.config import Settings, get_settings


ProviderName = Literal["host", "docker"]
MemoryTool = Literal[
    "none", "sanitizer", "valgrind", "sanitizer_and_valgrind"
]
_SAFE_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}")
_SAFE_RESOURCE = re.compile(r"[A-Za-z0-9.]+")
_OUTPUT_LIMIT = 64 * 1024


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
class DockerExecutionResult:
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


class ExecutionProvider(Protocol):
    name: ProviderName

    def capabilities(self) -> ProviderCapabilities: ...


def host_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider="host",
        runtime_available=True,
        image_available=False,
        compiler_available=True,
        address_sanitizer_available=False,
        undefined_behavior_sanitizer_available=False,
        leak_sanitizer_available=False,
        valgrind_available=False,
    )


class HostExecutionProvider:
    name: ProviderName = "host"

    def capabilities(self) -> ProviderCapabilities:
        return host_capabilities()


def _validated_settings(settings: Settings) -> Settings:
    if settings.cpp_execution_provider not in {"auto", "host", "docker"}:
        raise ValueError(
            "CPP_EXECUTION_PROVIDER must be auto, host, or docker."
        )
    if not _SAFE_IMAGE.fullmatch(settings.cpp_runner_image):
        raise ValueError("CPP_RUNNER_IMAGE is invalid.")
    if not _SAFE_RESOURCE.fullmatch(settings.cpp_runner_memory):
        raise ValueError("CPP_RUNNER_MEMORY is invalid.")
    if not _SAFE_RESOURCE.fullmatch(settings.cpp_runner_cpus):
        raise ValueError("CPP_RUNNER_CPUS is invalid.")
    if not 1 <= settings.cpp_runner_pids <= 256:
        raise ValueError("CPP_RUNNER_PIDS must be between 1 and 256.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", settings.cpp_runner_user):
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
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(settings.cpp_runner_pids),
        "--memory",
        settings.cpp_runner_memory,
        "--cpus",
        settings.cpp_runner_cpus,
        "--user",
        settings.cpp_runner_user,
        "--workdir",
        "/work",
        "--mount",
        f"type=bind,source={resolved},target=/work",
        settings.cpp_runner_image,
    ]


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
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=5,
            check=False,
            shell=False,
        )
        return None


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

    def compile_and_run(
        self,
        work_directory: Path,
        stdin: str,
        *,
        timeout_seconds: float,
        compile_only: bool = False,
    ) -> DockerExecutionResult:
        run_timeout = self.settings.cpp_docker_run_timeout_seconds
        manifest = {
            "mode": "compile_and_run_sanitized",
            "stdin": stdin,
            "compile_timeout_seconds": (
                self.settings.cpp_docker_compile_timeout_seconds
            ),
            "run_timeout_seconds": run_timeout,
            "valgrind_timeout_seconds": (
                self.settings.cpp_docker_valgrind_timeout_seconds
            ),
            "output_limit_bytes": _OUTPUT_LIMIT,
            "compile_only": compile_only,
            "leak_sanitizer_available": (
                self.capabilities().leak_sanitizer_available
            ),
            "valgrind_available": self.capabilities().valgrind_available,
        }
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
                self.settings.cpp_docker_compile_timeout_seconds
                if compile_only
                else run_timeout + 5
            ),
        )
        if completed is None:
            return DockerExecutionResult(
                infrastructure_error=(
                    "The isolated runner could not finish compiling the test "
                    "program in time."
                    if compile_only
                    else "The isolated memory-checking environment timed out."
                ),
                timed_out=not compile_only,
                compile_timed_out=compile_only,
            )
        if not result_path.is_file():
            message = completed.stderr[:_OUTPUT_LIMIT].decode(
                "utf-8", errors="replace"
            )
            return DockerExecutionResult(
                infrastructure_error=(
                    "The isolated memory-checking environment could not start."
                    if not message
                    else "The isolated memory-checking environment failed."
                )
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return DockerExecutionResult(
                infrastructure_error=(
                    "The isolated memory-checking environment returned an "
                    "invalid result."
                )
            )
        if not isinstance(payload, dict):
            return DockerExecutionResult(
                infrastructure_error=(
                    "The isolated memory-checking environment returned an "
                    "invalid result."
                )
            )
        return DockerExecutionResult(
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
        completed = _run_docker_command(
            _docker_base_command(work, container_name, settings),
            container_name,
            timeout_seconds=30,
        )
        result_path = work / "runner-result.json"
        if completed is None or not result_path.is_file():
            return ProviderCapabilities(
                "docker", True, True, False, False, False, False, False,
                "The C++ memory runner capability probe failed.",
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    return ProviderCapabilities(
        provider="docker",
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


def select_memory_provider(
    settings: Settings | None = None,
) -> tuple[ProviderName, ExecutionProvider | None, str | None]:
    selected = _validated_settings(settings or get_settings())
    if selected.cpp_execution_provider == "host":
        return "host", HostExecutionProvider(), None
    docker = DockerExecutionProvider(selected)
    capabilities = docker.capabilities()
    if (
        capabilities.runtime_available
        and capabilities.image_available
        and capabilities.compiler_available
    ):
        return "docker", docker, None
    if selected.cpp_execution_provider == "docker":
        return "docker", None, (
            capabilities.unavailable_reason
            or "The isolated memory-checking environment is unavailable."
        )
    return (
        "host",
        HostExecutionProvider(),
        capabilities.unavailable_reason,
    )
