import tempfile
from pathlib import Path

from app.schemas.compilation import CompileResponse
from app.services.compiler_diagnostics import parse_compiler_diagnostics
from app.services.execution_providers import (
    ExecutionProvider,
    select_execution_provider,
)

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
    execution_provider: ExecutionProvider | None = None,
) -> CompileResponse:
    if compiler != COMPILER_EXECUTABLE:
        raise CompilerServiceError(
            "compiler_unavailable",
            "Custom compiler executables are not permitted.",
            503,
        )
    provider: ExecutionProvider | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="inktocode-compile-") as directory:
            temporary_path = Path(directory)
            source_path = temporary_path / "main.cpp"
            source_path.write_bytes(code.encode("utf-8"))
            provider = execution_provider or select_execution_provider()
            completed = provider.compile_source(
                temporary_path,
                timeout_seconds=timeout_seconds,
            )
            if completed.compile_timed_out:
                raise CompilerServiceError(
                    "compiler_timeout",
                    "Compilation exceeded the 10-second time limit.",
                    504,
                )
            if completed.infrastructure_error or completed.exit_code is None:
                raise CompilerServiceError(
                    "runner_unavailable",
                    "The isolated C++ runner is unavailable.",
                    503,
                )
            stdout = _limit_output(completed.stdout)
            stderr = _limit_output(completed.stderr)
            success = completed.exit_code == 0
            return CompileResponse(
                success=success,
                stdout=stdout,
                stderr=stderr,
                exit_code=completed.exit_code,
                diagnostics=[] if success else parse_compiler_diagnostics(stderr),
            )
    except CompilerServiceError:
        raise
    except (OSError, ValueError) as error:
        raise CompilerServiceError(
            "runner_unavailable",
            "The isolated C++ runner is unavailable.",
            503,
        ) from error
    finally:
        if provider is not None:
            provider.close()
