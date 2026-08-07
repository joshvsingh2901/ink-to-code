import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_FILE)


@dataclass(frozen=True)
class Settings:
    frontend_origin: str
    gemini_api_key: str | None
    transcription_model: str
    environment: str
    test_generation_model: str = "gemini-3.5-flash-lite"
    max_question_chars: int = 8000
    cpp_execution_provider: str = "auto"
    cpp_runner_image: str = "inktocode-cpp-runner"
    cpp_runner_memory: str = "256m"
    cpp_runner_cpus: str = "1.0"
    cpp_runner_pids: int = 32
    cpp_runner_user: str = "runner"
    cpp_docker_compile_timeout_seconds: float = 30
    cpp_docker_run_timeout_seconds: float = 8
    cpp_docker_valgrind_timeout_seconds: float = 20


def get_settings() -> Settings:
    return Settings(
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        transcription_model=os.getenv("GEMINI_TRANSCRIPTION_MODEL")
        or "gemini-3.5-flash-lite",
        environment=os.getenv("ENVIRONMENT", "development"),
        test_generation_model=(
            os.getenv("GEMINI_TEST_GENERATION_MODEL")
            or os.getenv("GEMINI_TRANSCRIPTION_MODEL")
            or "gemini-3.5-flash-lite"
        ),
        max_question_chars=int(os.getenv("MAX_QUESTION_CHARS", "8000")),
        cpp_execution_provider=os.getenv(
            "CPP_EXECUTION_PROVIDER", "auto"
        ),
        cpp_runner_image=os.getenv(
            "CPP_RUNNER_IMAGE", "inktocode-cpp-runner"
        ),
        cpp_runner_memory=os.getenv("CPP_RUNNER_MEMORY", "256m"),
        cpp_runner_cpus=os.getenv("CPP_RUNNER_CPUS", "1.0"),
        cpp_runner_pids=int(os.getenv("CPP_RUNNER_PIDS", "32")),
        cpp_runner_user=os.getenv("CPP_RUNNER_USER", "runner"),
        cpp_docker_compile_timeout_seconds=float(
            os.getenv("CPP_DOCKER_COMPILE_TIMEOUT_SECONDS", "30")
        ),
        cpp_docker_run_timeout_seconds=float(
            os.getenv("CPP_DOCKER_RUN_TIMEOUT_SECONDS", "8")
        ),
        cpp_docker_valgrind_timeout_seconds=float(
            os.getenv("CPP_DOCKER_VALGRIND_TIMEOUT_SECONDS", "20")
        ),
    )
