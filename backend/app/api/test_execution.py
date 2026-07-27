from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.schemas.test_execution import RunTestsRequest, RunTestsResponse
from app.services.compiler import CompilerServiceError
from app.services.test_execution import run_cpp_tests

router = APIRouter(prefix="/api", tags=["test execution"])


@router.post(
    "/run-tests",
    response_model=RunTestsResponse,
)
async def run_tests(
    request: RunTestsRequest,
) -> RunTestsResponse | JSONResponse:
    if not request.code.strip():
        return error_response(
            "empty_source",
            "Source code cannot be empty.",
            400,
        )

    try:
        return await run_in_threadpool(
            run_cpp_tests,
            request.code,
            request.tests,
        )
    except CompilerServiceError as error:
        return error_response(error.code, error.message, error.status_code)
