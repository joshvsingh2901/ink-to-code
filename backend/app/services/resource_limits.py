"""Process-local concurrency guards for container and Gemini work."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.config import get_settings


class ResourceBusyError(RuntimeError):
    def __init__(self, code: str, message: str, retry_after: int = 5):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after = retry_after


class ResourceGate:
    def __init__(
        self,
        capacity: int,
        timeout_seconds: float,
        busy_error: ResourceBusyError,
    ):
        self.capacity = max(1, capacity)
        self.timeout_seconds = max(0.001, timeout_seconds)
        self.busy_error = busy_error
        self.semaphore = asyncio.Semaphore(self.capacity)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(
                self.semaphore.acquire(), timeout=self.timeout_seconds
            )
        except TimeoutError as error:
            raise ResourceBusyError(
                self.busy_error.code,
                self.busy_error.message,
                self.busy_error.retry_after,
            ) from error
        try:
            yield
        finally:
            self.semaphore.release()


_settings = get_settings()
CONTAINER_GATE = ResourceGate(
    _settings.cpp_max_concurrent_jobs,
    _settings.cpp_acquire_timeout_seconds,
    ResourceBusyError(
        "compiler_busy",
        "The compiler is busy. Try again in a moment.",
    ),
)
GEMINI_GATE = ResourceGate(
    _settings.ai_max_concurrent_calls,
    _settings.ai_acquire_timeout_seconds,
    ResourceBusyError(
        "ai_busy",
        "AI service is busy. Try again in a moment.",
    ),
)


@asynccontextmanager
async def container_slot() -> AsyncIterator[None]:
    async with CONTAINER_GATE.slot():
        yield


@asynccontextmanager
async def gemini_slot() -> AsyncIterator[None]:
    async with GEMINI_GATE.slot():
        yield
