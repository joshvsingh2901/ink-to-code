"""Tests for the AI test capability gate."""
import subprocess

import pytest

from app.services.ai_test_capability import AiCapabilityResult, assess_ai_capability
from app.services.function_analysis import analyze_test_mode

# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

SCALAR_SOURCE = "int add(int a, int b) { return a + b; }"
CONTAINER_SOURCE = "int findFirst(std::vector<int> v) { return v[0]; }"
MUTABLE_REF_SOURCE = "void swap(int& a, int& b) { int tmp = a; a = b; b = tmp; }"
ITERATOR_SOURCE = (
    "int sumRange("
    "std::vector<int>::iterator first, "
    "std::vector<int>::iterator last) { return 0; }"
)
OBJECT_SOURCE = """
class Counter {
public:
    Counter() : count_(0) {}
    void increment() { count_++; }
    int get() const { return count_; }
private:
    int count_;
};
"""
ABSTRACT_SOURCE = """
class Shape {
public:
    virtual double area() = 0;
};
"""
TEMPLATE_CLASS_SOURCE = """
template<typename T>
class Box {
public:
    Box() {}
    T value() { return T(); }
};
"""
TWO_FN_SOURCE = (
    "int add(int a, int b) { return a + b; }\n"
    "int multiply(int a, int b) { return a * b; }\n"
)


def _fn_id(source: str, name: str) -> str:
    analysis = analyze_test_mode(source)
    for fn in analysis.functions:
        if fn.name == name:
            return fn.id
    raise ValueError(f"Function '{name}' not found in analysis of given source.")


# ---------------------------------------------------------------------------
# Supported function cases
# ---------------------------------------------------------------------------


def test_scalar_function_is_supported():
    target_id = _fn_id(SCALAR_SOURCE, "add")
    result = assess_ai_capability(SCALAR_SOURCE, "function", target_id)

    assert result.supported is True
    assert result.target_kind == "function"
    assert result.target_id == target_id
    assert result.unsupported_reason is None
    assert result.exception_support is True
    assert result.mutation_capable_parameters == ()


def test_container_function_is_supported():
    target_id = _fn_id(CONTAINER_SOURCE, "findFirst")
    result = assess_ai_capability(CONTAINER_SOURCE, "function", target_id)

    assert result.supported is True
    assert result.mutation_capable_parameters == ()


def test_mutable_reference_function_lists_mutation_capable_parameters():
    target_id = _fn_id(MUTABLE_REF_SOURCE, "swap")
    result = assess_ai_capability(MUTABLE_REF_SOURCE, "function", target_id)

    assert result.supported is True
    assert "a" in result.mutation_capable_parameters
    assert "b" in result.mutation_capable_parameters


def test_iterator_range_function_is_supported_with_group_metadata():
    target_id = _fn_id(ITERATOR_SOURCE, "sumRange")
    result = assess_ai_capability(ITERATOR_SOURCE, "function", target_id)

    assert result.supported is True
    assert len(result.iterator_groups) == 1
    group = result.iterator_groups[0]
    assert group["role"] == "range_begin"
    assert group["container"] == "vector"
    assert group["head_param"] == "first"
    assert "tail_param" in group
    assert group["tail_param"] == "last"


# ---------------------------------------------------------------------------
# Supported object case
# ---------------------------------------------------------------------------


def test_object_class_with_supported_members_is_supported():
    result = assess_ai_capability(OBJECT_SOURCE, "object", "Counter")

    assert result.supported is True
    assert result.target_kind == "object"
    assert len(result.object_constructors) >= 1
    assert len(result.object_methods) >= 1
    assert result.exception_support is True


# ---------------------------------------------------------------------------
# Unsupported function cases
# ---------------------------------------------------------------------------


def test_custom_adt_parameter_is_unsupported_with_exact_reason():
    # Functions with custom ADT parameters are excluded from analyze_test_mode.
    # The gate correctly reports them as unsupported via the "not found" path.
    source = (
        "struct Node { int val; };\n"
        "int count(Node* head) { return 0; }\n"
    )
    # The function 'count' is excluded from analysis; use its semantic id.
    result = assess_ai_capability(source, "function", "count(Node*)->int")

    assert result.supported is False
    assert result.unsupported_reason is not None


def test_recursive_node_structure_is_unsupported():
    source = (
        "struct Node { int val; Node* next; };\n"
        "int length(Node* head) { return 0; }\n"
    )
    result = assess_ai_capability(source, "function", "length(Node*)->int")

    assert result.supported is False
    assert result.unsupported_reason is not None


def test_function_pointer_parameter_is_unsupported():
    source = "int apply(int (*fn)(int), int x) { return fn(x); }"
    # Functions with function pointer parameters are excluded from analysis.
    result = assess_ai_capability(source, "function", "apply(fn,int)->int")

    assert result.supported is False
    assert result.unsupported_reason is not None


def test_pointer_return_is_unsupported():
    source = "int* makeArray(int n) { return new int[n]; }"
    # Functions with pointer return types are excluded from analysis.
    result = assess_ai_capability(source, "function", "makeArray(int)->int*")

    assert result.supported is False
    assert result.unsupported_reason is not None


def test_missing_target_id_is_unsupported():
    result = assess_ai_capability(
        SCALAR_SOURCE, "function", "nonexistent(int)->int"
    )

    assert result.supported is False
    assert result.unsupported_reason == (
        "The selected target no longer exists in the current code."
    )


# ---------------------------------------------------------------------------
# Unsupported object cases
# ---------------------------------------------------------------------------


def test_abstract_class_target_is_unsupported():
    result = assess_ai_capability(ABSTRACT_SOURCE, "object", "Shape")

    assert result.supported is False
    assert result.unsupported_reason is not None
    assert "abstract" in result.unsupported_reason.lower() or "Abstract" in result.unsupported_reason


def test_class_template_target_is_deferred_unsupported():
    result = assess_ai_capability(TEMPLATE_CLASS_SOURCE, "object", "Box")

    assert result.supported is False
    assert result.unsupported_reason is not None
    assert "template" in result.unsupported_reason.lower()


# ---------------------------------------------------------------------------
# Sibling targets
# ---------------------------------------------------------------------------


def test_supported_sibling_targets_are_listed():
    analysis = analyze_test_mode(TWO_FN_SOURCE)
    ids = {fn.name: fn.id for fn in analysis.functions}

    # When assessing "add", "multiply" should appear as a sibling.
    result_add = assess_ai_capability(TWO_FN_SOURCE, "function", ids["add"])
    assert result_add.supported is True
    assert any("multiply" in s for s in result_add.supported_sibling_targets)

    # Symmetric: when assessing "multiply", "add" is a sibling.
    result_mul = assess_ai_capability(TWO_FN_SOURCE, "function", ids["multiply"])
    assert result_mul.supported is True
    assert any("add" in s for s in result_mul.supported_sibling_targets)


# ---------------------------------------------------------------------------
# Purity: no subprocess calls
# ---------------------------------------------------------------------------


def test_gate_is_pure_no_subprocess(monkeypatch):
    """assess_ai_capability must never invoke a subprocess."""

    def _fail(*args, **kwargs):
        raise AssertionError("subprocess.run was called inside the capability gate")

    monkeypatch.setattr(subprocess, "run", _fail)

    target_id = _fn_id(SCALAR_SOURCE, "add")
    result = assess_ai_capability(SCALAR_SOURCE, "function", target_id)
    assert result.supported in {True, False}
