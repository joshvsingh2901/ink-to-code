from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.schemas.compiler_suggestions import (
    CompilerSuggestionRequest,
    CompilerSuggestionResponse,
)
from app.services.compiler_suggestions import get_compiler_suggestions

router = APIRouter(prefix="/api", tags=["compilation"])


@router.post(
    "/compiler-suggestions",
    response_model=CompilerSuggestionResponse,
)
async def compiler_suggestions(
    request: CompilerSuggestionRequest,
) -> CompilerSuggestionResponse | JSONResponse:
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

    return await run_in_threadpool(
        get_compiler_suggestions,
        request.code,
        request.diagnostics,
    )
