import json
import os
import re
import signal
import shutil
import subprocess
import tempfile
import time
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


def run(command, *, timeout, stdin="", environment=None, output_limit=65536):
    """Run one fixed command with bounded output and kill its process group."""
    with (
        tempfile.TemporaryFile(dir=WORK) as stdin_file,
        tempfile.TemporaryFile(dir=WORK) as stdout_file,
        tempfile.TemporaryFile(dir=WORK) as stderr_file,
    ):
        stdin_file.write(stdin.encode())
        stdin_file.seek(0)
        process = subprocess.Popen(
            command,
            cwd=WORK,
            stdin=stdin_file,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            env=environment,
            start_new_session=True,
        )
        deadline = time.monotonic() + timeout
        timed_out = False
        output_limited = False
        while process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            if (
                os.fstat(stdout_file.fileno()).st_size > output_limit
                or os.fstat(stderr_file.fileno()).st_size > output_limit
            ):
                output_limited = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                break
            time.sleep(0.01)
        returncode = process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        return (
            subprocess.CompletedProcess(
                command,
                returncode,
                stdout_file.read(output_limit + 1),
                stderr_file.read(output_limit + 1),
            ),
            timed_out,
            output_limited,
        )


def compile_program(output, sanitized=True, timeout=10, source="main.cpp"):
    command = ["clang++" if sanitized else "g++"]
    command += SANITIZER_FLAGS if sanitized else ["-std=c++17", "-O0", "-g"]
    command += [source, "-o", output]
    return run(command, timeout=timeout)


def compile_source(request):
    limit = min(max(int(request.get("output_limit_bytes", 65536)), 1024), 65536)
    timeout = min(
        max(float(request.get("compile_timeout_seconds", 30)), 1), 120
    )
    completed, timed_out, output_limited = run(
        [
            "g++",
            "-std=c++17",
            "-D_LIBCPP_REMOVE_TRANSITIVE_INCLUDES",
            "-fsyntax-only",
            "main.cpp",
        ],
        timeout=timeout,
        output_limit=limit,
    )
    if timed_out:
        write_result(
            {
                "infrastructure_error": (
                    "The isolated runner could not finish compiling in time."
                ),
                "compile_timed_out": True,
            }
        )
        return
    stdout, stdout_limited = bounded(completed.stdout, limit)
    stderr, stderr_limited = bounded(completed.stderr, limit)
    write_result(
        {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": completed.returncode,
            "output_limited": (
                output_limited or stdout_limited or stderr_limited
            ),
        }
    )


def sidecar_payload(limit):
    def text(name):
        path = WORK / name
        if not path.exists() or path.stat().st_size > limit:
            return None
        return path.read_text(encoding="utf-8", errors="replace")

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
    payload = {
        "function_stdout": text("function-stdout.txt") or "",
        "result_metadata": text("function-result.json"),
        "constructor_metadata": text("object-constructor-result.json"),
        "step_stdout": step_stdout,
        "step_metadata": step_metadata,
        "progress_index": progress_index,
    }
    output_limited = any(
        path.is_file() and path.stat().st_size > limit
        for path in WORK.glob("*.txt")
    ) or any(
        path.is_file() and path.stat().st_size > limit
        for path in WORK.glob("*.json")
        if path != REQUEST
    )
    return payload, output_limited


def clear_sidecars():
    names = [
        "function-stdout.txt",
        "function-result.json",
        "function-result.json.tmp",
        "object-progress.txt",
        "object-constructor-stdout.txt",
        "object-constructor-result.json",
    ]
    names.extend(f"object-step-{index}-stdout.txt" for index in range(20))
    names.extend(f"object-step-{index}-result.json" for index in range(20))
    for name in names:
        (WORK / name).unlink(missing_ok=True)


def completed_exception_result():
    path = WORK / "function-result.json"
    if not path.is_file() or path.stat().st_size > 65536:
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("process_completed") is True
        and payload.get("outcome") in {"threw_standard", "threw_non_standard"}
    )


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

    # Write the probe program to its own file rather than overwriting
    # /work/main.cpp. The host seeds main.cpp and runner-request.json mode
    # 0644 owned by the API's user; on native Linux bind mounts that makes
    # them read-only to this container's UID 10001, so an in-place rewrite
    # fails with EACCES. Creating a new entry only needs write permission on
    # the work directory, which the host grants. Host-seeded inputs stay
    # immutable to the sandbox in every mode.
    probe_source = "probe.cpp"
    (WORK / probe_source).write_text(
        "int main(){ volatile int* p = new int(7); (void)p; return 0; }",
        encoding="utf-8",
    )
    compiled, _, _ = compile_program(
        "probe", sanitized=True, source=probe_source
    )
    sanitizer_available = compiled.returncode == 0
    leak_available = False
    if sanitizer_available:
        leaked, _, _ = run(
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
        plain, _, _ = compile_program(
            "probe-plain", sanitized=False, source=probe_source
        )
        if plain.returncode == 0:
            checked, _, _ = run(
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
    memory_checks = bool(request.get("run_memory_checks"))
    if request.get("compile_only"):
        compiled, compilation_timed_out, compilation_output_limited = compile_program(
            "program", sanitized=memory_checks, timeout=compile_timeout
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
            write_result(
                {
                    "compile_error": error,
                    "output_limited": limited or compilation_output_limited,
                }
            )
            return
        if (
            memory_checks
            and request.get("valgrind_available")
            and shutil.which("valgrind")
        ):
            plain, plain_timed_out, _ = compile_program(
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
        write_result(
            {"memory_tool": "sanitizer" if memory_checks else "none"}
        )
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

    clear_sidecars()
    executed, timed_out, process_output_limited = run(
        [str(WORK / "program")],
        timeout=run_timeout,
        stdin=str(request.get("stdin", "")),
        environment=(child_environment(leaks=True) if memory_checks else None),
        output_limit=limit,
    )
    if timed_out and not memory_checks and completed_exception_result():
        timed_out = False
        executed = subprocess.CompletedProcess(
            executed.args,
            0,
            executed.stdout,
            executed.stderr,
        )
    stdout, stdout_limited = bounded(executed.stdout, limit)
    stderr, stderr_limited = bounded(executed.stderr, limit)
    memory_tool = "sanitizer" if memory_checks else "none"
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
        memory_checks
        and not sanitizer_failed
        and not leak_supported
        and request.get("valgrind_available")
        and shutil.which("valgrind")
    ):
        if (WORK / "program-valgrind").is_file():
            checked, valgrind_timed_out, valgrind_output_limited = run(
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
            stderr_limited = stderr_limited or valgrind_output_limited
            timed_out = timed_out or valgrind_timed_out

    sidecars, sidecar_limited = sidecar_payload(limit)
    payload = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": None if timed_out else executed.returncode,
        "timed_out": timed_out,
        "output_limited": (
            process_output_limited
            or stdout_limited
            or stderr_limited
            or sidecar_limited
        ),
        "memory_tool": memory_tool,
        "valgrind_diagnostics": valgrind_diagnostics,
        "leak_kind": leak_kind,
        "leaked_bytes": leaked_bytes,
        "leaked_allocations": leaked_allocations,
        **sidecars,
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
    elif mode == "compile_source":
        compile_source(request)
    elif mode == "compile_and_run":
        compile_and_run(request)
    else:
        write_result({"infrastructure_error": "Unsupported runner mode."})


if __name__ == "__main__":
    main()
