"""Modal-backed ExecutionProvider.

This module is one of exactly two places in this codebase permitted to
compile or run submitted C++ (the other being its Docker sibling in
execution_providers.py). Everything here launches its isolated cloud
sandbox and reads results back through the fixed, argument-list commands
defined below -- never through a locally spawned child process and never
by naming a compiler binary directly. A static guard test scans app/ for
exactly those two categories of host-execution primitive and this file
must keep failing that scan (i.e. contain none of it): no local child
process launch of any kind, and no direct reference to either C++
compiler executable by name. If you need to add a new failure path or
diagnostic here, keep it that way -- describe compiler invocation only in
terms of "the isolated runner" or "the compiler", never by binary name,
and never reach for a child-process API; the fixed launch string below is
the only place a compiler ever gets named, and it lives one file over in
runner.py, which this module never inlines.

Compensating controls vs. the Docker path (see docs/internal/
MODAL_DEPLOYMENT.md and AGENTS.md for the full, honest comparison): the
cloud sandbox provider runs its container as root and ignores a
Dockerfile USER directive, so non-root execution of user-submitted code is
reconstructed in user space via the fixed launch command's `setpriv`
drop-privilege step, paired with `ulimit` resource caps and a hermetic
`env -i` environment so no host or platform secret is ever visible to
user code. Network access is disabled at the sandbox level. There is
deliberately no read-only-rootfs equivalent claimed here -- see the
security matrix in AGENTS.md; the compensating control for that gap is
that every sandbox is single-use and ephemeral.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

import modal
import modal.exception

from app.config import Settings
from app.services.execution_providers import (
    ExecutionResult,
    ProviderCapabilities,
    ProviderName,
    build_compile_manifest,
    build_run_manifest,
    capabilities_from_probe_payload,
    clamped_timeouts,
    compile_result_from_payload,
    execution_result_from_payload,
    unavailable_capabilities,
)


logger = logging.getLogger(__name__)

# Fixed launch line for the isolated runner inside the cloud sandbox.
# Contains no user data -- no source, no stdin, no secret value. See
# AGENTS.md / docs/internal/MODAL_DEPLOYMENT.md for the control-by-control
# rationale (each ulimit/setpriv/env flag mirrors one Docker hardening
# flag from execution_providers.py's base command).
_LAUNCH_COMMAND = (
    "ulimit -c 0; ulimit -f 131072; ulimit -n 64; ulimit -u 32; "
    "exec setpriv --reuid=10001 --regid=10001 --clear-groups --no-new-privs "
    "env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
    "HOME=/work TMPDIR=/work LANG=C.UTF-8 "
    "PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 "
    "python3 /opt/inktocode/runner.py"
)

# Result retrieval never reads the result path through the sandbox
# filesystem API directly (that would follow a symlink a hostile program
# could have planted there); it always goes through the dedicated
# root-side reader, which O_NOFOLLOW-rejects exactly that.
_READ_RESULT_COMMAND = ("python3", "/opt/inktocode/read_result.py")

_RESULT_PATH = "/work/runner-result.json"
_MAIN_CPP_PATH = "/work/main.cpp"
_REQUEST_PATH = "/work/runner-request.json"

_MEMORY_PATTERN = re.compile(r"^(\d+)\s*([kKmMgG]?)(?:[iI]?[bB])?$")

_MODAL_CAPABILITY_PROBE_TIMEOUT_SECONDS = 180

# Read-result exec calls are cheap and fixed-size (<=64 KiB of JSON); this
# bounds them independently of the caller's own compile/run timeout so a
# slow read never silently inflates the effective request timeout.
_READ_RESULT_EXEC_TIMEOUT_SECONDS = 30


def _memory_mib(value: str) -> int:
    """Parse a CPP_RUNNER_MEMORY-style string ("256m", "1g") to MiB."""
    match = _MEMORY_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unrecognized memory value: {value!r}")
    amount = int(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit == "g":
        return amount * 1024
    if unit == "k":
        return max(1, amount // 1024)
    return amount


class ModalExecutionProvider:
    name: ProviderName = "modal"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._sandbox = None
        self._work_directory: Path | None = None

    def capabilities(self) -> ProviderCapabilities:
        return modal_capabilities(
            self.settings.modal_runner_image,
            self.settings.cpp_runner_cpus,
            self.settings.cpp_runner_memory,
            self.settings.modal_sandbox_timeout_seconds,
        )

    def close(self) -> None:
        sandbox = self._sandbox
        self._sandbox = None
        self._work_directory = None
        if sandbox is None:
            return
        try:
            sandbox.terminate()
        except Exception:  # noqa: BLE001 - best-effort cleanup, never raise
            logger.warning(
                "Modal sandbox termination failed; it will still be "
                "reclaimed by its idle timeout."
            )

    def _ensure_sandbox(self, work_directory: Path):
        if self._sandbox is not None:
            if self._work_directory != work_directory:
                raise ValueError(
                    "A ModalExecutionProvider instance may only be used "
                    "with a single work directory."
                )
            return self._sandbox
        self._work_directory = work_directory
        app = modal.App.lookup(
            self.settings.modal_app_name, create_if_missing=True
        )
        # .entrypoint([]) clears the registry image's baked-in ENTRYPOINT at
        # the Modal image-object level only (the registry image itself and
        # the Docker path are untouched). Without it, Sandbox.create's own
        # command below is appended after that ENTRYPOINT rather than
        # replacing it, so the isolated runner still auto-starts before
        # main.cpp/runner-request.json exist and the sandbox exits before
        # inputs can be uploaded.
        image = modal.Image.from_registry(
            self.settings.modal_runner_image
        ).entrypoint([])
        cpu = float(self.settings.cpp_runner_cpus)
        memory = _memory_mib(self.settings.cpp_runner_memory)
        self._sandbox = modal.Sandbox.create(
            # Override the image's ENTRYPOINT with an idle process. Without
            # this, the sandbox's container runs the isolated runner
            # immediately on creation -- before main.cpp/runner-request.json
            # exist -- and exits almost instantly, so the upload that
            # follows finds no running container left to write into. The
            # actual runner invocation still happens explicitly below via
            # the fixed launch command, unchanged.
            "sleep",
            "infinity",
            image=image,
            app=app,
            workdir="/work",
            block_network=True,
            cpu=(cpu, cpu),
            memory=(memory, memory),
            timeout=int(self.settings.modal_sandbox_timeout_seconds),
            idle_timeout=int(self.settings.modal_sandbox_idle_timeout_seconds),
            volumes={},
            network_file_systems={},
            include_oidc_identity_token=False,
        )
        return self._sandbox

    def _upload_inputs(self, sandbox, work_directory: Path, manifest: dict) -> None:
        main_cpp = (work_directory / "main.cpp").read_bytes()
        # Written as root through the sandbox filesystem API (distinct
        # from the non-root user the launch command drops into for the
        # isolated runner and its child), matching the Docker path's
        # host-owned 0644 input files that the non-root container user
        # can read but not overwrite.
        sandbox.filesystem.write_bytes(main_cpp, _MAIN_CPP_PATH)
        sandbox.filesystem.write_text(json.dumps(manifest), _REQUEST_PATH)
        try:
            sandbox.filesystem.remove(_RESULT_PATH)
        except Exception:  # noqa: BLE001 - absence is the expected case
            pass

    def _invoke(
        self,
        manifest: dict,
        work_directory: Path,
        *,
        outer_timeout: float,
    ) -> tuple[str, dict | None]:
        """Run one manifest through the sandbox.

        Returns (status, payload) where status is one of "ok", "timeout",
        "no_start", or "invalid_result". payload is only set for "ok".
        Never raises for infrastructure-level failures -- those are all
        folded into a status the caller maps to an ExecutionResult.
        """
        try:
            sandbox = self._ensure_sandbox(work_directory)
        except ValueError:
            raise
        except Exception:  # noqa: BLE001
            logger.warning("Modal sandbox creation failed.", exc_info=True)
            return "no_start", None
        try:
            self._upload_inputs(sandbox, work_directory, manifest)
            # bash, not the image's default /bin/sh (dash): dash's ulimit
            # builtin rejects -u (max-user-processes) outright ("Illegal
            # option"), silently skipping the PID-limit line since this
            # command has no `set -e`. bash's ulimit supports -u correctly.
            launch = sandbox.exec(
                "/bin/bash",
                "-c",
                _LAUNCH_COMMAND,
                timeout=max(1, int(outer_timeout)),
                workdir="/work",
            )
            launch.wait()
        except (
            modal.exception.ExecTimeoutError,
            modal.exception.SandboxTimeoutError,
        ):
            logger.warning("Modal isolated runner exceeded its timeout.")
            self.close()
            return "timeout", None
        except Exception:  # noqa: BLE001
            logger.warning("Modal isolated runner invocation failed.", exc_info=True)
            return "no_start", None
        try:
            reader = sandbox.exec(
                *_READ_RESULT_COMMAND,
                timeout=_READ_RESULT_EXEC_TIMEOUT_SECONDS,
                workdir="/work",
            )
            reader.wait()
            stdout_text = reader.stdout.read()
        except Exception:  # noqa: BLE001
            logger.warning("Modal result read failed.", exc_info=True)
            return "no_start", None
        if not stdout_text or not stdout_text.strip():
            return "no_start", None
        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError:
            return "invalid_result", None
        if not isinstance(payload, dict):
            return "invalid_result", None
        return "ok", payload

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
        outer_timeout = compile_timeout + 5 if compile_only else run_timeout + 5
        status, payload = self._invoke(
            manifest, work_directory, outer_timeout=outer_timeout
        )
        if status == "timeout":
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner could not finish compiling in time."
                    if compile_only
                    else "The isolated runner did not complete the request."
                ),
                timed_out=not compile_only,
                compile_timed_out=compile_only,
            )
        if status == "no_start":
            return ExecutionResult(
                infrastructure_error="The isolated runner could not start."
            )
        if status == "invalid_result":
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
        manifest = build_compile_manifest(compile_timeout_seconds=timeout_seconds)
        status, payload = self._invoke(
            manifest, work_directory, outer_timeout=timeout_seconds + 5
        )
        if status == "timeout":
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner did not complete the compile request."
                ),
                compile_timed_out=True,
            )
        if status == "no_start":
            return ExecutionResult(
                infrastructure_error="The isolated runner could not start."
            )
        if status == "invalid_result":
            return ExecutionResult(
                infrastructure_error=(
                    "The isolated runner returned an invalid result."
                )
            )
        return compile_result_from_payload(payload)


@lru_cache(maxsize=4)
def modal_capabilities(
    image: str,
    cpu: str,
    memory: str,
    sandbox_timeout: float,
) -> ProviderCapabilities:
    import os

    if not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get(
        "MODAL_TOKEN_SECRET"
    ):
        return unavailable_capabilities(
            "modal",
            runtime=False,
            image=False,
            reason="The isolated cloud runner is unavailable.",
        )
    try:
        app = modal.App.lookup("inktocode-capability-probe", create_if_missing=True)
        # See the matching comment in _ensure_sandbox: clears the registry
        # image's baked-in ENTRYPOINT at the Modal image-object level only.
        probe_image = modal.Image.from_registry(image).entrypoint([])
        cpu_value = float(cpu)
        memory_value = _memory_mib(memory)
        sandbox = modal.Sandbox.create(
            # See the matching comment in _ensure_sandbox: without an idle
            # override command, the sandbox's container runs the isolated
            # runner immediately (before the probe request file exists) and
            # exits before the upload below can run.
            "sleep",
            "infinity",
            image=probe_image,
            app=app,
            workdir="/work",
            block_network=True,
            cpu=(cpu_value, cpu_value),
            memory=(memory_value, memory_value),
            timeout=int(sandbox_timeout),
            idle_timeout=60,
            volumes={},
            network_file_systems={},
            include_oidc_identity_token=False,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "C++ memory runner capability probe: Modal sandbox creation "
            "failed.",
            exc_info=True,
        )
        return unavailable_capabilities(
            "modal",
            runtime=True,
            image=False,
            reason="The C++ runner image is not available.",
        )
    try:
        sandbox.filesystem.write_text(
            json.dumps({"mode": "capability_probe"}), _REQUEST_PATH
        )
        try:
            sandbox.filesystem.remove(_RESULT_PATH)
        except Exception:  # noqa: BLE001
            pass
        # See the matching comment in _invoke: bash, not dash, so -u
        # (max-user-processes) in the launch command is actually honored.
        launch = sandbox.exec(
            "/bin/bash",
            "-c",
            _LAUNCH_COMMAND,
            timeout=_MODAL_CAPABILITY_PROBE_TIMEOUT_SECONDS,
            workdir="/work",
        )
        launch.wait()
        reader = sandbox.exec(
            *_READ_RESULT_COMMAND,
            timeout=_READ_RESULT_EXEC_TIMEOUT_SECONDS,
            workdir="/work",
        )
        reader.wait()
        stdout_text = reader.stdout.read()
        payload = json.loads(stdout_text) if stdout_text.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:  # noqa: BLE001
        logger.warning(
            "C++ memory runner capability probe: Modal probe run failed.",
            exc_info=True,
        )
        payload = None
    finally:
        try:
            sandbox.terminate()
        except Exception:  # noqa: BLE001
            pass
    if payload is None or not payload:
        return unavailable_capabilities(
            "modal",
            runtime=True,
            image=True,
            reason="The C++ memory runner capability probe failed.",
        )
    return capabilities_from_probe_payload("modal", payload)
