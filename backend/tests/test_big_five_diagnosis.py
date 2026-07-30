from app.schemas.test_execution import (
    ObjectScenarioStep,
    ObjectScenarioStepResult,
    ObjectScenarioTestCase,
    ObjectScenarioTestResult,
)
from app.services.big_five_diagnosis import diagnose_big_five


def _step_result(
    index: int,
    step_type: str,
    *,
    passed: bool = True,
    status: str = "completed",
) -> ObjectScenarioStepResult:
    return ObjectScenarioStepResult(
        index=index,
        step_type=step_type,
        method="operation",
        status=status,
        passed=passed,
    )


def _test_case(steps: list[dict]) -> ObjectScenarioTestCase:
    return ObjectScenarioTestCase(
        name="Scenario",
        class_id="class:Number",
        constructor_id="constructor:Number(int)",
        constructor_arguments=["5"],
        steps=[ObjectScenarioStep(**step) for step in steps],
    )


def _result(
    step_results: list[ObjectScenarioStepResult],
    *,
    passed: bool = False,
    memory_status: str = "not_run",
    memory_summary: str | None = None,
    leak_status: str = "not_run",
    destruction_failed: bool = False,
) -> ObjectScenarioTestResult:
    return ObjectScenarioTestResult(
        name="Scenario",
        passed=passed,
        class_name="Number",
        constructor="Number::Number(int)",
        constructor_arguments=["5"],
        constructor_completed=True,
        destruction_failed=destruction_failed,
        steps=step_results,
        stderr="",
        exit_code=0,
        timed_out=False,
        output_limited=False,
        match_type="exact" if passed else "mismatch",
        memory_check_enabled=memory_status != "not_run",
        memory_status=memory_status,
        memory_summary=memory_summary,
        leak_status=leak_status,
    )


def test_observer_confirmed_shallow_copy_gets_confirmed_diagnosis():
    test = _test_case(
        [
            {
                "step_type": "copy_construct",
                "special_member_id": "copy",
                "source_object_id": "original",
                "target_object_id": "original",
                "result_object_id": "copy",
                "result_name": "copy",
            },
            {
                "step_type": "method",
                "method_id": "set",
                "target_object_id": "copy",
            },
            {
                "step_type": "observer",
                "method_id": "get",
                "target_object_id": "original",
                "expected_return": "5",
            },
        ]
    )
    diagnosis = diagnose_big_five(
        "class Number {};",
        test,
        _result(
            [
                _step_result(0, "copy_construct"),
                _step_result(1, "method"),
                _step_result(2, "observer", passed=False),
            ]
        ),
    )
    assert diagnosis is not None
    assert diagnosis.confidence == "confirmed"
    assert diagnosis.related_operation == "copy_constructor"


def test_correct_deep_copy_produces_no_diagnosis():
    test = _test_case(
        [
            {
                "step_type": "copy_construct",
                "special_member_id": "copy",
                "source_object_id": "original",
                "target_object_id": "original",
                "result_object_id": "copy",
                "result_name": "copy",
            },
            {
                "step_type": "observer",
                "method_id": "get",
                "target_object_id": "original",
                "expected_return": "5",
            },
        ]
    )
    assert (
        diagnose_big_five(
            "class Number {};",
            test,
            _result(
                [
                    _step_result(0, "copy_construct"),
                    _step_result(1, "observer"),
                ],
                passed=True,
            ),
        )
        is None
    )


def test_self_assignment_crash_produces_confirmed_diagnosis():
    test = _test_case(
        [
            {
                "step_type": "self_assign",
                "special_member_id": "assign",
                "source_object_id": "original",
                "target_object_id": "original",
            }
        ]
    )
    diagnosis = diagnose_big_five(
        "class Number {};",
        test,
        _result(
            [_step_result(0, "self_assign", passed=False)],
            memory_status="use_after_free",
        ),
    )
    assert diagnosis is not None
    assert diagnosis.related_operation == "self_assignment"


def test_correct_self_assignment_produces_no_diagnosis():
    test = _test_case(
        [
            {
                "step_type": "self_assign",
                "special_member_id": "assign",
                "source_object_id": "original",
                "target_object_id": "original",
            }
        ]
    )
    assert (
        diagnose_big_five(
            "class Number {};",
            test,
            _result([_step_result(0, "self_assign")], passed=True),
        )
        is None
    )


def test_double_free_after_move_construction_identifies_ownership():
    test = _test_case(
        [
            {
                "step_type": "move_construct",
                "special_member_id": "move",
                "source_object_id": "original",
                "target_object_id": "original",
                "result_object_id": "moved",
                "result_name": "moved",
            }
        ]
    )
    diagnosis = diagnose_big_five(
        "class Number {};",
        test,
        _result(
            [_step_result(0, "move_construct")],
            memory_status="double_free",
            destruction_failed=True,
        ),
    )
    assert diagnosis is not None
    assert diagnosis.confidence == "confirmed"
    assert diagnosis.related_operation == "move_constructor"


RAW_POINTER_MOVE = """class Number {
    int* value;
public:
    Number(int input): value{new int{input}} {}
    Number& operator=(Number&& other) noexcept {
        value = other.value;
        other.value = nullptr;
        return *this;
    }
    ~Number() { delete value; }
};"""


def _move_assignment_test() -> ObjectScenarioTestCase:
    return _test_case(
        [
            {
                "step_type": "move_assign",
                "special_member_id": "move-assign",
                "source_object_id": "source",
                "target_object_id": "target",
            }
        ]
    )


def test_confirmed_leak_during_move_assignment_is_confirmed():
    diagnosis = diagnose_big_five(
        RAW_POINTER_MOVE,
        _move_assignment_test(),
        _result(
            [_step_result(0, "move_assign")],
            memory_status="leak",
            memory_summary="Memory leak detected.",
            leak_status="failed",
        ),
    )
    assert diagnosis is not None
    assert diagnosis.confidence == "confirmed"


def test_unavailable_leak_check_plus_narrow_pattern_is_likely():
    diagnosis = diagnose_big_five(
        RAW_POINTER_MOVE,
        _move_assignment_test(),
        _result(
            [_step_result(0, "move_assign")],
            memory_status="partial",
            leak_status="unavailable",
        ),
    )
    assert diagnosis is not None
    assert diagnosis.confidence == "likely"
    assert diagnosis.suspicious_ranges[0].start_line == 6
    assert diagnosis.suspicious_ranges[0].end_line == 7


def test_unique_ptr_and_swap_move_assignment_do_not_warn():
    unique_source = """#include <memory>
class Number {
    std::unique_ptr<int> value;
public:
    Number& operator=(Number&& other) noexcept {
        value = std::move(other.value);
        return *this;
    }
};"""
    swap_source = RAW_POINTER_MOVE.replace(
        "value = other.value;\n        other.value = nullptr;",
        "std::swap(value, other.value);",
    )
    result = _result(
        [_step_result(0, "move_assign")],
        memory_status="partial",
        leak_status="unavailable",
    )
    assert diagnose_big_five(unique_source, _move_assignment_test(), result) is None
    assert diagnose_big_five(swap_source, _move_assignment_test(), result) is None


def test_helper_cleanup_and_non_owning_pointer_do_not_warn():
    helper_source = RAW_POINTER_MOVE.replace(
        "value = other.value;",
        "cleanup();\n        value = other.value;",
    )
    non_owning = RAW_POINTER_MOVE.replace(
        "Number(int input): value{new int{input}} {}",
        "Number(int* input): value{input} {}",
    ).replace("~Number() { delete value; }", "~Number() {}")
    result = _result(
        [_step_result(0, "move_assign")],
        memory_status="partial",
        leak_status="unavailable",
    )
    assert diagnose_big_five(helper_source, _move_assignment_test(), result) is None
    assert diagnose_big_five(non_owning, _move_assignment_test(), result) is None


def test_unrelated_runtime_error_has_no_big_five_diagnosis():
    test = _test_case(
        [
            {
                "step_type": "method",
                "method_id": "run",
                "target_object_id": "original",
            }
        ]
    )
    assert (
        diagnose_big_five(
            "class Number {};",
            test,
            _result(
                [_step_result(0, "method", passed=False)],
                memory_status="runtime_error",
            ),
        )
        is None
    )


def test_diagnosis_does_not_change_pass_fail_and_is_not_stale():
    test = _move_assignment_test()
    result = _result(
        [_step_result(0, "move_assign")],
        passed=False,
        memory_status="partial",
        leak_status="unavailable",
    )
    diagnosis = diagnose_big_five(RAW_POINTER_MOVE, test, result)
    assert diagnosis is not None
    assert result.passed is False
    assert (
        diagnose_big_five(
            "class Number { public: Number& operator=(Number&&) = default; };",
            test,
            result,
        )
        is None
    )
