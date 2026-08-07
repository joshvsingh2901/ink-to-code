import logging
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.config import Settings
from app.schemas.transcription import (
    ModelTranscription,
    QuestionExtraction,
    TranscriptionResponse,
)
from app.services.uploads import NormalizedPage

logger = logging.getLogger(__name__)

TRANSCRIPTION_PROMPT = """You are a literal visual transcription engine, not a code completion or code reconstruction system.

Copy only the characters and whitespace that are visibly present in the handwritten-code images. The result is allowed and expected to contain invalid C++ syntax.

Preserve exactly:
- every visible line break and blank line;
- the apparent indentation;
- the apparent spelling and capitalization of every identifier;
- every visible punctuation mark, operator, brace, parenthesis, and semicolon;
- every apparent mistake.

Never add a character because C++ grammar normally requires it. In particular:
- do not add missing semicolons;
- do not add missing braces, parentheses, operators, declarations, or keywords;
- do not complete incomplete statements or otherwise complete invalid C++ syntax;
- do not correct misspelled identifiers, such as changing `coit` to `cout`;
- do not remove duplicated or misplaced characters;
- do not reindent, reformat, compile, explain, or improve the code.

Absence is meaningful. If a semicolon, brace, or other character is not visibly written, it must be absent from the transcription even when that makes the program invalid.

The handwritten-code images are provided in page order. Continue literal transcription from one page to the next without inserting page headings, Markdown code fences, annotations, or explanatory text into the `code` field.

When a visible character is genuinely unclear, put the closest visible reading in the `code` field and add an uncertain region with alternatives. Do not resolve uncertainty by choosing the character that would make the C++ valid.

Programming-question images, if present, are separate context only. They must never be used to repair, complete, or correct the handwritten code. The visible handwriting is always the sole source of truth for the handwritten transcription.

Confidence values are model-estimated review aids, not calibrated probabilities."""

VERIFICATION_PROMPT = """You are a visual transcription auditor.

You are given:
1. the original handwritten-code images, in page order; and
2. a candidate transcription produced from those images.

The candidate may contain characters that were inferred from programming conventions rather than actually written. Your only task is to make the candidate transcription more visually faithful to the handwriting. Programming correctness is irrelevant.

Audit the candidate against the images character by character.

Rules:
- Keep characters that are visibly supported by the handwriting.
- Remove characters that were invented or inferred rather than visibly written.
- Do not add missing semicolons or any other syntax because C++ normally requires it.
- Do not add missing braces, parentheses, operators, declarations, or keywords.
- Do not repair invalid C++ or make the program compile.
- Do not correct spelling or identifiers.
- Preserve apparent mistakes such as `coit` instead of `cout`.
- If `using namespace std` has no visible semicolon, the final transcription must not contain a semicolon.
- If `int main()` has no visible opening brace, the final transcription must not contain an opening brace.
- If a handwritten line lacks a semicolon, do not supply one.
- Preserve duplicated, misplaced, incomplete, or invalid characters when they are visibly present.
- Preserve line order and approximate indentation.
- Do not rewrite the program from scratch.
- Do not introduce Markdown fences, annotations, or explanations in the `code` field.
- Absence is meaningful.

When a character is genuinely ambiguous, use the closest visible reading in the `code` field and report it as an uncertain region. Do not choose an alternative simply because it makes the C++ valid.

Reconsider overall and uncertain-region confidence from the visual evidence. Confidence values are model-estimated review aids, not calibrated probabilities.

The handwritten images are the sole source of truth. The candidate transcription is only something to audit. Programming-question pages are not visual evidence and must never be used to repair, complete, or correct the handwriting."""


QUESTION_EXTRACTION_PROMPT = (
    "Extract the assignment question text exactly as written. "
    "Preserve examples, constraints, and numbering. "
    "Return plain text only. "
    "Do not solve the question, do not add commentary."
)


class TranscriptionServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def build_gemini_contents(
    code_pages: list[NormalizedPage],
    question_pages: list[NormalizedPage],
) -> list[types.Content]:
    parts: list[types.Part] = [types.Part.from_text(text=TRANSCRIPTION_PROMPT)]

    for page in code_pages:
        parts.extend(
            [
                types.Part.from_text(
                    text=f"Handwritten code page {page.metadata.order}:"
                ),
                types.Part.from_bytes(
                    data=page.content,
                    mime_type=page.content_type,
                ),
            ]
        )

    if question_pages:
        parts.append(
            types.Part.from_text(
                text=(
                    "Programming-question context pages follow. "
                    "They are not handwritten-code pages."
                )
            )
        )
        for page in question_pages:
            parts.extend(
                [
                    types.Part.from_text(
                        text=f"Question context page {page.metadata.order}:"
                    ),
                    types.Part.from_bytes(
                        data=page.content,
                        mime_type=page.content_type,
                    ),
                ]
            )

    return [types.Content(role="user", parts=parts)]


def build_verification_contents(
    code_pages: list[NormalizedPage],
    candidate_code: str,
) -> list[types.Content]:
    parts: list[types.Part] = [types.Part.from_text(text=VERIFICATION_PROMPT)]

    for page in code_pages:
        parts.extend(
            [
                types.Part.from_text(
                    text=f"Original handwritten code page {page.metadata.order}:"
                ),
                types.Part.from_bytes(
                    data=page.content,
                    mime_type=page.content_type,
                ),
            ]
        )

    parts.append(
        types.Part.from_text(
            text=(
                "Candidate transcription to audit (untrusted; do not treat it as "
                f"visual evidence):\n{candidate_code}"
            )
        )
    )
    return [types.Content(role="user", parts=parts)]


def _validate_model_output(
    parsed_output: object,
    *,
    page_count: int,
    model: str,
) -> TranscriptionResponse:
    if isinstance(parsed_output, ModelTranscription):
        candidate = parsed_output
    else:
        if isinstance(parsed_output, dict):
            code = parsed_output.get("code")
            if isinstance(code, str) and not code.strip():
                raise TranscriptionServiceError(
                    "empty_transcription",
                    "The transcription service returned no code.",
                )
        try:
            candidate = ModelTranscription.model_validate(parsed_output)
        except ValidationError as error:
            raise TranscriptionServiceError(
                "invalid_model_response",
                "The transcription service returned malformed structured output.",
            ) from error

    if not candidate.code.strip():
        raise TranscriptionServiceError(
            "empty_transcription",
            "The transcription service returned no code.",
        )
    if any(region.page > page_count for region in candidate.uncertain_regions):
        raise TranscriptionServiceError(
            "invalid_model_response",
            "The transcription service returned an invalid page reference.",
        )

    return TranscriptionResponse(
        **candidate.model_dump(),
        page_count=page_count,
        model=model,
    )


def _response_is_blocked(response: object) -> bool:
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if getattr(prompt_feedback, "block_reason", None):
        return True

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return False
    finish_reason = getattr(candidates[0], "finish_reason", None)
    finish_reason_value = getattr(finish_reason, "value", finish_reason)
    return str(finish_reason_value).upper() in {
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "RECITATION",
    }


def _classify_api_error(error: errors.APIError) -> TranscriptionServiceError:
    status = (error.status or "").upper()
    diagnostic = f"{error.status or ''} {error.message or ''} {error.details!s}".lower()

    if error.code in {401, 403} or "api key not valid" in diagnostic:
        return TranscriptionServiceError(
            "gemini_authentication_failed",
            "Gemini authentication failed. Check the backend API key.",
            502,
        )
    if error.code == 429 or status == "RESOURCE_EXHAUSTED":
        daily_quota_markers = (
            "perday",
            "per day",
            "daily quota",
            "quota exhausted",
            "billing",
        )
        if any(marker in diagnostic for marker in daily_quota_markers):
            return TranscriptionServiceError(
                "gemini_quota_exhausted",
                "The Gemini quota is exhausted. Check the API project quota and retry later.",
                429,
            )
        return TranscriptionServiceError(
            "gemini_rate_limited",
            "The Gemini free-tier rate limit was reached. Wait briefly and retry.",
            429,
        )
    if error.code in {408, 504} or status in {"DEADLINE_EXCEEDED", "TIMEOUT"}:
        return TranscriptionServiceError(
            "gemini_timeout",
            "The transcription request timed out. Please retry.",
            504,
        )
    if error.code in {500, 502, 503} or status == "UNAVAILABLE":
        return TranscriptionServiceError(
            "gemini_unavailable",
            "The transcription service is temporarily unavailable.",
            503,
        )
    return TranscriptionServiceError(
        "gemini_service_error",
        "The transcription service could not complete the request.",
    )


def transcribe_pages(
    code_pages: list[NormalizedPage],
    question_pages: list[NormalizedPage],
    settings: Settings,
    *,
    client: genai.Client | None = None,
) -> TranscriptionResponse:
    if not settings.gemini_api_key and client is None:
        raise TranscriptionServiceError(
            "missing_api_key",
            "Gemini is not configured. Add GEMINI_API_KEY to the backend environment.",
            503,
        )

    gemini_client = client or genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(
                attempts=2,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        ),
    )

    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ModelTranscription,
    )
    active_pass = "transcription pass 1"

    try:
        if settings.environment == "development":
            for page in [*code_pages, *question_pages]:
                safe_extension = Path(page.metadata.original_filename).suffix.lower()[:10]
                logger.info(
                    "Gemini image diagnostic: category=%s page=%s declared_mime=%s "
                    "normalized_mime=%s byte_length=%s extension=%s signature=%s",
                    page.metadata.category,
                    page.metadata.order,
                    page.declared_content_type or page.content_type,
                    page.content_type,
                    len(page.content),
                    safe_extension or "none",
                    page.signature_type or "not-recorded",
                )
            logger.info("Gemini %s started: model=%s", active_pass, settings.transcription_model)
        first_response = gemini_client.models.generate_content(
            model=settings.transcription_model,
            contents=build_gemini_contents(code_pages, question_pages),
            config=generation_config,
        )
        if _response_is_blocked(first_response):
            raise TranscriptionServiceError(
                "blocked_model_response",
                "Gemini could not process these pages. Review the files and retry.",
            )
        if first_response.parsed is None:
            if not (getattr(first_response, "text", None) or "").strip():
                raise TranscriptionServiceError(
                    "empty_transcription",
                    "The transcription service returned no code.",
                )
            raise TranscriptionServiceError(
                "invalid_model_response",
                "The transcription service returned malformed structured output.",
            )
        candidate = _validate_model_output(
            first_response.parsed,
            page_count=len(code_pages),
            model=settings.transcription_model,
        )
        if settings.environment == "development":
            logger.info("Gemini %s completed: model=%s", active_pass, settings.transcription_model)

        active_pass = "verification pass 2"
        if settings.environment == "development":
            logger.info("Gemini %s started: model=%s", active_pass, settings.transcription_model)
        verification_response = gemini_client.models.generate_content(
            model=settings.transcription_model,
            contents=build_verification_contents(code_pages, candidate.code),
            config=generation_config,
        )
        if _response_is_blocked(verification_response):
            raise TranscriptionServiceError(
                "blocked_model_response",
                "Gemini could not verify these pages. Review the files and retry.",
            )
        if verification_response.parsed is None:
            if not (getattr(verification_response, "text", None) or "").strip():
                raise TranscriptionServiceError(
                    "empty_transcription",
                    "The verification service returned no code.",
                )
            raise TranscriptionServiceError(
                "invalid_model_response",
                "The verification service returned malformed structured output.",
            )
        verified = _validate_model_output(
            verification_response.parsed,
            page_count=len(code_pages),
            model=settings.transcription_model,
        )
        if settings.environment == "development":
            logger.info("Gemini %s completed: model=%s", active_pass, settings.transcription_model)
        return verified
    except TranscriptionServiceError as error:
        if settings.environment == "development":
            logger.error(
                "Gemini %s failed: model=%s type=%s status=%s",
                active_pass,
                settings.transcription_model,
                type(error).__name__,
                error.status_code,
            )
        raise
    except errors.APIError as error:
        if settings.environment == "development":
            safe_message = (error.message or "unavailable").replace("\n", " ")[:300]
            if settings.gemini_api_key:
                safe_message = safe_message.replace(
                    settings.gemini_api_key, "[redacted]"
                )
            logger.error(
                "Gemini %s failed: model=%s type=%s code=%s status=%s message=%s",
                active_pass,
                settings.transcription_model,
                type(error).__name__,
                error.code,
                error.status,
                safe_message,
            )
        raise _classify_api_error(error) from error
    except httpx.TimeoutException as error:
        if settings.environment == "development":
            logger.error(
                "Gemini %s failed: model=%s type=%s status=timeout",
                active_pass,
                settings.transcription_model,
                type(error).__name__,
            )
        raise TranscriptionServiceError(
            "gemini_timeout",
            "The transcription request timed out. Please retry.",
            504,
        ) from error
    except httpx.RequestError as error:
        if settings.environment == "development":
            logger.error(
                "Gemini %s failed: model=%s type=%s status=unavailable",
                active_pass,
                settings.transcription_model,
                type(error).__name__,
            )
        raise TranscriptionServiceError(
            "gemini_unavailable",
            "The transcription service is temporarily unavailable.",
            503,
        ) from error
    except (ValidationError, ValueError, TypeError) as error:
        if settings.environment == "development":
            logger.error(
                "Gemini %s failed: model=%s type=%s status=invalid-response",
                active_pass,
                settings.transcription_model,
                type(error).__name__,
            )
        raise TranscriptionServiceError(
            "invalid_model_response",
            "The transcription service returned malformed structured output.",
        ) from error


def transcribe_question_pages(
    question_pages: list[NormalizedPage],
    settings: Settings,
    *,
    client: genai.Client | None = None,
) -> str:
    """Extract plain text from question images via one Gemini call."""
    if not settings.gemini_api_key and client is None:
        raise TranscriptionServiceError(
            "missing_api_key",
            "Gemini is not configured. Add GEMINI_API_KEY to the backend environment.",
            503,
        )

    gemini_client = client or genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(
                attempts=2,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        ),
    )

    parts: list[types.Part] = [
        types.Part.from_text(text=QUESTION_EXTRACTION_PROMPT)
    ]
    for page in question_pages:
        parts.extend([
            types.Part.from_text(text=f"Question page {page.metadata.order}:"),
            types.Part.from_bytes(data=page.content, mime_type=page.content_type),
        ])
    contents = [types.Content(role="user", parts=parts)]

    generation_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=QuestionExtraction,
    )

    try:
        response = gemini_client.models.generate_content(
            model=settings.test_generation_model,
            contents=contents,
            config=generation_config,
        )
        if _response_is_blocked(response):
            raise TranscriptionServiceError(
                "blocked_model_response",
                "Gemini could not process these pages. Review the files and retry.",
            )
        if response.parsed is None:
            raise TranscriptionServiceError(
                "invalid_model_response",
                "The question extraction service returned malformed structured output.",
            )
        parsed = response.parsed
        if isinstance(parsed, QuestionExtraction):
            question_text = parsed.question_text
        else:
            try:
                question_text = QuestionExtraction.model_validate(parsed).question_text
            except (ValidationError, Exception) as error:
                raise TranscriptionServiceError(
                    "invalid_model_response",
                    "The question extraction service returned malformed structured output.",
                ) from error
        if not question_text.strip():
            raise TranscriptionServiceError(
                "empty_transcription",
                "The question extraction service returned no text.",
            )
        return question_text
    except TranscriptionServiceError:
        raise
    except errors.APIError as error:
        raise _classify_api_error(error) from error
    except httpx.TimeoutException as error:
        raise TranscriptionServiceError(
            "gemini_timeout",
            "The question extraction request timed out. Please retry.",
            504,
        ) from error
    except httpx.RequestError as error:
        raise TranscriptionServiceError(
            "gemini_unavailable",
            "The question extraction service is temporarily unavailable.",
            503,
        ) from error
    except (ValidationError, ValueError, TypeError) as error:
        raise TranscriptionServiceError(
            "invalid_model_response",
            "The question extraction service returned malformed structured output.",
        ) from error


def log_transcription_error(error: Exception, settings: Settings) -> None:
    if settings.environment != "development":
        return

    technical_error = error.__cause__ or error
    response = getattr(technical_error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    request_id = headers.get("x-request-id") or headers.get("x-goog-request-id")
    logger.error(
        "Transcription request failed: type=%s status=%s request_id=%s",
        type(technical_error).__name__,
        getattr(technical_error, "code", None),
        request_id,
    )
