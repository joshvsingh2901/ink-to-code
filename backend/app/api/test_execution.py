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
    ObjectOperatorParameterResponse,
    ObjectOperatorResponse,
    ObjectSpecialMemberResponse,
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
                        is_virtual=method.is_virtual,
                        is_pure_virtual=method.is_pure_virtual,
                        is_override=method.is_override,
                        is_final=method.is_final,
                        overrides_method_id=method.overrides_method_id,
                        override_mismatch_reason=(
                            method.override_mismatch_reason
                        ),
                    )
                    for method in object_class.methods
                ],
                operators=[
                    ObjectOperatorResponse(
                        id=operator.id,
                        symbol=operator.symbol,
                        display=operator.display,
                        kind=operator.kind,
                        declaring_class_id=operator.declaring_class_id,
                        parameters=[
                            ObjectOperatorParameterResponse(
                                name=parameter.name,
                                type=parameter.display_type,
                                operand_kind=(
                                    "stream"
                                    if parameter.is_stream
                                    else "object"
                                    if parameter.object_class_id
                                    else "value"
                                ),
                                object_class_id=parameter.object_class_id,
                                type_metadata=(
                                    type_response(parameter.value_type)
                                    if parameter.value_type
                                    else None
                                ),
                            )
                            for parameter in operator.parameters
                        ],
                        return_type=operator.return_display_type,
                        return_kind=operator.return_kind,
                        return_object_class_id=(
                            operator.return_object_class_id
                        ),
                        return_type_metadata=(
                            type_response(operator.return_value_type)
                            if operator.return_value_type
                            else None
                        ),
                        is_const=operator.is_const,
                    )
                    for operator in object_class.operators
                ],
                special_members=[
                    ObjectSpecialMemberResponse(
                        id=member.id,
                        kind=member.kind,
                        display=member.display,
                        is_defaulted=member.is_defaulted,
                    )
                    for member in object_class.special_members
                ],
                base_class_id=object_class.base_class_id,
                inheritance_access=object_class.inheritance_access,
                inheritance_supported=object_class.inheritance_supported,
                is_abstract=object_class.is_abstract,
                has_virtual_destructor=(
                    object_class.has_virtual_destructor
                ),
                derived_class_ids=list(object_class.derived_class_ids),
                inheritance_depth=object_class.inheritance_depth,
            )
            for object_class in object_analysis.classes
        ],
        available_modes=available_modes,
        message=(
            object_analysis.message
            if object_analysis.message
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
