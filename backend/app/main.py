from typing import Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.compilation import router as compilation_router
from app.api.test_execution import router as test_execution_router
from app.api.transcription import router as transcription_router
from app.config import get_settings
from app.schemas.transcription import ErrorBody, ErrorResponse


class HealthResponse(BaseModel):
    status: Literal["ok"]


settings = get_settings()

app = FastAPI(title="InkToCode API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(transcription_router)
app.include_router(compilation_router)
app.include_router(test_execution_router)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: object, _error: RequestValidationError
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code="request_validation_error",
            message="Required multipart fields are missing or invalid.",
        )
    )
    return JSONResponse(status_code=422, content=body.model_dump())


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
