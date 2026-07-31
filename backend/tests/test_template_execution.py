import pytest
from pydantic import ValidationError

from app.schemas.test_execution import (
    FunctionRunTestsRequest,
    ObjectScenarioRunTestsRequest,
)
from app.services.function_analysis import (
    TemplateArgument,
    analyze_test_mode,
    instantiate_function_template,
)
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import (
    HarnessArgument,
    _build_function_harness,
    run_test_request,
)


def _function_request(
    source: str,
    *,
    arguments: list[str],
    expected: str | None = None,
    mode: str = "deduced",
    template_arguments: list[dict] | None = None,
    expected_outcome: str = "return_value",
    exception_type: str | None = None,
):
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    return FunctionRunTestsRequest.model_validate(
        {
            "mode": "function",
            "code": source,
            "language": "cpp",
            "target_function": analysis.functions[0].id,
            "template_argument_mode": mode,
            "template_arguments": template_arguments or [],
            "tests": [
                {
                    "name": "Test 1",
                    "arguments": arguments,
                    "expected_return": expected,
                    "expected_outcome": expected_outcome,
                    "expected_exception_type": exception_type,
                }
            ],
        }
    )


MAXIMUM = """
template <typename T>
T maximum(T a, T b)
{
    return a > b ? a : b;
}
"""


def test_single_type_function_template_parsing():
    function = analyze_test_mode(MAXIMUM).functions[0]
    assert function.template_kind == "function_template"
    assert [item.name for item in function.template_parameters] == ["T"]
    assert function.template_argument_mode == "deduced"


def test_multiple_type_and_non_type_template_parameter_parsing():
    source = """
template <typename T, typename U>
auto add(T a, U b) { return a + b; }
"""
    function = analyze_test_mode(source).functions[0]
    assert [item.name for item in function.template_parameters] == ["T", "U"]

    non_type = analyze_test_mode(
        "template <typename T, int N>\nint sizeOf(T value) { return N; }"
    ).functions[0]
    assert non_type.template_parameters[1].kind == "non_type"
    assert non_type.template_parameters[1].non_type_type == "int"


@pytest.mark.parametrize(
    ("arguments", "expected", "instantiation"),
    [
        (["3", "5"], "5", "maximum<int>"),
        (["3.5", "2.0"], "3.5", "maximum<double>"),
    ],
)
def test_automatic_function_template_deduction(
    arguments: list[str], expected: str, instantiation: str
):
    result = run_test_request(
        _function_request(MAXIMUM, arguments=arguments, expected=expected)
    )
    assert result.success is True
    assert result.tests[0].passed is True
    assert result.tests[0].concrete_instantiation == instantiation
    assert result.tests[0].template_argument_mode == "deduced"


def test_explicit_function_template_arguments():
    result = run_test_request(
        _function_request(
            MAXIMUM,
            arguments=["3.5", "2.0"],
            expected="3.5",
            mode="explicit",
            template_arguments=[
                {
                    "parameter_name": "T",
                    "kind": "type",
                    "value": "double",
                }
            ],
        )
    )
    assert result.success is True
    assert result.tests[0].concrete_instantiation == "maximum<double>"


def test_deduction_failure_remains_a_compile_error():
    result = run_test_request(
        _function_request(
            MAXIMUM,
            arguments=["3", "2.5"],
            expected="3",
        )
    )
    assert result.success is False
    assert result.compile_error
    assert result.input_error is None


def test_multiple_type_parameters_execute_in_order():
    source = """
template <typename T, typename U>
auto add(T a, U b) { return a + b; }
"""
    result = run_test_request(
        _function_request(
            source,
            arguments=["3", "2.5"],
            expected="5.5",
            mode="explicit",
            template_arguments=[
                {"parameter_name": "T", "kind": "type", "value": "int"},
                {"parameter_name": "U", "kind": "type", "value": "double"},
            ],
        )
    )
    assert result.success is True
    assert result.tests[0].concrete_instantiation == "add<int, double>"


def test_non_type_parameter_and_default_are_validated():
    source = """
template <typename T = int, int N = 5>
int configuredSize(T value) { return N; }
"""
    defaulted = run_test_request(
        _function_request(
            source,
            arguments=["1"],
            expected="5",
            mode="explicit",
            template_arguments=[],
        )
    )
    assert defaulted.success is True
    assert defaulted.tests[0].concrete_instantiation == (
        "configuredSize<int, 5>"
    )

    invalid = run_test_request(
        _function_request(
            source,
            arguments=["1"],
            expected="5",
            mode="explicit",
            template_arguments=[
                {"parameter_name": "T", "kind": "type", "value": "int"},
                {
                    "parameter_name": "N",
                    "kind": "non_type",
                    "value": "2 + 3",
                },
            ],
        )
    )
    assert invalid.input_error


def test_arbitrary_template_type_text_is_rejected():
    result = run_test_request(
        _function_request(
            MAXIMUM,
            arguments=["1", "2"],
            expected="2",
            mode="explicit",
            template_arguments=[
                {
                    "parameter_name": "T",
                    "kind": "type",
                    "value": "int>; system(1)",
                }
            ],
        )
    )
    assert "unsupported" in (result.input_error or "").lower()


def test_explicit_specialization_is_reported():
    source = """
template <typename T>
int identify(T) { return 0; }
template <>
int identify<int>(int) { return 1; }
"""
    result = run_test_request(
        _function_request(
            source,
            arguments=["10"],
            expected="1",
            mode="explicit",
            template_arguments=[
                {"parameter_name": "T", "kind": "type", "value": "int"}
            ],
        )
    )
    assert result.success is True
    assert result.tests[0].specialization_selected is True
    assert result.tests[0].template_kind == "explicit_specialization"
    assert result.tests[0].specialization_kind == "explicit_specialization"


@pytest.mark.parametrize("specialized_parameter", ["int", "int value"])
def test_named_and_unnamed_specializations_link_to_the_primary(
    specialized_parameter: str,
):
    source = f"""
template <typename T>
int identify(T) {{ return 0; }}
template <>
int identify<int>({specialized_parameter}) {{ return 1; }}
"""
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    assert len(analysis.functions) == 1
    primary = analysis.functions[0]
    assert primary.name == "identify"
    assert primary.parameters[0].name == "argument1"
    assert len(primary.explicit_specializations) == 1
    specialization = primary.explicit_specializations[0]
    assert specialization.primary_template_name == "identify"
    assert specialization.effective_template_arguments == ("int",)
    assert specialization.parameter_types == ("int",)
    assert specialization.source_line > primary.source_line
    assert primary.template_argument_mode == "explicit"


def test_template_specialization_does_not_replace_primary_availability():
    source = """
template <typename T>
int identify(T) { return 0; }
template <>
int identify<int>(int) { return 1; }
"""
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    assert [function.name for function in analysis.functions] == ["identify"]
    assert analysis.message is None


def test_generated_harness_calls_validated_specializations():
    primary = analyze_test_mode(
        """
template <typename T>
int identify(T) { return 0; }
template <>
int identify<int>(int) { return 1; }
"""
    ).functions[0]
    for type_name, literal in (("int", "10"), ("double", "10.0")):
        instantiated = instantiate_function_template(
            primary,
            (
                TemplateArgument(
                    parameter_name="T",
                    kind="type",
                    value=type_name,
                ),
            ),
            argument_mode="explicit",
            call_arguments=(literal,),
            unqualified_vector_allowed=False,
        )
        harness = _build_function_harness(
            "",
            instantiated,
            [[HarnessArgument(literal)]],
            (),
        )
        assert f"identify<{type_name}>({literal})" in harness


def test_function_template_expected_exception():
    source = """
#include <stdexcept>
template <typename T>
T divide(T a, T b)
{
    if (b == 0) throw std::invalid_argument("division by zero");
    return a / b;
}
"""
    result = run_test_request(
        _function_request(
            source,
            arguments=["4", "0"],
            expected_outcome="throws",
            exception_type="std::invalid_argument",
        )
    )
    assert result.success is True
    assert result.tests[0].exception_result.expectation_passed is True


BOX = """
template <typename T>
class Box
{
    T value;
public:
    Box(T value): value{value} {}
    T get() const { return value; }
};
"""


def test_class_template_parsing_and_object_execution():
    analysis = analyze_object_scenarios(BOX)
    box = analysis.classes[0]
    assert box.template_kind == "class_template"
    assert box.concrete_type == "Box<int>"
    request = ObjectScenarioRunTestsRequest.model_validate(
        {
            "mode": "object",
            "code": BOX,
            "language": "cpp",
            "tests": [
                {
                    "name": "Scenario 1",
                    "objects": [],
                    "steps": [
                        {
                            "step_type": "create_object",
                            "class_id": box.id,
                            "constructor_id": box.constructors[0].id,
                            "template_arguments": [
                                {
                                    "parameter_name": "T",
                                    "kind": "type",
                                    "value": "int",
                                }
                            ],
                            "arguments": ["42"],
                            "result_object_id": "box",
                            "result_name": "box",
                        },
                        {
                            "step_type": "observer",
                            "target_object_id": "box",
                            "method_id": box.methods[0].id,
                            "expected_outcome": "return_value",
                            "expected_return": "42",
                        },
                    ],
                }
            ],
        }
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].passed is True


def test_class_template_operator_result_remains_instantiated():
    source = """
template <typename T>
class Box
{
    T value;
public:
    Box(T value): value{value} {}
    Box operator+(const Box& other) const { return Box(value + other.value); }
    T get() const { return value; }
};
"""
    box = analyze_object_scenarios(source).classes[0]
    constructor = box.constructors[0]
    operator = next(item for item in box.operators if item.symbol == "+")
    get = next(item for item in box.methods if item.name == "get")
    template_arguments = [
        {"parameter_name": "T", "kind": "type", "value": "int"}
    ]
    request = ObjectScenarioRunTestsRequest.model_validate(
        {
            "mode": "object",
            "code": source,
            "language": "cpp",
            "tests": [
                {
                    "name": "Scenario 1",
                    "objects": [
                        {
                            "object_id": "left",
                            "name": "left",
                            "class_id": box.id,
                            "constructor_id": constructor.id,
                            "template_arguments": template_arguments,
                            "arguments": ["20"],
                        },
                        {
                            "object_id": "right",
                            "name": "right",
                            "class_id": box.id,
                            "constructor_id": constructor.id,
                            "template_arguments": template_arguments,
                            "arguments": ["22"],
                        },
                    ],
                    "steps": [
                        {
                            "step_type": "operator",
                            "target_object_id": "left",
                            "operator_id": operator.id,
                            "operands": ["right"],
                            "result_object_id": "sum",
                            "result_name": "sum",
                        },
                        {
                            "step_type": "observer",
                            "target_object_id": "sum",
                            "method_id": get.id,
                            "expected_outcome": "return_value",
                            "expected_return": "42",
                        },
                    ],
                }
            ],
        }
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].passed is True


def test_primary_template_selected_for_non_specialized_type():
    source = """
template <typename T>
int identify(T value) { return 0; }
template <>
int identify<int>(int value) { return 1; }
"""
    result = run_test_request(
        _function_request(
            source,
            arguments=["10.0"],
            expected="0",
            mode="explicit",
            template_arguments=[
                {"parameter_name": "T", "kind": "type", "value": "double"}
            ],
        )
    )
    assert result.success is True
    assert result.tests[0].specialization_selected is False
    assert result.tests[0].specialization_kind == "primary"


def test_wrong_specialization_argument_count_is_rejected():
    analysis = analyze_test_mode(
        """
template <typename T>
int identify(T) { return 0; }
template <>
int identify<int, double>(int) { return 1; }
"""
    )
    assert analysis.mode == "unsupported"
    assert "wrong number" in (analysis.message or "").lower()


def test_function_template_overloads_remain_distinct():
    analysis = analyze_test_mode(
        """
template <typename T>
int identify(T value) { return 0; }
template <typename T>
int identify(T left, T right) { return 1; }
"""
    )
    assert analysis.mode == "function"
    assert len(analysis.functions) == 2
    assert analysis.functions[0].id != analysis.functions[1].id


def test_advanced_template_forms_report_a_limitation():
    analysis = analyze_test_mode(
        "template <typename... Ts>\nint count(Ts... values) { return 0; }"
    )
    assert analysis.mode == "unsupported"
    assert "variadic" in (analysis.message or "").lower()


def test_invalid_template_argument_schema_kind_is_rejected():
    with pytest.raises(ValidationError):
        _function_request(
            MAXIMUM,
            arguments=["1", "2"],
            expected="2",
            template_arguments=[
                {"parameter_name": "T", "kind": "raw", "value": "int"}
            ],
        )
