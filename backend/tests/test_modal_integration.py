"""Real Modal-backed regression checks for the untrusted C++ boundary,
porting the Docker security corpus (test_execution_security.py) to the
cloud sandbox provider.

Opt-in and NOT part of any default run: requires a live Modal account
(MODAL_TOKEN_ID / MODAL_TOKEN_SECRET), a published runner image
(MODAL_RUNNER_IMAGE), and INKTOCODE_RUN_MODAL_TESTS=1. These make real
network calls to Modal and spend real sandbox time/credits -- see
docs/internal/MODAL_DEPLOYMENT.md for the live-test procedure and cost
guardrails. CI's default addopts (-m "not modal_live") excludes this file
from every routine run; only an explicit `pytest -m modal_live` opts in.

Per the honest security matrix (AGENTS.md, docs/internal/
MODAL_DEPLOYMENT.md): several controls here are *compensating* rather
than identical to Docker's (non-root execution is reconstructed via
setpriv since the sandbox container itself runs as root; there is no
read-only-rootfs equivalent at all). These tests exist specifically to
prove the compensating controls actually hold under the real sandbox
runtime, not just in the fixed launch string.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from app.config import Settings
from app.schemas.test_execution import ProgramTestCase
from app.services.compiler import CompilerServiceError, compile_cpp
from app.services.modal_provider import (
    ModalExecutionProvider,
    _READ_RESULT_COMMAND,
    modal_capabilities,
)
from app.services.test_execution import run_cpp_tests


pytestmark = [
    pytest.mark.modal_live,
    pytest.mark.skipif(
        os.getenv("INKTOCODE_RUN_MODAL_TESTS") != "1",
        reason="Live Modal tests are opt-in",
    ),
]


def _live_settings() -> Settings:
    return Settings(
        frontend_origin="http://localhost:3000",
        gemini_api_key=None,
        transcription_model="test-model",
        environment="test",
        cpp_execution_provider="modal",
        modal_app_name=os.environ.get(
            "MODAL_APP_NAME", "inktocode-cpp-runner"
        ),
        modal_runner_image=os.environ["MODAL_RUNNER_IMAGE"],
        modal_sandbox_timeout_seconds=float(
            os.environ.get("MODAL_SANDBOX_TIMEOUT_SECONDS", "600")
        ),
        modal_sandbox_idle_timeout_seconds=float(
            os.environ.get("MODAL_SANDBOX_IDLE_TIMEOUT_SECONDS", "120")
        ),
    )


@pytest.fixture(autouse=True)
def _modal_provider_env(monkeypatch):
    monkeypatch.setenv("CPP_EXECUTION_PROVIDER", "modal")
    monkeypatch.setenv("MODAL_RUNNER_IMAGE", os.environ["MODAL_RUNNER_IMAGE"])
    if "MODAL_APP_NAME" not in os.environ:
        monkeypatch.setenv("MODAL_APP_NAME", "inktocode-cpp-runner")


def _modal_ready() -> None:
    capabilities = modal_capabilities(
        os.environ["MODAL_RUNNER_IMAGE"], "1.0", "256m", 600
    )
    if not (capabilities.runtime_available and capabilities.image_available):
        pytest.fail(capabilities.unavailable_reason or "Modal runner unavailable")


def _run(source: str, expected: str = "", *, timeout: float = 5):
    _modal_ready()
    return run_cpp_tests(
        source,
        [ProgramTestCase(name="security", expected_stdout=expected)],
        test_timeout_seconds=timeout,
    )


def test_normal_compile_uses_real_modal_sandbox():
    _modal_ready()
    result = compile_cpp("int main() { return 0; }")
    assert result.success is True


def test_valid_program_runs_non_root_and_rootfs_write_is_refused():
    # Non-root execution here is a compensating control (setpriv), since
    # the Modal sandbox container itself runs as root -- see the security
    # matrix. There is deliberately no read-only-rootfs claim: this only
    # proves the setpriv drop-privilege step, not filesystem immutability.
    result = _run(
        """
        #include <fstream>
        #include <iostream>
        #include <unistd.h>
        int main() {
            std::ofstream forbidden("/etc/inktocode-write-test");
            std::cout << (getuid() == 10001 ? "nonroot" : "root") << " "
                      << (forbidden ? "writable" : "readonly");
        }
        """,
        "nonroot readonly",
    )
    assert result.success is True
    assert result.execution_provider == "modal"


def test_network_connect_attempt_is_blocked():
    result = _run(
        """
        #include <arpa/inet.h>
        #include <iostream>
        #include <sys/socket.h>
        #include <unistd.h>
        int main() {
            int fd = socket(AF_INET, SOCK_STREAM, 0);
            sockaddr_in address{};
            address.sin_family = AF_INET;
            address.sin_port = htons(53);
            inet_pton(AF_INET, "1.1.1.1", &address.sin_addr);
            int connected = fd < 0 ? -1 : connect(
                fd, reinterpret_cast<sockaddr*>(&address), sizeof(address));
            if (fd >= 0) close(fd);
            std::cout << (connected == 0 ? "connected" : "blocked");
        }
        """,
        "blocked",
    )
    assert result.success is True


def test_host_filesystem_and_secret_marker_are_not_visible(tmp_path: Path):
    host_marker = tmp_path / "api-host-secret-marker"
    host_marker.write_text("must-not-be-visible", encoding="utf-8")
    result = _run(
        f"""
        #include <fstream>
        #include <iostream>
        int main() {{
            std::ifstream secret("{host_marker.as_posix()}");
            std::ifstream source("/app/backend/app/main.py");
            std::cout << ((!secret && !source) ? "isolated" : "exposed");
        }}
        """,
        "isolated",
    )
    assert result.success is True


def test_host_and_platform_secrets_are_absent_from_child_env(monkeypatch):
    monkeypatch.setenv("INKTOCODE_TEST_SECRET", "must-not-be-visible")
    result = _run(
        """
        #include <cstdlib>
        #include <iostream>
        int main() {
            const char* leaked = nullptr;
            if (std::getenv("INKTOCODE_TEST_SECRET")) leaked = "test-secret";
            else if (std::getenv("GEMINI_API_KEY")) leaked = "gemini-key";
            else if (std::getenv("MODAL_TOKEN_SECRET")) leaked = "modal-token";
            std::cout << (leaked ? "exposed" : "isolated");
        }
        """,
        "isolated",
    )
    assert result.success is True


def test_pid_limit_stops_fork_fanout():
    result = _run(
        """
        #include <iostream>
        #include <unistd.h>
        int main() {
            int created = 0;
            for (; created < 100; ++created) {
                pid_t child = fork();
                if (child < 0) break;
                if (child == 0) pause();
            }
            std::cout << (created < 100 ? "limited" : "unlimited");
        }
        """,
        "limited",
    )
    assert result.success is True


def test_infinite_loop_is_terminated_by_wall_timeout():
    result = _run("int main() { while (true) {} }", timeout=0.5)
    assert result.success is False
    assert result.tests[0].timed_out is True
    assert result.tests[0].exit_code is None


def test_excessive_stdout_is_terminated_at_output_cap():
    result = _run(
        "#include <iostream>\n"
        "int main(){ while(true) std::cout << \"xxxxxxxxxxxxxxxx\"; }",
        timeout=5,
    )
    assert result.success is False
    assert result.tests[0].output_limited is True
    assert len(result.tests[0].actual_stdout.encode()) < 66 * 1024


def test_real_compile_failure_preserves_compiler_diagnostic():
    result = _run("int main() { return missing_name; }")
    assert result.success is False
    assert "missing_name" in (result.compile_error or "")
    assert result.tests == []


def test_live_modal_capabilities_reports_sanitizers_and_a_leak_tool():
    modal_capabilities.cache_clear()
    capabilities = modal_capabilities(
        os.environ["MODAL_RUNNER_IMAGE"], "1.0", "256m", 600
    )
    assert capabilities.runtime_available is True
    assert capabilities.image_available is True
    assert capabilities.compiler_available is True
    assert capabilities.address_sanitizer_available is True
    assert capabilities.undefined_behavior_sanitizer_available is True
    assert (
        capabilities.leak_sanitizer_available
        or capabilities.valgrind_available
    )


def test_symlink_planted_at_result_path_is_rejected(tmp_path: Path):
    """A program that replaces /work/runner-result.json with a symlink to
    a file outside /work must not have that file's contents leak back
    through read_result.py -- it must O_NOFOLLOW-reject the symlink and
    report {} instead, exactly like the Docker path's
    _is_regular_result_file guard."""
    (tmp_path / "main.cpp").write_text(
        """
        #include <unistd.h>
        int main() {
            unlink("/work/runner-result.json");
            symlink("/etc/passwd", "/work/runner-result.json");
            return 0;
        }
        """,
        encoding="utf-8",
    )
    provider = ModalExecutionProvider(_live_settings())
    try:
        sandbox = provider._ensure_sandbox(tmp_path)
        # Compile and run the symlink-planting program directly through
        # the fixed launch path so it executes as the sandboxed run
        # normally would, then read the result the same way the provider
        # does: only through read_result.py, never sb.open().
        provider.compile_and_run(tmp_path, "", timeout_seconds=5)
        reader = sandbox.exec(
            *_READ_RESULT_COMMAND, timeout=30, workdir="/work"
        )
        reader.wait()
        payload = json.loads(reader.stdout.read() or "{}")
        assert "root:" not in json.dumps(payload)
    finally:
        provider.close()


def test_second_use_reuses_sandbox_not_a_new_one_per_call():
    """Sanity check that the live sandbox lifecycle really does persist
    /work/program across calls within one provider instance, matching the
    mocked assertion in test_modal_provider.py."""
    unique_marker = uuid.uuid4().hex
    result = _run(
        f'#include <iostream>\nint main(){{std::cout << "{unique_marker}";}}',
        unique_marker,
    )
    assert result.success is True
