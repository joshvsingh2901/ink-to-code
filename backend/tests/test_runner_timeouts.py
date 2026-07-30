import importlib.util
import subprocess
from pathlib import Path


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
        return subprocess.CompletedProcess(command, 0, b"", b""), False

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
