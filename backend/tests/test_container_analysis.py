"""
Pure unit tests for STL container type parsing in function_analysis.py.
No compilation required.
"""

import pytest

from app.services.function_analysis import _parse_value_type, analyze_test_mode


def _source_with_param(param_decl: str) -> str:
    return f"void f({param_decl}) {{}}"


def _source_with_return(return_type: str) -> str:
    return f"{return_type} f() {{ {return_type} v; return v; }}"


def _parse_param(param_decl: str):
    """Parse a single-parameter function and return the ValueType, or None on rejection."""
    vt, err = _parse_value_type(
        param_decl,
        allow_reference=True,
        unqualified_vector_allowed=False,
    )
    return vt, err


# ---------------------------------------------------------------------------
# Sequence containers
# ---------------------------------------------------------------------------


def test_deque_int_param():
    vt, err = _parse_param("std::deque<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "deque"
    assert vt.container_family == "sequence"
    assert vt.ordered is True
    assert vt.associative is False
    assert vt.unordered is False
    assert vt.adapter is False


def test_list_int_return():
    vt, err = _parse_value_type(
        "std::list<int>",
        allow_reference=False,
        unqualified_vector_allowed=False,
    )
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "list"
    assert vt.container_family == "sequence"


# ---------------------------------------------------------------------------
# Set containers
# ---------------------------------------------------------------------------


def test_set_int():
    vt, err = _parse_param("std::set<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "set"
    assert vt.container_family == "associative"
    assert vt.ordered is True
    assert vt.associative is True
    assert vt.unordered is False


def test_multiset_int():
    vt, err = _parse_param("std::multiset<int>")
    assert err is None
    assert vt is not None
    assert vt.container_name == "multiset"
    assert vt.unordered is False


def test_unordered_set_int():
    vt, err = _parse_param("std::unordered_set<int>")
    assert err is None
    assert vt is not None
    assert vt.container_name == "unordered_set"
    assert vt.unordered is True
    assert vt.container_family == "unordered"


# ---------------------------------------------------------------------------
# Map containers
# ---------------------------------------------------------------------------


def test_map_string_int():
    vt, err = _parse_param("std::map<std::string, int>")
    assert err is None
    assert vt is not None
    assert vt.container_name == "map"
    assert vt.key_type == "std::string"
    assert vt.mapped_type == "int"
    assert vt.container_family == "associative"


def test_multimap_string_int():
    vt, err = _parse_param("std::multimap<std::string, int>")
    assert err is None
    assert vt is not None
    assert vt.container_name == "multimap"
    assert vt.container_family == "associative"


def test_unordered_map_string_int():
    vt, err = _parse_param("std::unordered_map<std::string, int>")
    assert err is None
    assert vt is not None
    assert vt.container_name == "unordered_map"
    assert vt.unordered is True
    assert vt.key_type == "std::string"
    assert vt.mapped_type == "int"


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------


def test_nested_set_vector_rejected():
    vt, err = _parse_param("std::set<std::vector<int>>")
    assert vt is None
    assert err is not None
    assert "not yet supported" in err


def test_nested_deque_map_rejected():
    vt, err = _parse_param("std::deque<std::map<std::string, int>>")
    assert vt is None
    assert err is not None
    assert "not yet supported" in err


def test_array_vector_rejected():
    """std::array<std::vector<int>, 3> is intentionally postponed."""
    vt, err = _parse_param("std::array<std::vector<int>, 3>")
    assert vt is None
    assert err is not None


def test_stack_accepted():
    vt, err = _parse_param("std::stack<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "stack"
    assert vt.container_family == "adapter"
    assert vt.adapter is True


def test_queue_accepted():
    vt, err = _parse_param("std::queue<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "queue"
    assert vt.adapter is True


def test_priority_queue_accepted():
    vt, err = _parse_param("std::priority_queue<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "container"
    assert vt.container_name == "priority_queue"
    assert vt.adapter is True


# ---------------------------------------------------------------------------
# Legacy vector regressions — must be unchanged
# ---------------------------------------------------------------------------


def test_legacy_vector_int():
    vt, err = _parse_param("std::vector<int>")
    assert err is None
    assert vt is not None
    assert vt.kind == "vector"
    assert vt.vector_depth == 1


def test_legacy_vector_vector_int():
    vt, err = _parse_param("std::vector<std::vector<int>>")
    assert err is None
    assert vt is not None
    assert vt.kind == "vector"
    assert vt.vector_depth == 2
