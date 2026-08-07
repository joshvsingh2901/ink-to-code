"""Tests for ai_test_generation.py: prompt building, source context,
Gemini transport, response parsing, and the repair call."""
import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.config import Settings
from app.schemas.ai_tests import AiTestServiceError
from app.services.ai_test_capability import AiCapabilityResult, assess_ai_capability
from app.services.ai_test_generation import (
    AI_SOURCE_CHAR_LIMIT,
    build_function_prompt,
    generate_function_tests,
    select_source_context,
)
from app.services.function_analysis import analyze_test_mode

# ---------------------------------------------------------------------------
# Source fixtures
# ---------------------------------------------------------------------------

SCALAR_SOURCE = "int add(int a, int b) { return a + b; }"
MUTABLE_SOURCE = "void swap(int& a, int& b) { int t = a; a = b; b = t; }"
OBJECT_SOURCE = (
    "class Box { public: Box(int s) : size(s) {} "
    "int get() const { return size; } private: int size; };"
)


def _settings(key: str | None = "test-key") -> Settings:
    return Settings("http://localhost:3000", key, "test-model", "test")


def _fn_id(source: str, name: str) -> str:
    analysis = analyze_test_mode(source)
    for fn in analysis.functions:
        if fn.name == name:
            return fn.id
    raise ValueError(f"Function '{name}' not found.")


def _scalar_capability() -> tuple[str, AiCapabilityResult]:
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    return target_id, cap


def _mutable_capability() -> tuple[str, AiCapabilityResult]:
    target_id = _fn_id(MUTABLE_SOURCE, "swap")
    cap = assess_ai_capability(MUTABLE_SOURCE, "function", target_id)
    return target_id, cap


# ---------------------------------------------------------------------------
# FakeClient helpers
# ---------------------------------------------------------------------------


class _FakeModels:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, *outcomes):
        self.models = _FakeModels(*outcomes)


def _object_capability() -> tuple[str, AiCapabilityResult]:
    from app.services.object_analysis import analyze_object_scenarios
    obj_analysis = analyze_object_scenarios(OBJECT_SOURCE)
    cls = obj_analysis.classes[0]
    cap = assess_ai_capability(OBJECT_SOURCE, "object", cls.id)
    return cls.id, cap


def _ok_scenario_plan(target_id: str):
    from app.schemas.ai_tests import (
        AiModelScenarioObject,
        AiModelScenarioPlan,
        AiModelScenarioStep,
        AiModelScenarioTest,
    )
    obj = AiModelScenarioObject(
        name="box",
        constructor_id="Box::Box(int)",
        arguments=["5"],
    )
    step = AiModelScenarioStep(
        step_type="observer",
        target_object_name="box",
        method_id="Box::get() const->int",
        arguments=[],
        expected_outcome="return_value",
        expected_return="5",
    )
    test = AiModelScenarioTest(
        name="get_returns_initial_value",
        category="normal",
        reason="Checks initial state is returned correctly.",
        objects=[obj],
        steps=[step],
    )
    plan = AiModelScenarioPlan(target_id=target_id, tests=[test], skipped_topics=[])
    return SimpleNamespace(
        parsed=plan,
        text=plan.model_dump_json(),
        prompt_feedback=None,
        candidates=[],
    )


def _ok_plan(target_id: str, tests: list | None = None):
    from app.schemas.ai_tests import AiModelFunctionTest, AiModelTestPlan
    plan = AiModelTestPlan(
        target_id=target_id,
        tests=tests or [
            AiModelFunctionTest(
                name="adds_two_positives",
                category="normal",
                reason="Basic positive addition.",
                arguments=["2", "3"],
                expected_outcome="return_value",
                expected_return="5",
            )
        ],
        skipped_topics=[],
    )
    return SimpleNamespace(
        parsed=plan,
        text=plan.model_dump_json(),
        prompt_feedback=None,
        candidates=[],
    )


def _text_only_response(data: dict):
    """Response with parsed=None and raw JSON text (exercises fallback path)."""
    return SimpleNamespace(
        parsed=None,
        text=json.dumps(data),
        prompt_feedback=None,
        candidates=[],
    )


def _blocked_response():
    class _BlockedFeedback:
        block_reason = "SAFETY"

    return SimpleNamespace(
        parsed=None,
        text="",
        prompt_feedback=_BlockedFeedback(),
        candidates=[],
    )


# ---------------------------------------------------------------------------
# Prompt content tests
# ---------------------------------------------------------------------------


def test_prompt_contains_signature_metadata_and_category_allowlist():
    target_id, cap = _scalar_capability()
    analysis = analyze_test_mode(SCALAR_SOURCE)
    fn_sig = next(fn for fn in analysis.functions if fn.id == target_id)
    from app.services.ai_test_generation import _compute_suggested_range_function
    rng = _compute_suggested_range_function(cap, fn_sig)

    prompt = build_function_prompt(
        "Write an add function.",
        SCALAR_SOURCE,
        target_id,
        cap,
        fn_sig,
        None,
        [],
        rng,
    )

    assert "add" in prompt
    assert target_id in prompt
    assert "int" in prompt
    # Category list must be present
    assert '"normal"' in prompt
    assert '"negative"' in prompt
    assert '"boundary"' in prompt


def test_prompt_labels_question_and_source_as_untrusted():
    target_id, cap = _scalar_capability()
    analysis = analyze_test_mode(SCALAR_SOURCE)
    fn_sig = next(fn for fn in analysis.functions if fn.id == target_id)
    from app.services.ai_test_generation import _compute_suggested_range_function
    rng = _compute_suggested_range_function(cap, fn_sig)

    prompt = build_function_prompt(
        "some question",
        SCALAR_SOURCE,
        target_id,
        cap,
        fn_sig,
        None,
        [],
        rng,
    )

    lower = prompt.lower()
    assert "untrusted" in lower


def test_prompt_embeds_suggested_count_range_per_target_kind():
    target_id, cap = _scalar_capability()
    analysis = analyze_test_mode(SCALAR_SOURCE)
    fn_sig = next(fn for fn in analysis.functions if fn.id == target_id)
    from app.services.ai_test_generation import _compute_suggested_range_function
    lo, hi = _compute_suggested_range_function(cap, fn_sig)

    prompt = build_function_prompt(
        "q",
        SCALAR_SOURCE,
        target_id,
        cap,
        fn_sig,
        None,
        [],
        (lo, hi),
    )

    assert str(lo) in prompt
    assert str(hi) in prompt


# ---------------------------------------------------------------------------
# Source context tests
# ---------------------------------------------------------------------------


def test_source_context_returns_whole_file_unchanged_under_limit():
    code = "int f() { return 1; }"
    assert select_source_context(code) == code


def test_source_context_raises_source_too_large_over_limit():
    code = "x" * (AI_SOURCE_CHAR_LIMIT + 1)
    with pytest.raises(AiTestServiceError) as exc_info:
        select_source_context(code)
    assert exc_info.value.code == "source_too_large"
    assert exc_info.value.status_code == 400


def test_source_context_performs_no_parsing():
    """select_source_context must never compile or parse — just measure length."""
    # A deliberately broken source must pass if within the char limit.
    bad_source = "THIS IS NOT C++ AT ALL !!@@##"
    assert select_source_context(bad_source) == bad_source


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------


def test_valid_structured_output_parses():
    target_id, cap = _scalar_capability()
    response = _ok_plan(target_id)
    client = _FakeClient(response)

    plan = generate_function_tests(
        SCALAR_SOURCE,
        "Write an add function.",
        target_id,
        cap,
        None,
        [],
        _settings(),
        client=client,
    )

    assert plan.target_id == target_id
    assert len(plan.tests) == 1
    assert len(client.models.calls) == 1


def test_malformed_json_raises_invalid_model_response():
    target_id, cap = _scalar_capability()
    bad_response = SimpleNamespace(
        parsed=None,
        text="THIS IS NOT JSON {{{",
        prompt_feedback=None,
        candidates=[],
    )
    client = _FakeClient(bad_response)

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_unknown_field_rejected_by_schema():
    target_id, cap = _scalar_capability()
    # Build a valid plan dict, then add an unknown field.
    plan_dict = {
        "target_id": target_id,
        "tests": [
            {
                "name": "t1",
                "category": "normal",
                "reason": "basic",
                "arguments": ["1", "2"],
                "expected_outcome": "return_value",
                "expected_return": "3",
                "unknown_field": "this should be rejected",
            }
        ],
        "skipped_topics": [],
    }
    client = _FakeClient(_text_only_response(plan_dict))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_wrong_target_id_rejects_response():
    target_id, cap = _scalar_capability()
    wrong_plan = {
        "target_id": "wrong(x,y)->int",
        "tests": [],
        "skipped_topics": [],
    }
    client = _FakeClient(_text_only_response(wrong_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_more_than_eight_tests_rejected_by_schema():
    target_id, cap = _scalar_capability()
    base_entry = {
        "category": "normal",
        "reason": "basic",
        "arguments": ["1", "2"],
        "expected_outcome": "return_value",
        "expected_return": "3",
    }
    tests = [dict(**base_entry, name=f"t{i}") for i in range(9)]
    bad_plan = {"target_id": target_id, "tests": tests, "skipped_topics": []}
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_invalid_category_rejected_by_schema():
    target_id, cap = _scalar_capability()
    bad_plan = {
        "target_id": target_id,
        "tests": [
            {
                "name": "t1",
                "category": "NOT_A_VALID_CATEGORY",
                "reason": "basic",
                "arguments": ["1", "2"],
                "expected_outcome": "return_value",
                "expected_return": "3",
            }
        ],
        "skipped_topics": [],
    }
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


# ---------------------------------------------------------------------------
# Error mapping tests
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_before_any_call():
    target_id, cap = _scalar_capability()
    no_key_settings = Settings("http://localhost:3000", None, "model", "test")
    # Do NOT provide client either.
    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], no_key_settings
        )
    assert exc_info.value.code == "generation_unavailable"
    assert exc_info.value.status_code == 503


def test_timeout_maps_to_generation_timeout():
    target_id, cap = _scalar_capability()

    class _TimeoutError(errors.APIError):
        def __init__(self):
            self.code = 408
            self.status = "DEADLINE_EXCEEDED"
            self.message = "timeout"
            self.details = []

    client = _FakeClient(_TimeoutError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "generation_timeout"


def test_rate_limit_maps_to_generation_rate_limited():
    target_id, cap = _scalar_capability()

    class _RateLimitError(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "rate limit"
            self.details = []

    client = _FakeClient(_RateLimitError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "generation_rate_limited"


# ---------------------------------------------------------------------------
# Repair call test
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AI-specific error message contract
# ---------------------------------------------------------------------------


def test_authentication_error_uses_ai_specific_message():
    """Auth failures must say 'Gemini' or 'AI test generation', never 'transcription service'."""
    target_id, cap = _scalar_capability()

    class _AuthError(errors.APIError):
        def __init__(self):
            self.code = 401
            self.status = "UNAUTHENTICATED"
            self.message = "api key not valid"
            self.details = []

    client = _FakeClient(_AuthError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    err = exc_info.value
    assert err.code == "generation_unavailable"
    assert "transcription" not in err.message.lower(), (
        f"Expected AI-specific message, got: {err.message!r}"
    )


def test_rate_limit_message_is_ai_specific():
    """Rate-limit messages must not mention 'transcription'."""
    target_id, cap = _scalar_capability()

    class _RateError(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "rate limited"
            self.details = []

    client = _FakeClient(_RateError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    err = exc_info.value
    assert err.code == "generation_rate_limited"
    assert "transcription" not in err.message.lower(), (
        f"Expected AI-specific message, got: {err.message!r}"
    )


def test_generic_api_error_does_not_mention_transcription():
    """Catch-all API errors (e.g. HTTP 400) must not say 'The transcription service'."""
    target_id, cap = _scalar_capability()

    class _BadSchemaError(errors.APIError):
        def __init__(self):
            self.code = 400
            self.status = "INVALID_ARGUMENT"
            self.message = "schema error"
            self.details = []

    client = _FakeClient(_BadSchemaError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    err = exc_info.value
    assert err.code == "generation_failed"
    assert "transcription" not in err.message.lower(), (
        f"Expected AI-specific message, got: {err.message!r}"
    )


def test_api_error_logs_safe_technical_cause_without_key(caplog):
    """Logger must emit error-level details but never expose the API key."""
    import logging

    target_id, cap = _scalar_capability()
    secret_key = "sk-supersecret-key-never-log-me"
    secure_settings = Settings("http://localhost:3000", secret_key, "model", "test")

    class _AuthError(errors.APIError):
        def __init__(self):
            self.code = 401
            self.status = "UNAUTHENTICATED"
            self.message = "api key not valid"
            self.details = []

    client = _FakeClient(_AuthError())

    with caplog.at_level(logging.ERROR, logger="app.services.ai_test_generation"):
        with pytest.raises(AiTestServiceError):
            generate_function_tests(
                SCALAR_SOURCE, "q", target_id, cap, None, [],
                secure_settings, client=client,
            )

    combined = " ".join(caplog.messages)
    assert combined, "Expected an error-level log entry from ai_test_generation"
    assert secret_key not in combined, "API key must not appear in logs"


def test_invalid_model_response_message_is_ai_specific():
    """Blocked responses must use AI-specific wording, not mention transcription."""
    target_id, cap = _scalar_capability()
    client = _FakeClient(_blocked_response())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    err = exc_info.value
    assert err.code == "generation_failed"
    assert "transcription" not in err.message.lower(), (
        f"Expected AI-specific message, got: {err.message!r}"
    )


def test_successful_generation_unaffected_by_error_mapping_change():
    """Valid model responses must still parse correctly after the error-mapping refactor."""
    target_id, cap = _scalar_capability()
    client = _FakeClient(_ok_plan(target_id))

    plan = generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
    )
    assert plan.target_id == target_id
    assert len(plan.tests) >= 1


# ---------------------------------------------------------------------------


def test_repair_prompt_contains_only_rejected_tests():
    """The repair prompt must include rejected test info and the 'ONLY' directive."""
    target_id, cap = _scalar_capability()
    rejected = [
        ("bad_test_1", "invalid_argument_value", "value out of range"),
        ("bad_test_2", "wrong_argument_count", "expected 2 got 1"),
    ]

    captured_prompts: list[str] = []

    class _CapturingModels:
        def generate_content(self, **kwargs):
            contents = kwargs.get("contents", [])
            for content in contents:
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        captured_prompts.append(part.text)
            # Return a valid plan so the call completes.
            return _ok_plan(target_id)

    class _CapturingClient:
        models = _CapturingModels()

    generate_function_tests(
        SCALAR_SOURCE,
        "Write an add function.",
        target_id,
        cap,
        None,
        [],
        _settings(),
        client=_CapturingClient(),
        rejected_tests=rejected,
    )

    assert captured_prompts, "No prompt was captured."
    full_prompt = " ".join(captured_prompts)

    # Must mention the rejected test names.
    assert "bad_test_1" in full_prompt
    assert "bad_test_2" in full_prompt
    # Must indicate the repair constraint.
    assert "ONLY" in full_prompt or "only" in full_prompt.lower()


# ---------------------------------------------------------------------------
# Gemini schema transport: response_json_schema (Task 3)
# ---------------------------------------------------------------------------


def test_function_generation_uses_response_json_schema():
    """_call_gemini must pass response_json_schema (dict), not response_schema."""
    target_id, cap = _scalar_capability()
    client = _FakeClient(_ok_plan(target_id))

    generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
    )

    config = client.models.calls[0]["config"]
    assert config.response_json_schema is not None, "response_json_schema must be set"
    assert config.response_schema is None, "legacy response_schema must be None"


def test_object_generation_uses_response_json_schema():
    """generate_object_tests must also pass response_json_schema, not response_schema."""
    from app.services.ai_test_generation import generate_object_tests

    target_id, cap = _object_capability()
    client = _FakeClient(_ok_scenario_plan(target_id))

    generate_object_tests(
        OBJECT_SOURCE, "q", target_id, cap, _settings(), client=client
    )

    config = client.models.calls[0]["config"]
    assert config.response_json_schema is not None
    assert config.response_schema is None


def test_repair_generation_uses_response_json_schema():
    """The repair path (rejected_tests provided) must still use response_json_schema."""
    target_id, cap = _scalar_capability()
    rejected = [("bad_test", "invalid_argument_value", "expected int, got string")]
    client = _FakeClient(_ok_plan(target_id))

    generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(),
        client=client, rejected_tests=rejected,
    )

    config = client.models.calls[0]["config"]
    assert config.response_json_schema is not None
    assert config.response_schema is None


def test_model_json_schema_retains_nested_properties_and_required_fields():
    """model_json_schema() must preserve additionalProperties, properties, and required
    at both the top level and inside nested $defs (the dict sent to the endpoint)."""
    from app.schemas.ai_tests import AiModelTestPlan

    schema = AiModelTestPlan.model_json_schema()

    assert "properties" in schema, "Top-level 'properties' must be present"
    assert "required" in schema, "Top-level 'required' must be present"
    assert "target_id" in schema["required"]
    assert "tests" in schema["required"]
    assert "additionalProperties" in schema
    assert schema["additionalProperties"] is False

    assert "$defs" in schema, "Nested schemas expected in $defs"
    fn_test = schema["$defs"].get("AiModelFunctionTest")
    assert fn_test is not None, "AiModelFunctionTest must appear in $defs"
    assert "properties" in fn_test
    assert "required" in fn_test
    assert "name" in fn_test["required"]
    assert "category" in fn_test["required"]
    assert fn_test.get("additionalProperties") is False


def test_strict_parsing_rejects_unknown_top_level_field():
    """An extra field at the plan root must raise invalid_model_response."""
    target_id, cap = _scalar_capability()
    bad_plan = {
        "target_id": target_id,
        "tests": [],
        "skipped_topics": [],
        "injected_top_level": "evil",
    }
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_strict_parsing_rejects_unknown_nested_test_field():
    """An extra field inside a test entry must raise invalid_model_response."""
    target_id, cap = _scalar_capability()
    bad_plan = {
        "target_id": target_id,
        "tests": [
            {
                "name": "t1",
                "category": "normal",
                "reason": "basic",
                "arguments": ["1", "2"],
                "expected_outcome": "return_value",
                "expected_return": "3",
                "injected_nested": "evil",
            }
        ],
        "skipped_topics": [],
    }
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_valid_function_output_parses_via_text_path():
    """A response with parsed=None must succeed via the text → model_validate_json path."""
    from app.schemas.ai_tests import AiModelFunctionTest, AiModelTestPlan

    target_id, cap = _scalar_capability()
    plan_obj = AiModelTestPlan(
        target_id=target_id,
        tests=[
            AiModelFunctionTest(
                name="via_text",
                category="normal",
                reason="Text-path parsing check.",
                arguments=["1", "2"],
                expected_outcome="return_value",
                expected_return="3",
            )
        ],
        skipped_topics=[],
    )
    response = SimpleNamespace(
        parsed=None,
        text=plan_obj.model_dump_json(),
        prompt_feedback=None,
        candidates=[],
    )
    client = _FakeClient(response)

    plan = generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
    )
    assert plan.target_id == target_id
    assert plan.tests[0].name == "via_text"


def test_valid_object_scenario_output_parses_via_text_path():
    """Object generation must parse valid JSON text through model_validate_json."""
    from app.services.ai_test_generation import generate_object_tests

    target_id, cap = _object_capability()
    response = _ok_scenario_plan(target_id)
    response.parsed = None  # force text path
    client = _FakeClient(response)

    plan = generate_object_tests(
        OBJECT_SOURCE, "q", target_id, cap, _settings(), client=client
    )
    assert plan.target_id == target_id
    assert len(plan.tests) == 1


def test_invalid_json_raises_invalid_model_response_via_text_path():
    """Malformed JSON in response.text must map to invalid_model_response."""
    target_id, cap = _scalar_capability()
    bad = SimpleNamespace(
        parsed=None,
        text="{INVALID JSON{{{{",
        prompt_feedback=None,
        candidates=[],
    )
    client = _FakeClient(bad)

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_api_error_mapping_unaffected_by_json_schema_transport_change():
    """API errors must still map correctly after switching to response_json_schema."""
    target_id, cap = _scalar_capability()

    class _QuotaError(errors.APIError):
        def __init__(self):
            self.code = 429
            self.status = "RESOURCE_EXHAUSTED"
            self.message = "quota exceeded"
            self.details = []

    client = _FakeClient(_QuotaError())

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    err = exc_info.value
    assert err.code == "generation_rate_limited"
    assert "transcription" not in err.message.lower()


# ---------------------------------------------------------------------------
# _wire_schema: transport-only maxItems removal (Task 4)
# ---------------------------------------------------------------------------


def test_wire_schema_removes_max_items_recursively_function():
    """_wire_schema(AiModelTestPlan) must contain no 'maxItems' key at any depth."""
    import json
    from app.schemas.ai_tests import AiModelTestPlan
    from app.services.ai_test_generation import _wire_schema

    result = _wire_schema(AiModelTestPlan)
    blob = json.dumps(result)
    assert "maxItems" not in blob, (
        "maxItems must not appear anywhere in the wire schema"
    )


def test_wire_schema_removes_max_items_recursively_object():
    """_wire_schema(AiModelScenarioPlan) must contain no 'maxItems' at any depth,
    including inside nested $defs (objects, steps)."""
    import json
    from app.schemas.ai_tests import AiModelScenarioPlan
    from app.services.ai_test_generation import _wire_schema

    result = _wire_schema(AiModelScenarioPlan)
    blob = json.dumps(result)
    assert "maxItems" not in blob


def test_wire_schema_preserves_additional_properties_false():
    """additionalProperties: false must survive at top level and inside all $defs."""
    from app.schemas.ai_tests import AiModelTestPlan
    from app.services.ai_test_generation import _wire_schema

    result = _wire_schema(AiModelTestPlan)
    assert result.get("additionalProperties") is False, (
        "Top-level additionalProperties must be False"
    )
    for def_name, def_schema in result.get("$defs", {}).items():
        assert def_schema.get("additionalProperties") is False, (
            f"$defs.{def_name} must retain additionalProperties: false"
        )


def test_wire_schema_preserves_min_items_and_other_keywords():
    """minItems, minLength, maxLength, enum, anyOf, default, $ref, $defs, required
    must all survive the maxItems-only stripping."""
    import json
    from app.schemas.ai_tests import AiModelTestPlan, AiModelScenarioPlan
    from app.services.ai_test_generation import _wire_schema

    for M in (AiModelTestPlan, AiModelScenarioPlan):
        blob = json.dumps(_wire_schema(M))
        for kw in ("minItems", "minLength", "maxLength", "enum", "anyOf",
                   "default", "$ref", "$defs", "required"):
            assert kw in blob, f"{M.__name__} wire schema must retain '{kw}'"


def test_wire_schema_does_not_mutate_pydantic_model():
    """Calling _wire_schema must not alter the Pydantic model's own JSON schema."""
    import json
    from app.schemas.ai_tests import AiModelTestPlan
    from app.services.ai_test_generation import _wire_schema

    original_before = json.dumps(AiModelTestPlan.model_json_schema(), sort_keys=True)
    _wire_schema(AiModelTestPlan)
    _wire_schema(AiModelTestPlan)
    original_after = json.dumps(AiModelTestPlan.model_json_schema(), sort_keys=True)
    assert original_before == original_after, (
        "model_json_schema() must be identical before and after _wire_schema calls"
    )
    # Confirm original still has maxItems
    assert "maxItems" in original_after


def test_wire_schema_preserves_property_names():
    """Property names (even one coincidentally named 'maxItems') must not be removed."""
    from app.services.ai_test_generation import _wire_schema
    from pydantic import BaseModel, ConfigDict, Field

    class _Probe(BaseModel):
        model_config = ConfigDict(extra="forbid")
        maxItems: int = 0
        items: list[str] = Field(default_factory=list, max_length=5)

    result = _wire_schema(_Probe)
    props = result.get("properties", {})
    assert "maxItems" in props, (
        "A property NAMED 'maxItems' must not be removed from the 'properties' map"
    )
    assert "items" in props


def test_function_call_sends_wire_schema_without_max_items():
    """generate_function_tests must pass a schema with no maxItems to the SDK."""
    import json
    target_id, cap = _scalar_capability()
    client = _FakeClient(_ok_plan(target_id))

    generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
    )

    sent_schema = client.models.calls[0]["config"].response_json_schema
    assert sent_schema is not None
    assert "maxItems" not in json.dumps(sent_schema)
    assert client.models.calls[0]["config"].response_schema is None


def test_object_call_sends_wire_schema_without_max_items():
    """generate_object_tests must pass a schema with no maxItems to the SDK."""
    import json
    from app.services.ai_test_generation import generate_object_tests

    target_id, cap = _object_capability()
    client = _FakeClient(_ok_scenario_plan(target_id))

    generate_object_tests(
        OBJECT_SOURCE, "q", target_id, cap, _settings(), client=client
    )

    sent_schema = client.models.calls[0]["config"].response_json_schema
    assert sent_schema is not None
    assert "maxItems" not in json.dumps(sent_schema)
    assert client.models.calls[0]["config"].response_schema is None


def test_repair_call_sends_wire_schema_without_max_items():
    """Repair generation (rejected_tests supplied) must also use the wire schema."""
    import json
    target_id, cap = _scalar_capability()
    rejected = [("bad_test", "invalid_argument_value", "out of range")]
    client = _FakeClient(_ok_plan(target_id))

    generate_function_tests(
        SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(),
        client=client, rejected_tests=rejected,
    )

    sent_schema = client.models.calls[0]["config"].response_json_schema
    assert "maxItems" not in json.dumps(sent_schema)


def test_more_than_eight_tests_still_rejected_locally_after_wire_schema_change():
    """maxItems removed from the transport schema must not weaken local validation.
    A 9-test payload must still raise invalid_model_response."""
    target_id, cap = _scalar_capability()
    base_entry = {
        "category": "normal",
        "reason": "basic",
        "arguments": ["1", "2"],
        "expected_outcome": "return_value",
        "expected_return": "3",
    }
    too_many = [dict(**base_entry, name=f"t{i}") for i in range(9)]
    bad_plan = {"target_id": target_id, "tests": too_many, "skipped_topics": []}
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"


def test_unknown_field_still_rejected_locally_after_wire_schema_change():
    """extra='forbid' must still reject unknown nested fields after the wire change."""
    target_id, cap = _scalar_capability()
    bad_plan = {
        "target_id": target_id,
        "tests": [
            {
                "name": "t1",
                "category": "normal",
                "reason": "basic",
                "arguments": ["1", "2"],
                "expected_outcome": "return_value",
                "expected_return": "3",
                "injected_unknown": "evil",
            }
        ],
        "skipped_topics": [],
    }
    client = _FakeClient(_text_only_response(bad_plan))

    with pytest.raises(AiTestServiceError) as exc_info:
        generate_function_tests(
            SCALAR_SOURCE, "q", target_id, cap, None, [], _settings(), client=client
        )
    assert exc_info.value.code == "invalid_model_response"
