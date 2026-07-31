import shutil
import time

import pytest
from pydantic import ValidationError

from app.schemas.test_execution import (
    FunctionRunTestsRequest,
    FunctionTestCase,
    ObjectScenarioRunTestsRequest,
)
from app.services.function_analysis import analyze_test_mode
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request
from app.services import test_execution


pytestmark = pytest.mark.skipif(
    shutil.which("g++") is None, reason="g++ is not installed"
)

DIVIDE_SOURCE = """
#include <stdexcept>
int divide(int a, int b) {
    if (b == 0) throw std::invalid_argument("division by zero");
    return a / b;
}
"""


def function_request(
    *,
    arguments=("10", "0"),
    outcome="throws",
    exception_type="std::invalid_argument",
    message_rule="ignore",
    message=None,
    expected_return=None,
    source=DIVIDE_SOURCE,
    run_memory_checks=False,
):
    function = analyze_test_mode(source).functions[0]
    return FunctionRunTestsRequest(
        mode="function",
        code=source,
        language="cpp",
        target_function=function.id,
        run_memory_checks=run_memory_checks,
        tests=[
            {
                "name": "Exception test",
                "arguments": list(arguments),
                "expected_outcome": outcome,
                "expected_exception_type": (
                    exception_type if outcome == "throws" else None
                ),
                "exception_message_rule": message_rule,
                "expected_exception_message": message,
                "expected_return": expected_return,
            }
        ],
    )


def test_expected_invalid_argument_passes():
    result = run_test_request(function_request())
    exception = result.tests[0].exception_result
    assert result.success is True
    assert exception.actual_outcome == "threw_standard"
    assert exception.actual_exception_type == "std::invalid_argument"
    assert exception.expectation_passed is True


def test_expected_runtime_error_without_memory_checks_passes():
    source = """
    #include <stdexcept>
    int fail() { throw std::runtime_error("failed"); }
    """
    result = run_test_request(
        function_request(
            source=source,
            arguments=(),
            exception_type="std::runtime_error",
        )
    )
    assert result.success is True
    assert result.tests[0].timed_out is False


def test_wrong_exception_type_fails_exact_matching():
    result = run_test_request(
        function_request(exception_type="std::runtime_error")
    )
    exception = result.tests[0].exception_result
    assert result.success is False
    assert exception.type_matched is False
    assert exception.actual_exception_type == "std::invalid_argument"


@pytest.mark.parametrize(
    ("rule", "message", "passed"),
    [
        ("exact", "division by zero", True),
        ("exact", "cannot divide", False),
        ("contains", "by zero", True),
        ("contains", "cannot", False),
        ("ignore", None, True),
    ],
)
def test_exception_message_rules(rule, message, passed):
    result = run_test_request(
        function_request(message_rule=rule, message=message)
    )
    assert result.tests[0].exception_result.message_matched is passed
    assert result.success is passed


def test_expected_exception_but_returned_fails():
    result = run_test_request(function_request(arguments=("10", "2")))
    exception = result.tests[0].exception_result
    assert result.success is False
    assert exception.actual_outcome == "returned"


def test_expected_return_but_standard_exception_is_unexpected():
    result = run_test_request(
        function_request(
            outcome="return_value",
            exception_type=None,
            expected_return="0",
        )
    )
    exception = result.tests[0].exception_result
    assert result.success is False
    assert exception.actual_outcome == "threw_standard"
    assert exception.actual_exception_type == "std::invalid_argument"


@pytest.mark.parametrize("throw_expression", ["5", '"error"'])
def test_non_standard_exceptions_are_distinct(throw_expression):
    source = f"int fail() {{ throw {throw_expression}; }}"
    result = run_test_request(
        function_request(
            source=source,
            arguments=(),
            exception_type="any_std_exception",
        )
    )
    exception = result.tests[0].exception_result
    assert result.success is False
    assert exception.actual_outcome == "threw_non_standard"
    assert exception.type_matched is False


def test_any_std_exception_matches_allowlisted_standard_exception():
    result = run_test_request(
        function_request(exception_type="any_std_exception")
    )
    assert result.success is True


def test_unsupported_type_and_empty_messages_are_rejected():
    with pytest.raises(ValidationError):
        FunctionTestCase(
            name="Bad type",
            arguments=[],
            expected_outcome="throws",
            expected_exception_type="CustomError",
        )
    for rule in ("exact", "contains"):
        with pytest.raises(ValidationError):
            FunctionTestCase(
                name="Empty message",
                arguments=[],
                expected_outcome="throws",
                expected_exception_type="std::runtime_error",
                exception_message_rule=rule,
                expected_exception_message="",
            )


def test_legacy_function_payload_keeps_return_behavior():
    test = FunctionTestCase(
        name="Legacy",
        arguments=["2", "1"],
        expected_return="2",
    )
    assert test.expected_outcome == "return_value"


def test_runtime_crash_remains_distinct_from_a_catchable_exception():
    source = "int fail() { int* value = nullptr; return *value; }"
    result = run_test_request(
        function_request(source=source, arguments=())
    )
    assert result.success is False
    assert result.tests[0].exception_result.actual_outcome == "crashed"


def test_runtime_timeout_remains_distinct_from_an_exception(monkeypatch):
    monkeypatch.setattr(test_execution, "TEST_TIMEOUT_SECONDS", 0.05)
    source = "int wait_forever() { while (true) {} }"
    result = run_test_request(
        function_request(source=source, arguments=())
    )
    assert result.success is False
    assert result.tests[0].exception_result.actual_outcome == "timed_out"


def test_completed_exception_result_is_not_overwritten_by_exit_timeout(
    monkeypatch,
):
    source = """
    #include <chrono>
    #include <stdexcept>
    #include <thread>
    struct SlowExit {
        ~SlowExit() {
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
        }
    } slow_exit;
    int fail() { throw std::invalid_argument("finished"); }
    """
    monkeypatch.setattr(test_execution, "TEST_TIMEOUT_SECONDS", 0.05)
    started = time.monotonic()
    result = run_test_request(
        function_request(source=source, arguments=())
    )
    elapsed = time.monotonic() - started
    assert elapsed < 2
    assert result.success is True
    assert result.tests[0].timed_out is False
    assert result.tests[0].exception_result.actual_outcome == "threw_standard"


def test_exception_harness_flushes_closes_and_exits_catch_branch():
    function = analyze_test_mode(DIVIDE_SOURCE).functions[0]
    arguments = [
        [
            test_execution.HarnessArgument(expression="1"),
            test_execution.HarnessArgument(expression="0"),
        ]
    ]
    harness = test_execution._build_function_harness(
        DIVIDE_SOURCE,
        function,
        arguments,
        (),
    )
    assert "output.flush();" in harness
    assert "output.close();" in harness
    assert '\\"process_completed\\":true' in harness
    assert "return 0; }" in harness


def test_actual_stderr_does_not_prevent_exception_result_parsing():
    source = """
    #include <iostream>
    #include <stdexcept>
    int fail() {
        std::cerr << "student diagnostic";
        throw std::invalid_argument("failed");
    }
    """
    result = run_test_request(
        function_request(source=source, arguments=())
    )
    assert result.success is True
    assert "student diagnostic" in result.tests[0].stderr
    assert result.tests[0].exception_result.expectation_passed is True


def test_compile_error_is_not_classified_as_an_exception_failure():
    source = "int fail() { return missing_identifier; }"
    result = run_test_request(
        function_request(source=source, arguments=())
    )
    assert result.success is False
    assert result.compile_error
    assert result.tests == []


def test_student_stdout_cannot_be_confused_with_exception_metadata():
    source = """
    #include <iostream>
    int noisy() {
        std::cout << "{\\"outcome\\":\\"threw_standard\\"}";
        return 7;
    }
    """
    result = run_test_request(
        function_request(
            source=source,
            arguments=(),
            outcome="return_value",
            exception_type=None,
            expected_return="7",
        )
    )
    assert result.success is True
    assert result.tests[0].exception_result.actual_outcome == "returned"


def test_expected_exception_remains_separate_from_memory_status():
    source = """
    #include <stdexcept>
    int leak_then_throw() {
        volatile int* leaked = new int{5};
        (void)leaked;
        throw std::runtime_error("failed");
    }
    """
    result = run_test_request(
        function_request(
            source=source,
            arguments=(),
            exception_type="std::runtime_error",
            run_memory_checks=True,
        )
    )
    if result.memory_status == "unavailable":
        pytest.skip("The installed compiler does not support sanitizers")
    exception = result.tests[0].exception_result
    assert exception.expectation_passed is True
    if result.tests[0].memory_status == "leak":
        assert result.success is False


CONSTRUCTOR_SOURCE = """
#include <stdexcept>
class Number {
public:
    Number(int value) {
        if (value < 0) throw std::invalid_argument(
            "value must be non-negative");
    }
    int get() const { return 5; }
};
"""


def test_constructor_expected_exception_passes_and_object_is_not_registered():
    object_class = analyze_object_scenarios(CONSTRUCTOR_SOURCE).classes[0]
    constructor = object_class.constructors[0]
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=CONSTRUCTOR_SOURCE,
        language="cpp",
        tests=[
            {
                "name": "Constructor",
                "objects": [
                    {
                        "object_id": "number",
                        "name": "number",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["-1"],
                        "expected_outcome": "throws",
                        "expected_exception_type": "std::invalid_argument",
                        "exception_message_rule": "contains",
                        "expected_exception_message": "non-negative",
                    }
                ],
                "steps": [],
            }
        ],
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].constructed_objects == []
    assert result.tests[0].constructor_exception_result.expectation_passed


def test_later_reference_to_failed_constructor_is_rejected():
    object_class = analyze_object_scenarios(CONSTRUCTOR_SOURCE).classes[0]
    constructor = object_class.constructors[0]
    observer = object_class.methods[0]
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=CONSTRUCTOR_SOURCE,
        language="cpp",
        tests=[
            {
                "name": "Invalid continuation",
                "objects": [
                    {
                        "object_id": "number",
                        "name": "number",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["-1"],
                        "expected_outcome": "throws",
                        "expected_exception_type": "std::invalid_argument",
                    }
                ],
                "steps": [
                    {
                        "step_type": "observer",
                        "target_object_id": "number",
                        "method_id": observer.id,
                        "expected_outcome": "return_value",
                        "expected_return": "5",
                    }
                ],
            }
        ],
    )
    result = run_test_request(request)
    assert result.success is False
    assert "cannot be used later" in (result.input_error or "")


def test_method_expected_exception_passes():
    source = """
    #include <stdexcept>
    class Number {
    public:
        Number() {}
        void fail() { throw std::runtime_error("failed"); }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        tests=[
            {
                "name": "Method",
                "objects": [
                    {
                        "object_id": "number",
                        "name": "number",
                        "class_id": object_class.id,
                        "constructor_id": object_class.constructors[0].id,
                        "arguments": [],
                    }
                ],
                "steps": [
                    {
                        "step_type": "method",
                        "target_object_id": "number",
                        "method_id": object_class.methods[0].id,
                        "expected_outcome": "throws",
                        "expected_exception_type": "std::runtime_error",
                    }
                ],
            }
        ],
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].steps[0].exception_result.expectation_passed


@pytest.mark.parametrize(
    ("step_type", "member_kind", "creates_object"),
    [
        ("copy_construct", "copy_constructor", True),
        ("copy_assign", "copy_assignment", False),
        ("move_construct", "move_constructor", True),
        ("move_assign", "move_assignment", False),
    ],
)
def test_big_five_step_expected_exception(
    step_type, member_kind, creates_object
):
    source = """
    #include <stdexcept>
    class Number {
        int value;
    public:
        Number(int input): value{input} {}
        Number(const Number& other): value{other.value} {
            throw std::runtime_error("copy");
        }
        Number(Number&& other): value{other.value} {
            throw std::runtime_error("move");
        }
        Number& operator=(const Number&) {
            throw std::runtime_error("copy assign");
        }
        Number& operator=(Number&&) {
            throw std::runtime_error("move assign");
        }
        int get() const { return value; }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]
    constructor = object_class.constructors[0]
    member = next(
        item
        for item in object_class.special_members
        if item.kind == member_kind
    )
    step = {
        "step_type": step_type,
        "target_object_id": "target",
        "source_object_id": "source",
        "special_member_id": member.id,
        "expected_outcome": "throws",
        "expected_exception_type": "std::runtime_error",
    }
    if creates_object:
        step.update(
            {
                "result_object_id": "result",
                "result_name": "result",
            }
        )
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        tests=[
            {
                "name": member_kind,
                "objects": [
                    {
                        "object_id": object_id,
                        "name": object_id,
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": [str(index)],
                    }
                    for index, object_id in enumerate(("source", "target"))
                ],
                "steps": [step],
            }
        ],
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].steps[0].exception_result.expectation_passed
    if creates_object:
        assert "result" not in result.tests[0].constructed_objects


STEP_CONSTRUCTOR_SOURCE = """
#include <iostream>
#include <stdexcept>
class Number {
    int value;
public:
    Number(int input): value{input} {
        if (input < 0) {
            throw std::invalid_argument("value must be non-negative");
        }
    }
    ~Number() { std::cout << "destroyed"; }
    int get() const { return value; }
};
"""


def constructor_step_request(
    *,
    value="-1",
    outcome="throws",
    exception_type="std::invalid_argument",
    message_rule="ignore",
    message=None,
    later_observer=False,
    check_stdout=False,
    include_setup=True,
):
    object_class = analyze_object_scenarios(STEP_CONSTRUCTOR_SOURCE).classes[0]
    constructor = object_class.constructors[0]
    observer = next(
        item for item in object_class.methods if item.name == "get"
    )
    steps = [
        {
            "step_type": "create_object",
            "class_id": object_class.id,
            "constructor_id": constructor.id,
            "arguments": [value],
            "result_object_id": "created",
            "result_name": "badNumber",
            "expected_outcome": outcome,
            "expected_exception_type": (
                exception_type if outcome == "throws" else None
            ),
            "exception_message_rule": message_rule,
            "expected_exception_message": message,
            "check_stdout": check_stdout,
            "expected_stdout": "" if check_stdout else None,
        }
    ]
    if later_observer:
        steps.append(
            {
                "step_type": "observer",
                "target_object_id": "created",
                "method_id": observer.id,
                "expected_return": value,
            }
        )
    return ObjectScenarioRunTestsRequest(
        mode="object",
        code=STEP_CONSTRUCTOR_SOURCE,
        language="cpp",
        tests=[
            {
                "name": "Constructor step",
                "objects": [
                    {
                        "object_id": "setup",
                        "name": "setup",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["1"],
                    }
                ] if include_setup else [],
                "steps": steps,
            }
        ],
    )


def test_constructor_step_succeeds_and_object_is_available():
    result = run_test_request(
        constructor_step_request(
            value="7",
            outcome="return_void",
            exception_type=None,
            later_observer=True,
        )
    )
    assert result.success is True
    assert [step.passed for step in result.tests[0].steps] == [True, True]


def test_constructor_step_expected_exception_passes():
    result = run_test_request(constructor_step_request())
    step = result.tests[0].steps[0]
    assert result.success is True
    assert step.step_type == "create_object"
    assert step.exception_result.expectation_passed is True


def test_empty_setup_object_list_is_accepted_for_constructor_only_scenario():
    request = constructor_step_request(include_setup=False)
    assert request.tests[0].objects == []


def test_constructor_only_scenario_executes_without_setup_objects():
    result = run_test_request(
        constructor_step_request(include_setup=False)
    )
    assert result.success is True
    assert result.tests[0].constructed_objects == []
    assert result.tests[0].steps[0].exception_result.expectation_passed


def test_blank_setup_object_is_rejected_if_submitted():
    with pytest.raises(ValidationError):
        ObjectScenarioRunTestsRequest(
            mode="object",
            code=STEP_CONSTRUCTOR_SOURCE,
            language="cpp",
            tests=[
                {
                    "name": "Blank setup",
                    "objects": [
                        {
                            "object_id": "",
                            "name": "",
                            "class_id": "",
                            "constructor_id": "",
                            "arguments": [],
                        }
                    ],
                    "steps": [],
                }
            ],
        )


@pytest.mark.parametrize(
    ("exception_type", "message_rule", "message"),
    [
        ("std::runtime_error", "ignore", None),
        ("std::invalid_argument", "exact", "wrong message"),
    ],
)
def test_constructor_step_wrong_exception_expectation_fails(
    exception_type, message_rule, message
):
    result = run_test_request(
        constructor_step_request(
            exception_type=exception_type,
            message_rule=message_rule,
            message=message,
        )
    )
    assert result.success is False
    assert result.tests[0].steps[0].exception_result.expectation_passed is False


def test_constructor_step_returned_when_throw_expected_fails():
    result = run_test_request(constructor_step_request(value="5"))
    exception = result.tests[0].steps[0].exception_result
    assert result.success is False
    assert exception.actual_outcome == "returned"


def test_expected_failed_constructor_cannot_be_referenced_later():
    result = run_test_request(
        constructor_step_request(later_observer=True)
    )
    assert result.success is False
    assert "unavailable object" in (result.input_error or "")


def test_incomplete_constructor_does_not_run_object_destructor():
    result = run_test_request(
        constructor_step_request(check_stdout=True)
    )
    assert result.success is True
    assert result.tests[0].steps[0].stdout_result.actual == ""


def test_legacy_setup_constructor_still_works_with_constructor_steps():
    result = run_test_request(constructor_step_request())
    assert result.tests[0].constructor_completed is True
    assert result.tests[0].constructed_objects == [
        "setup = Number(int)(1)"
    ]


def test_partial_construction_leak_remains_a_memory_failure():
    source = """
    #include <stdexcept>
    class Leaky {
    public:
        Leaky(int input) {
            if (input < 0) {
                volatile int* leaked = new int{input};
                (void)leaked;
                throw std::invalid_argument("negative");
            }
        }
        int get() const { return 1; }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]
    constructor = object_class.constructors[0]
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        run_memory_checks=True,
        tests=[
            {
                "name": "Partial construction leak",
                "objects": [
                    {
                        "object_id": "setup",
                        "name": "setup",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["1"],
                    }
                ],
                "steps": [
                    {
                        "step_type": "create_object",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["-1"],
                        "result_object_id": "failed",
                        "result_name": "failed",
                        "expected_outcome": "throws",
                        "expected_exception_type": "std::invalid_argument",
                    }
                ],
            }
        ],
    )
    result = run_test_request(request)
    if (
        result.memory_status == "unavailable"
        or result.tests[0].leak_status == "unavailable"
    ):
        pytest.skip("Leak detection is unavailable in this runtime")
    assert result.tests[0].steps[0].exception_result.expectation_passed
    assert result.tests[0].memory_status == "leak"
    assert result.success is False
