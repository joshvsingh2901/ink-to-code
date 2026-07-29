from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.compilation import error_response
from app.schemas.test_execution import (
    FunctionParameterResponse,
    FunctionResponse,
    FunctionTypeResponse,
    ObjectClassResponse,
    ObjectConstructorResponse,
    ObjectMethodResponse,
    RunTestsRequest,
    RunTestsResponse,
    SourceModeRequest,
    SourceModeResponse,
)
from app.services.compiler import CompilerServiceError
from app.services.function_analysis import analyze_test_mode
from app.services.object_analysis import analyze_object_scenarios
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
    object_analysis = await run_in_threadpool(
        analyze_object_scenarios,
        request.code,
    )

    def type_response(value_type) -> FunctionTypeResponse:
        return FunctionTypeResponse(
            kind=value_type.kind,
            display_type=value_type.display_type,
            scalar_type=value_type.scalar_type,
            element_type=value_type.element_type,
            vector_depth=value_type.vector_depth,
            passing=value_type.passing,
            size_parameter_name=value_type.size_parameter_name,
        )

    available_modes = (
        [analysis.mode] if analysis.mode != "unsupported" else []
    )
    if object_analysis.classes:
        available_modes.append("object")
    response_mode = (
        "object"
        if analysis.mode == "unsupported" and object_analysis.classes
        else analysis.mode
    )
    return SourceModeResponse(
        mode=response_mode,
        functions=[
            FunctionResponse(
                id=function.id,
                name=function.name,
                return_type=function.return_type,
                parameters=[
                    FunctionParameterResponse(
                        name=parameter.name,
                        type=parameter.type,
                        type_metadata=type_response(parameter.value_type),
                    )
                    for parameter in function.parameters
                ],
                display=function.display,
                return_type_metadata=type_response(
                    function.return_value_type
                ),
            )
            for function in analysis.functions
        ],
        classes=[
            ObjectClassResponse(
                id=object_class.id,
                name=object_class.name,
                kind=object_class.kind,
                constructors=[
                    ObjectConstructorResponse(
                        id=constructor.id,
                        display=constructor.display,
                        parameters=[
                            FunctionParameterResponse(
                                name=parameter.name,
                                type=parameter.type,
                                type_metadata=type_response(
                                    parameter.value_type
                                ),
                            )
                            for parameter in constructor.parameters
                        ],
                    )
                    for constructor in object_class.constructors
                ],
                methods=[
                    ObjectMethodResponse(
                        id=method.id,
                        name=method.name,
                        display=method.display,
                        parameters=[
                            FunctionParameterResponse(
                                name=parameter.name,
                                type=parameter.type,
                                type_metadata=type_response(
                                    parameter.value_type
                                ),
                            )
                            for parameter in method.parameters
                        ],
                        return_type=method.return_value_type.display_type,
                        return_type_metadata=type_response(
                            method.return_value_type
                        ),
                        is_const=method.is_const,
                    )
                    for method in object_class.methods
                ],
            )
            for object_class in object_analysis.classes
        ],
        available_modes=available_modes,
        message=(
            object_analysis.message
            if response_mode == "object" and not object_analysis.classes
            else analysis.message
            if not available_modes
            else None
        ),
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
