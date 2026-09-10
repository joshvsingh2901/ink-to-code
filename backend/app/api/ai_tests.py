"""AI test generation and rerun API routes."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.config import get_settings
from app.schemas.ai_tests import AiTestRunRequest, AiTestRunResponse, AiTestRerunRequest
from app.services.ai_test_orchestration import rerun_ai_tests, run_ai_tests
from app.services.resource_limits import (
    ResourceBusyError,
    container_slot,
    gemini_slot,
)

router = APIRouter(prefix="/api", tags=["ai tests"])


@router.post(
    "/ai-tests/run",
    response_model=AiTestRunResponse,
)
async def ai_tests_run(
    request: AiTestRunRequest,
) -> AiTestRunResponse | JSONResponse:
    settings = get_settings()
    try:
        # Global acquisition order is AI first, then container.
        async with gemini_slot():
            async with container_slot():
                return await run_in_threadpool(run_ai_tests, request, settings)
    except ResourceBusyError as error:
        response = error_response(error.code, error.message, 503)
        response.headers["Retry-After"] = str(error.retry_after)
        return response


@router.post(
    "/ai-tests/rerun",
    response_model=AiTestRunResponse,
)
async def ai_tests_rerun(
    request: AiTestRerunRequest,
) -> AiTestRunResponse | JSONResponse:
    settings = get_settings()
    try:
        async with container_slot():
            return await run_in_threadpool(rerun_ai_tests, request, settings)
    except ResourceBusyError as error:
        response = error_response(error.code, error.message, 503)
        response.headers["Retry-After"] = str(error.retry_after)
        return response
