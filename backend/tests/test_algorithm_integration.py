"""
Integration tests proving ordinary functions using STL algorithms compile and run
correctly when the student includes the right headers themselves.

No algorithm engine or algorithm registry is tested here — these are plain function
and object-scenario tests that happen to call STL algorithms internally.

Requires g++; all tests that compile/execute are guarded by NEEDS_GPP.
"""

import shutil

import pytest

from app.schemas.test_execution import (
    FunctionMutationExpectation,
    FunctionRunTestsRequest,
    FunctionTestCase,
    ObjectScenarioRunTestsRequest,
    ObjectScenarioStep,
    ObjectScenarioTestCase,
)
from app.services.function_analysis import analyze_test_mode
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import (
    HarnessArgument,
    _build_function_harness,
    run_test_request,
)

NEEDS_GPP = pytest.mark.skipif(
    shutil.which("g++") is None, reason="g++ is not installed"
)


def _fn_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str | None = None,
    expected_mutations: list[dict] | None = None,
    expected_outcome: str | None = None,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.mode == "function", (
        f"Expected function mode, got {analysis.mode}: {analysis.message}"
    )
    fn = analysis.functions[0]
    mutation_objects = None
    if expected_mutations is not None:
        mutation_objects = [
            FunctionMutationExpectation(
                parameter_id=m["parameter_id"],
                expected_final_value=m["expected_final_value"],
            )
            for m in expected_mutations
        ]
    if expected_outcome is None:
        expected_outcome = "return_value" if expected_return is not None else "return_void"
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=fn.id,
        tests=[
            FunctionTestCase(
                name="Algorithm test",
                arguments=arguments,
                expected_return=expected_return,
                expected_outcome=expected_outcome,
                expected_mutations=mutation_objects,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. std::find — student includes <algorithm>
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_find_with_own_algorithm_include():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "int findIndex(std::vector<int> v, int target) {\n"
        "  auto it = std::find(v.begin(), v.end(), target);\n"
        "  return (it == v.end()) ? -1 : static_cast<int>(it - v.begin());\n"
        "}"
    )
    result = run_test_request(
        _fn_request(source, arguments=["[10, 20, 30, 40]", "30"], expected_return="2")
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 2. std::count_if — internal lambda
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_count_if_with_internal_lambda():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "int countPositive(std::vector<int> v) {\n"
        "  return static_cast<int>(std::count_if(v.begin(), v.end(),\n"
        "    [](int x) { return x > 0; }));\n"
        "}"
    )
    result = run_test_request(
        _fn_request(source, arguments=["[-1, 2, -3, 4, 5]"], expected_return="3")
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 3. std::sort — mutates a mutable_reference vector parameter
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_sort_mutates_vector_parameter():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "void sortInPlace(std::vector<int>& v) {\n"
        "  std::sort(v.begin(), v.end());\n"
        "}"
    )
    result = run_test_request(
        _fn_request(
            source,
            arguments=["[3, 1, 4, 1, 5, 9, 2, 6]"],
            expected_outcome="return_void",
            expected_mutations=[
                {
                    "parameter_id": "v",
                    "expected_final_value": "[1, 1, 2, 3, 4, 5, 6, 9]",
                }
            ],
        )
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 4. std::transform — returns a new vector
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_transform_returns_vector():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "std::vector<int> doubled(std::vector<int> v) {\n"
        "  std::vector<int> out(v.size());\n"
        "  std::transform(v.begin(), v.end(), out.begin(),\n"
        "    [](int x) { return x * 2; });\n"
        "  return out;\n"
        "}"
    )
    result = run_test_request(
        _fn_request(source, arguments=["[1, 2, 3, 4]"], expected_return="[2, 4, 6, 8]")
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 5. std::accumulate — student includes <numeric>
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_accumulate_with_own_numeric_include():
    source = (
        "#include <vector>\n"
        "#include <numeric>\n"
        "int sumVector(std::vector<int> v) {\n"
        "  return std::accumulate(v.begin(), v.end(), 0);\n"
        "}"
    )
    result = run_test_request(
        _fn_request(source, arguments=["[1, 2, 3, 4, 5]"], expected_return="15")
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 6. std::remove_if + erase — erase-remove idiom
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_remove_if_erase_idiom():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "void removeNegatives(std::vector<int>& v) {\n"
        "  v.erase(std::remove_if(v.begin(), v.end(),\n"
        "    [](int x) { return x < 0; }), v.end());\n"
        "}"
    )
    result = run_test_request(
        _fn_request(
            source,
            arguments=["[1, -2, 3, -4, 5]"],
            expected_outcome="return_void",
            expected_mutations=[
                {
                    "parameter_id": "v",
                    "expected_final_value": "[1, 3, 5]",
                }
            ],
        )
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 7. std::for_each — internal lambda capturing by reference
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_std_for_each_lambda_captures_by_reference():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "int sumWithForEach(std::vector<int> v) {\n"
        "  int total = 0;\n"
        "  std::for_each(v.begin(), v.end(), [&total](int x) { total += x; });\n"
        "  return total;\n"
        "}"
    )
    result = run_test_request(
        _fn_request(source, arguments=["[10, 20, 30]"], expected_return="60")
    )
    assert result.success is True, result.input_error or result.compile_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 8. Object scenario whose method calls std::sort internally
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_object_scenario_method_calls_std_sort():
    source = (
        "#include <vector>\n"
        "#include <algorithm>\n"
        "class SortedBag {\n"
        "  std::vector<int> data;\n"
        "public:\n"
        "  SortedBag() = default;\n"
        "  void add(int x) { data.push_back(x); std::sort(data.begin(), data.end()); }\n"
        "  int front() const { return data.empty() ? -1 : data[0]; }\n"
        "};\n"
    )
    analysis = analyze_object_scenarios(source)
    assert len(analysis.classes) == 1
    cls = analysis.classes[0]
    add_method = next(m for m in cls.methods if m.name == "add")
    front_method = next(m for m in cls.methods if m.name == "front")
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        comparison_mode="whitespace_tolerant",
        tests=[
            ObjectScenarioTestCase(
                name="SortedBag test",
                class_id=cls.id,
                constructor_id=cls.constructors[0].id,
                constructor_arguments=[],
                steps=[
                    ObjectScenarioStep(
                        method_id=add_method.id,
                        arguments=["5"],
                    ),
                    ObjectScenarioStep(
                        method_id=add_method.id,
                        arguments=["2"],
                    ),
                    ObjectScenarioStep(
                        method_id=front_method.id,
                        arguments=[],
                        expected_return="2",
                    ),
                ],
            )
        ],
    )
    result = run_test_request(request)
    assert result.success is True, getattr(result, "input_error", None) or getattr(result, "compile_error", None)
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 9. Harness never injects <algorithm> or <numeric> (locks in the decision)
#    On some platforms (macOS/libc++) missing <algorithm> still compiles because
#    <vector> pulls it in transitively, so we cannot assert a compile failure.
#    Instead, assert that the generated harness preamble itself never includes
#    these headers — ensuring the student must include them explicitly.
# ---------------------------------------------------------------------------

def test_harness_preamble_never_injects_algorithm_or_numeric():
    source = (
        "#include <vector>\n"
        "int sumVector(std::vector<int> v) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    fn = analysis.functions[0]
    harness = _build_function_harness(
        source,
        fn,
        [[HarnessArgument(expression="std::vector<int>{1, 2, 3}")]],
        (),
    )
    assert "#include <algorithm>" not in harness, (
        "Harness must not inject <algorithm> — student must include it themselves."
    )
    assert "#include <numeric>" not in harness, (
        "Harness must not inject <numeric> — student must include it themselves."
    )
