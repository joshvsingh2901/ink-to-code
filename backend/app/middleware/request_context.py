import contextvars
import logging
import time
import uuid

from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings, validate_web_settings
from app.schemas.transcription import ErrorBody, ErrorResponse


logger = logging.getLogger("inktocode.requests")
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

REQUEST_ID_HEADER = "X-Request-ID"
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
API_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.hsts_enabled = (
            settings.environment == "production" and settings.hsts_enabled
        )
        self.allowed_origins = frozenset(validate_web_settings(settings))

    def _add_headers(self, headers: MutableHeaders, path: str) -> None:
        headers["X-Content-Type-Options"] = "nosniff"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Permissions-Policy"] = PERMISSIONS_POLICY
        headers["X-Frame-Options"] = "DENY"
        if path == "/health" or path.startswith("/api/"):
            headers["Content-Security-Policy"] = API_CONTENT_SECURITY_POLICY
        if self.hsts_enabled:
            headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

    def _add_error_cors(self, headers: MutableHeaders, scope: Scope) -> None:
        origin = dict(scope.get("headers", [])).get(b"origin", b"").decode(
            "latin-1"
        )
        if origin not in self.allowed_origins:
            return
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Expose-Headers"] = REQUEST_ID_HEADER
        headers.add_vary_header("Origin")

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        token = _request_id.set(request_id)
        started = time.perf_counter()
        response_started = False
        status_code = 500
        path = str(scope.get("path", ""))
        method = str(scope.get("method", ""))

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                self._add_headers(headers, path)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as error:
            if response_started:
                raise
            logger.error(
                "request_failed request_id=%s method=%s path=%r error_type=%s",
                request_id,
                method,
                path,
                type(error).__name__,
            )
            body = ErrorResponse(
                error=ErrorBody(
                    code="internal_server_error",
                    message="An unexpected server error occurred.",
                ),
                request_id=request_id,
            )
            response = JSONResponse(
                status_code=500,
                content=body.model_dump(exclude_none=True),
            )
            self._add_error_cors(response.headers, scope)
            await response(scope, receive, send_with_headers)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "request_complete request_id=%s method=%s path=%r status=%s "
                "duration_ms=%.2f",
                request_id,
                method,
                path,
                status_code,
                duration_ms,
            )
            _request_id.reset(token)
