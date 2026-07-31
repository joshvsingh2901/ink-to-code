import pytest

from app.services.memory_classifier import classify_memory_findings
from app.services.memory_runtime_parser import (
    MAX_DIAGNOSTIC_CHARS,
    parse_memory_runtime,
)
from app.services.memory_source_analysis import analyze_memory_source


@pytest.mark.parametrize(
    ("diagnostic", "category"),
    [
        ("ERROR: AddressSanitizer: heap-use-after-free", "use_after_free"),
        ("ERROR: AddressSanitizer: attempting double-free", "double_free"),
        (
            "attempting free on address which was not malloc()-ed",
            "invalid_free",
        ),
        ("ERROR: AddressSanitizer: heap-buffer-overflow", "heap_buffer_overflow"),
        ("ERROR: AddressSanitizer: stack-buffer-overflow", "stack_buffer_overflow"),
        ("ERROR: AddressSanitizer: global-buffer-overflow", "global_buffer_overflow"),
        ("Invalid read of size 4", "out_of_bounds_read"),
        ("Invalid write of size 4", "out_of_bounds_write"),
        (
            "Conditional jump or move depends on uninitialised value(s)",
            "uninitialized_read",
        ),
        ("Use of uninitialized value of size 8", "uninitialized_value"),
        ("alloc-dealloc-mismatch (operator new [] vs operator delete)", "mismatched_allocation_deallocation"),
        ("runtime error: load of null pointer", "null_pointer_access"),
        ("runtime error: pointer overflow", "invalid_pointer_arithmetic"),
        ("ERROR: LeakSanitizer: detected memory leaks", "memory_leak"),
    ],
)
def test_runtime_tools_normalize_to_stable_categories(
    diagnostic: str, category: str
):
    findings = parse_memory_runtime(diagnostic)
    assert findings
    assert findings[0].category == category
    assert findings[0].confirmed is True


def test_source_frame_prefers_student_code_and_excludes_harness():
    source = "int broken() {\n  int *p = new int{4};\n  return *p;\n}\n"
    diagnostic = """
ERROR: LeakSanitizer: detected memory leaks
#0 0x1 in operator new /runtime/asan.cpp:10
#1 0x2 in generated_main /work/harness.cpp:88
#2 0x3 in broken /work/solution.cpp:2:12
"""
    diagnosis = classify_memory_findings(
        parse_memory_runtime(diagnostic), source
    )[0]
    assert diagnosis.location is not None
    assert diagnosis.location.start_line == 2
    assert diagnosis.location.excerpt == "  int *p = new int{4};"
    assert "harness" not in diagnosis.location.excerpt


def test_exception_leak_has_exception_specific_explanation():
    diagnoses = classify_memory_findings(
        parse_memory_runtime(
            "ERROR: LeakSanitizer: detected memory leaks"
        ),
        "void f() {}",
        exception_active=True,
    )
    assert diagnoses[0].title == "Memory leak after exception"
    assert "exception" in diagnoses[0].summary


def test_move_assignment_leak_uses_operation_context():
    diagnoses = classify_memory_findings(
        parse_memory_runtime(
            "ERROR: LeakSanitizer: detected memory leaks"
        ),
        "Number& operator=(Number&& other) {}",
        operation_context="move_assignment",
        related_operation="move_assign",
    )
    assert diagnoses[0].title == (
        "Resource overwritten during move assignment"
    )
    assert diagnoses[0].related_operation == "move_assign"


def test_related_findings_are_deduplicated_and_prioritized():
    diagnostic = "\n".join(
        [
            "ERROR: LeakSanitizer: detected memory leaks",
            "ERROR: AddressSanitizer: heap-use-after-free",
            "ERROR: AddressSanitizer: heap-use-after-free",
        ]
    )
    diagnoses = classify_memory_findings(
        parse_memory_runtime(diagnostic), "int main() {}"
    )
    assert diagnoses[0].category == "use_after_free"
    assert [item.category for item in diagnoses].count("use_after_free") == 1


def test_parser_is_bounded_and_malformed_output_falls_back_safely():
    assert parse_memory_runtime("not a sanitizer report") == []
    huge = "x" * MAX_DIAGNOSTIC_CHARS + (
        "ERROR: AddressSanitizer: heap-use-after-free"
    )
    assert parse_memory_runtime(huge) == []


def test_temporary_paths_are_not_present_in_student_facing_diagnosis():
    diagnostic = """
ERROR: AddressSanitizer: heap-use-after-free
#0 0x1 in broken /private/tmp/inktocode-tests-secret/main.cpp:1:3
"""
    diagnosis = classify_memory_findings(
        parse_memory_runtime(diagnostic), "return *value;"
    )[0]
    assert "/private/tmp" not in diagnosis.title
    assert "/private/tmp" not in diagnosis.summary
    assert "/private/tmp" not in diagnosis.suggested_direction


def test_static_source_suspicion_is_possible_not_confirmed():
    source = """
class Number {
  int *value;
  Number(int n): value{new int{n}} {}
  Number& operator=(Number&& other) {
    value = other.value;
    other.value = nullptr;
    return *this;
  }
};
"""
    findings = analyze_memory_source(source)
    assert len(findings) == 1
    assert findings[0].category == "resource_overwrite"
    assert findings[0].confidence == "possible"
    assert findings[0].confirmed is False


def test_raii_source_does_not_produce_static_memory_suspicion():
    source = """
#include <memory>
int clean() {
  auto value = std::make_unique<int>(42);
  return *value;
}
"""
    assert analyze_memory_source(source) == []


def test_raw_stdout_is_not_parsed_as_runtime_evidence():
    # The parser is called only with bounded diagnostic/stderr channels.
    assert parse_memory_runtime("") == []


@pytest.mark.parametrize(
    ("diagnostic", "source_line", "expected_category"),
    [
        (
            "main.cpp:4:12: runtime error: index 5 out of bounds "
            "for type 'int[2]'",
            "return values[5];",
            "out_of_bounds_read",
        ),
        (
            "main.cpp:4:5: runtime error: index 5 out of bounds "
            "for type 'int[2]'",
            "values[5] = 10;",
            "out_of_bounds_write",
        ),
        (
            "ERROR: AddressSanitizer: heap-buffer-overflow\n"
            "READ of size 4\nmain.cpp:4:12",
            "return values[5];",
            "out_of_bounds_read",
        ),
        (
            "ERROR: AddressSanitizer: heap-buffer-overflow\n"
            "WRITE of size 4\nmain.cpp:4:5",
            "values[5] = 10;",
            "out_of_bounds_write",
        ),
        (
            "main.cpp:4:12: runtime error: index i out of bounds "
            "for type 'int[2]'",
            "return values[i];",
            "out_of_bounds_read",
        ),
        (
            "main.cpp:4:12: runtime error: load of address 0x1 "
            "with insufficient space for an object of type 'int'",
            "return *(values + 2);",
            "out_of_bounds_read",
        ),
        (
            "main.cpp:4:5: runtime error: store to address 0x1 "
            "with insufficient space for an object of type 'int'",
            "*(values + 2) = 10;",
            "out_of_bounds_write",
        ),
        (
            "ERROR: AddressSanitizer: stack-buffer-overflow\n"
            "READ of size 4\nmain.cpp:4:12",
            "return values[5];",
            "out_of_bounds_read",
        ),
        (
            "Invalid read of size 4\nmain.cpp:4",
            "return values[5];",
            "out_of_bounds_read",
        ),
        (
            "Invalid write of size 4\nmain.cpp:4",
            "values[5] = 10;",
            "out_of_bounds_write",
        ),
    ],
)
def test_confirmed_bounds_evidence_is_refined_from_student_source(
    diagnostic: str,
    source_line: str,
    expected_category: str,
):
    source = f"int broken() {{\nint values[2] = {{1, 2}};\nint i = 5;\n{source_line}\n}}\n"
    diagnosis = classify_memory_findings(
        parse_memory_runtime(diagnostic),
        source,
    )[0]
    assert diagnosis.category == expected_category
    assert diagnosis.confidence == "confirmed"
    assert diagnosis.location is not None
    assert diagnosis.location.start_line == 4
    assert diagnosis.location.excerpt == source_line


def test_specific_bounds_finding_suppresses_generic_undefined_behaviour():
    diagnostic = """
main.cpp:4:12: runtime error: index 5 out of bounds for type 'int[2]'
SUMMARY: UndefinedBehaviorSanitizer: undefined-behavior main.cpp:4:12
"""
    diagnoses = classify_memory_findings(
        parse_memory_runtime(diagnostic),
        "int broken() {\nint values[2];\nreturn 0;\nreturn values[5];\n}",
    )
    assert [item.category for item in diagnoses] == [
        "out_of_bounds_read"
    ]


def test_duplicate_ubsan_bounds_messages_collapse_to_one_diagnosis():
    diagnostic = """
main.cpp:4:12: runtime error: index 5 out of bounds for type 'int[2]'
main.cpp:4:12: runtime error: load of address 0x1 with insufficient space
main.cpp:4:12: runtime error: index 5 out of bounds for type 'int[2]'
"""
    diagnoses = classify_memory_findings(
        parse_memory_runtime(diagnostic),
        "int broken() {\nint values[2];\nreturn 0;\nreturn values[5];\n}",
    )
    assert len(diagnoses) == 1
    assert diagnoses[0].category == "out_of_bounds_read"


def test_unrelated_undefined_behaviour_remains_generic_fallback():
    diagnoses = classify_memory_findings(
        parse_memory_runtime(
            "main.cpp:3:12: runtime error: division by zero"
        ),
        "int broken() {\nint x = 10;\nreturn x / 0;\n}",
    )
    assert diagnoses[0].category == "undefined_behaviour"
