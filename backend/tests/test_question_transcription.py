"""Tests for the /api/transcribe-question endpoint and transcribe_question_pages service."""
import asyncio
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.schemas.transcription import PageMetadata, QuestionExtraction
from app.services.transcription import (
    QUESTION_EXTRACTION_PROMPT,
    TranscriptionServiceError,
    transcribe_question_pages,
)
from app.services.uploads import MAX_PAGE_SIZE, PNG_SIGNATURE, NormalizedPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(key: str | None = "test-key") -> Settings:
    return Settings("http://localhost:3000", key, "test-model", "test")


def _question_page(order: int) -> NormalizedPage:
    content = PNG_SIGNATURE + f"question-page-{order}".encode()
    return NormalizedPage(
        metadata=PageMetadata(
            file_id=f"question-{order}.png",
            order=order,
            category="question",
            source_type="image",
            original_filename=f"question-{order}.png",
        ),
        content=content,
        content_type="image/png",
        declared_content_type="image/png",
        signature_type="image/png",
    )


class _FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, *outcomes):
        self.models = _FakeModels(*outcomes)


def _ok_response(text: str) -> object:
    return SimpleNamespace(
        parsed=QuestionExtraction(question_text=text),
        text=f'{{"question_text": "{text}"}}',
        prompt_feedback=None,
        candidates=[],
    )


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


def test_question_pages_transcribe_with_single_gemini_call():
    pages = [_question_page(1), _question_page(2)]
    client = _FakeClient(_ok_response("Write a function that adds two integers."))

    result = transcribe_question_pages(pages, _settings(), client=client)

    assert result == "Write a function that adds two integers."
    # Exactly ONE Gemini call (not two like the transcription pass/verify flow).
    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    # The call uses test_generation_model, not transcription_model.
    assert call["model"] == _settings().test_generation_model
    # The extraction prompt is included in the contents.
    all_text = " ".join(
        p.text
        for content in call["contents"]
        for p in content.parts
        if p.text is not None
    )
    assert "Extract the assignment question text" in all_text


def test_question_text_response_shape():
    """transcribe_question_pages returns a plain string (question text)."""
    pages = [_question_page(1)]
    expected = "Implement binary search on a sorted array."
    client = _FakeClient(_ok_response(expected))

    result = transcribe_question_pages(pages, _settings(), client=client)

    assert isinstance(result, str)
    assert result == expected


def test_transcribe_question_error_classification_reuses_existing_codes():
    """Errors go through the same _classify_api_error as transcription."""
    pages = [_question_page(1)]

    class _FakeRateLimit(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "rate limit"
            self.details = []

    client = _FakeClient(_FakeRateLimit())
    with pytest.raises(TranscriptionServiceError) as exc_info:
        transcribe_question_pages(pages, _settings(), client=client)

    # Same code that transcription.py produces for rate limits.
    assert exc_info.value.code == "gemini_rate_limited"
    assert exc_info.value.status_code == 429


def test_oversized_page_rejected_by_existing_upload_rules():
    """validate_and_normalize_pages raises UploadValidationError for pages > 10 MiB."""
    from app.services.uploads import UploadValidationError, validate_and_normalize_pages

    oversized = PNG_SIGNATURE + b"x" * (MAX_PAGE_SIZE + 1)

    class _FakeUpload:
        filename = "big.png"
        content_type = "image/png"

        async def read(self, n: int = -1) -> bytes:
            return oversized[:n] if n >= 0 else oversized

    raw_metadata = (
        '[{"file_id": "big.png", "order": 1, "category": "question",'
        ' "source_type": "image", "original_filename": "big.png"}]'
    )

    async def _run():
        with pytest.raises(UploadValidationError, match="exceeds"):
            await validate_and_normalize_pages(
                [_FakeUpload()],
                raw_metadata,
                category="question",
                minimum=1,
                maximum=5,
            )

    asyncio.run(_run())
