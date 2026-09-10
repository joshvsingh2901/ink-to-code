import asyncio
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.resource_limits import ResourceBusyError, ResourceGate


def gate(capacity: int = 1, timeout: float = 0.02) -> ResourceGate:
    return ResourceGate(
        capacity,
        timeout,
        ResourceBusyError("busy", "Resource is busy."),
    )


def test_gate_never_exceeds_configured_concurrency():
    async def exercise():
        resource_gate = gate(capacity=2, timeout=1)
        active = 0
        maximum = 0

        async def worker():
            nonlocal active, maximum
            async with resource_gate.slot():
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(worker() for _ in range(8)))
        return maximum

    assert asyncio.run(exercise()) == 2


def test_excess_work_times_out_with_busy_error_and_does_not_leak_slot():
    async def exercise():
        resource_gate = gate()
        async with resource_gate.slot():
            with pytest.raises(ResourceBusyError):
                async with resource_gate.slot():
                    pass
        async with resource_gate.slot():
            pass

    asyncio.run(exercise())


def test_slot_is_released_after_success_and_exception():
    async def exercise():
        resource_gate = gate()
        async with resource_gate.slot():
            pass
        with pytest.raises(RuntimeError):
            async with resource_gate.slot():
                raise RuntimeError("failure")
        async with resource_gate.slot():
            pass

    asyncio.run(exercise())


def test_cancelled_waiter_does_not_consume_or_leak_slot():
    async def exercise():
        resource_gate = gate(timeout=1)
        async with resource_gate.slot():
            waiter = asyncio.create_task(resource_gate.semaphore.acquire())
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        async with resource_gate.slot():
            pass

    asyncio.run(exercise())


def test_independent_container_and_gemini_gates_can_follow_fixed_order():
    async def exercise():
        gemini = gate(timeout=1)
        container = gate(timeout=1)
        order: list[str] = []
        async with gemini.slot():
            order.append("ai")
            async with container.slot():
                order.append("container")
        return order

    assert asyncio.run(exercise()) == ["ai", "container"]


def test_compiler_busy_route_returns_503_without_compiling(monkeypatch):
    calls = 0

    @asynccontextmanager
    async def busy_slot():
        raise ResourceBusyError(
            "compiler_busy",
            "The compiler is busy. Try again in a moment.",
        )
        yield

    def forbidden_compile(_code: str):
        nonlocal calls
        calls += 1
        raise AssertionError("compiler must not run")

    monkeypatch.setattr("app.api.compilation.container_slot", busy_slot)
    monkeypatch.setattr("app.api.compilation.compile_cpp", forbidden_compile)

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/compile",
                json={"code": "int main() {}", "language": "cpp"},
            )

    response = asyncio.run(request())
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "compiler_busy"
    assert calls == 0


def test_ai_busy_route_returns_503_without_generation(monkeypatch):
    calls = 0

    @asynccontextmanager
    async def busy_slot():
        raise ResourceBusyError(
            "ai_busy",
            "AI service is busy. Try again in a moment.",
        )
        yield

    def forbidden_generation(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("Gemini must not run")

    monkeypatch.setattr("app.api.ai_tests.gemini_slot", busy_slot)
    monkeypatch.setattr("app.api.ai_tests.run_ai_tests", forbidden_generation)

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/ai-tests/run",
                json={
                    "code": "int add(int a) { return a; }",
                    "language": "cpp",
                    "question_text": "Return the input.",
                    "target_kind": "function",
                    "target_id": "add(int)",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_busy"
    assert calls == 0
