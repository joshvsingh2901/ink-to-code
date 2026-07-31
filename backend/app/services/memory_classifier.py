import re
from dataclasses import replace

from app.services.memory_diagnosis_models import (
    MemoryDiagnosis,
    MemoryFinding,
)
from app.services.memory_explanations import build_memory_diagnosis
from app.services.memory_source_mapping import map_finding_to_source


_PRIORITY = {
    "use_after_free": 0,
    "double_free": 1,
    "invalid_free": 2,
    "mismatched_allocation_deallocation": 3,
    "heap_buffer_overflow": 4,
    "stack_buffer_overflow": 5,
    "global_buffer_overflow": 6,
    "out_of_bounds_write": 7,
    "out_of_bounds_read": 8,
    "null_pointer_access": 9,
    "invalid_pointer_arithmetic": 10,
    "uninitialized_read": 11,
    "uninitialized_value": 11,
    "memory_leak": 12,
    "undefined_behaviour": 13,
    "memory_check_incomplete": 14,
}


_INDEXED_ACCESS = re.compile(
    r"(?:\b[A-Za-z_]\w*\s*\[[^\]]+\]|\*\s*\([^)]*\+[^)]*\))"
)
_WRITE_ACCESS = re.compile(
    r"(?:\+\+|--)\s*(?:[A-Za-z_]\w*\s*\[[^\]]+\]|\*\s*\([^)]*\+[^)]*\))|"
    r"(?:[A-Za-z_]\w*\s*\[[^\]]+\]|\*\s*\([^)]*\+[^)]*\))"
    r"\s*(?:(?:\+\+|--)|(?:[+\-*/%&|^]?=(?!=)))"
)


def _student_line(finding: MemoryFinding) -> int | None:
    return next(
        (
            frame.line
            for frame in finding.frames
            if frame.student_source and frame.line is not None
        ),
        None,
    )


def _student_column(finding: MemoryFinding) -> int | None:
    return next(
        (
            frame.column
            for frame in finding.frames
            if frame.student_source
            and frame.line is not None
            and frame.column is not None
        ),
        None,
    )


def _refine_bounds_access(
    finding: MemoryFinding,
    source: str,
) -> MemoryFinding:
    if finding.category not in {
        "out_of_bounds_read",
        "out_of_bounds_write",
        "heap_buffer_overflow",
        "stack_buffer_overflow",
        "global_buffer_overflow",
    }:
        return finding
    line_number = _student_line(finding)
    lines = source.splitlines()
    if line_number is None or not 1 <= line_number <= len(lines):
        return finding
    source_line = lines[line_number - 1]
    accesses = list(_INDEXED_ACCESS.finditer(source_line))
    if not accesses:
        return finding
    column = _student_column(finding)
    access = (
        min(
            accesses,
            key=lambda match: abs(match.start() - max(column - 1, 0)),
        )
        if column is not None
        else accesses[-1]
    )
    fragment = source_line[
        max(access.start() - 2, 0) : min(access.end() + 4, len(source_line))
    ]
    category = (
        "out_of_bounds_write"
        if _WRITE_ACCESS.search(fragment)
        else "out_of_bounds_read"
    )
    return replace(
        finding,
        category=category,
        subtype=(
            finding.subtype
            if finding.subtype
            in {
                "heap_buffer_overflow",
                "stack_buffer_overflow",
                "global_buffer_overflow",
            }
            else f"{finding.subtype or 'bounds_violation'}_{category.rsplit('_', 1)[-1]}"
        ),
    )


def _suppress_generic_undefined_behaviour(
    findings: list[MemoryFinding],
) -> list[MemoryFinding]:
    specific_lines = {
        _student_line(finding)
        for finding in findings
        if finding.category != "undefined_behaviour"
    }
    return [
        finding
        for finding in findings
        if not (
            finding.category == "undefined_behaviour"
            and _student_line(finding) in specific_lines
        )
    ]


def _deduplicate(findings: list[MemoryFinding]) -> list[MemoryFinding]:
    seen: set[tuple[object, ...]] = set()
    unique: list[MemoryFinding] = []
    for finding in findings:
        student_line = _student_line(finding)
        key = (
            finding.category,
            student_line,
            finding.operation_context,
            finding.related_step,
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def classify_memory_findings(
    findings: list[MemoryFinding],
    source: str,
    *,
    exception_active: bool = False,
    operation_context: str = "unknown",
    related_operation: str | None = None,
) -> list[MemoryDiagnosis]:
    normalized = [
        replace(
            finding,
            exception_active=(
                exception_active and finding.category == "memory_leak"
            ),
            operation_context=(
                operation_context
                if finding.operation_context == "unknown"
                else finding.operation_context
            ),
            related_operation=(
                related_operation or finding.related_operation
            ),
        )
        for finding in findings
    ]
    normalized = [
        _refine_bounds_access(finding, source)
        for finding in normalized
    ]
    normalized = _deduplicate(
        _suppress_generic_undefined_behaviour(normalized)
    )
    normalized.sort(key=lambda item: _PRIORITY.get(item.category, 50))
    diagnoses = [
        build_memory_diagnosis(
            finding,
            map_finding_to_source(finding, source),
        )
        for finding in normalized[:3]
    ]
    return diagnoses
