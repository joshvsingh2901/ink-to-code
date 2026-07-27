from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.schemas.compilation import CompileRequest, CompileResponse
from app.schemas.transcription import ErrorBody, ErrorResponse
from app.services.compiler import CompilerServiceError, compile_cpp

router = APIRouter(prefix="/api", tags=["compilation"])


def error_response(code: str, message: str, status_code: int) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


@router.post(
    "/compile",
    response_model=CompileResponse,
    responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
async def compile_source(
    request: CompileRequest,
) -> CompileResponse | JSONResponse:
    if request.language != "cpp":
        return error_response(
            "unsupported_language",
            "Only the 'cpp' language is supported.",
            400,
        )
    if not request.code.strip():
        return error_response(
            "empty_source",
            "Source code cannot be empty.",
            400,
        )

    try:
        return await run_in_threadpool(compile_cpp, request.code)
    except CompilerServiceError as error:
        return error_response(error.code, error.message, error.status_code)
