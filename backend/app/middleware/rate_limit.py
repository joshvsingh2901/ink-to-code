"""Bounded in-process fixed-window rate limiting for expensive routes."""

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import ipaddress
import math
import time

from starlette.types import Receive, Scope, Send

from app.config import Settings
from app.schemas.transcription import ErrorBody, ErrorResponse


AI_ROUTES = frozenset(
    {"/api/transcribe", "/api/transcribe-question", "/api/ai-tests/run"}
)
COMPILER_ROUTES = frozenset(
    {"/api/compile", "/api/test-mode", "/api/run-tests", "/api/ai-tests/rerun"}
)


@dataclass
class _Window:
    started_at: float
    expires_at: float
    count: int


class FixedWindowLimiter:
    """Fixed-window counters with expired-entry sweeping and LRU eviction."""

    def __init__(self, max_keys: int = 10_000):
        self.max_keys = max_keys
        self._windows: OrderedDict[tuple[str, str], _Window] = OrderedDict()
        self._operations = 0

    @property
    def tracked_keys(self) -> int:
        return len(self._windows)

    def check(
        self,
        bucket: str,
        identity: str,
        *,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> tuple[bool, int]:
        if limit <= 0 or window_seconds <= 0:
            return False, max(window_seconds, 1)

        self._operations += 1
        if self._operations % 256 == 0:
            self._sweep(now)

        key = (bucket, identity)
        window = self._windows.get(key)
        if window is None or now >= window.expires_at:
            self._windows[key] = _Window(
                started_at=now,
                expires_at=now + window_seconds,
                count=1,
            )
            self._windows.move_to_end(key)
            self._evict()
            return True, 0

        self._windows.move_to_end(key)
        if window.count >= limit:
            retry_after = max(1, math.ceil(window.expires_at - now))
            return False, retry_after
        window.count += 1
        return True, 0

    def _sweep(self, now: float) -> None:
        expired = [
            key
            for key, window in self._windows.items()
            if now >= window.expires_at
        ]
        for key in expired:
            self._windows.pop(key, None)

    def _evict(self) -> None:
        while len(self._windows) > self.max_keys:
            self._windows.popitem(last=False)


def resolve_client_identity(scope: Scope, trusted_proxy_count: int) -> str:
    client = scope.get("client")
    direct_host = client[0] if client else "unknown"
    candidate = direct_host

    if trusted_proxy_count > 0:
        forwarded = _header(scope, b"x-forwarded-for")
        if forwarded:
            chain = [
                entry.strip()
                for entry in forwarded.split(",")
                if entry.strip()
            ]
            if len(chain) >= trusted_proxy_count:
                candidate = chain[-trusted_proxy_count]

    return (
        _normalize_ip(candidate)
        or _normalize_ip(direct_host)
        or direct_host
    )


def _header(scope: Scope, target: bytes) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == target:
            return value.decode("latin-1")
    return None


def _normalize_ip(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        network = ipaddress.ip_network(f"{address}/64", strict=False)
        return f"{network.network_address}/64"
    return str(address)


class RateLimitMiddleware:
    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        settings: Settings,
    ):
        self.app = app
        self.settings = settings
        self.limiter = FixedWindowLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not self.settings.rate_limit_enabled
            or scope["type"] != "http"
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in AI_ROUTES:
            allowed, retry_after = self._check_ai(scope)
        elif path in COMPILER_ROUTES:
            allowed, retry_after = self._check_compiler(scope)
        else:
            await self.app(scope, receive, send)
            return

        if not allowed:
            await self._send_rejection(send, retry_after)
            return
        await self.app(scope, receive, send)

    def _check_ai(self, scope: Scope) -> tuple[bool, int]:
        now = time.monotonic()
        identity = resolve_client_identity(
            scope,
            self.settings.trusted_proxy_count,
        )
        allowed, retry_after = self.limiter.check(
            "ai-client",
            identity,
            limit=self.settings.rate_limit_ai_per_window,
            window_seconds=self.settings.rate_limit_ai_window_seconds,
            now=now,
        )
        if not allowed:
            return allowed, retry_after
        return self.limiter.check(
            "ai-global",
            "all-clients",
            limit=self.settings.rate_limit_global_ai_per_minute,
            window_seconds=60,
            now=now,
        )

    def _check_compiler(self, scope: Scope) -> tuple[bool, int]:
        return self.limiter.check(
            "compiler-client",
            resolve_client_identity(scope, self.settings.trusted_proxy_count),
            limit=self.settings.rate_limit_compile_per_minute,
            window_seconds=60,
            now=time.monotonic(),
        )

    @staticmethod
    async def _send_rejection(send: Send, retry_after: int) -> None:
        body = ErrorResponse(
            error=ErrorBody(
                code="rate_limited",
                message="Too many requests. Try again shortly.",
            )
        ).model_dump_json().encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
