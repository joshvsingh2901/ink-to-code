"""Real Docker-backed regression checks for the untrusted C++ boundary."""

import os
import shutil
from pathlib import Path

import pytest

from app.schemas.test_execution import ProgramTestCase
from app.services.compiler import CompilerServiceError, compile_cpp
from app.services.execution_providers import DockerExecutionProvider
from app.services.test_execution import run_cpp_tests


REQUIRE_DOCKER_TESTS = os.getenv("INKTOCODE_REQUIRE_DOCKER_TESTS") == "1"


pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None and not REQUIRE_DOCKER_TESTS,
    reason="Docker is not installed",
)


def _docker_ready() -> None:
    capabilities = DockerExecutionProvider().capabilities()
    if not (
        capabilities.runtime_available
        and capabilities.image_available
        and capabilities.compiler_available
    ):
        reason = capabilities.unavailable_reason or "Docker runner unavailable"
        if REQUIRE_DOCKER_TESTS:
            pytest.fail(reason)
        pytest.skip(reason)


def _run(source: str, expected: str = "", *, timeout: float = 2):
    _docker_ready()
    return run_cpp_tests(
        source,
        [ProgramTestCase(name="security", expected_stdout=expected)],
        test_timeout_seconds=timeout,
    )


def test_normal_compile_uses_real_isolated_runner():
    _docker_ready()
    result = compile_cpp("int main() { return 0; }")
    assert result.success is True


def test_valid_program_runs_in_non_root_read_only_container():
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
    assert result.execution_provider == "docker"


def test_infinite_loop_is_terminated_by_wall_timeout():
    result = _run("int main() { while (true) {} }", timeout=0.1)
    assert result.success is False
    assert result.tests[0].timed_out is True
    assert result.tests[0].exit_code is None


def test_excessive_stdout_is_terminated_at_output_cap():
    result = _run(
        "#include <iostream>\n"
        "int main(){ while(true) std::cout << \"xxxxxxxxxxxxxxxx\"; }",
        timeout=2,
    )
    assert result.success is False
    assert result.tests[0].output_limited is True
    assert len(result.tests[0].actual_stdout.encode()) < 66 * 1024


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


def test_application_filesystem_and_secrets_are_not_mounted(tmp_path: Path):
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


def test_api_host_environment_is_not_injected(monkeypatch):
    monkeypatch.setenv("INKTOCODE_TEST_SECRET", "must-not-be-visible")
    result = _run(
        """
        #include <cstdlib>
        #include <iostream>
        int main() {
            std::cout << (std::getenv("INKTOCODE_TEST_SECRET")
                ? "exposed" : "isolated");
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


def test_memory_exhaustion_is_confined_and_runner_recovers():
    try:
        exhausted = _run(
            """
            #include <cstring>
            #include <vector>
            int main() {
                std::vector<char*> blocks;
                while (true) {
                    char* block = new char[16 * 1024 * 1024];
                    std::memset(block, 1, 16 * 1024 * 1024);
                    blocks.push_back(block);
                }
            }
            """,
            timeout=2,
        )
        assert exhausted.success is False
    except CompilerServiceError as error:
        assert error.code == "runner_unavailable"

    recovered = _run("#include <iostream>\nint main(){std::cout << 7;}", "7")
    assert recovered.success is True


def test_real_compile_failure_preserves_compiler_diagnostic():
    result = _run("int main() { return missing_name; }")
    assert result.success is False
    assert "missing_name" in (result.compile_error or "")
    assert result.tests == []
