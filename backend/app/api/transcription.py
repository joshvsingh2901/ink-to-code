from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.schemas.transcription import ErrorBody, ErrorResponse, TranscriptionResponse
from app.services.transcription import (
    TranscriptionServiceError,
    log_transcription_error,
    transcribe_pages,
)
from app.services.uploads import UploadValidationError, validate_and_normalize_pages

router = APIRouter(prefix="/api", tags=["transcription"])


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


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

        return await run_in_threadpool(
            transcribe_pages, code_pages, normalized_question_pages, settings
        )
    except UploadValidationError as error:
        return error_response("upload_validation_failed", str(error), 400)
    except TranscriptionServiceError as error:
        log_transcription_error(error, settings)
        return error_response(error.code, error.message, error.status_code)
