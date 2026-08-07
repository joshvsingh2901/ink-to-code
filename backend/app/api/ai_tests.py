"""AI test generation and rerun API routes."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.config import get_settings
from app.schemas.ai_tests import AiTestRunRequest, AiTestRunResponse, AiTestRerunRequest
from app.services.ai_test_orchestration import rerun_ai_tests, run_ai_tests

router = APIRouter(prefix="/api", tags=["ai tests"])


@router.post(
    "/ai-tests/run",
    response_model=AiTestRunResponse,
)
async def ai_tests_run(request: AiTestRunRequest) -> AiTestRunResponse:
    settings = get_settings()
    return await run_in_threadpool(run_ai_tests, request, settings)


@router.post(
    "/ai-tests/rerun",
    response_model=AiTestRunResponse,
)
async def ai_tests_rerun(request: AiTestRerunRequest) -> AiTestRunResponse:
    settings = get_settings()
    return await run_in_threadpool(rerun_ai_tests, request, settings)
