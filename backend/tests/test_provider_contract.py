"""Pure, provider-neutral contract tests for the shared helpers extracted
from execution_providers.py during the Docker -> Docker+Modal migration.

No Docker, no Modal, no network, no subprocess, no filesystem beyond
whatever pytest's own tmp_path machinery might touch. These tests exist to
pin down the exact runner-request.json / runner-result.json schema and the
payload -> dataclass conversions that BOTH providers (Docker and Modal) rely
on, so that a change to one provider's wire format is caught immediately
instead of silently drifting from the other.
"""

import pytest

from app.config import Settings
from app.services.execution_providers import (
    ExecutionResult,
    ProviderCapabilities,
    build_compile_manifest,
    build_run_manifest,
    capabilities_from_probe_payload,
    clamped_timeouts,
    compile_result_from_payload,
    execution_result_from_payload,
    unavailable_capabilities,
)
from app.services.test_execution import _provider_process_output


def _settings(**overrides) -> Settings:
    defaults = dict(
        frontend_origin="http://localhost:3000",
        gemini_api_key=None,
        transcription_model="test-model",
        environment="test",
        cpp_runner_image="inktocode-cpp-runner",
        cpp_runner_memory="256m",
        cpp_runner_cpus="1.0",
        cpp_runner_pids=32,
        cpp_runner_user="runner",
        cpp_docker_compile_timeout_seconds=30,
        cpp_docker_run_timeout_seconds=8,
        cpp_docker_valgrind_timeout_seconds=20,
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# build_run_manifest / build_compile_manifest
# ---------------------------------------------------------------------------


def test_build_run_manifest_matches_runner_schema_for_normal_run():
    manifest = build_run_manifest(
        stdin="hello",
        compile_timeout_seconds=30,
        run_timeout_seconds=8,
        valgrind_timeout_seconds=20,
        compile_only=False,
        run_memory_checks=False,
        leak_sanitizer_available=False,
        valgrind_available=False,
    )
    assert manifest == {
        "mode": "compile_and_run",
        "stdin": "hello",
        "compile_timeout_seconds": 30,
        "run_timeout_seconds": 8,
        "valgrind_timeout_seconds": 20,
        "output_limit_bytes": 65536,
        "compile_only": False,
        "run_memory_checks": False,
        "leak_sanitizer_available": False,
        "valgrind_available": False,
    }


def test_build_run_manifest_compile_only_variant():
    manifest = build_run_manifest(
        stdin="",
        compile_timeout_seconds=2,
        run_timeout_seconds=2,
        valgrind_timeout_seconds=20,
        compile_only=True,
        run_memory_checks=False,
        leak_sanitizer_available=False,
        valgrind_available=False,
    )
    assert manifest["mode"] == "compile_and_run"
    assert manifest["compile_only"] is True
    assert manifest["compile_timeout_seconds"] == 2
    assert manifest["run_timeout_seconds"] == 2


def test_build_run_manifest_run_memory_checks_variant_carries_availability():
    manifest = build_run_manifest(
        stdin="1\n",
        compile_timeout_seconds=30,
        run_timeout_seconds=8,
        valgrind_timeout_seconds=20,
        compile_only=False,
        run_memory_checks=True,
        leak_sanitizer_available=True,
        valgrind_available=True,
    )
    assert manifest["run_memory_checks"] is True
    assert manifest["leak_sanitizer_available"] is True
    assert manifest["valgrind_available"] is True


def test_build_compile_manifest_matches_runner_schema():
    manifest = build_compile_manifest(compile_timeout_seconds=10)
    assert manifest == {
        "mode": "compile_source",
        "compile_timeout_seconds": 10,
        "output_limit_bytes": 65536,
    }


# ---------------------------------------------------------------------------
# clamped_timeouts
# ---------------------------------------------------------------------------


def test_clamped_timeouts_run_only_uses_configured_compile_timeout():
    run_timeout, compile_timeout = clamped_timeouts(
        _settings(cpp_docker_run_timeout_seconds=8, cpp_docker_compile_timeout_seconds=30),
        2,
        compile_only=False,
    )
    assert run_timeout == 2
    assert compile_timeout == 30


def test_clamped_timeouts_compile_only_clamps_to_requested_timeout():
    run_timeout, compile_timeout = clamped_timeouts(
        _settings(cpp_docker_run_timeout_seconds=8, cpp_docker_compile_timeout_seconds=30),
        2,
        compile_only=True,
    )
    assert compile_timeout == 2


def test_clamped_timeouts_run_timeout_floor_is_005():
    run_timeout, _ = clamped_timeouts(
        _settings(cpp_docker_run_timeout_seconds=8),
        0.0,
        compile_only=False,
    )
    assert run_timeout == 0.05


def test_clamped_timeouts_run_timeout_ceiling_is_configured_value():
    run_timeout, _ = clamped_timeouts(
        _settings(cpp_docker_run_timeout_seconds=8),
        1000,
        compile_only=False,
    )
    assert run_timeout == 8


def test_clamped_timeouts_compile_only_floor_is_1():
    _, compile_timeout = clamped_timeouts(
        _settings(cpp_docker_compile_timeout_seconds=30),
        0.1,
        compile_only=True,
    )
    assert compile_timeout == 1


def test_clamped_timeouts_compile_only_ceiling_is_configured_value():
    _, compile_timeout = clamped_timeouts(
        _settings(cpp_docker_compile_timeout_seconds=30),
        1000,
        compile_only=True,
    )
    assert compile_timeout == 30


# ---------------------------------------------------------------------------
# execution_result_from_payload
# ---------------------------------------------------------------------------


def test_execution_result_from_payload_successful_execution():
    result = execution_result_from_payload(
        {
            "stdout": "hi\n",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "output_limited": False,
            "memory_tool": "none",
        }
    )
    assert result.stdout == "hi\n"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.infrastructure_error is None
    assert result.memory_tool == "none"


def test_execution_result_from_payload_invalid_compile():
    result = execution_result_from_payload(
        {"compile_error": "main.cpp:1:1: error: expected ';'"}
    )
    assert result.compile_error == "main.cpp:1:1: error: expected ';'"
    assert result.exit_code is None


def test_execution_result_from_payload_runtime_failure_nonzero_exit():
    result = execution_result_from_payload(
        {"stdout": "", "stderr": "boom", "exit_code": 1}
    )
    assert result.exit_code == 1
    assert result.stderr == "boom"


def test_execution_result_from_payload_timeout_has_no_exit_code():
    result = execution_result_from_payload(
        {"stdout": "partial", "exit_code": None, "timed_out": True}
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_execution_result_from_payload_excessive_output_is_flagged():
    result = execution_result_from_payload(
        {"stdout": "x" * 100, "output_limited": True}
    )
    assert result.output_limited is True


def test_execution_result_from_payload_sanitizer_detection_round_trips():
    result = execution_result_from_payload(
        {
            "stderr": "AddressSanitizer: heap-buffer-overflow ...",
            "exit_code": 1,
            "memory_tool": "sanitizer",
        }
    )
    assert result.memory_tool == "sanitizer"
    assert "AddressSanitizer" in result.stderr

    undefined = execution_result_from_payload(
        {
            "stderr": "runtime error: signed integer overflow",
            "exit_code": 1,
            "memory_tool": "sanitizer",
        }
    )
    assert undefined.memory_tool == "sanitizer"
    assert "runtime error" in undefined.stderr


@pytest.mark.parametrize("leak_kind", ["definite", "indirect", "possible", "invalid_memory"])
def test_execution_result_from_payload_memory_diagnostics_leak_kinds(leak_kind):
    result = execution_result_from_payload(
        {
            "exit_code": 97,
            "memory_tool": "sanitizer_and_valgrind",
            "leak_kind": leak_kind,
            "leaked_bytes": 4,
            "leaked_allocations": 1,
            "valgrind_diagnostics": f"{leak_kind} lost: 4 bytes in 1 blocks",
        }
    )
    assert result.leak_kind == leak_kind
    assert result.leaked_bytes == 4
    assert result.leaked_allocations == 1


def test_execution_result_from_payload_malformed_non_dict_payload():
    result = execution_result_from_payload("not a dict")
    assert result.infrastructure_error == (
        "The isolated runner returned an invalid result."
    )
    assert result.exit_code is None


def test_execution_result_from_payload_none_payload():
    result = execution_result_from_payload(None)
    assert result.infrastructure_error == (
        "The isolated runner returned an invalid result."
    )


def test_execution_result_from_payload_list_payload():
    result = execution_result_from_payload([1, 2, 3])
    assert result.infrastructure_error == (
        "The isolated runner returned an invalid result."
    )


# ---------------------------------------------------------------------------
# compile_result_from_payload
# ---------------------------------------------------------------------------


def test_compile_result_from_payload_valid_compile():
    result = compile_result_from_payload(
        {"stdout": "", "stderr": "", "exit_code": 0, "output_limited": False}
    )
    assert result.exit_code == 0
    assert result.infrastructure_error is None


def test_compile_result_from_payload_invalid_compile_has_stderr():
    result = compile_result_from_payload(
        {
            "stdout": "",
            "stderr": "main.cpp:2:1: error: expected ';'",
            "exit_code": 1,
        }
    )
    assert result.exit_code == 1
    assert "error" in result.stderr


def test_compile_result_from_payload_malformed_non_dict_payload():
    result = compile_result_from_payload(42)
    assert result.infrastructure_error == (
        "The isolated runner returned an invalid result."
    )


# ---------------------------------------------------------------------------
# capabilities_from_probe_payload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["docker", "modal"])
def test_capabilities_from_probe_payload_full_capability(provider):
    capabilities = capabilities_from_probe_payload(
        provider,
        {
            "compiler_available": True,
            "address_sanitizer_available": True,
            "undefined_behavior_sanitizer_available": True,
            "leak_sanitizer_available": True,
            "valgrind_available": True,
        },
    )
    assert capabilities.provider == provider
    assert capabilities.runtime_available is True
    assert capabilities.image_available is True
    assert capabilities.compiler_available is True
    assert capabilities.address_sanitizer_available is True
    assert capabilities.undefined_behavior_sanitizer_available is True
    assert capabilities.leak_sanitizer_available is True
    assert capabilities.valgrind_available is True
    assert capabilities.unavailable_reason is None


@pytest.mark.parametrize("provider", ["docker", "modal"])
def test_capabilities_from_probe_payload_missing_fields_default_false(provider):
    capabilities = capabilities_from_probe_payload(provider, {})
    assert capabilities.provider == provider
    assert capabilities.runtime_available is True
    assert capabilities.image_available is True
    assert capabilities.compiler_available is False
    assert capabilities.address_sanitizer_available is False
    assert capabilities.undefined_behavior_sanitizer_available is False
    assert capabilities.leak_sanitizer_available is False
    assert capabilities.valgrind_available is False


# ---------------------------------------------------------------------------
# unavailable_capabilities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["docker", "modal"])
def test_unavailable_capabilities_shape(provider):
    capabilities = unavailable_capabilities(
        provider,
        runtime=False,
        image=False,
        reason="The isolated cloud runner is unavailable.",
    )
    assert capabilities == ProviderCapabilities(
        provider,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        "The isolated cloud runner is unavailable.",
    )


def test_unavailable_capabilities_runtime_true_image_false():
    capabilities = unavailable_capabilities(
        "modal",
        runtime=True,
        image=False,
        reason="The C++ runner image is not available.",
    )
    assert capabilities.runtime_available is True
    assert capabilities.image_available is False
    assert capabilities.compiler_available is False


# ---------------------------------------------------------------------------
# _provider_process_output sets execution_provider from capabilities.provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider_name", ["docker", "modal"])
def test_provider_process_output_uses_capabilities_provider(tmp_path, provider_name):
    capabilities = ProviderCapabilities(
        provider_name, True, True, True, True, True, True, True
    )
    output = _provider_process_output(
        ExecutionResult(stdout="ok", exit_code=0),
        capabilities,
        tmp_path,
        run_memory_checks=False,
    )
    assert output.execution_provider == provider_name


@pytest.mark.parametrize("provider_name", ["docker", "modal"])
def test_provider_process_output_infrastructure_error_uses_capabilities_provider(
    tmp_path, provider_name
):
    capabilities = ProviderCapabilities(
        provider_name, False, False, False, False, False, False, False,
        "The isolated runner is unavailable.",
    )
    output = _provider_process_output(
        ExecutionResult(infrastructure_error="The isolated runner is unavailable."),
        capabilities,
        tmp_path,
        run_memory_checks=False,
    )
    assert output.execution_provider == provider_name
    assert output.memory_status == "unavailable"
