import importlib.util
import subprocess
from pathlib import Path

import pytest


RUNNER_PATH = Path(__file__).resolve().parents[2] / "runner" / "runner.py"


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "inktocode_runner_for_tests", RUNNER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_reuses_compiled_program_and_uses_run_timeout(
    tmp_path: Path, monkeypatch
):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    (tmp_path / "program").write_bytes(b"compiled")
    calls = []
    payloads = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"", b""), False, False

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(
        runner,
        "compile_program",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Runtime must not compile again")
        ),
    )
    monkeypatch.setattr(runner, "write_result", payloads.append)

    runner.compile_and_run(
        {
            "compile_only": False,
            "run_timeout_seconds": 8,
            "valgrind_timeout_seconds": 20,
            "leak_sanitizer_available": True,
        }
    )

    assert calls[0][1]["timeout"] == 8
    assert payloads[0]["timed_out"] is False


def test_compile_timeout_has_dedicated_runner_result(
    tmp_path: Path, monkeypatch
):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    payloads = []
    monkeypatch.setattr(
        runner,
        "compile_program",
        lambda *_args, **_kwargs: (
            subprocess.CompletedProcess(["clang++"], -1, b"", b""),
            True,
            False,
        ),
    )
    monkeypatch.setattr(runner, "write_result", payloads.append)

    runner.compile_and_run(
        {
            "compile_only": True,
            "compile_timeout_seconds": 30,
        }
    )

    assert payloads == [
        {
            "infrastructure_error": (
                "The isolated runner could not finish compiling the test "
                "program in time."
            ),
            "compile_timed_out": True,
        }
    ]


@pytest.mark.parametrize(
    ("memory_checks", "leaks", "valgrind", "installed", "expected_compiles"),
    [
        (True, True, True, True, [True]),
        (True, False, True, True, [True, False]),
        (True, False, False, True, [True]),
        (True, False, True, False, [True]),
        (False, False, True, True, [False]),
    ],
)
def test_compile_only_builds_valgrind_only_for_leak_fallback(
    tmp_path, monkeypatch, memory_checks, leaks, valgrind, installed,
    expected_compiles,
):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    monkeypatch.setattr(
        runner.shutil, "which", lambda _: "/usr/bin/valgrind" if installed else None
    )
    calls = []
    payloads = []

    def compile_program(output, *, sanitized, timeout):
        calls.append((output, sanitized, timeout))
        return subprocess.CompletedProcess([], 0, b"", b""), False, False

    monkeypatch.setattr(runner, "compile_program", compile_program)
    monkeypatch.setattr(runner, "write_result", payloads.append)
    runner.compile_and_run({
        "compile_only": True,
        "run_memory_checks": memory_checks,
        "leak_sanitizer_available": leaks,
        "valgrind_available": valgrind,
        "compile_timeout_seconds": 10,
    })

    assert [call[1] for call in calls] == expected_compiles
    assert all(call[2] == 10 for call in calls)
    assert [call[0] for call in calls] == ["program", "program-valgrind"][:len(calls)]
    assert payloads == [{"memory_tool": "sanitizer" if memory_checks else "none"}]
    # Even a compile using its whole allowed 10s fits the existing 15s
    # provider budget on the deployed LeakSanitizer path (formerly two).
    if memory_checks and leaks:
        assert sum(call[2] for call in calls) < 15


@pytest.mark.parametrize("leaks", [False, True])
@pytest.mark.parametrize("sanitizer_failed", [False, True])
def test_runtime_preserves_valgrind_fallback_and_individual_limits(
    tmp_path, monkeypatch, leaks, sanitizer_failed,
):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/valgrind")
    for name in ("program", "program-valgrind"):
        (tmp_path / name).write_bytes(b"compiled")
    calls = []
    payloads = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        stderr = (
            b"definitely lost: 20 bytes in 1 blocks"
            if command[0] == "valgrind"
            else b"AddressSanitizer: heap-buffer-overflow" if sanitizer_failed else b""
        )
        return subprocess.CompletedProcess(command, 0, b"", stderr), False, False

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "write_result", payloads.append)
    runner.compile_and_run({
        "run_memory_checks": True,
        "leak_sanitizer_available": leaks,
        "valgrind_available": True,
        "run_timeout_seconds": 2,
        "valgrind_timeout_seconds": 20,
    })

    fallback = not leaks and not sanitizer_failed
    assert [kwargs["timeout"] for _, kwargs in calls] == ([2, 20] if fallback else [2])
    assert payloads[0]["memory_tool"] == (
        "sanitizer_and_valgrind" if fallback else "sanitizer"
    )
    if fallback:
        assert payloads[0]["leak_kind"] == "definite"
        assert payloads[0]["leaked_bytes"] == 20


def test_valgrind_fallback_compile_timeout_still_fails_closed(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda _: "/usr/bin/valgrind")
    calls = []
    payloads = []

    def compile_program(output, *, sanitized, timeout):
        calls.append(timeout)
        timed_out = output == "program-valgrind"
        return subprocess.CompletedProcess([], -1 if timed_out else 0, b"", b""), timed_out, False

    monkeypatch.setattr(runner, "compile_program", compile_program)
    monkeypatch.setattr(runner, "write_result", payloads.append)
    runner.compile_and_run({
        "compile_only": True,
        "run_memory_checks": True,
        "leak_sanitizer_available": False,
        "valgrind_available": True,
        "compile_timeout_seconds": 10,
    })
    assert calls == [10, 10]
    assert payloads[0]["compile_timed_out"] is True
    assert payloads[0]["infrastructure_error"]


def test_sanitized_compile_and_link_share_one_deadline(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    clock = iter([100, 106])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    calls = []

    def fake_run(command, *, timeout):
        calls.append((command, timeout))
        (tmp_path / "program.o").write_bytes(b"object")
        return subprocess.CompletedProcess(command, 0, b"", b""), False, False

    monkeypatch.setattr(runner, "run", fake_run)
    result = runner.compile_program("program", timeout=10)
    assert result[1:] == (False, False)
    assert [timeout for _, timeout in calls] == [10, 4]
    assert calls[0][0] == [
        "clang++", *runner.SANITIZER_FLAGS, "-c", "main.cpp", "-o", "program.o",
    ]
    assert calls[1][0] == [
        "clang++", *runner.SANITIZER_FLAGS, "program.o", "-o", "program",
    ]
    assert "-fsanitize=address,undefined" in runner.SANITIZER_FLAGS
    assert "-O0" in runner.SANITIZER_FLAGS
    assert "-gline-tables-only" in runner.SANITIZER_FLAGS
    assert "-g" not in runner.SANITIZER_FLAGS
    assert not (tmp_path / "program.o").exists()


@pytest.mark.parametrize(
    ("returncode", "timed_out", "limited"),
    [(1, False, False), (-9, True, False), (-9, False, True)],
)
def test_failed_sanitized_compile_never_links(
    tmp_path, monkeypatch, returncode, timed_out, limited,
):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    calls = []

    def fake_run(command, *, timeout):
        calls.append(command)
        (tmp_path / "program.o").write_bytes(b"partial object")
        return subprocess.CompletedProcess(command, returncode, b"", b"diagnostic"), timed_out, limited

    monkeypatch.setattr(runner, "run", fake_run)
    completed, actual_timeout, actual_limit = runner.compile_program("program", timeout=10)
    assert len(calls) == 1
    assert completed.stderr == b"diagnostic"
    assert (actual_timeout, actual_limit) == (timed_out, limited)
    assert not (tmp_path / "program.o").exists()


def test_exhausted_compile_budget_never_starts_linker(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    clock = iter([100, 110])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    calls = []

    def fake_run(command, *, timeout):
        calls.append(timeout)
        return subprocess.CompletedProcess(command, 0, b"", b""), False, False

    monkeypatch.setattr(runner, "run", fake_run)
    _, timed_out, _ = runner.compile_program("program", timeout=10)
    assert timed_out is True
    assert calls == [10]


def test_linker_timeout_reports_compile_timeout(tmp_path, monkeypatch):
    runner = load_runner()
    monkeypatch.setattr(runner, "WORK", tmp_path)
    clock = iter([100, 106])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(clock))
    calls = []
    payloads = []

    def fake_run(command, *, timeout):
        calls.append(timeout)
        timed_out = "-c" not in command
        return subprocess.CompletedProcess(command, -9 if timed_out else 0, b"", b""), timed_out, False

    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(runner, "write_result", payloads.append)
    runner.compile_and_run({
        "compile_only": True,
        "run_memory_checks": True,
        "leak_sanitizer_available": True,
        "compile_timeout_seconds": 10,
    })
    assert calls == [10, 4]
    assert payloads[0]["compile_timed_out"] is True
    assert payloads[0]["infrastructure_error"]


def test_plain_compile_remains_one_unchanged_command(monkeypatch):
    runner = load_runner()
    calls = []

    def fake_run(command, *, timeout):
        calls.append((command, timeout))
        return subprocess.CompletedProcess(command, 0, b"", b""), False, False

    monkeypatch.setattr(runner, "run", fake_run)
    runner.compile_program("program", sanitized=False, timeout=10)
    assert calls == [(["g++", "-std=c++17", "-O0", "-g", "main.cpp", "-o", "program"], 10)]
