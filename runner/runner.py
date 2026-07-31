import json
import os
import re
import shutil
import subprocess
from pathlib import Path


WORK = Path("/work")
REQUEST = WORK / "runner-request.json"
RESULT = WORK / "runner-result.json"
SANITIZER_FLAGS = [
    "-std=c++17",
    "-O0",
    "-g",
    "-fno-omit-frame-pointer",
    "-fsanitize=address,undefined",
]
ASAN_ENV = "detect_leaks=1:halt_on_error=1:abort_on_error=1"
UBSAN_ENV = "halt_on_error=1:print_stacktrace=1"
VALGRIND_FLAGS = [
    "--tool=memcheck",
    "--leak-check=full",
    "--show-leak-kinds=definite,indirect,possible",
    "--errors-for-leak-kinds=definite,indirect,possible",
    "--error-exitcode=97",
    "--track-origins=yes",
]


def write_result(payload):
    temporary = RESULT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(RESULT)


def bounded(value, limit):
    data = value if isinstance(value, bytes) else value.encode()
    limited = len(data) > limit
    text = data[:limit].decode("utf-8", errors="replace")
    if limited:
        text += "\n[Output limited to 64 KiB.]"
    return text, limited


def child_environment(leaks=True):
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = (
        ASAN_ENV
        if leaks
        else "detect_leaks=0:halt_on_error=1:abort_on_error=1"
    )
    environment["UBSAN_OPTIONS"] = UBSAN_ENV
    environment["TMPDIR"] = "/work"
    return environment


def run(command, *, timeout, stdin="", environment=None):
    try:
        return subprocess.run(
            command,
            cwd=WORK,
            input=stdin.encode(),
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=environment,
        ), False
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command,
            -1,
            error.stdout or b"",
            error.stderr or b"",
        ), True


def compile_program(output, sanitized=True, timeout=10):
    command = ["clang++"]
    command += SANITIZER_FLAGS if sanitized else ["-std=c++17", "-O0", "-g"]
    command += ["main.cpp", "-o", output]
    result, timed_out = run(command, timeout=timeout)
    return result, timed_out


def sidecar_payload():
    def text(name):
        path = WORK / name
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else None

    step_stdout = []
    step_metadata = []
    for index in range(20):
        step_stdout.append(text(f"object-step-{index}-stdout.txt") or "")
        step_metadata.append(text(f"object-step-{index}-result.json"))
    progress = text("object-progress.txt")
    try:
        progress_index = int(progress.strip()) if progress is not None else None
    except ValueError:
        progress_index = None
    return {
        "function_stdout": text("function-stdout.txt") or "",
        "result_metadata": text("function-result.json"),
        "constructor_metadata": text("object-constructor-result.json"),
        "step_stdout": step_stdout,
        "step_metadata": step_metadata,
        "progress_index": progress_index,
    }


def classify_valgrind(stderr):
    lowered = stderr.lower()
    patterns = {
        "definite": r"definitely lost:\s*([\d,]+) bytes in ([\d,]+) blocks",
        "indirect": r"indirectly lost:\s*([\d,]+) bytes in ([\d,]+) blocks",
        "possible": r"possibly lost:\s*([\d,]+) bytes in ([\d,]+) blocks",
    }
    for kind in ("definite", "indirect", "possible"):
        match = re.search(patterns[kind], lowered)
        if match and int(match.group(1).replace(",", "")) > 0:
            return kind, int(match.group(1).replace(",", "")), int(
                match.group(2).replace(",", "")
            )
    if any(
        marker in lowered
        for marker in (
            "invalid read",
            "invalid write",
            "invalid free",
            "mismatched free",
            "uninitialised value",
            "uninitialized value",
        )
    ):
        return "invalid_memory", None, None
    return None, None, None


def capability_probe():
    compiler = shutil.which("clang++") is not None
    valgrind = shutil.which("valgrind") is not None
    if not compiler:
        write_result(
            {
                "compiler_available": False,
                "address_sanitizer_available": False,
                "undefined_behavior_sanitizer_available": False,
                "leak_sanitizer_available": False,
                "valgrind_available": valgrind,
                "unavailable_reason": "No C++ compiler is installed in the runner.",
            }
        )
        return

    (WORK / "main.cpp").write_text(
        "int main(){ volatile int* p = new int(7); (void)p; return 0; }",
        encoding="utf-8",
    )
    compiled, _ = compile_program("probe", sanitized=True)
    sanitizer_available = compiled.returncode == 0
    leak_available = False
    if sanitizer_available:
        leaked, _ = run(
            [str(WORK / "probe")],
            timeout=3,
            environment=child_environment(leaks=True),
        )
        report = (leaked.stderr + leaked.stdout).decode(
            "utf-8", errors="replace"
        ).lower()
        leak_available = (
            "leaksanitizer" in report or "detected memory leaks" in report
        )
    valgrind_available = False
    if valgrind:
        plain, _ = compile_program("probe-plain", sanitized=False)
        if plain.returncode == 0:
            checked, _ = run(
                ["valgrind", *VALGRIND_FLAGS, str(WORK / "probe-plain")],
                timeout=8,
            )
            kind, _, _ = classify_valgrind(
                checked.stderr.decode("utf-8", errors="replace")
            )
            valgrind_available = kind == "definite"
    write_result(
        {
            "compiler_available": compiler,
            "address_sanitizer_available": sanitizer_available,
            "undefined_behavior_sanitizer_available": sanitizer_available,
            "leak_sanitizer_available": leak_available,
            "valgrind_available": valgrind_available,
        }
    )


def compile_and_run(request):
    limit = min(max(int(request.get("output_limit_bytes", 65536)), 1024), 65536)
    compile_timeout = min(
        max(float(request.get("compile_timeout_seconds", 30)), 1), 120
    )
    run_timeout = min(
        max(float(request.get("run_timeout_seconds", 8)), 0.05), 30
    )
    valgrind_timeout = min(
        max(float(request.get("valgrind_timeout_seconds", 20)), 1), 60
    )
    if request.get("compile_only"):
        compiled, compilation_timed_out = compile_program(
            "program", sanitized=True, timeout=compile_timeout
        )
        if compilation_timed_out:
            write_result(
                {
                    "infrastructure_error": (
                        "The isolated runner could not finish compiling the "
                        "test program in time."
                    ),
                    "compile_timed_out": True,
                }
            )
            return
        if compiled.returncode != 0:
            error, limited = bounded(compiled.stderr or compiled.stdout, limit)
            write_result({"compile_error": error, "output_limited": limited})
            return
        if request.get("valgrind_available") and shutil.which("valgrind"):
            plain, plain_timed_out = compile_program(
                "program-valgrind",
                sanitized=False,
                timeout=compile_timeout,
            )
            if plain_timed_out:
                write_result(
                    {
                        "infrastructure_error": (
                            "The isolated runner could not finish compiling "
                            "the test program in time."
                        ),
                        "compile_timed_out": True,
                    }
                )
                return
        write_result({"memory_tool": "sanitizer"})
        return
    if not (WORK / "program").is_file():
        write_result(
            {
                "infrastructure_error": (
                    "The isolated runner could not find the compiled test "
                    "program."
                )
            }
        )
        return

    executed, timed_out = run(
        [str(WORK / "program")],
        timeout=run_timeout,
        stdin=str(request.get("stdin", "")),
        environment=child_environment(leaks=True),
    )
    stdout, stdout_limited = bounded(executed.stdout, limit)
    stderr, stderr_limited = bounded(executed.stderr, limit)
    memory_tool = "sanitizer"
    valgrind_diagnostics = None
    leak_kind = None
    leaked_bytes = None
    leaked_allocations = None

    sanitizer_report = stderr.lower()
    leak_supported = bool(request.get("leak_sanitizer_available"))
    sanitizer_failed = any(
        marker in sanitizer_report
        for marker in ("addresssanitizer", "runtime error:", "leaksanitizer")
    )
    if (
        not sanitizer_failed
        and not leak_supported
        and request.get("valgrind_available")
        and shutil.which("valgrind")
    ):
        if (WORK / "program-valgrind").is_file():
            checked, valgrind_timed_out = run(
                ["valgrind", *VALGRIND_FLAGS, str(WORK / "program-valgrind")],
                timeout=valgrind_timeout,
                stdin=str(request.get("stdin", "")),
            )
            memory_tool = "sanitizer_and_valgrind"
            valgrind_diagnostics, valgrind_limited = bounded(
                checked.stderr, limit
            )
            leak_kind, leaked_bytes, leaked_allocations = classify_valgrind(
                valgrind_diagnostics
            )
            stderr_limited = stderr_limited or valgrind_limited
            timed_out = timed_out or valgrind_timed_out

    payload = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": None if timed_out else executed.returncode,
        "timed_out": timed_out,
        "output_limited": stdout_limited or stderr_limited,
        "memory_tool": memory_tool,
        "valgrind_diagnostics": valgrind_diagnostics,
        "leak_kind": leak_kind,
        "leaked_bytes": leaked_bytes,
        "leaked_allocations": leaked_allocations,
        **sidecar_payload(),
    }
    write_result(payload)


def main():
    try:
        request = json.loads(REQUEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        write_result({"infrastructure_error": "Invalid runner request."})
        return
    mode = request.get("mode")
    if mode == "capability_probe":
        capability_probe()
    elif mode == "compile_and_run_sanitized":
        compile_and_run(request)
    else:
        write_result({"infrastructure_error": "Unsupported runner mode."})


if __name__ == "__main__":
    main()
