from typing import Literal

from pydantic import BaseModel, Field


class CompileRequest(BaseModel):
    code: str = Field(max_length=1_000_000)
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
