"""Tests for iterator-type parsing and grouping in function_analysis.py.

No compilation or execution — metadata only.
"""
import pytest
from app.services.function_analysis import analyze_test_mode


def _find_function(source: str):
    analysis = analyze_test_mode(source)
    assert analysis.mode == "function", f"Expected function mode, got: {analysis.mode} — {analysis.message}"
    assert len(analysis.functions) == 1
    return analysis.functions[0]


def _unsupported(source: str):
    analysis = analyze_test_mode(source)
    return analysis.mode, analysis.message


# ─── Parameter parsing ────────────────────────────────────────────────────────

def test_vector_iterator_parameter():
    fn = _find_function(
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    assert fn.parameters[0].value_type.kind == "iterator"
    assert fn.parameters[0].value_type.iterator_container == "vector"
    assert fn.parameters[0].value_type.element_type == "int"
    assert fn.parameters[0].value_type.iterator_const is False
    assert fn.parameters[0].value_type.passing == "value"


def test_deque_iterator_parameter():
    fn = _find_function(
        "int f(std::deque<int>::iterator it) { return 0; }"
    )
    assert fn.parameters[0].value_type.kind == "iterator"
    assert fn.parameters[0].value_type.iterator_container == "deque"


def test_list_iterator_parameter():
    fn = _find_function(
        "int f(std::list<int>::iterator it) { return 0; }"
    )
    assert fn.parameters[0].value_type.kind == "iterator"
    assert fn.parameters[0].value_type.iterator_container == "list"


def test_array_iterator_parameter():
    fn = _find_function(
        "int f(std::array<int, 3>::iterator it) { return 0; }"
    )
    vt = fn.parameters[0].value_type
    assert vt.kind == "iterator"
    assert vt.iterator_container == "array"
    assert vt.fixed_size == 3


def test_const_iterator_sets_const_flag():
    fn = _find_function(
        "int f(std::vector<int>::const_iterator it) { return 0; }"
    )
    assert fn.parameters[0].value_type.iterator_const is True


def test_adjacent_same_type_pair_becomes_range():
    fn = _find_function(
        "int sumRange(std::vector<int>::iterator first, "
        "std::vector<int>::iterator last) { return 0; }"
    )
    p0 = fn.parameters[0].value_type
    p1 = fn.parameters[1].value_type
    assert p0.iterator_role == "range_begin"
    assert p1.iterator_role == "range_end"
    assert p0.iterator_group_index == 0
    assert p1.iterator_group_index == 0


def test_adjacent_different_types_become_separate_singles():
    fn = _find_function(
        "int f(std::vector<int>::iterator a, "
        "std::list<int>::iterator b) { return 0; }"
    )
    p0 = fn.parameters[0].value_type
    p1 = fn.parameters[1].value_type
    assert p0.iterator_role == "single"
    assert p1.iterator_role == "single"
    assert p0.iterator_group_index == 0
    assert p1.iterator_group_index == 1


def test_three_adjacent_same_type_is_rejected():
    mode, msg = _unsupported(
        "int f(std::vector<int>::iterator a, "
        "std::vector<int>::iterator b, "
        "std::vector<int>::iterator c) { return 0; }"
    )
    assert mode == "unsupported"
    assert "ambiguous" in msg.lower()


# ─── Rejected iterator types ──────────────────────────────────────────────────

def test_reverse_iterator_is_rejected():
    mode, msg = _unsupported(
        "int f(std::vector<int>::reverse_iterator it) { return 0; }"
    )
    assert mode == "unsupported"
    assert "iterator" in msg.lower() or "unsupported" in msg.lower()


def test_set_iterator_is_rejected():
    mode, msg = _unsupported(
        "int f(std::set<int>::iterator it) { return 0; }"
    )
    assert mode == "unsupported"
    assert "iterator" in msg.lower() or "unsupported" in msg.lower()


def test_nested_element_iterator_is_rejected():
    mode, msg = _unsupported(
        "int f(std::vector<std::vector<int>>::iterator it) { return 0; }"
    )
    assert mode == "unsupported"


# ─── Iterator return types ────────────────────────────────────────────────────

def test_iterator_return_with_one_matching_backing_is_supported():
    fn = _find_function(
        "std::vector<int>::iterator findValue("
        "std::vector<int>& values, int target) { return values.begin(); }"
    )
    rvt = fn.return_value_type
    assert rvt.kind == "iterator"
    assert rvt.supported is True
    assert rvt.iterator_group_index is not None


def test_iterator_return_with_zero_candidates_is_unsupported():
    fn = _find_function(
        "std::vector<int>::iterator findValue(int x, int y) { return {}; }"
    )
    rvt = fn.return_value_type
    assert rvt.kind == "iterator"
    assert rvt.supported is False
    assert "unambiguously" in rvt.unsupported_reason.lower()


def test_iterator_return_with_two_candidates_is_unsupported():
    fn = _find_function(
        "std::vector<int>::iterator f("
        "std::vector<int>& a, std::vector<int>& b) { return a.begin(); }"
    )
    rvt = fn.return_value_type
    assert rvt.kind == "iterator"
    assert rvt.supported is False
    assert "unambiguously" in rvt.unsupported_reason.lower()
