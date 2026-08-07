import subprocess
import tempfile
from pathlib import Path

from app.schemas.compilation import CompileResponse
from app.services.compiler_diagnostics import parse_compiler_diagnostics

COMPILER_EXECUTABLE = "g++"
COMPILE_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARACTERS = 64 * 1024


class CompilerServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _limit_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARACTERS:
        return output
    return output[:MAX_OUTPUT_CHARACTERS] + "\n[Compiler output truncated.]"


def compile_cpp(
    code: str,
    *,
    compiler: str = COMPILER_EXECUTABLE,
    timeout_seconds: int = COMPILE_TIMEOUT_SECONDS,
) -> CompileResponse:
    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-compile-") as directory:
            temporary_path = Path(directory)
            source_path = temporary_path / "main.cpp"
            source_path.write_bytes(code.encode("utf-8"))

            command = [
                compiler,
                "-std=c++17",
                # Disable transitive includes in libc++ (Apple Clang / macOS):
                # without this, <vector> silently provides std::sort, hiding a
                # missing #include <algorithm>.  Harmless no-op on libstdc++.
                "-D_LIBCPP_REMOVE_TRANSITIVE_INCLUDES",
                "-fsyntax-only",
                "main.cpp",
            ]
            completed = subprocess.run(
                command,
                cwd=temporary_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )

            stdout = _limit_output(completed.stdout)
            stderr = _limit_output(completed.stderr)
            success = completed.returncode == 0
            return CompileResponse(
                success=success,
                stdout=stdout,
                stderr=stderr,
                exit_code=completed.returncode,
                diagnostics=[] if success else parse_compiler_diagnostics(stderr),
            )
    except FileNotFoundError as error:
        raise CompilerServiceError(
            "compiler_unavailable",
            "The C++ compiler is unavailable on the backend.",
            503,
        ) from error
    except subprocess.TimeoutExpired as error:
        raise CompilerServiceError(
            "compiler_timeout",
            "Compilation exceeded the 10-second time limit.",
            504,
        ) from error
    except (OSError, subprocess.SubprocessError) as error:
        raise CompilerServiceError(
            "compiler_failed",
            "The backend could not start the C++ compiler.",
            500,
        ) from error
