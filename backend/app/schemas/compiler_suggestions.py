from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.compilation import CompilerDiagnostic


class CompilerSuggestionRequest(BaseModel):
    code: str = Field(max_length=1_000_000)
    language: str
    diagnostics: list[CompilerDiagnostic] = Field(min_length=1, max_length=100)


class FixSuggestion(BaseModel):
    diagnostic_index: int = Field(ge=0)
    source: Literal["compiler"]
    start_line: int = Field(ge=1)
    start_column: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_column: int = Field(ge=1)
    original_text: str = Field(max_length=1_000)
    replacement_text: str = Field(max_length=1_000)
    explanation: str = Field(min_length=1, max_length=300)


class CompilerSuggestionResponse(BaseModel):
    suggestions: list[FixSuggestion]
