"""
Execution tests for STL container support.
Requires g++ to be installed; each test is guarded accordingly.
"""

import shutil

import pytest

from app.schemas.test_execution import (
    FunctionRunTestsRequest,
    FunctionTestCase,
)
from app.services.function_analysis import analyze_test_mode
from app.services.test_execution import run_test_request

NEEDS_GPP = pytest.mark.skipif(
    shutil.which("g++") is None, reason="g++ is not installed"
)


def container_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str,
    target_index: int = 0,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.mode == "function", f"Expected function mode, got {analysis.mode}"
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=analysis.functions[target_index].id,
        tests=[
            FunctionTestCase(
                name="Container test",
                arguments=arguments,
                expected_return=expected_return,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. std::deque<int> argument and return
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_deque_int_doubling():
    source = (
        "#include <deque>\n"
        "std::deque<int> twice(std::deque<int> values) {"
        " for (int& v : values) v *= 2; return values; }"
    )
    result = run_test_request(
        container_request(source, arguments=["[1, 2, 3]"], expected_return="[2, 4, 6]")
    )
    assert result.success is True
    assert result.tests[0].actual_return == "[2, 4, 6]"
    assert result.tests[0].match_type == "exact"


# ---------------------------------------------------------------------------
# 2. std::list<int> return
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_list_int_identity():
    source = (
        "#include <list>\n"
        "std::list<int> identity(std::list<int> values) { return values; }"
    )
    result = run_test_request(
        container_request(source, arguments=["[10, 20, 30]"], expected_return="[10, 20, 30]")
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 3. std::set<int> — order-insensitive comparison
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_set_int_order_independent():
    source = (
        "#include <set>\n"
        "std::set<int> identity(std::set<int> values) { return values; }"
    )
    # std::set iterates in sorted order; user provides unsorted expected
    result = run_test_request(
        container_request(source, arguments=["[3, 1, 2]"], expected_return="[3, 1, 2]")
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 4. std::multiset<int> — multiplicity matters
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_multiset_multiplicity_mismatch():
    source = (
        "#include <set>\n"
        "std::multiset<int> identity(std::multiset<int> values) { return values; }"
    )
    # input has duplicate 1, expected missing the duplicate → should fail
    result = run_test_request(
        container_request(source, arguments=["[1, 1, 2]"], expected_return="[1, 2]")
    )
    assert result.success is False
    assert result.tests[0].match_type == "mismatch"


@NEEDS_GPP
def test_multiset_multiplicity_match():
    source = (
        "#include <set>\n"
        "std::multiset<int> identity(std::multiset<int> values) { return values; }"
    )
    result = run_test_request(
        container_request(source, arguments=["[1, 1, 2]"], expected_return="[1, 1, 2]")
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 5. std::map<std::string, int> — expected as JSON object (cross-representation)
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_map_string_int_json_object_expected():
    source = (
        '#include <map>\n'
        '#include <string>\n'
        'std::map<std::string, int> inventory() {'
        ' return {{"apple", 3}, {"orange", 5}}; }'
    )
    # Expected as plain JSON object — canonical normalizer must bridge the gap
    result = run_test_request(
        container_request(
            source,
            arguments=[],
            expected_return='{"apple": 3, "orange": 5}',
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 6. std::map — expected as list-of-{key,value} in reverse order
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_map_string_int_list_form_reversed_order():
    source = (
        '#include <map>\n'
        '#include <string>\n'
        'std::map<std::string, int> inventory() {'
        ' return {{"apple", 3}, {"orange", 5}}; }'
    )
    result = run_test_request(
        container_request(
            source,
            arguments=[],
            expected_return='[{"key": "orange", "value": 5}, {"key": "apple", "value": 3}]',
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 7. std::map — wrong value → mismatch
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_map_string_int_wrong_value():
    source = (
        '#include <map>\n'
        '#include <string>\n'
        'std::map<std::string, int> inventory() {'
        ' return {{"apple", 3}, {"orange", 5}}; }'
    )
    result = run_test_request(
        container_request(
            source,
            arguments=[],
            expected_return='{"apple": 4, "orange": 5}',
        )
    )
    assert result.success is False
    assert result.tests[0].match_type == "mismatch"


# ---------------------------------------------------------------------------
# 8. std::unordered_set<int> — order-insensitive
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_unordered_set_int():
    source = (
        "#include <unordered_set>\n"
        "std::unordered_set<int> identity(std::unordered_set<int> v) { return v; }"
    )
    result = run_test_request(
        container_request(source, arguments=["[3, 1, 2]"], expected_return="[1, 2, 3]")
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 9. std::unordered_map<std::string, int>
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_unordered_map_string_int():
    source = (
        '#include <unordered_map>\n'
        '#include <string>\n'
        'std::unordered_map<std::string, int> f() {'
        ' return {{"x", 1}, {"y", 2}}; }'
    )
    result = run_test_request(
        container_request(
            source,
            arguments=[],
            expected_return='{"x": 1, "y": 2}',
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 10. Mutable std::deque<int>& — mutation pathway
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_deque_mutable_reference():
    source = (
        "#include <deque>\n"
        "void doubleAll(std::deque<int>& values) {"
        " for (int& v : values) v *= 2; }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    fn = analysis.functions[0]
    request = FunctionRunTestsRequest(
        mode="function",
        code=source,
        language="cpp",
        target_function=fn.id,
        tests=[
            FunctionTestCase(
                name="Mutation test",
                arguments=["[1, 2, 3]"],
                expected_final_arguments={"values": "[2, 4, 6]"},
            )
        ],
    )
    result = run_test_request(request)
    assert result.success is True


# ---------------------------------------------------------------------------
# 11. Scalar regression — serializer injection must not break scalar harnesses
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_scalar_regression_unaffected():
    source = "int add(int a, int b) { return a + b; }"
    analysis = analyze_test_mode(source)
    request = FunctionRunTestsRequest(
        mode="function",
        code=source,
        language="cpp",
        target_function=analysis.functions[0].id,
        tests=[
            FunctionTestCase(
                name="Scalar test",
                arguments=["3", "4"],
                expected_return="7",
            )
        ],
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].actual_return == "7"


# ---------------------------------------------------------------------------
# 12. Legacy vector regression
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_legacy_vector_int_regression():
    source = (
        "#include <vector>\n"
        "std::vector<int> doubled(std::vector<int> values)"
        " { for (int& v : values) v *= 2; return values; }"
    )
    analysis = analyze_test_mode(source)
    request = FunctionRunTestsRequest(
        mode="function",
        code=source,
        language="cpp",
        target_function=analysis.functions[0].id,
        tests=[
            FunctionTestCase(
                name="Vector test",
                arguments=["[1, 2, 3]"],
                expected_return="[2, 4, 6]",
            )
        ],
    )
    result = run_test_request(request)
    assert result.success is True
    assert result.tests[0].actual_return == "[2, 4, 6]"


# ---------------------------------------------------------------------------
# 13. Rejected nested type — analysis returns None, no invalid C++ generated
# ---------------------------------------------------------------------------


def test_nested_container_rejected_at_analysis():
    """set<vector<int>> must be rejected during analysis, never reaching harness."""
    from app.services.function_analysis import _parse_value_type

    vt, err = _parse_value_type(
        "std::set<std::vector<int>>",
        allow_reference=False,
        unqualified_vector_allowed=False,
    )
    assert vt is None
    assert err is not None
    assert "not yet supported" in err
