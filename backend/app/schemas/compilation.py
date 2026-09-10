from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings

# Evaluated once at import time from MAX_SOURCE_CHARS (Field constraints are
# static). A 1 MB source made analyze_test_mode's quadratic cost reach ~24s
# on a single request with no compiler/Gemini call involved.
_MAX_SOURCE_CHARS = get_settings().max_source_chars


class CompileRequest(BaseModel):
    code: str = Field(max_length=_MAX_SOURCE_CHARS)
    language: str


class CompilerDiagnostic(BaseModel):
    line: int = Field(ge=1)
    column: int = Field(ge=1)
    severity: Literal["error", "warning", "note"]
    message: str
    explanation: str | None = None


class CompileResponse(BaseModel):
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    diagnostics: list[CompilerDiagnostic] = Field(default_factory=list)
