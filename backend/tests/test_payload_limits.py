import asyncio

from httpx import ASGITransport, AsyncClient
import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.main import app
from app.schemas.ai_tests import AiStoredTest, AiTestRerunRequest
from app.schemas.compilation import CompileRequest
from app.schemas.test_execution import (
    FunctionMutationExpectation,
    FunctionTestCase,
    ObjectScenarioStep,
    ObjectScenarioTestCase,
    SourceModeRequest,
)


def test_source_limit_accepts_normal_and_boundary_values():
    limit = get_settings().max_source_chars
    assert CompileRequest(code="int main() {}", language="cpp").code
    assert SourceModeRequest(code="x" * limit, language="cpp").code == "x" * limit


def test_source_limit_rejects_over_boundary():
    with pytest.raises(ValidationError):
        CompileRequest(
            code="x" * (get_settings().max_source_chars + 1),
            language="cpp",
        )


def test_test_mode_rejects_oversized_source_before_analysis(monkeypatch):
    calls = 0

    def forbidden_analysis(_code: str):
        nonlocal calls
        calls += 1
        raise AssertionError("analysis must not run")

    monkeypatch.setattr("app.api.test_execution.analyze_test_mode", forbidden_analysis)
    monkeypatch.setattr(
        "app.api.test_execution.analyze_object_scenarios", forbidden_analysis
    )

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/test-mode",
                json={
                    "code": "x" * (get_settings().max_source_chars + 1),
                    "language": "cpp",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_too_large"
    assert calls == 0


def test_normal_nested_test_values_validate():
    test = FunctionTestCase(
        name="sum",
        arguments=["[1, 2, 3]"],
        expected_return="6",
    )
    assert test.arguments == ["[1, 2, 3]"]


def test_oversized_argument_is_rejected():
    with pytest.raises(ValidationError):
        FunctionTestCase(
            arguments=["x" * (get_settings().max_test_value_chars + 1)],
            expected_return="0",
        )


def test_oversized_operator_operand_is_rejected():
    with pytest.raises(ValidationError):
        ObjectScenarioStep(
            step_type="operator",
            operator_id="operator:+",
            operands=["x" * (get_settings().max_test_value_chars + 1)],
        )


def test_oversized_object_constructor_argument_is_rejected():
    with pytest.raises(ValidationError):
        ObjectScenarioTestCase(
            name="large constructor",
            class_id="Widget",
            constructor_id="Widget(string)",
            constructor_arguments=[
                "x" * (get_settings().max_test_value_chars + 1)
            ],
            steps=[],
        )


def test_oversized_mutation_value_is_rejected():
    with pytest.raises(ValidationError):
        FunctionMutationExpectation(
            parameter_id="value",
            expected_final_value="x" * (get_settings().max_test_value_chars + 1),
        )


def test_oversized_stored_rerun_test_is_rejected():
    oversized = "x" * (get_settings().max_test_value_chars + 1)
    with pytest.raises(ValidationError):
        AiTestRerunRequest(
            code="int add(int a, int b) { return a + b; }",
            language="cpp",
            target_kind="function",
            target_id="add(int,int)",
            tests=[
                AiStoredTest(
                    id="test-1",
                    name="normal",
                    category="normal",
                    reason="checks addition",
                    function_test={
                        "arguments": [oversized, "2"],
                        "expected_return": "3",
                    },
                )
            ],
        )


def test_oversized_nested_run_payload_is_rejected_before_execution(monkeypatch):
    calls = 0

    def forbidden_execution(_request):
        nonlocal calls
        calls += 1
        raise AssertionError("execution must not run")

    monkeypatch.setattr("app.api.test_execution.run_test_request", forbidden_execution)

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/run-tests",
                json={
                    "mode": "function",
                    "code": "int add(int a) { return a; }",
                    "language": "cpp",
                    "target_function": "add(int)",
                    "tests": [
                        {
                            "name": "large",
                            "arguments": [
                                "x" * (get_settings().max_test_value_chars + 1)
                            ],
                            "expected_return": "0",
                        }
                    ],
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "test_value_too_large"
    assert calls == 0


def test_oversized_stored_rerun_payload_is_rejected_before_execution(monkeypatch):
    calls = 0

    def forbidden_rerun(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("rerun must not execute")

    monkeypatch.setattr("app.api.ai_tests.rerun_ai_tests", forbidden_rerun)

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/ai-tests/rerun",
                json={
                    "code": "int add(int a) { return a; }",
                    "language": "cpp",
                    "target_kind": "function",
                    "target_id": "add(int)",
                    "tests": [
                        {
                            "id": "test-1",
                            "name": "large",
                            "category": "normal",
                            "reason": "checks input",
                            "function_test": {
                                "name": "large",
                                "arguments": [
                                    "x"
                                    * (get_settings().max_test_value_chars + 1)
                                ],
                                "expected_return": "0",
                            },
                        }
                    ],
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "test_value_too_large"
    assert calls == 0


def test_oversized_ai_source_is_rejected_before_generation(monkeypatch):
    calls = 0

    def forbidden_generation(*_args):
        nonlocal calls
        calls += 1
        raise AssertionError("Gemini must not run")

    monkeypatch.setattr("app.api.ai_tests.run_ai_tests", forbidden_generation)

    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/ai-tests/run",
                json={
                    "code": "x" * (get_settings().max_source_chars + 1),
                    "language": "cpp",
                    "question_text": "Return the input.",
                    "target_kind": "function",
                    "target_id": "add(int)",
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "source_too_large"
    assert calls == 0
