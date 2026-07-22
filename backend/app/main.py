import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

app = FastAPI(title="InkToCode API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
