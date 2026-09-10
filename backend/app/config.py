import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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
    cpp_execution_provider: str = "docker"
    cpp_runner_image: str = "inktocode-cpp-runner"
    cpp_runner_memory: str = "256m"
    cpp_runner_cpus: str = "1.0"
    cpp_runner_pids: int = 32
    cpp_runner_user: str = "runner"
    cpp_docker_compile_timeout_seconds: float = 30
    cpp_docker_run_timeout_seconds: float = 8
    cpp_docker_valgrind_timeout_seconds: float = 20
    max_source_chars: int = 100_000
    max_test_value_chars: int = 2_000
    max_request_bytes: int = 12_582_912
    rate_limit_enabled: bool = True
    rate_limit_ai_per_window: int = 10
    rate_limit_ai_window_seconds: int = 300
    rate_limit_compile_per_minute: int = 60
    rate_limit_global_ai_per_minute: int = 30
    trusted_proxy_count: int = 0
    cpp_max_concurrent_jobs: int = 2
    ai_max_concurrent_calls: int = 2
    cpp_acquire_timeout_seconds: float = 10
    ai_acquire_timeout_seconds: float = 20
    allowed_frontend_origins: tuple[str, ...] = ()
    hsts_enabled: bool = False

    @property
    def cors_origins(self) -> tuple[str, ...]:
        return self.allowed_frontend_origins or (self.frontend_origin,)


def _enabled(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"true", "1", "yes"}


def validate_web_settings(settings: Settings) -> tuple[str, ...]:
    normalized: list[str] = []
    for configured_origin in settings.cors_origins:
        origin = configured_origin.strip().rstrip("/")
        parsed = urlsplit(origin)
        if (
            not origin
            or origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in origin
            )
        ):
            raise ValueError(
                "Frontend origins must be explicit HTTP(S) origins without "
                "paths, wildcards, or credentials."
            )
        if origin not in normalized:
            normalized.append(origin)
    if not normalized:
        raise ValueError("At least one frontend origin must be configured.")
    return tuple(normalized)


def get_settings() -> Settings:
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    configured_origins = os.getenv("FRONTEND_ORIGINS")
    legacy_origin = os.getenv("FRONTEND_ORIGIN")
    if environment == "production" and not (configured_origins or legacy_origin):
        raise ValueError(
            "Production requires FRONTEND_ORIGINS or FRONTEND_ORIGIN."
        )
    raw_origins = configured_origins or legacy_origin or "http://localhost:3000"
    origins = tuple(item.strip() for item in raw_origins.split(",") if item.strip())
    settings = Settings(
        frontend_origin=origins[0] if origins else "",
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        transcription_model=os.getenv("GEMINI_TRANSCRIPTION_MODEL")
        or "gemini-3.5-flash-lite",
        environment=environment,
        test_generation_model=(
            os.getenv("GEMINI_TEST_GENERATION_MODEL")
            or os.getenv("GEMINI_TRANSCRIPTION_MODEL")
            or "gemini-3.5-flash-lite"
        ),
        max_question_chars=int(os.getenv("MAX_QUESTION_CHARS", "8000")),
        cpp_execution_provider=os.getenv(
            "CPP_EXECUTION_PROVIDER", "docker"
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
        max_source_chars=int(os.getenv("MAX_SOURCE_CHARS", "100000")),
        max_test_value_chars=int(os.getenv("MAX_TEST_VALUE_CHARS", "2000")),
        max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", "12582912")),
        rate_limit_enabled=os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower()
        not in {"false", "0", "no"},
        rate_limit_ai_per_window=int(
            os.getenv("RATE_LIMIT_AI_PER_WINDOW", "10")
        ),
        rate_limit_ai_window_seconds=int(
            os.getenv("RATE_LIMIT_AI_WINDOW_SECONDS", "300")
        ),
        rate_limit_compile_per_minute=int(
            os.getenv("RATE_LIMIT_COMPILE_PER_MINUTE", "60")
        ),
        rate_limit_global_ai_per_minute=int(
            os.getenv("RATE_LIMIT_GLOBAL_AI_PER_MINUTE", "30")
        ),
        trusted_proxy_count=int(os.getenv("TRUSTED_PROXY_COUNT", "0")),
        cpp_max_concurrent_jobs=int(
            os.getenv("CPP_MAX_CONCURRENT_JOBS", "2")
        ),
        ai_max_concurrent_calls=int(
            os.getenv("AI_MAX_CONCURRENT_CALLS", "2")
        ),
        cpp_acquire_timeout_seconds=float(
            os.getenv("CPP_ACQUIRE_TIMEOUT_SECONDS", "10")
        ),
        ai_acquire_timeout_seconds=float(
            os.getenv("AI_ACQUIRE_TIMEOUT_SECONDS", "20")
        ),
        allowed_frontend_origins=origins,
        hsts_enabled=_enabled(os.getenv("ENABLE_HSTS")),
    )
    validate_web_settings(settings)
    return settings
