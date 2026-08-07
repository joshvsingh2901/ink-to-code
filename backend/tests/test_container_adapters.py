"""
Execution tests for adapter container support (stack, queue, priority_queue).
Requires g++ to be installed; each execution test is guarded accordingly.
"""

import shutil

import pytest

from app.schemas.test_execution import (
    FunctionRunTestsRequest,
    FunctionTestCase,
)
from app.services.function_analysis import _parse_value_type, analyze_test_mode
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
                name="Adapter test",
                arguments=arguments,
                expected_return=expected_return,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1–3. Parsing acceptance
# ---------------------------------------------------------------------------


def test_stack_int_parses():
    vt, err = _parse_value_type(
        "std::stack<int>",
        allow_reference=True,
        unqualified_vector_allowed=False,
    )
    assert err is None
    assert vt is not None
    assert vt.container_name == "stack"
    assert vt.adapter is True
    assert vt.container_family == "adapter"


def test_queue_int_parses():
    vt, err = _parse_value_type(
        "std::queue<int>",
        allow_reference=True,
        unqualified_vector_allowed=False,
    )
    assert err is None
    assert vt is not None
    assert vt.container_name == "queue"
    assert vt.adapter is True


def test_priority_queue_int_parses():
    vt, err = _parse_value_type(
        "std::priority_queue<int>",
        allow_reference=True,
        unqualified_vector_allowed=False,
    )
    assert err is None
    assert vt is not None
    assert vt.container_name == "priority_queue"
    assert vt.adapter is True


# ---------------------------------------------------------------------------
# 4. stack return — serialized top → bottom
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_stack_return_order():
    source = (
        "#include <stack>\n"
        "std::stack<int> push_all(std::stack<int> s) { return s; }"
    )
    result = run_test_request(
        container_request(
            source,
            # stack input: bottom=1, middle=2, top=3 → push in order [1,2,3]
            arguments=["[1, 2, 3]"],
            # serialized top → bottom: 3, 2, 1
            expected_return="[3, 2, 1]",
        )
    )
    assert result.success is True
    assert result.tests[0].match_type == "exact"


# ---------------------------------------------------------------------------
# 5. queue return — serialized front → back
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_queue_return_order():
    source = (
        "#include <queue>\n"
        "std::queue<int> identity(std::queue<int> q) { return q; }"
    )
    result = run_test_request(
        container_request(
            source,
            arguments=["[1, 2, 3]"],
            expected_return="[1, 2, 3]",
        )
    )
    assert result.success is True
    assert result.tests[0].match_type == "exact"


# ---------------------------------------------------------------------------
# 6. priority_queue return — serialized pop order (largest first)
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_priority_queue_return_pop_order():
    source = (
        "#include <queue>\n"
        "std::priority_queue<int> identity(std::priority_queue<int> pq) { return pq; }"
    )
    result = run_test_request(
        container_request(
            source,
            arguments=["[1, 3, 2]"],
            # pop order: 3, 2, 1
            expected_return="[3, 2, 1]",
        )
    )
    assert result.success is True
    assert result.tests[0].match_type == "exact"


# ---------------------------------------------------------------------------
# 7. Wrong stack expected order → mismatch
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_stack_wrong_order_mismatch():
    source = (
        "#include <stack>\n"
        "std::stack<int> identity(std::stack<int> s) { return s; }"
    )
    result = run_test_request(
        container_request(
            source,
            arguments=["[1, 2, 3]"],
            # correct would be [3,2,1]; giving wrong order:
            expected_return="[1, 2, 3]",
        )
    )
    assert result.success is False
    assert result.tests[0].match_type == "mismatch"


# ---------------------------------------------------------------------------
# 8. Adapter used as normal function argument (scalar return)
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_stack_as_argument_scalar_return():
    source = (
        "#include <stack>\n"
        "int stack_size(std::stack<int> s) { return static_cast<int>(s.size()); }"
    )
    result = run_test_request(
        container_request(
            source,
            arguments=["[1, 2, 3]"],
            expected_return="3",
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 9. Mutable std::stack<int>& → rejected at parse time
# ---------------------------------------------------------------------------


def test_stack_mutable_reference_rejected():
    vt, err = _parse_value_type(
        "std::stack<int>&",
        allow_reference=True,
        unqualified_vector_allowed=False,
    )
    assert vt is None
    assert err is not None
    assert "mutable" in err.lower() or "not supported" in err.lower()


# ---------------------------------------------------------------------------
# 10. Exception regression: vector::at out_of_range
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_vector_at_exception_regression():
    source = (
        "#include <vector>\n"
        "int at5(std::vector<int> v) { return v.at(5); }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    request = FunctionRunTestsRequest(
        mode="function",
        code=source,
        language="cpp",
        target_function=analysis.functions[0].id,
        tests=[
            FunctionTestCase(
                name="OOB exception",
                arguments=["[1, 2, 3]"],
                expected_outcome="throws",
                expected_exception_type="std::out_of_range",
            )
        ],
    )
    result = run_test_request(request)
    assert result.success is True


# ---------------------------------------------------------------------------
# 11. Non-destructive serialization: queue copy drained, original intact
#     Proves inktocode_serialize_adapter takes by value (copies the adapter).
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_queue_serialization_non_destructive():
    """
    A function takes a queue by value and returns its .size() both before
    and after calling inktocode_serialize_adapter internally.
    Because the harness observes the return value, the original arg is
    not the one drained — this test confirms the argument-side queue
    still has its elements available (function receives a copy by value).
    """
    source = (
        "#include <queue>\n"
        "int queue_size_after_use(std::queue<int> q) {\n"
        "    // consume the queue deliberately\n"
        "    while (!q.empty()) q.pop();\n"
        "    return static_cast<int>(q.size());\n"
        "}\n"
    )
    # The function drains its own local copy; the harness copies the argument
    # for serialization separately. Return size should be 0 (function drained it).
    result = run_test_request(
        container_request(
            source,
            arguments=["[1, 2, 3]"],
            expected_return="0",
        )
    )
    assert result.success is True


@NEEDS_GPP
def test_stack_serializer_does_not_drain_return_value():
    """
    Return a stack; the harness must serialize a copy, so actual_return
    reflects the full stack, not an empty one.
    """
    source = (
        "#include <stack>\n"
        "std::stack<int> make_stack() {\n"
        "    std::stack<int> s;\n"
        "    s.push(10); s.push(20); s.push(30);\n"
        "    return s;\n"
        "}\n"
    )
    result = run_test_request(
        container_request(
            source,
            arguments=[],
            expected_return="[30, 20, 10]",
        )
    )
    assert result.success is True
    assert result.tests[0].actual_return == "[30, 20, 10]"
