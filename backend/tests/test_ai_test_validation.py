"""Tests for ai_test_validation.py: argument normalization, per-test
validation rules, duplicate prevention, and object-scenario validation."""
import pytest

from app.schemas.ai_tests import (
    AiModelFunctionTest,
    AiModelMutation,
    AiModelScenarioObject,
    AiModelScenarioStep,
    AiModelScenarioTest,
)
from app.services.ai_test_capability import assess_ai_capability
from app.services.ai_test_validation import (
    AiTestRejection,
    ValidatedAiTest,
    validate_and_deduplicate_function_tests,
    validate_and_deduplicate_object_tests,
    validate_function_test,
    validate_object_test,
)
from app.services.function_analysis import analyze_test_mode
from app.services.object_analysis import analyze_object_scenarios

# ---------------------------------------------------------------------------
# Source fixtures
# ---------------------------------------------------------------------------

SCALAR_SOURCE = "int add(int a, int b) { return a + b; }"
STRING_BOOL_SOURCE = "bool startsWith(std::string s, char c) { return s[0] == c; }"
CONTAINER_SOURCE = "int sumVec(std::vector<int> v) { int s=0; for(auto x:v) s+=x; return s; }"
VOID_SOURCE = "void doNothing(int x) {}"
MUTABLE_REF_SOURCE = "void swap(int& a, int& b) { int t = a; a = b; b = t; }"
ITERATOR_SOURCE = (
    "int sumRange(std::vector<int>::iterator first, "
    "std::vector<int>::iterator last) { return 0; }"
)
OBJECT_SOURCE = """
class Counter {
public:
    Counter() : count_(0) {}
    Counter(int start) : count_(start) {}
    void increment() { count_++; }
    int get() const { return count_; }
private:
    int count_;
};
"""


def _fn_id(source: str, name: str) -> str:
    analysis = analyze_test_mode(source)
    for fn in analysis.functions:
        if fn.name == name:
            return fn.id
    raise ValueError(f"Function '{name}' not found.")


def _fn_sig(source: str, name: str):
    analysis = analyze_test_mode(source)
    for fn in analysis.functions:
        if fn.name == name:
            return fn
    raise ValueError(f"Function '{name}' not found.")


def _make_test(
    name: str = "t1",
    category: str = "normal",
    reason: str = "basic test",
    arguments: list[str] | None = None,
    expected_outcome: str = "return_value",
    expected_return: str | None = "3",
    expected_mutations: list | None = None,
    expected_exception_type=None,
) -> AiModelFunctionTest:
    return AiModelFunctionTest(
        name=name,
        category=category,
        reason=reason,
        arguments=arguments if arguments is not None else ["1", "2"],
        expected_outcome=expected_outcome,
        expected_return=expected_return,
        expected_mutations=expected_mutations or [],
        expected_exception_type=expected_exception_type,
    )


# ---------------------------------------------------------------------------
# Function test — argument normalization
# ---------------------------------------------------------------------------


def test_scalar_arguments_normalize_to_function_test_case():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    ai_test = _make_test(arguments=["5", "7"], expected_return="12")
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, ValidatedAiTest)
    assert result.test_case.arguments == ["5", "7"]
    assert result.test_case.expected_return == "12"


def test_string_and_boolean_values_normalize():
    target_id = _fn_id(STRING_BOOL_SOURCE, "startsWith")
    cap = assess_ai_capability(STRING_BOOL_SOURCE, "function", target_id)
    sig = _fn_sig(STRING_BOOL_SOURCE, "startsWith")

    ai_test = AiModelFunctionTest(
        name="starts_with_h",
        category="normal",
        reason="basic string test",
        arguments=["hello", "h"],
        expected_outcome="return_value",
        expected_return="true",
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, ValidatedAiTest)
    # 'h' is a single char — should come through as a valid char literal.
    assert len(result.test_case.arguments) == 2


def test_container_values_normalize():
    target_id = _fn_id(CONTAINER_SOURCE, "sumVec")
    cap = assess_ai_capability(CONTAINER_SOURCE, "function", target_id)
    sig = _fn_sig(CONTAINER_SOURCE, "sumVec")

    ai_test = AiModelFunctionTest(
        name="sum_three",
        category="normal",
        reason="simple sum",
        arguments=["[1, 2, 3]"],
        expected_outcome="return_value",
        expected_return="6",
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, ValidatedAiTest)
    # Arguments must survive normalization.
    assert result.test_case.arguments[0] is not None


def test_iterator_head_and_tail_payloads_normalize():
    target_id = _fn_id(ITERATOR_SOURCE, "sumRange")
    cap = assess_ai_capability(ITERATOR_SOURCE, "function", target_id)
    sig = _fn_sig(ITERATOR_SOURCE, "sumRange")

    # Head: carries container and a position; tail: position only.
    head_raw = '{"container": [1, 2, 3], "position": 0}'
    tail_raw = '{"position": 3}'

    ai_test = AiModelFunctionTest(
        name="full_range",
        category="full_range",
        reason="iterate entire container",
        arguments=[head_raw, tail_raw],
        expected_outcome="return_value",
        expected_return="6",
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, ValidatedAiTest)
    # Raw JSON strings stored as-is for re-parsing by test_execution.py.
    assert result.test_case.arguments[0] == head_raw
    assert result.test_case.arguments[1] == tail_raw


# ---------------------------------------------------------------------------
# Function test — mutation validation
# ---------------------------------------------------------------------------


def test_mutation_expectation_for_mutable_reference_accepted():
    target_id = _fn_id(MUTABLE_REF_SOURCE, "swap")
    cap = assess_ai_capability(MUTABLE_REF_SOURCE, "function", target_id)
    sig = _fn_sig(MUTABLE_REF_SOURCE, "swap")

    ai_test = AiModelFunctionTest(
        name="swap_3_5",
        category="mutation",
        reason="verifies swap mutation",
        arguments=["3", "5"],
        expected_outcome="return_void",
        expected_return=None,
        expected_mutations=[
            AiModelMutation(parameter_name="a", expected_final_value="5"),
            AiModelMutation(parameter_name="b", expected_final_value="3"),
        ],
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, ValidatedAiTest)
    assert result.test_case.expected_mutations is not None
    assert len(result.test_case.expected_mutations) == 2


def test_mutation_for_non_mutable_parameter_rejected():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    ai_test = _make_test(
        arguments=["1", "2"],
        expected_mutations=[
            AiModelMutation(parameter_name="a", expected_final_value="99"),
        ],
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "invalid_mutation_target"


# ---------------------------------------------------------------------------
# Function test — rejection cases
# ---------------------------------------------------------------------------


def test_wrong_argument_count_rejected():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    # add() expects 2 args; supply 1.
    ai_test = _make_test(arguments=["5"])
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "wrong_argument_count"


def test_invalid_argument_literal_rejected_via_existing_helpers():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    # "abc" is not a valid int literal.
    ai_test = _make_test(arguments=["abc", "2"])
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "invalid_argument_value"


def test_return_expectation_on_void_function_rejected():
    target_id = _fn_id(VOID_SOURCE, "doNothing")
    cap = assess_ai_capability(VOID_SOURCE, "function", target_id)
    sig = _fn_sig(VOID_SOURCE, "doNothing")

    ai_test = AiModelFunctionTest(
        name="expects_return",
        category="normal",
        reason="wrong",
        arguments=["1"],
        expected_outcome="return_value",
        expected_return="42",
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "return_expectation_on_void"


def test_throws_with_expected_return_rejected():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    ai_test = AiModelFunctionTest(
        name="throws_and_returns",
        category="exception",
        reason="bad",
        arguments=["1", "2"],
        expected_outcome="throws",
        expected_return="3",  # contradicts throws
        expected_exception_type="std::runtime_error",
    )
    result = validate_function_test(ai_test, cap, sig)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "contradictory_expectations"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_exact_duplicate_rejected():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    tests = [
        _make_test(name="same_name", arguments=["1", "2"], expected_return="3"),
        _make_test(name="same_name", arguments=["1", "2"], expected_return="3"),
    ]
    accepted, rejected = validate_and_deduplicate_function_tests(tests, cap, sig)

    assert len(accepted) == 0
    assert len(rejected) == 2
    assert all(r.reason_code == "contradictory_duplicate" for r in rejected)


def test_renamed_duplicate_rejected():
    """Same inputs/outcome, different names — second is rejected as behavioral duplicate."""
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    tests = [
        _make_test(name="first_version", arguments=["1", "2"], expected_return="3"),
        _make_test(name="second_version", arguments=["1", "2"], expected_return="3"),
    ]
    accepted, rejected = validate_and_deduplicate_function_tests(tests, cap, sig)

    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0].reason_code == "behavioral_duplicate"


def test_contradictory_duplicate_rejects_both():
    """Same name but different expected values — both instances rejected."""
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    tests = [
        _make_test(name="same_name", arguments=["1", "2"], expected_return="3"),
        _make_test(name="same_name", arguments=["10", "20"], expected_return="30"),
    ]
    accepted, rejected = validate_and_deduplicate_function_tests(tests, cap, sig)

    assert len(accepted) == 0
    assert len(rejected) == 2
    assert all(r.reason_code == "contradictory_duplicate" for r in rejected)


def test_distinct_boundary_tests_in_same_category_kept():
    """Different arguments in the same category must both be accepted."""
    target_id = _fn_id(SCALAR_SOURCE, "add")
    cap = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    sig = _fn_sig(SCALAR_SOURCE, "add")

    tests = [
        _make_test(
            name="boundary_low",
            category="boundary",
            arguments=["0", "1"],
            expected_return="1",
        ),
        _make_test(
            name="boundary_high",
            category="boundary",
            arguments=["100", "200"],
            expected_return="300",
        ),
    ]
    accepted, rejected = validate_and_deduplicate_function_tests(tests, cap, sig)

    assert len(accepted) == 2
    assert len(rejected) == 0


# ---------------------------------------------------------------------------
# Object-scenario validation
# ---------------------------------------------------------------------------


def _counter_class():
    obj_analysis = analyze_object_scenarios(OBJECT_SOURCE)
    return next(cls for cls in obj_analysis.classes if cls.name == "Counter")


def _counter_cap():
    return assess_ai_capability(OBJECT_SOURCE, "object", "Counter")


def _get_counter_ctor_id(with_args: bool = False) -> str:
    obj_class = _counter_class()
    for ctor in obj_class.constructors:
        has_params = len(ctor.parameters) > 0
        if has_params == with_args:
            return ctor.id
    raise ValueError("Required Counter constructor not found.")


def _get_method_id(method_name: str) -> str:
    obj_class = _counter_class()
    for m in obj_class.methods:
        if m.name == method_name:
            return m.id
    raise ValueError(f"Method '{method_name}' not found.")


def test_object_scenario_normalizes_with_generated_object_ids():
    cap = _counter_cap()
    obj_class = _counter_class()
    ctor_id = _get_counter_ctor_id(with_args=False)
    inc_id = _get_method_id("increment")
    get_id = _get_method_id("get")

    ai_test = AiModelScenarioTest(
        name="increment_once",
        category="object_state",
        reason="basic increment",
        objects=[
            AiModelScenarioObject(
                name="c1",
                constructor_id=ctor_id,
                arguments=[],
            )
        ],
        steps=[
            AiModelScenarioStep(
                step_type="method",
                target_object_name="c1",
                method_id=inc_id,
                arguments=[],
                expected_outcome="return_void",
            ),
            AiModelScenarioStep(
                step_type="observer",
                target_object_name="c1",
                method_id=get_id,
                arguments=[],
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
    )

    result = validate_object_test(ai_test, cap, obj_class)

    assert isinstance(result, ValidatedAiTest)
    tc = result.test_case
    assert tc.objects is not None
    assert len(tc.objects) == 1
    assert tc.objects[0].object_id == "c1"
    assert len(tc.steps) == 2


def test_object_step_referencing_unknown_object_rejected():
    cap = _counter_cap()
    obj_class = _counter_class()
    ctor_id = _get_counter_ctor_id(with_args=False)
    inc_id = _get_method_id("increment")

    ai_test = AiModelScenarioTest(
        name="bad_step",
        category="object_state",
        reason="references undeclared object",
        objects=[
            AiModelScenarioObject(
                name="c1",
                constructor_id=ctor_id,
                arguments=[],
            )
        ],
        steps=[
            AiModelScenarioStep(
                step_type="method",
                target_object_name="nonexistent",  # not declared above
                method_id=inc_id,
                arguments=[],
                expected_outcome="return_void",
            )
        ],
    )

    result = validate_object_test(ai_test, cap, obj_class)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "unknown_object_reference"


def test_object_method_id_outside_allowlist_rejected():
    cap = _counter_cap()
    obj_class = _counter_class()
    ctor_id = _get_counter_ctor_id(with_args=False)

    ai_test = AiModelScenarioTest(
        name="bad_method",
        category="object_state",
        reason="method not in capability list",
        objects=[
            AiModelScenarioObject(
                name="c1",
                constructor_id=ctor_id,
                arguments=[],
            )
        ],
        steps=[
            AiModelScenarioStep(
                step_type="method",
                target_object_name="c1",
                method_id="Counter::nonexistentMethod()->void",
                arguments=[],
                expected_outcome="return_void",
            )
        ],
    )

    result = validate_object_test(ai_test, cap, obj_class)

    assert isinstance(result, AiTestRejection)
    assert result.reason_code == "unsupported_method"
