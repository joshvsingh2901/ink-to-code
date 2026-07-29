import shutil

import pytest

from app.schemas.test_execution import ObjectScenarioRunTestsRequest
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request


VEC_SOURCE = """
#include <iostream>
class Vec {
    int x;
public:
    Vec(int x): x{x} {}
    Vec operator+(const Vec& other) const { return Vec{x + other.x}; }
    Vec operator-(const Vec& other) const { return Vec{x - other.x}; }
    Vec& operator+=(const Vec& other) { x += other.x; return *this; }
    bool operator==(const Vec& other) const { return x == other.x; }
    bool operator<(const Vec& other) const { return x < other.x; }
    int operator[](int index) const { return x + index; }
    int operator()(int amount) const { return x * amount; }
    int getX() const { return x; }
    friend Vec operator*(int amount, const Vec& value) {
        return Vec{amount * value.x};
    }
    friend std::ostream& operator<<(std::ostream& out, const Vec& value) {
        return out << value.x;
    }
};
"""


def metadata():
    object_class = analyze_object_scenarios(VEC_SOURCE).classes[0]
    operators = {item.symbol: item for item in object_class.operators}
    methods = {item.name: item for item in object_class.methods}
    return object_class, operators, methods


def request(steps, objects=None):
    object_class, _, _ = metadata()
    constructor = object_class.constructors[0]
    return ObjectScenarioRunTestsRequest(
        mode="object",
        code=VEC_SOURCE,
        language="cpp",
        tests=[
            {
                "name": "Operator scenario",
                "objects": objects
                or [
                    {
                        "object_id": "first",
                        "name": "first",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["4"],
                    },
                    {
                        "object_id": "second",
                        "name": "second",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["3"],
                    },
                ],
                "steps": steps,
            }
        ],
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_member_object_result_is_available_to_later_observer():
    _, operators, methods = metadata()
    result = run_test_request(
        request(
            [
                {
                    "step_type": "operator",
                    "operator_id": operators["+"].id,
                    "target_object_id": "first",
                    "operands": ["second"],
                    "result_object_id": "sum",
                    "result_name": "sum",
                },
                {
                    "step_type": "method",
                    "method_id": methods["getX"].id,
                    "target_object_id": "sum",
                    "expected_return": "7",
                },
            ]
        )
    )
    assert result.success is True
    assert result.tests[0].steps[0].result_object_name == "sum"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_standalone_scalar_left_operator_and_member_mutation():
    _, operators, methods = metadata()
    multiply = next(
        item for item in operators.values() if item.symbol == "*"
    )
    result = run_test_request(
        request(
            [
                {
                    "step_type": "operator",
                    "operator_id": multiply.id,
                    "target_object_id": "first",
                    "operands": ["2", "first"],
                    "result_object_id": "scaled",
                    "result_name": "scaled",
                },
                {
                    "step_type": "operator",
                    "operator_id": operators["+="].id,
                    "target_object_id": "scaled",
                    "operands": ["second"],
                },
                {
                    "step_type": "method",
                    "method_id": methods["getX"].id,
                    "target_object_id": "scaled",
                    "expected_return": "11",
                },
            ]
        )
    )
    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("symbol", "operands", "expected"),
    [
        ("==", ["second"], "false"),
        ("<", ["second"], "false"),
        ("[]", ["2"], "6"),
        ("()", ["3"], "12"),
    ],
)
def test_scalar_operator_results(symbol, operands, expected):
    _, operators, _ = metadata()
    result = run_test_request(
        request(
            [
                {
                    "step_type": "operator",
                    "operator_id": operators[symbol].id,
                    "target_object_id": "first",
                    "operands": operands,
                    "expected_return": expected,
                }
            ]
        )
    )
    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(("expected", "passed"), [("4", True), ("5", False)])
def test_stream_operator_output(expected, passed):
    object_class, _, _ = metadata()
    stream = next(
        item for item in object_class.operators if item.symbol == "<<"
    )
    result = run_test_request(
        request(
            [
                {
                    "step_type": "operator",
                    "operator_id": stream.id,
                    "target_object_id": "first",
                    "operands": ["first"],
                    "check_stdout": True,
                    "expected_stdout": expected,
                }
            ]
        )
    )
    assert result.tests[0].passed is passed


def test_operator_validation_rejects_stale_duplicate_and_wrong_operands():
    _, operators, _ = metadata()
    stale = request(
        [
            {
                "step_type": "operator",
                "operator_id": "stale",
                "target_object_id": "first",
            }
        ]
    )
    duplicate_objects = request(
        [
            {
                "step_type": "operator",
                "operator_id": operators["=="].id,
                "target_object_id": "first",
                "operands": ["first"],
                "expected_return": "true",
            }
        ]
    )
    duplicate_objects.tests[0].objects[1].name = "first"
    wrong_operand = request(
        [
            {
                "step_type": "operator",
                "operator_id": operators["+"].id,
                "target_object_id": "first",
                "operands": ["missing"],
                "result_object_id": "result",
                "result_name": "result",
            }
        ]
    )
    assert run_test_request(stale).input_error
    assert run_test_request(duplicate_objects).input_error
    assert run_test_request(wrong_operand).input_error


def test_private_assignment_and_pointer_return_operators_are_excluded():
    source = """
    class Hidden {
        Hidden operator+(const Hidden& other) const { return other; }
    public:
        Hidden() {}
        Hidden& operator=(const Hidden& other) { return *this; }
        Hidden* operator-(const Hidden& other) { return nullptr; }
        int value() const { return 1; }
    };
    """
    operators = analyze_object_scenarios(source).classes[0].operators
    assert operators == ()


def test_top_level_and_overloaded_operators_use_distinct_full_signatures():
    source = """
    class Number {
    public:
        Number(int value) {}
        int value() const { return 1; }
    };
    Number operator+(const Number& left, const Number& right) {
        return Number{1};
    }
    Number operator*(int amount, const Number& value) {
        return Number{amount};
    }
    Number operator*(double amount, const Number& value) {
        return Number{static_cast<int>(amount)};
    }
    """
    operators = analyze_object_scenarios(source).classes[0].operators

    assert {operator.symbol for operator in operators} == {"+", "*"}
    multiply_ids = {
        operator.id for operator in operators if operator.symbol == "*"
    }
    assert len(multiply_ids) == 2
    assert any("(int,constNumber&)" in identifier for identifier in multiply_ids)
    assert any(
        "(double,constNumber&)" in identifier for identifier in multiply_ids
    )


def test_protected_and_unsupported_reference_result_operators_are_excluded():
    source = """
    class Value {
    public:
        Value() {}
        int get() const { return 1; }
        Value& operator+(const Value& other) { return *this; }
    protected:
        bool operator==(const Value& other) const { return true; }
    };
    """
    assert analyze_object_scenarios(source).classes[0].operators == ()
