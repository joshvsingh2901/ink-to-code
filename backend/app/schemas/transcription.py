from typing import Literal

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator


PageCategory = Literal["handwritten_code", "question"]
SourceType = Literal["image", "pdf"]


class PageMetadata(BaseModel):
    file_id: str = Field(min_length=1, max_length=200)
    order: StrictInt = Field(ge=1)
    category: PageCategory
    source_type: SourceType
    original_filename: str = Field(min_length=1, max_length=500)
    original_pdf_page_number: StrictInt | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_pdf_page_number(self) -> "PageMetadata":
        if self.source_type == "pdf" and self.original_pdf_page_number is None:
            raise ValueError("PDF-derived pages require an original PDF page number")
        if self.source_type == "image" and self.original_pdf_page_number is not None:
            raise ValueError("Image pages cannot include an original PDF page number")
        return self


class UncertainRegion(BaseModel):
    id: str = Field(min_length=1)
    page: int = Field(ge=1)
    line: int | None = Field(default=None, ge=1)
    detected: str
    alternatives: list[str]
    confidence: float = Field(ge=0, le=1)
    reason: str


class ModelTranscription(BaseModel):
    code: str
    overall_confidence: float = Field(ge=0, le=1)
    uncertain_regions: list[UncertainRegion] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def code_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Transcription code cannot be empty")
        return value


class TranscriptionResponse(ModelTranscription):
    page_count: int = Field(ge=1, le=5)
    model: str = Field(min_length=1)


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
