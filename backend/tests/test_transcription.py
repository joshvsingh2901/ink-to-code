from types import SimpleNamespace

import pytest
from google.genai import errors, types

from app.config import Settings
from app.schemas.transcription import ModelTranscription, PageMetadata
from app.services.transcription import (
    TRANSCRIPTION_PROMPT,
    VERIFICATION_PROMPT,
    TranscriptionServiceError,
    build_gemini_contents,
    transcribe_pages,
)
from app.services.uploads import JPEG_SIGNATURE, PNG_SIGNATURE, NormalizedPage


def page(
    order: int,
    category: str = "handwritten_code",
    mime_type: str = "image/png",
) -> NormalizedPage:
    content = (
        JPEG_SIGNATURE + f"image-{order}".encode() + b"\xff\xd9"
        if mime_type == "image/jpeg"
        else PNG_SIGNATURE + f"image-{order}".encode()
    )
    return NormalizedPage(
        metadata=PageMetadata(
            file_id=f"{category}-{order}.png",
            order=order,
            category=category,
            source_type="image",
            original_filename=f"page-{order}.png",
        ),
        content=content,
        content_type=mime_type,
        declared_content_type=mime_type,
        signature_type=mime_type,
    )


def settings(key: str | None = "test-key") -> Settings:
    return Settings("http://localhost:3000", key, "test-model", "test")


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, *outcomes):
        self.models = FakeModels(outcomes)


def response(parsed, text="structured-json"):
    return SimpleNamespace(
        parsed=parsed,
        text=text,
        prompt_feedback=None,
        candidates=[],
    )


def test_builds_ordered_code_images_and_separate_question_images():
    contents = build_gemini_contents(
        [page(1), page(2)], [page(1, "question")]
    )
    parts = contents[0].parts
    text_parts = [part.text for part in parts if part.text is not None]
    image_parts = [part.inline_data.data for part in parts if part.inline_data]

    assert text_parts[1:3] == [
        "Handwritten code page 1:",
        "Handwritten code page 2:",
    ]
    assert "not handwritten-code pages" in text_parts[3]
    assert text_parts[4] == "Question context page 1:"
    assert image_parts == [
        PNG_SIGNATURE + b"image-1",
        PNG_SIGNATURE + b"image-2",
        PNG_SIGNATURE + b"image-1",
    ]


def test_png_and_jpeg_reach_both_gemini_passes_with_correct_reusable_data():
    code_pages = [page(1), page(2, mime_type="image/jpeg")]
    first_output = ModelTranscription(
        code="candidate", overall_confidence=0.8, uncertain_regions=[]
    )
    verified_output = ModelTranscription(
        code="verified", overall_confidence=0.7, uncertain_regions=[]
    )
    client = FakeClient(response(first_output), response(verified_output))

    transcribe_pages(code_pages, [], settings(), client=client)

    assert len(client.models.calls) == 2
    for call in client.models.calls:
        image_parts = [
            part.inline_data
            for part in call["contents"][0].parts
            if part.inline_data
        ]
        assert [part.mime_type for part in image_parts] == [
            "image/png",
            "image/jpeg",
        ]
        assert [part.data for part in image_parts] == [
            code_pages[0].content,
            code_pages[1].content,
        ]
        assert all(part.data for part in image_parts)


def test_prompt_requires_literal_invalid_cpp_transcription():
    assert "do not add missing semicolons" in TRANSCRIPTION_PROMPT
    assert "do not add missing braces" in TRANSCRIPTION_PROMPT
    assert "changing `coit` to `cout`" in TRANSCRIPTION_PROMPT
    assert "do not complete incomplete statements" in TRANSCRIPTION_PROMPT
    assert "complete invalid C++ syntax" in TRANSCRIPTION_PROMPT


def test_prompt_keeps_handwriting_as_the_only_source_of_truth():
    assert (
        "must never be used to repair, complete, or correct the handwritten code"
        in TRANSCRIPTION_PROMPT
    )


def test_verification_prompt_forbids_programming_based_repairs():
    assert "Do not add missing semicolons" in VERIFICATION_PROMPT
    assert "Do not add missing braces" in VERIFICATION_PROMPT
    assert "`coit` instead of `cout`" in VERIFICATION_PROMPT
    assert "Do not repair invalid C++" in VERIFICATION_PROMPT
    assert "Programming correctness is irrelevant" in VERIFICATION_PROMPT
    assert "handwritten images are the sole source of truth" in VERIFICATION_PROMPT
    assert (
        "visible handwriting is always the sole source of truth"
        in TRANSCRIPTION_PROMPT
    )


def test_two_passes_return_verified_code_without_network_call():
    first_output = ModelTranscription(
        code="using namespace std;\nint main()\n{\ncoit << sum << endl;",
        overall_confidence=0.8,
        uncertain_regions=[
            {
                "id": "u-1",
                "page": 1,
                "line": 1,
                "detected": "main",
                "alternatives": ["ma1n"],
                "confidence": 0.5,
                "reason": "Character is unclear.",
            }
        ],
    )
    verified_code = "using namespace std\nint main()\ncoit << sum << endl"
    verified_output = ModelTranscription(
        code=verified_code,
        overall_confidence=0.7,
        uncertain_regions=[],
    )
    client = FakeClient(response(first_output), response(verified_output))
    result = transcribe_pages([page(1)], [], settings(), client=client)

    assert len(client.models.calls) == 2
    assert result.code == verified_code
    assert result.page_count == 1
    assert result.model == "test-model"
    for call in client.models.calls:
        config = call["config"]
        supplied_config = config.model_dump(exclude_none=True)
        assert "temperature" not in supplied_config
        assert "top_p" not in supplied_config
        assert "top_k" not in supplied_config
        assert "candidate_count" not in supplied_config
        assert config.response_mime_type == "application/json"
        assert config.response_schema is ModelTranscription


def test_all_ordered_pages_are_bundled_in_each_pass_with_candidate_in_second():
    first_output = ModelTranscription(
        code="candidate code",
        overall_confidence=0.8,
        uncertain_regions=[],
    )
    verified_output = ModelTranscription(
        code="verified code",
        overall_confidence=0.7,
        uncertain_regions=[],
    )
    client = FakeClient(response(first_output), response(verified_output))

    transcribe_pages([page(1), page(2), page(3)], [], settings(), client=client)

    assert len(client.models.calls) == 2
    first_parts = client.models.calls[0]["contents"][0].parts
    second_parts = client.models.calls[1]["contents"][0].parts
    first_images = [part.inline_data.data for part in first_parts if part.inline_data]
    second_images = [part.inline_data.data for part in second_parts if part.inline_data]
    expected_images = [page(1).content, page(2).content, page(3).content]
    assert first_images == expected_images
    assert second_images == expected_images
    second_text = "\n".join(
        part.text for part in second_parts if part.text is not None
    )
    assert "Candidate transcription to audit" in second_text
    assert "candidate code" in second_text


def test_verification_failure_does_not_return_unverified_first_pass():
    first_output = ModelTranscription(
        code="unverified code;",
        overall_confidence=0.8,
        uncertain_regions=[],
    )
    verification_error = errors.ServerError(
        503,
        {"error": {"code": 503, "status": "UNAVAILABLE", "message": "busy"}},
    )
    client = FakeClient(response(first_output), verification_error)

    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages([page(1)], [], settings(), client=client)

    assert len(client.models.calls) == 2
    assert caught.value.code == "gemini_unavailable"


def test_missing_gemini_api_key_is_distinguished():
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages([page(1)], [], settings(None))
    assert caught.value.code == "missing_api_key"
    assert caught.value.status_code == 503


def test_rejects_malformed_gemini_output():
    client = FakeClient(response({"code": "ok", "overall_confidence": 2}))
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages([page(1)], [], settings(), client=client)
    assert caught.value.code == "invalid_model_response"


@pytest.mark.parametrize("parsed", [None, {"code": "", "overall_confidence": 0.8, "uncertain_regions": []}])
def test_rejects_empty_transcription(parsed):
    client = FakeClient(response(parsed, text="" if parsed is None else "json"))
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages([page(1)], [], settings(), client=client)
    assert caught.value.code == "empty_transcription"


def test_rejects_uncertainty_page_outside_uploaded_pages():
    output = {
        "code": "ok",
        "overall_confidence": 0.8,
        "uncertain_regions": [
            {
                "id": "u",
                "page": 2,
                "detected": "x",
                "alternatives": [],
                "confidence": 0.5,
                "reason": "unclear",
            }
        ],
    }
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages(
            [page(1)], [], settings(), client=FakeClient(response(output))
        )
    assert caught.value.code == "invalid_model_response"


def test_classifies_free_tier_rate_limit():
    api_error = errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Free tier requests per minute rate limit exceeded",
            }
        },
    )
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages(
            [page(1)], [], settings(), client=FakeClient(api_error)
        )
    assert caught.value.code == "gemini_rate_limited"
    assert caught.value.status_code == 429


def test_classifies_daily_quota_exhaustion():
    api_error = errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Daily quota exhausted for requests per day",
            }
        },
    )
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages(
            [page(1)], [], settings(), client=FakeClient(api_error)
        )
    assert caught.value.code == "gemini_quota_exhausted"
    assert caught.value.status_code == 429


def test_classifies_invalid_api_key():
    api_error = errors.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "API key not valid",
            }
        },
    )
    with pytest.raises(TranscriptionServiceError) as caught:
        transcribe_pages(
            [page(1)], [], settings(), client=FakeClient(api_error)
        )
    assert caught.value.code == "gemini_authentication_failed"


def test_development_client_error_log_excludes_provider_message_and_secret(caplog):
    secret = "test-secret-key"
    api_error = errors.ClientError(
        400,
        {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": f"Unsupported parameter: temperature {secret}",
            }
        },
    )
    development_settings = Settings(
        "http://localhost:3000",
        secret,
        "gemini-3.5-flash-lite",
        "development",
    )

    with caplog.at_level("ERROR"), pytest.raises(TranscriptionServiceError):
        transcribe_pages(
            [page(1)], [], development_settings, client=FakeClient(api_error)
        )

    log_output = caplog.text
    assert "code=400" in log_output
    assert "status=INVALID_ARGUMENT" in log_output
    assert "Unsupported parameter: temperature" not in log_output
    assert secret not in log_output
