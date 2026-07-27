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


def get_settings() -> Settings:
    return Settings(
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        transcription_model=os.getenv("GEMINI_TRANSCRIPTION_MODEL")
        or "gemini-3.5-flash-lite",
        environment=os.getenv("ENVIRONMENT", "development"),
    )
