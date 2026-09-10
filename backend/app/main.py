from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.ai_tests import router as ai_tests_router
from app.api.compilation import router as compilation_router
from app.api.test_execution import router as test_execution_router
from app.api.transcription import router as transcription_router
from app.config import Settings, get_settings, validate_web_settings
from app.middleware.body_limit import RequestBodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.schemas.transcription import ErrorBody, ErrorResponse


class HealthResponse(BaseModel):
    status: Literal["ok"]


def create_app(configured_settings: Settings | None = None) -> FastAPI:
    settings = configured_settings or get_settings()
    origins = validate_web_settings(settings)
    application = FastAPI(title="InkToCode API", version="0.1.0", debug=False)
    application.add_middleware(RateLimitMiddleware, settings=settings)
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=settings.max_request_bytes,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    # Outermost so IDs and safe error responses also cover CORS preflight,
    # body-limit, rate-limit, validation, and unexpected failures.
    application.add_middleware(RequestContextMiddleware, settings=settings)
    application.include_router(transcription_router)
    application.include_router(compilation_router)
    application.include_router(test_execution_router)
    application.include_router(ai_tests_router)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors = error.errors()
        oversized_locations = [
            tuple(str(part) for part in item.get("loc", ()))
            for item in errors
            if item.get("type") == "string_too_long"
        ]
        if any(
            location and location[-1] == "code"
            for location in oversized_locations
        ):
            body = ErrorResponse(
                error=ErrorBody(
                    code="source_too_large",
                    message=(
                        "Source code exceeds the "
                        f"{settings.max_source_chars}-character limit."
                    ),
                ),
                request_id=request.state.request_id,
            )
            return JSONResponse(
                status_code=422,
                content=body.model_dump(exclude_none=True),
            )
        test_value_fields = {
            "arguments",
            "constructor_arguments",
            "operands",
            "expected_final_value",
            "expected_return",
        }
        if any(
            any(part in test_value_fields for part in location)
            for location in oversized_locations
        ):
            body = ErrorResponse(
                error=ErrorBody(
                    code="test_value_too_large",
                    message="A test value is too large to process.",
                ),
                request_id=request.state.request_id,
            )
            return JSONResponse(
                status_code=422,
                content=body.model_dump(exclude_none=True),
            )
        body = ErrorResponse(
            error=ErrorBody(
                code="request_validation_error",
                message="Required request fields are missing or invalid.",
            ),
            request_id=request.state.request_id,
        )
        return JSONResponse(
            status_code=422,
            content=body.model_dump(exclude_none=True),
        )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return application


app = create_app()
