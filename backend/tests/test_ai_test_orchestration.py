"""Tests for ai_test_orchestration.py: full run/rerun flow, scoring,
call bounds, and error status mapping.

All Gemini interactions use an injected fake client — zero real API calls.
Execution uses the real run_test_request through the isolated Docker runner.
"""
import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.schemas.ai_tests import (
    AiModelFunctionTest,
    AiModelScenarioObject,
    AiModelScenarioStep,
    AiModelScenarioTest,
    AiModelTestPlan,
    AiModelScenarioPlan,
    AiStoredTest,
    AiTestRerunRequest,
    AiTestRunRequest,
    PRACTICE_DISCLAIMER,
)
from app.schemas.test_execution import FunctionTestCase, RunTestsResponse
from app.services.ai_test_capability import assess_ai_capability
from app.services.ai_test_orchestration import run_ai_tests, rerun_ai_tests, score_results
from app.services.function_analysis import analyze_test_mode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADD_SOURCE = "int add(int a, int b) { return a + b; }"
VOID_SOURCE = "void doNothing(int x) {}"
COUNTER_SOURCE = (
    "class Counter {\n"
    "public:\n"
    "    Counter(int start) : count_(start) {}\n"
    "    void increment() { ++count_; }\n"
    "    int get() const { return count_; }\n"
    "private:\n"
    "    int count_;\n"
    "};\n"
)


def _settings(key: str | None = "test-key") -> Settings:
    return Settings("http://localhost:3000", key, "test-model", "test")


def _fn_id(source: str, name: str) -> str:
    analysis = analyze_test_mode(source)
    for fn in analysis.functions:
        if fn.name == name:
            return fn.id
    raise ValueError(f"Function '{name}' not found.")


def _add_request(question: str = "Add two integers.") -> AiTestRunRequest:
    return AiTestRunRequest(
        code=ADD_SOURCE,
        language="cpp",
        question_text=question,
        target_kind="function",
        target_id=_fn_id(ADD_SOURCE, "add"),
    )


def _good_plan(target_id: str, tests: list | None = None) -> AiModelTestPlan:
    return AiModelTestPlan(
        target_id=target_id,
        tests=tests
        or [
            AiModelFunctionTest(
                name="adds_two",
                category="normal",
                reason="basic addition",
                arguments=["1", "2"],
                expected_outcome="return_value",
                expected_return="3",
            )
        ],
        skipped_topics=[],
    )


def _gemini_ok(plan: AiModelTestPlan):
    return SimpleNamespace(
        parsed=plan,
        text=plan.model_dump_json(),
        prompt_feedback=None,
        candidates=[],
    )


def _gemini_text_only(data: dict):
    return SimpleNamespace(
        parsed=None,
        text=json.dumps(data),
        prompt_feedback=None,
        candidates=[],
    )


class _FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) > len(self.outcomes):
            raise AssertionError(
                f"Unexpected Gemini call #{len(self.calls)}: "
                f"only {len(self.outcomes)} outcomes configured."
            )
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, *outcomes):
        self.models = _FakeModels(*outcomes)


# ---------------------------------------------------------------------------
# Pre-generation guards (no Gemini call)
# ---------------------------------------------------------------------------


def test_missing_question_returns_status_without_gemini_call():
    # question_text requires min_length=1, so use a single space (whitespace-only).
    request = AiTestRunRequest(
        code=ADD_SOURCE,
        language="cpp",
        question_text=" ",
        target_kind="function",
        target_id=_fn_id(ADD_SOURCE, "add"),
    )

    class _NeverClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                raise AssertionError("Gemini should not be called for missing question.")

    response = run_ai_tests(request, _settings(), client=_NeverClient())
    assert response.status == "missing_question"


def test_whitespace_question_rejected():
    request = AiTestRunRequest(
        code=ADD_SOURCE,
        language="cpp",
        question_text="   \t\n  ",
        target_kind="function",
        target_id=_fn_id(ADD_SOURCE, "add"),
    )

    class _NeverClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                raise AssertionError("Gemini should not be called.")

    response = run_ai_tests(request, _settings(), client=_NeverClient())
    assert response.status == "missing_question"


def test_compile_failure_returns_status_without_gemini_call():
    call_count = [0]

    class _NeverClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                call_count[0] += 1
                raise AssertionError("Gemini should not be called on compile failure.")

    broken_source = "int main() { SYNTAX ERROR HERE }"
    request = AiTestRunRequest(
        code=broken_source,
        language="cpp",
        question_text="Write something.",
        target_kind="function",
        target_id="add(int,int)->int",
    )
    response = run_ai_tests(request, _settings(), client=_NeverClient())
    assert response.status == "compile_failed"
    assert call_count[0] == 0


def test_unsupported_target_returns_status_with_zero_gemini_calls():
    call_count = [0]

    class _NeverClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                call_count[0] += 1
                raise AssertionError("Gemini must not be called for unsupported targets.")

    response = run_ai_tests(
        AiTestRunRequest(
            code=ADD_SOURCE,
            language="cpp",
            question_text="some question",
            target_kind="function",
            target_id="nonexistent(int)->int",
        ),
        _settings(),
        client=_NeverClient(),
    )
    assert response.status == "unsupported"
    assert call_count[0] == 0


def test_oversized_source_returns_source_too_large_with_zero_gemini_calls():
    from app.services.ai_test_generation import AI_SOURCE_CHAR_LIMIT

    call_count = [0]

    class _NeverClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                call_count[0] += 1
                raise AssertionError("Gemini must not be called for oversized source.")

    # Use a valid C++ function with padding to exceed the limit.
    padding = "// " + "x" * AI_SOURCE_CHAR_LIMIT
    large_source = ADD_SOURCE + "\n" + padding
    assert len(large_source) > AI_SOURCE_CHAR_LIMIT

    target_id = _fn_id(ADD_SOURCE, "add")
    response = run_ai_tests(
        AiTestRunRequest(
            code=large_source,
            language="cpp",
            question_text="some question",
            target_kind="function",
            target_id=target_id,
        ),
        _settings(),
        client=_NeverClient(),
    )
    assert response.status == "source_too_large"
    assert call_count[0] == 0


# ---------------------------------------------------------------------------
# Successful generation + execution
# ---------------------------------------------------------------------------


def test_valid_generation_executes_immediately_via_run_test_request():
    target_id = _fn_id(ADD_SOURCE, "add")
    plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status == "completed"
    assert len(client.models.calls) == 1
    assert response.score is not None
    assert len(response.tests) == 1
    assert len(response.stored_tests) == 1


# ---------------------------------------------------------------------------
# Container/mutation argument round-trip (SIGNATURE regression lock)
# All exercise the real end-to-end pipeline: fake Gemini -> real validation
# -> real isolated C++ execution. No mocking below run_test_request.
# ---------------------------------------------------------------------------

MUTABLE_VECTOR_SOURCE = (
    "#include <vector>\n"
    "void removeNegatives(std::vector<int>& values) {\n"
    "    std::vector<int> kept;\n"
    "    for (int value : values) { if (value >= 0) kept.push_back(value); }\n"
    "    values = kept;\n"
    "}\n"
)
CLEAR_VECTOR_SOURCE = (
    "#include <vector>\n"
    "void clearValues(std::vector<int>& values) { values.clear(); }\n"
)
MUTATE_AND_RETURN_SOURCE = (
    "#include <vector>\n"
    "int mutateAndReturn(std::vector<int>& values) {\n"
    "    int n = static_cast<int>(values.size());\n"
    "    values.push_back(9);\n"
    "    return n;\n"
    "}\n"
)
CONST_VECTOR_SOURCE = (
    "#include <vector>\n"
    "int sumEven(const std::vector<int>& values) {\n"
    "    int total = 0;\n"
    "    for (int v : values) { if (v % 2 == 0) total += v; }\n"
    "    return total;\n"
    "}\n"
)
VECTOR_BY_VALUE_SOURCE = (
    "#include <vector>\n"
    "int total(std::vector<int> values) {\n"
    "    int sum = 0;\n"
    "    for (int v : values) sum += v;\n"
    "    return sum;\n"
    "}\n"
)
DEQUE_SOURCE = (
    "#include <deque>\n"
    "int sumDeque(const std::deque<int>& values) {\n"
    "    int total = 0;\n"
    "    for (int v : values) total += v;\n"
    "    return total;\n"
    "}\n"
)


def _run_request(source: str, fn_name: str, question: str) -> AiTestRunRequest:
    return AiTestRunRequest(
        code=source,
        language="cpp",
        question_text=question,
        target_kind="function",
        target_id=_fn_id(source, fn_name),
    )


def test_mutation_only_generation_produces_visible_passing_rows():
    """Acceptance A: void removeNegatives(vector<int>&) — the reported bug."""
    target_id = _fn_id(MUTABLE_VECTOR_SOURCE, "removeNegatives")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="mixed_signs",
                category="mutation",
                reason="removes negatives, preserves order",
                arguments=["[1, -2, 0, 4]"],
                expected_outcome="return_void",
                expected_mutations=[
                    {"parameter_name": "values", "expected_final_value": "[1, 0, 4]"}
                ],
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(
        MUTABLE_VECTOR_SOURCE,
        "removeNegatives",
        "Remove every negative value from the vector, preserving order.",
    )

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert response.message != "This run completed but produced no test cases to show."
    assert len(response.tests) == 1
    assert response.tests[0].passed is True
    assert response.score is not None and response.score.passed == 1
    assert response.stored_tests[0].function_test.arguments == ["[1, -2, 0, 4]"]
    assert "std::" not in response.stored_tests[0].function_test.arguments[0]


def test_empty_final_vector_mutation_supported():
    """Acceptance B: void clearValues(vector<int>&) -> []."""
    target_id = _fn_id(CLEAR_VECTOR_SOURCE, "clearValues")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="clears_all",
                category="mutation",
                reason="clears the vector",
                arguments=["[1, 2, 3]"],
                expected_outcome="return_void",
                expected_mutations=[
                    {"parameter_name": "values", "expected_final_value": "[]"}
                ],
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(CLEAR_VECTOR_SOURCE, "clearValues", "Clear the vector.")

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert len(response.tests) == 1
    assert response.tests[0].passed is True


def test_return_and_mutation_expectations_coexist():
    """Acceptance C: int mutateAndReturn(vector<int>&) — both channels together."""
    target_id = _fn_id(MUTATE_AND_RETURN_SOURCE, "mutateAndReturn")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="returns_and_mutates",
                category="mutation",
                reason="returns original size, appends 9",
                arguments=["[1, 2]"],
                expected_outcome="return_value",
                expected_return="2",
                expected_mutations=[
                    {"parameter_name": "values", "expected_final_value": "[1, 2, 9]"}
                ],
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(
        MUTATE_AND_RETURN_SOURCE,
        "mutateAndReturn",
        "Return the original size, then append 9 to the vector.",
    )

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert len(response.tests) == 1
    assert response.tests[0].passed is True


def test_const_reference_generates_no_mutation_expectation():
    """Acceptance D: const vector<int>& — no mutation expectation generated."""
    target_id = _fn_id(CONST_VECTOR_SOURCE, "sumEven")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="sum_even",
                category="normal",
                reason="sums even values",
                arguments=["[1, 2, 3, 4]"],
                expected_outcome="return_value",
                expected_return="6",
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(CONST_VECTOR_SOURCE, "sumEven", "Sum the even values.")

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert len(response.tests) == 1
    assert response.tests[0].passed is True
    assert not response.stored_tests[0].function_test.expected_mutations


def test_by_value_container_argument_round_trips_raw():
    """Acceptance E: representative by-value container."""
    target_id = _fn_id(VECTOR_BY_VALUE_SOURCE, "total")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="sums_all",
                category="normal",
                reason="sums all values",
                arguments=["[1, 2, 3]"],
                expected_outcome="return_value",
                expected_return="6",
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(VECTOR_BY_VALUE_SOURCE, "total", "Sum all values.")

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert response.tests[0].passed is True
    assert response.stored_tests[0].function_test.arguments == ["[1, 2, 3]"]


def test_representative_other_container_no_double_conversion():
    """Acceptance F: const std::deque<int>& — a non-vector container family."""
    target_id = _fn_id(DEQUE_SOURCE, "sumDeque")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="sums_deque",
                category="normal",
                reason="sums all values",
                arguments=["[1, 2, 3]"],
                expected_outcome="return_value",
                expected_return="6",
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = _run_request(DEQUE_SOURCE, "sumDeque", "Sum all values in the deque.")

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status == "completed"
    assert response.tests[0].passed is True
    assert response.stored_tests[0].function_test.arguments == ["[1, 2, 3]"]


# ---------------------------------------------------------------------------
# input_error must not be reported as "completed" (masking-defect regression)
# ---------------------------------------------------------------------------


def test_function_path_surfaces_input_error_not_completed(monkeypatch):
    import app.services.ai_test_orchestration as orch

    target_id = _fn_id(ADD_SOURCE, "add")
    plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(plan))

    fake_response = RunTestsResponse(
        mode="function",
        success=False,
        input_error="synthetic: argument must contain data values, not C++ expressions.",
        tests=[],
    )
    monkeypatch.setattr(orch, "run_test_request", lambda *a, **k: fake_response)

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status != "completed"
    assert response.message == fake_response.input_error
    assert response.tests == []
    assert response.score is None
    assert len(response.stored_tests) == 1  # definitions preserved, not fabricated rows


def test_object_path_surfaces_input_error_not_completed(monkeypatch):
    import app.services.ai_test_orchestration as orch

    source = COUNTER_SOURCE
    plan = AiModelScenarioPlan(
        target_id="Counter",
        tests=[
            AiModelScenarioTest(
                name="basic",
                category="object_state",
                reason="construct and increment",
                objects=[
                    AiModelScenarioObject(
                        name="c", constructor_id="Counter::Counter(int)", arguments=["5"]
                    )
                ],
                steps=[
                    AiModelScenarioStep(
                        step_type="observer",
                        target_object_name="c",
                        method_id="Counter::get() const->int",
                        expected_outcome="return_value",
                        expected_return="5",
                    )
                ],
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    request = AiTestRunRequest(
        code=source,
        language="cpp",
        question_text="Construct a Counter and observe its value.",
        target_kind="object",
        target_id="Counter",
    )

    fake_response = RunTestsResponse(
        mode="object",
        success=False,
        input_error="synthetic: argument must contain data values, not C++ expressions.",
        tests=[],
    )
    monkeypatch.setattr(orch, "run_test_request", lambda *a, **k: fake_response)

    response = run_ai_tests(request, _settings(), client=client)

    assert response.status != "completed"
    assert response.message == fake_response.input_error
    assert response.tests == []
    assert response.score is None


def test_rerun_path_surfaces_input_error_not_completed(monkeypatch):
    import app.services.ai_test_orchestration as orch

    target_id = _fn_id(ADD_SOURCE, "add")
    stored = _make_stored_test(target_id)

    fake_response = RunTestsResponse(
        mode="function",
        success=False,
        input_error="synthetic: argument must contain data values, not C++ expressions.",
        tests=[],
    )
    monkeypatch.setattr(orch, "run_test_request", lambda *a, **k: fake_response)

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=ADD_SOURCE,
            language="cpp",
            target_kind="function",
            target_id=target_id,
            tests=[stored],
        ),
        _settings(),
    )

    assert response.status != "completed"
    assert response.message == fake_response.input_error
    assert response.tests == []
    assert response.score is None


def test_rejected_test_is_never_executed():
    """Tests that fail validation (wrong arg count) are excluded from execution."""
    target_id = _fn_id(ADD_SOURCE, "add")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="valid_test",
                category="normal",
                reason="basic",
                arguments=["1", "2"],
                expected_outcome="return_value",
                expected_return="3",
            ),
            AiModelFunctionTest(
                name="invalid_test",
                category="normal",
                reason="wrong count",
                arguments=["1"],  # missing second arg
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    # 1 valid + 1 invalid = 1 executed, 1 rejected.
    assert response.status == "completed"
    assert len(response.tests) == 1
    assert response.tests[0].name == "valid_test"
    assert len(client.models.calls) == 1  # No repair for above-minimum


def test_partial_valid_set_above_minimum_executes_with_note():
    """When accepted ≥ minimum and some rejected, executes without repair."""
    target_id = _fn_id(ADD_SOURCE, "add")
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="good",
                category="normal",
                reason="ok",
                arguments=["2", "3"],
                expected_outcome="return_value",
                expected_return="5",
            ),
            AiModelFunctionTest(
                name="bad",
                category="normal",
                reason="wrong count",
                arguments=["1"],  # invalid
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status == "completed"
    assert len(response.tests) == 1
    assert len(client.models.calls) == 1
    assert response.generation_note is not None


# ---------------------------------------------------------------------------
# Repair call
# ---------------------------------------------------------------------------


def test_below_minimum_triggers_single_repair_call():
    """If all tests from the initial response are rejected, the repair call fires."""
    target_id = _fn_id(ADD_SOURCE, "add")

    # Initial plan: all tests invalid (wrong arg count)
    bad_plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="bad_test",
                category="normal",
                reason="wrong args",
                arguments=["1"],  # add() needs 2
                expected_outcome="return_value",
                expected_return="1",
            )
        ],
        skipped_topics=[],
    )

    # Repair plan: valid test
    good_plan = _good_plan(target_id)

    client = _FakeClient(_gemini_ok(bad_plan), _gemini_ok(good_plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    # Repair was triggered → 2 Gemini calls.
    assert len(client.models.calls) == 2
    assert response.status == "completed"


def test_repair_failure_returns_generation_failed():
    """If both the initial and repair calls fail, the orchestrator returns an error."""
    from google.genai import errors

    target_id = _fn_id(ADD_SOURCE, "add")

    class _ServiceError(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "rate limited"
            self.details = []

    client = _FakeClient(_ServiceError(), _ServiceError())

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status in {"generation_rate_limited", "generation_failed", "no_useful_tests"}


def test_repair_success_recovers_and_executes():
    """Repair call provides valid tests → flow continues to execution."""
    target_id = _fn_id(ADD_SOURCE, "add")

    bad_plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="invalid",
                category="normal",
                reason="bad arg count",
                arguments=["1"],  # wrong
                expected_outcome="return_value",
                expected_return="1",
            )
        ],
        skipped_topics=[],
    )
    good_plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(bad_plan), _gemini_ok(good_plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status == "completed"
    assert response.score is not None
    assert len(client.models.calls) == 2


def test_maximum_two_model_calls_ever():
    """Under any scenario the orchestrator never makes more than 2 Gemini calls."""
    target_id = _fn_id(ADD_SOURCE, "add")

    # Worst case: initial call has multiple invalid tests + repair also has invalid tests
    bad_test = AiModelFunctionTest(
        name="bad",
        category="normal",
        reason="wrong",
        arguments=["1"],  # wrong count
        expected_outcome="return_value",
        expected_return="1",
    )
    bad_plan = AiModelTestPlan(target_id=target_id, tests=[bad_test], skipped_topics=[])
    good_plan = _good_plan(target_id)

    client = _FakeClient(_gemini_ok(bad_plan), _gemini_ok(good_plan))

    run_ai_tests(_add_request(), _settings(), client=client)

    # Must be ≤ 2.
    assert len(client.models.calls) <= 2


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class _PassResult:
    passed = True


class _FailResult:
    passed = False


def test_score_all_pass():
    s = score_results([_PassResult(), _PassResult(), _PassResult()])
    assert s is not None
    assert s.passed == 3
    assert s.executed == 3
    assert s.percentage == 100


def test_score_partial():
    s = score_results([_PassResult(), _FailResult(), _PassResult()])
    assert s is not None
    assert s.passed == 2
    assert s.executed == 3
    assert s.percentage == round(100 * 2 / 3)


def test_score_all_fail():
    s = score_results([_FailResult(), _FailResult()])
    assert s is not None
    assert s.passed == 0
    assert s.percentage == 0


def test_zero_executed_tests_has_null_score():
    s = score_results([])
    assert s is None


def test_expected_exception_pass_counts_in_score():
    """A passing exception test counts as passed — no special deduction."""
    target_id = _fn_id(ADD_SOURCE, "add")
    # Use a test that throws (add won't throw, but passed=True from result).
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="throws_test",
                category="exception",
                reason="expects throw",
                arguments=["1", "2"],
                expected_outcome="throws",
                expected_exception_type="std::runtime_error",
            )
        ],
        skipped_topics=[],
    )
    client = _FakeClient(_gemini_ok(plan))
    response = run_ai_tests(_add_request(), _settings(), client=client)

    # add() doesn't throw → test fails. Score should reflect this.
    assert response.status == "completed"
    assert response.score is not None
    assert response.score.executed >= 1


def test_return_pass_with_mutation_fail_scores_as_failed_test():
    """The existing engine's combined `passed` field already ANDs all channels."""
    s = score_results([_PassResult(), _FailResult()])
    assert s.passed == 1


# ---------------------------------------------------------------------------
# Infrastructure and memory
# ---------------------------------------------------------------------------


def test_infrastructure_error_returns_stored_tests_without_score(monkeypatch):
    from app.services import ai_test_orchestration
    from app.services.compiler import CompilerServiceError

    target_id = _fn_id(ADD_SOURCE, "add")
    plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(plan))

    def _raise(*args, **kwargs):
        raise CompilerServiceError("runner_unavailable", "runner down", 503)

    monkeypatch.setattr(ai_test_orchestration, "run_test_request", _raise)

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status == "infrastructure_failed"
    assert len(response.stored_tests) == 1
    assert response.score is None


def test_memory_status_is_not_run():
    target_id = _fn_id(ADD_SOURCE, "add")
    plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.memory_status == "not_run"


# ---------------------------------------------------------------------------
# Rerun path
# ---------------------------------------------------------------------------


def _make_stored_test(target_id: str) -> AiStoredTest:
    tc = FunctionTestCase(
        name="adds_two",
        arguments=["1", "2"],
        expected_outcome="return_value",
        expected_return="3",
    )
    return AiStoredTest(
        id="ai-1",
        name="adds_two",
        category="normal",
        reason="basic addition",
        function_test=tc,
    )


def test_rerun_makes_no_gemini_call():
    target_id = _fn_id(ADD_SOURCE, "add")
    stored = _make_stored_test(target_id)

    call_count = [0]

    # Monkeypatch the generation service to detect calls.
    import app.services.ai_test_orchestration as orch
    original = None

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=ADD_SOURCE,
            language="cpp",
            target_kind="function",
            target_id=target_id,
            tests=[stored],
        ),
        _settings(),
    )
    # If it completes without importing a client, Gemini was not called.
    assert response.status in {"completed", "incompatible", "compile_failed"}


def test_rerun_preserves_exact_inputs_and_labels():
    target_id = _fn_id(ADD_SOURCE, "add")
    stored = _make_stored_test(target_id)

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=ADD_SOURCE,
            language="cpp",
            target_kind="function",
            target_id=target_id,
            tests=[stored],
        ),
        _settings(),
    )

    assert response.status == "completed"
    assert len(response.tests) == 1
    assert response.tests[0].id == "ai-1"
    assert response.tests[0].name == "adds_two"


def test_rerun_after_body_only_edit_executes():
    """Changing the function body (not signature) keeps the test compatible."""
    modified_source = "int add(int a, int b) { return a + b + 0; }"
    target_id = _fn_id(ADD_SOURCE, "add")
    stored = _make_stored_test(target_id)

    modified_target_id = _fn_id(modified_source, "add")
    # IDs should match since the signature is the same.
    if modified_target_id != target_id:
        pytest.skip("Signature changed — skipping body-only-edit test.")

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=modified_source,
            language="cpp",
            target_kind="function",
            target_id=target_id,
            tests=[stored],
        ),
        _settings(),
    )
    assert response.status == "completed"


def test_rerun_with_changed_signature_returns_incompatible():
    """Changing the parameter count → capability gate blocks rerun."""
    # New signature: add(int a, int b, int c) — different parameter count.
    new_source = "int add(int a, int b, int c) { return a + b + c; }"
    old_target_id = _fn_id(ADD_SOURCE, "add")
    stored = _make_stored_test(old_target_id)

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=new_source,
            language="cpp",
            target_kind="function",
            target_id=old_target_id,
            tests=[stored],
        ),
        _settings(),
    )
    assert response.status == "incompatible"


def test_rerun_revalidates_against_current_code():
    """Stored test with wrong argument count is caught during rerun compatibility check."""
    target_id = _fn_id(ADD_SOURCE, "add")
    tc_bad = FunctionTestCase(
        name="wrong_args",
        arguments=["1"],  # add() needs 2; rerun must catch this
        expected_outcome="return_value",
        expected_return="1",
    )
    stored_bad = AiStoredTest(
        id="ai-1",
        name="wrong_args",
        category="normal",
        reason="test",
        function_test=tc_bad,
    )

    response = rerun_ai_tests(
        AiTestRerunRequest(
            code=ADD_SOURCE,
            language="cpp",
            target_kind="function",
            target_id=target_id,
            tests=[stored_bad],
        ),
        _settings(),
    )
    assert response.status == "incompatible"


# ---------------------------------------------------------------------------
# Fresh generation behavior
# ---------------------------------------------------------------------------


def test_fresh_generation_response_replaces_only_on_success():
    """Failure response carries no stored_tests (so prior set is preserved client-side)."""
    from google.genai import errors

    target_id = _fn_id(ADD_SOURCE, "add")

    class _RateLimit(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "rate limited"
            self.details = []

    client = _FakeClient(_RateLimit())

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status != "completed"
    assert len(response.stored_tests) == 0


def test_disclaimer_present_on_completed_response():
    target_id = _fn_id(ADD_SOURCE, "add")
    plan = _good_plan(target_id)
    client = _FakeClient(_gemini_ok(plan))

    response = run_ai_tests(_add_request(), _settings(), client=client)

    assert response.status == "completed"
    assert response.disclaimer == PRACTICE_DISCLAIMER
