from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.middleware.request_context import current_request_id
from app.schemas.transcription import (
    ErrorBody,
    ErrorResponse,
    QuestionTextResponse,
    TranscriptionResponse,
)
from app.services.transcription import (
    TranscriptionServiceError,
    log_transcription_error,
    transcribe_pages,
    transcribe_question_pages,
)
from app.services.resource_limits import ResourceBusyError, gemini_slot
from app.services.uploads import UploadValidationError, validate_and_normalize_pages

router = APIRouter(prefix="/api", tags=["transcription"])


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message),
        request_id=current_request_id(),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
    )


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def transcribe(
    handwritten_code_pages: Annotated[list[UploadFile], File()],
    handwritten_code_metadata: Annotated[str, Form()],
    question_pages: Annotated[list[UploadFile] | None, File()] = None,
    question_metadata: Annotated[str | None, Form()] = None,
) -> TranscriptionResponse | JSONResponse:
    settings = get_settings()
    question_files = question_pages or []

    try:
        code_pages = await validate_and_normalize_pages(
            handwritten_code_pages,
            handwritten_code_metadata,
            category="handwritten_code",
            minimum=1,
            maximum=5,
        )

        if question_files or question_metadata is not None:
            if question_metadata is None:
                raise UploadValidationError(
                    "invalid_upload_metadata",
                    "Question metadata is required when question pages are supplied."
                )
            normalized_question_pages = await validate_and_normalize_pages(
                question_files,
                question_metadata,
                category="question",
                minimum=0,
                maximum=5,
            )
        else:
            normalized_question_pages = []

        async with gemini_slot():
            return await run_in_threadpool(
                transcribe_pages, code_pages, normalized_question_pages, settings
            )
    except ResourceBusyError as error:
        response = error_response(error.code, error.message, 503)
        response.headers["Retry-After"] = str(error.retry_after)
        return response
    except UploadValidationError as error:
        return error_response(error.code, error.message, 400)
    except TranscriptionServiceError as error:
        log_transcription_error(error, settings)
        return error_response(error.code, error.message, error.status_code)


@router.post(
    "/transcribe-question",
    response_model=QuestionTextResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def transcribe_question(
    question_pages: Annotated[list[UploadFile], File()],
    question_metadata: Annotated[str, Form()],
) -> QuestionTextResponse | JSONResponse:
    settings = get_settings()
    try:
        normalized_pages = await validate_and_normalize_pages(
            question_pages,
            question_metadata,
            category="question",
            minimum=1,
            maximum=5,
        )
        async with gemini_slot():
            question_text = await run_in_threadpool(
                transcribe_question_pages, normalized_pages, settings
            )
        return QuestionTextResponse(
            question_text=question_text,
            model=settings.test_generation_model,
        )
    except ResourceBusyError as error:
        response = error_response(error.code, error.message, 503)
        response.headers["Retry-After"] = str(error.retry_after)
        return response
    except UploadValidationError as error:
        return error_response(error.code, error.message, 400)
    except TranscriptionServiceError as error:
        log_transcription_error(error, settings)
        return error_response(error.code, error.message, error.status_code)
