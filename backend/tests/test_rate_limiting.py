import asyncio
from dataclasses import replace

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.middleware.rate_limit import (
    FixedWindowLimiter,
    RateLimitMiddleware,
    resolve_client_identity,
)


def settings(**overrides) -> Settings:
    base = Settings("http://localhost:3000", None, "model", "test")
    values = {
        "rate_limit_enabled": True,
        "rate_limit_compile_per_minute": 2,
        "rate_limit_ai_per_window": 2,
        "rate_limit_ai_window_seconds": 300,
        "rate_limit_global_ai_per_minute": 100,
    }
    values.update(overrides)
    return replace(base, **values)


def make_app(config: Settings) -> FastAPI:
    test_app = FastAPI()

    @test_app.post("/api/compile")
    async def compile_endpoint():
        return {"ok": True}

    @test_app.post("/api/transcribe")
    async def transcribe_endpoint():
        return {"ok": True}

    @test_app.get("/health")
    async def health_endpoint():
        return {"status": "ok"}

    test_app.add_middleware(RateLimitMiddleware, settings=config)
    return test_app


async def post(test_app: FastAPI, ip: str, path: str = "/api/compile", **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=test_app, client=(ip, 1234)),
        base_url="http://test",
    ) as client:
        return await client.post(path, **kwargs)


def test_within_quota_then_over_quota_returns_retry_after_and_error_shape():
    async def exercise():
        test_app = make_app(settings())
        return [await post(test_app, "192.0.2.1") for _ in range(3)]

    responses = asyncio.run(exercise())
    assert [response.status_code for response in responses] == [200, 200, 429]
    assert int(responses[-1].headers["Retry-After"]) >= 1
    assert responses[-1].json()["error"]["code"] == "rate_limited"


def test_two_clients_have_independent_quotas():
    async def exercise():
        test_app = make_app(settings(rate_limit_compile_per_minute=1))
        return (
            await post(test_app, "192.0.2.1"),
            await post(test_app, "192.0.2.2"),
        )

    first, second = asyncio.run(exercise())
    assert first.status_code == second.status_code == 200


def test_forged_forwarded_for_is_ignored_by_default():
    async def exercise():
        test_app = make_app(settings(rate_limit_compile_per_minute=1))
        first = await post(
            test_app, "192.0.2.1", headers={"X-Forwarded-For": "198.51.100.1"}
        )
        second = await post(
            test_app, "192.0.2.1", headers={"X-Forwarded-For": "198.51.100.2"}
        )
        return first, second

    first, second = asyncio.run(exercise())
    assert first.status_code == 200
    assert second.status_code == 429


def test_trusted_proxy_uses_nth_entry_from_right_and_ignores_attacker_prefix():
    scope = {
        "client": ("10.0.0.10", 1234),
        "headers": [(b"x-forwarded-for", b"attacker, 198.51.100.8, 10.0.0.9")],
    }
    assert resolve_client_identity(scope, 1) == "10.0.0.9"
    assert resolve_client_identity(scope, 2) == "198.51.100.8"


def test_ipv6_identity_is_normalized_to_64_prefix():
    first = {"client": ("2001:db8:abcd:12::1", 1), "headers": []}
    second = {"client": ("2001:db8:abcd:12:ffff::2", 1), "headers": []}
    assert resolve_client_identity(first, 0) == "2001:db8:abcd:12::/64"
    assert resolve_client_identity(second, 0) == "2001:db8:abcd:12::/64"


def test_disabled_limiter_does_not_enforce_quota():
    async def exercise():
        test_app = make_app(settings(rate_limit_enabled=False))
        return [await post(test_app, "192.0.2.1") for _ in range(4)]

    assert all(response.status_code == 200 for response in asyncio.run(exercise()))


def test_unrelated_cheap_route_is_not_limited():
    async def exercise():
        test_app = make_app(settings(rate_limit_compile_per_minute=1))
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            return [await client.get("/health") for _ in range(3)]

    assert all(response.status_code == 200 for response in asyncio.run(exercise()))


def test_window_expiry_restores_quota():
    limiter = FixedWindowLimiter()
    assert limiter.check("compile", "client", limit=1, window_seconds=60, now=1)[0]
    assert not limiter.check("compile", "client", limit=1, window_seconds=60, now=2)[0]
    assert limiter.check("compile", "client", limit=1, window_seconds=60, now=61)[0]


def test_limiter_state_is_bounded():
    limiter = FixedWindowLimiter(max_keys=10)
    for index in range(100):
        limiter.check("compile", str(index), limit=1, window_seconds=60, now=1)
    assert limiter.tracked_keys == 10


def test_global_ai_backstop_applies_across_clients():
    async def exercise():
        test_app = make_app(
            settings(
                rate_limit_ai_per_window=10,
                rate_limit_global_ai_per_minute=2,
            )
        )
        return [
            await post(test_app, f"192.0.2.{index}", path="/api/transcribe")
            for index in range(1, 4)
        ]

    responses = asyncio.run(exercise())
    assert [response.status_code for response in responses] == [200, 200, 429]
