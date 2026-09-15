import importlib.util
import json
import os
from pathlib import Path


READ_RESULT_PATH = (
    Path(__file__).resolve().parents[2] / "runner" / "read_result.py"
)


def load_read_result():
    spec = importlib.util.spec_from_file_location(
        "inktocode_read_result_for_tests", READ_RESULT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regular_file_is_read_and_returned_verbatim(tmp_path: Path):
    read_result = load_read_result()
    path = tmp_path / "runner-result.json"
    payload = {"stdout": "hi", "exit_code": 0}
    path.write_text(json.dumps(payload), encoding="utf-8")

    output = read_result.read_result(str(path))

    assert json.loads(output) == payload


def test_symlink_is_rejected(tmp_path: Path):
    read_result = load_read_result()
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    path = tmp_path / "runner-result.json"
    path.symlink_to(target)

    output = read_result.read_result(str(path))

    assert output == "{}"


def test_missing_file_returns_empty_object(tmp_path: Path):
    read_result = load_read_result()
    path = tmp_path / "does-not-exist.json"

    output = read_result.read_result(str(path))

    assert output == "{}"


def test_oversized_file_is_rejected(tmp_path: Path):
    read_result = load_read_result()
    path = tmp_path / "runner-result.json"
    # One byte over the 64 KiB cap.
    path.write_text("x" * (64 * 1024 + 1), encoding="utf-8")

    output = read_result.read_result(str(path), limit=64 * 1024)

    assert output == "{}"


def test_file_at_exactly_the_limit_is_accepted(tmp_path: Path):
    read_result = load_read_result()
    path = tmp_path / "runner-result.json"
    payload = json.dumps({"stdout": "x" * 100})
    path.write_text(payload, encoding="utf-8")

    output = read_result.read_result(str(path), limit=len(payload) + 10)

    assert json.loads(output) == json.loads(payload)


def test_non_regular_file_such_as_a_fifo_is_rejected(tmp_path: Path):
    read_result = load_read_result()
    path = tmp_path / "runner-result.json"
    os.mkfifo(path)

    try:
        output = read_result.read_result(str(path))
    finally:
        path.unlink(missing_ok=True)

    assert output == "{}"


def test_main_prints_the_read_result(tmp_path: Path, monkeypatch, capsys):
    read_result = load_read_result()
    path = tmp_path / "runner-result.json"
    path.write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    monkeypatch.setattr(read_result, "RESULT_PATH", str(path))

    read_result.main()

    captured = capsys.readouterr()
    assert json.loads(captured.out.strip()) == {"exit_code": 0}
