from dataclasses import dataclass, field
from typing import Literal


MemoryCategory = Literal[
    "memory_leak",
    "use_after_free",
    "double_free",
    "invalid_free",
    "out_of_bounds_read",
    "out_of_bounds_write",
    "stack_buffer_overflow",
    "heap_buffer_overflow",
    "global_buffer_overflow",
    "null_pointer_access",
    "uninitialized_read",
    "uninitialized_value",
    "mismatched_allocation_deallocation",
    "overlapping_memory_operation",
    "invalid_pointer_arithmetic",
    "dangling_reference",
    "lifetime_error",
    "resource_overwrite",
    "ownership_aliasing",
    "destructor_failure",
    "cleanup_failure",
    "undefined_behaviour",
    "memory_limit_exceeded",
    "allocator_failure",
    "leak_check_unavailable",
    "memory_check_incomplete",
    "unknown_memory_failure",
]

OperationContext = Literal[
    "normal_return",
    "early_return",
    "exception_exit",
    "constructor",
    "partial_construction",
    "destructor",
    "copy_constructor",
    "copy_assignment",
    "move_constructor",
    "move_assignment",
    "method_call",
    "observer_call",
    "operator_call",
    "array_access",
    "pointer_dereference",
    "deallocation",
    "object_cleanup",
    "scenario_cleanup",
    "temporary_object",
    "polymorphic_call",
    "base_pointer_deletion",
    "derived_destruction",
    "base_destruction",
    "object_slicing",
    "dynamic_cast",
    "unknown",
]


@dataclass(frozen=True)
class RuntimeFrame:
    file: str
    line: int | None
    column: int | None
    function: str | None
    role: Literal[
        "access", "allocation", "deallocation", "creation", "destruction", "other"
    ] = "other"
    student_source: bool = False


@dataclass(frozen=True)
class MemoryFinding:
    finding_id: str
    category: MemoryCategory
    subtype: str | None
    severity: Literal["error", "warning", "incomplete"]
    runtime_tool: Literal["asan", "ubsan", "lsan", "valgrind", "process"]
    confirmed: bool
    confidence: Literal["confirmed", "likely", "possible"]
    process_phase: Literal["compile", "run", "cleanup", "unknown"]
    operation_context: OperationContext = "unknown"
    frames: tuple[RuntimeFrame, ...] = ()
    leaked_bytes: int | None = None
    allocation_count: int | None = None
    access_size: int | None = None
    raw_summary: str = ""
    evidence: tuple[str, ...] = ()
    related_step: int | None = None
    related_object: str | None = None
    related_operation: str | None = None
    exception_active: bool = False
    provider: Literal["host", "docker"] = "host"


@dataclass(frozen=True)
class SourceLocation:
    start_line: int
    end_line: int
    excerpt: str
    label: str
    confidence: Literal["confirmed", "likely", "possible"] = "likely"


@dataclass(frozen=True)
class MemoryDiagnosis:
    category: MemoryCategory
    title: str
    confidence: Literal["confirmed", "likely", "possible"]
    summary: str
    likely_cause: str | None
    location: SourceLocation | None
    suggested_direction: str
    related_operation: str | None
    confirmed_by: tuple[str, ...] = ()
    technical_details: tuple[str, ...] = ()
    supporting_findings: tuple[str, ...] = field(default_factory=tuple)
