from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.schemas.test_execution import (
    FunctionParameterResponse,
    FunctionResponse,
    FunctionTypeResponse,
    RunTestsRequest,
    RunTestsResponse,
    SourceModeRequest,
    SourceModeResponse,
)
from app.services.compiler import CompilerServiceError
from app.services.function_analysis import analyze_test_mode
from app.services.test_execution import run_test_request

router = APIRouter(prefix="/api", tags=["test execution"])


@router.post(
    "/test-mode",
    response_model=SourceModeResponse,
)
async def analyze_source_mode(
    request: SourceModeRequest,
) -> SourceModeResponse:
    analysis = await run_in_threadpool(analyze_test_mode, request.code)
    return SourceModeResponse(
        mode=analysis.mode,
        functions=[
            FunctionResponse(
                id=function.id,
                name=function.name,
                return_type=function.return_type,
                parameters=[
                    FunctionParameterResponse(
                        name=parameter.name,
                        type=parameter.type,
                        type_metadata=FunctionTypeResponse(
                            kind=parameter.value_type.kind,
                            display_type=parameter.value_type.display_type,
                            scalar_type=parameter.value_type.scalar_type,
                            element_type=parameter.value_type.element_type,
                            passing=parameter.value_type.passing,
                            size_parameter_name=(
                                parameter.value_type.size_parameter_name
                            ),
                        ),
                    )
                    for parameter in function.parameters
                ],
                display=function.display,
                return_type_metadata=FunctionTypeResponse(
                    kind=function.return_value_type.kind,
                    display_type=function.return_value_type.display_type,
                    scalar_type=function.return_value_type.scalar_type,
                    element_type=function.return_value_type.element_type,
                    passing=function.return_value_type.passing,
                    size_parameter_name=(
                        function.return_value_type.size_parameter_name
                    ),
                ),
            )
            for function in analysis.functions
        ],
        message=analysis.message,
    )


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
            run_test_request,
            request,
        )
    except CompilerServiceError as error:
        return error_response(error.code, error.message, error.status_code)
