"""
Execution tests for iterator parameter and return support.
Requires g++; each test is guarded by NEEDS_GPP.
"""

import json
import shutil

import pytest

from app.schemas.test_execution import (
    FunctionMutationExpectation,
    FunctionRunTestsRequest,
    FunctionTestCase,
)
from app.services.function_analysis import analyze_test_mode
from app.services.test_execution import (
    HarnessArgument,
    _build_function_harness,
    _prepare_iterator_arguments,
    run_test_request,
)

NEEDS_GPP = pytest.mark.skipif(
    shutil.which("g++") is None, reason="g++ is not installed"
)


def _iterator_request(
    code: str,
    *,
    arguments: list[str],
    expected_return: str | None = None,
    expected_mutations: list[dict] | None = None,
) -> FunctionRunTestsRequest:
    analysis = analyze_test_mode(code)
    assert analysis.mode == "function", (
        f"Expected function mode, got {analysis.mode} — {analysis.message}"
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
    return FunctionRunTestsRequest(
        mode="function",
        code=code,
        language="cpp",
        target_function=fn.id,
        tests=[
            FunctionTestCase(
                name="Iterator test",
                arguments=arguments,
                expected_return=expected_return,
                expected_outcome=(
                    "return_value" if expected_return is not None
                    else "return_void" if expected_mutations is not None
                    else "return_value"
                ),
                expected_mutations=mutation_objects,
            )
        ],
    )


def _head_arg(container: list, position: int) -> str:
    return json.dumps({"container": container, "position": position})


def _tail_arg(position: int) -> str:
    return json.dumps({"position": position})


# ---------------------------------------------------------------------------
# 1. Single iterator — deref result
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_single_iterator_deref():
    source = (
        "#include <vector>\n"
        "int derefFirst(std::vector<int>::iterator it) { return *it; }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=[_head_arg([10, 20, 30], 0)],
            expected_return="10",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 2. Range sum: vector iterators
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_sum_range_vector():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=[_head_arg([1, 2, 3, 4, 5], 1), _tail_arg(4)],
            expected_return="9",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 3. Empty container, range [0, 0) — returns 0
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_empty_container_empty_range():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=[_head_arg([], 0), _tail_arg(0)],
            expected_return="0",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 4. Position equal to size is accepted (end)
# ---------------------------------------------------------------------------

def test_position_equal_to_size_accepted():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    raw_args = [_head_arg([1, 2, 3], 3), _tail_arg(3)]
    # Should not raise
    result = _prepare_iterator_arguments(fn, raw_args, 0)
    assert 0 in result and 1 in result


# ---------------------------------------------------------------------------
# 5. Negative position rejected
# ---------------------------------------------------------------------------

def test_negative_position_rejected():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    raw_args = [_head_arg([1, 2, 3], -1), _tail_arg(3)]
    with pytest.raises(ValueError, match="negative"):
        _prepare_iterator_arguments(fn, raw_args, 0)


# ---------------------------------------------------------------------------
# 6. Position > size rejected
# ---------------------------------------------------------------------------

def test_position_exceeds_size_rejected():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    raw_args = [_head_arg([1, 2, 3], 4), _tail_arg(4)]
    with pytest.raises(ValueError, match="exceeds"):
        _prepare_iterator_arguments(fn, raw_args, 0)


# ---------------------------------------------------------------------------
# 7. std::list iterators use std::next, not begin()+n
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_list_iterator_range():
    source = (
        "#include <list>\n"
        "int sumRange(std::list<int>::iterator first, "
        "std::list<int>::iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=[_head_arg([10, 20, 30, 40], 1), _tail_arg(3)],
            expected_return="50",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 8. const_iterator range compiles and passes
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_const_iterator_range():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::const_iterator first, "
        "std::vector<int>::const_iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=[_head_arg([3, 5, 7], 0), _tail_arg(3)],
            expected_return="15",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 9. Mutation: doubleRange modifies backing container
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_mutation_double_range():
    source = (
        "#include <vector>\n"
        "void doubleRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " for (auto it = first; it != last; ++it) *it *= 2; }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Mutation test",
                    arguments=[
                        _head_arg([1, 2, 3, 4], 1),
                        _tail_arg(3),
                    ],
                    expected_outcome="return_void",
                    expected_mutations=[
                        FunctionMutationExpectation(
                            parameter_id="first",
                            expected_final_value="[1, 4, 6, 4]",
                        )
                    ],
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 10. Returned iterator reports Index N
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_returned_iterator_reports_index():
    source = (
        "#include <vector>\n"
        "std::vector<int>::iterator findValue("
        "std::vector<int>& values, int target) {"
        " for (auto it = values.begin(); it != values.end(); ++it)"
        "  if (*it == target) return it;"
        " return values.end(); }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=["[10, 20, 30, 40]", "20"],
            expected_return="1",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 11. Returned end() iterator reports "end"
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_returned_end_iterator_reports_end():
    source = (
        "#include <vector>\n"
        "std::vector<int>::iterator findValue("
        "std::vector<int>& values, int target) {"
        " for (auto it = values.begin(); it != values.end(); ++it)"
        "  if (*it == target) return it;"
        " return values.end(); }"
    )
    result = run_test_request(
        _iterator_request(
            source,
            arguments=["[10, 20, 30]", "99"],
            expected_return="end",
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 12. Aliasing proof: exactly ONE inktocode_iterbase_ declaration
# ---------------------------------------------------------------------------

def test_aliasing_proof_single_declaration():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    raw_args = [_head_arg([1, 2, 3], 0), _tail_arg(2)]
    iterator_args = _prepare_iterator_arguments(fn, raw_args, 0)
    harness_args = [
        iterator_args.get(i, HarnessArgument(expression=f"arg{i}"))
        for i in range(len(fn.parameters))
    ]
    harness = _build_function_harness(
        source,
        fn,
        [harness_args],
        (),
    )
    count = harness.count("inktocode_iterbase_")
    # Exactly 2 uses expected: once in declaration (LHS), once in the begin/next expr
    # But there must be exactly ONE assignment (declaration with `=`)
    decl_count = sum(
        1 for line in harness.split(";")
        if "inktocode_iterbase_" in line and "=" in line and "==" not in line and "next" not in line
    )
    assert decl_count == 1, (
        f"Expected exactly 1 declaration, found {decl_count}. Harness:\n{harness}"
    )


# ---------------------------------------------------------------------------
# 13. Iterator function that throws — exception path
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_iterator_function_throws():
    source = (
        "#include <vector>\n"
        "#include <stdexcept>\n"
        "int getAt(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last, int idx) {"
        " int i = 0;"
        " for (auto it = first; it != last; ++it, ++i)"
        "  if (i == idx) return *it;"
        " throw std::out_of_range(\"Index out of range\"); }"
    )
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function"
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Throws test",
                    arguments=[
                        _head_arg([1, 2, 3], 0),
                        _tail_arg(3),
                        "99",
                    ],
                    expected_outcome="throws",
                    expected_exception_type="std::out_of_range",
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 14. Legacy scalar/vector tests still pass with <iterator> preamble
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_scalar_legacy_regression():
    source = "int add(int a, int b) { return a + b; }"
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Scalar test",
                    arguments=["3", "4"],
                    expected_return="7",
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


@NEEDS_GPP
def test_vector_legacy_regression():
    source = (
        "#include <vector>\n"
        "int sumVec(std::vector<int> v) {"
        " int s = 0; for (int x : v) s += x; return s; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Vector test",
                    arguments=["[1, 2, 3]"],
                    expected_return="6",
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 15. Harness preamble never injects <algorithm> or <numeric>
# ---------------------------------------------------------------------------

def test_harness_preamble_never_injects_algorithm_or_numeric():
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    raw_args = [_head_arg([1], 0), _tail_arg(1)]
    iterator_args = _prepare_iterator_arguments(fn, raw_args, 0)
    harness_args = [
        iterator_args.get(i, HarnessArgument(expression=f"arg{i}"))
        for i in range(len(fn.parameters))
    ]
    harness = _build_function_harness(source, fn, [harness_args], ())
    preamble_end = harness.find(source)
    preamble = harness[:preamble_end] if preamble_end >= 0 else harness
    assert "<algorithm>" not in preamble, (
        "Harness preamble must not inject <algorithm>"
    )
    assert "<numeric>" not in preamble, (
        "Harness preamble must not inject <numeric>"
    )


# ---------------------------------------------------------------------------
# 16. Read-only mutable iterator: expected_return only, no mutation → PASS
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_read_only_mutable_iterator_no_mutation_check():
    """sumRange reads through mutable iterators but does not mutate them.
    When no expected_mutations are sent (opt-in checkbox unchecked), the
    test should pass on the return value alone without any mutation comparison."""
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    # Verify the function is recognised as having mutable iterator parameters
    mutable_iter_params = [
        p for p in fn.parameters
        if p.value_type.kind == "iterator" and p.value_type.iterator_const is False
    ]
    assert len(mutable_iter_params) > 0, (
        "sumRange should have at least one mutable iterator parameter"
    )
    # Send NO expected_mutations — mutation checking is opt-in
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Read-only test",
                    arguments=[_head_arg([1, 2, 3, 4, 5], 1), _tail_arg(4)],
                    expected_return="9",
                    expected_outcome="return_value",
                    # expected_mutations intentionally omitted
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 17. Mutable iterator with mutation checking enabled → PASS
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_mutable_iterator_with_mutation_check_passes():
    """When the user opts in to mutation checking by providing
    expected_mutations for the iterator group head, the backing container
    is compared and a correct expected value passes."""
    source = (
        "#include <vector>\n"
        "void addOne(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " for (auto it = first; it != last; ++it) *it += 1; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Mutation enabled",
                    arguments=[_head_arg([10, 20, 30], 0), _tail_arg(3)],
                    expected_outcome="return_void",
                    expected_mutations=[
                        FunctionMutationExpectation(
                            parameter_id="first",
                            expected_final_value="[11, 21, 31]",
                        )
                    ],
                )
            ],
        )
    )
    assert result.success is True, result.input_error
    assert result.tests[0].passed is True


# ---------------------------------------------------------------------------
# 18. Mutable iterator with wrong expected final container → FAIL
# ---------------------------------------------------------------------------

@NEEDS_GPP
def test_mutable_iterator_wrong_expected_final_fails():
    """When mutation checking is enabled and the expected final container
    does not match the actual result, the test must fail."""
    source = (
        "#include <vector>\n"
        "void addOne(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " for (auto it = first; it != last; ++it) *it += 1; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Wrong mutation",
                    arguments=[_head_arg([10, 20, 30], 0), _tail_arg(3)],
                    expected_outcome="return_void",
                    expected_mutations=[
                        FunctionMutationExpectation(
                            parameter_id="first",
                            # Wrong: actual result is [11, 21, 31]
                            expected_final_value="[10, 20, 30]",
                        )
                    ],
                )
            ],
        )
    )
    assert result.input_error is None
    assert len(result.tests) == 1
    assert result.tests[0].passed is False


# ---------------------------------------------------------------------------
# 19. const_iterator: not in mutation_capable_parameters
# ---------------------------------------------------------------------------

def test_const_iterator_not_mutation_capable():
    """const_iterator parameters must never appear in mutation_capable_parameters,
    so sending any expected_mutations for them must be rejected."""
    source = (
        "#include <vector>\n"
        "int sumRange(std::vector<int>::const_iterator first, "
        "std::vector<int>::const_iterator last) {"
        " int s = 0;"
        " for (auto it = first; it != last; ++it) s += *it;"
        " return s; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    # Confirm neither parameter is mutation-capable
    for p in fn.parameters:
        assert p.value_type.iterator_const is True, (
            f"const_iterator param {p.name} must have iterator_const=True"
        )
    # Sending expected_mutations for a const_iterator must be rejected
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Const mutation attempt",
                    arguments=[_head_arg([1, 2, 3], 0), _tail_arg(3)],
                    expected_outcome="return_value",
                    expected_return="6",
                    expected_mutations=[
                        FunctionMutationExpectation(
                            parameter_id="first",
                            expected_final_value="[1, 2, 3]",
                        )
                    ],
                )
            ],
        )
    )
    assert result.success is False
    assert result.input_error is not None


# ---------------------------------------------------------------------------
# 20. range_end must not appear in expected_mutations (only range_begin)
# ---------------------------------------------------------------------------

def test_range_end_in_expected_mutations_rejected():
    """Only the range_begin (head) parameter should carry mutation expectations.
    Sending expected_mutations for range_end must be rejected because it is
    not in mutation_capable_parameters."""
    source = (
        "#include <vector>\n"
        "void addOne(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) {"
        " for (auto it = first; it != last; ++it) *it += 1; }"
    )
    analysis = analyze_test_mode(source)
    fn = analysis.functions[0]
    result = run_test_request(
        FunctionRunTestsRequest(
            mode="function",
            code=source,
            language="cpp",
            target_function=fn.id,
            tests=[
                FunctionTestCase(
                    name="Range end mutation attempt",
                    arguments=[_head_arg([1, 2, 3], 0), _tail_arg(3)],
                    expected_outcome="return_void",
                    expected_mutations=[
                        FunctionMutationExpectation(
                            parameter_id="last",  # range_end — invalid
                            expected_final_value="[1, 2, 3]",
                        )
                    ],
                )
            ],
        )
    )
    assert result.success is False
    assert result.input_error is not None
