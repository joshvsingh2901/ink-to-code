"""Streaming ASGI request-body size enforcement."""

from collections.abc import Awaitable, Callable
from starlette.types import Message, Receive, Scope, Send

from app.schemas.transcription import ErrorBody, ErrorResponse


class RequestBodyLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._send_rejection(send)
            return

        # Read no more than max_bytes + one incoming ASGI chunk. This bounded
        # pre-read ensures FastAPI cannot translate a receive-side exception
        # into a generic 400 while still preventing unbounded buffering.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if len(chunk) > self.max_bytes - len(body):
                await self._send_rejection(send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def limited_receive() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, limited_receive, send)

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return None
            return parsed if parsed >= 0 else None
        return None

    @staticmethod
    async def _send_rejection(send: Send) -> None:
        body = ErrorResponse(
            error=ErrorBody(
                code="request_body_too_large",
                message="This request is too large to process.",
            )
        ).model_dump_json().encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
