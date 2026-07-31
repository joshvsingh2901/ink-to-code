from app.services.memory_diagnosis_models import (
    MemoryCategory,
    MemoryDiagnosis,
    MemoryFinding,
    SourceLocation,
)


_PRESENTATION: dict[MemoryCategory, tuple[str, str, str]] = {
    "memory_leak": ("Memory leak", "Allocated memory remained active when the program finished.", "Prefer automatic ownership or ensure cleanup happens on every exit path."),
    "use_after_free": ("Use after free", "Memory was accessed after its lifetime ended.", "Do not use the pointer or reference after the owned object has been released."),
    "double_free": ("Double deletion", "The same allocation appears to be released more than once.", "Ensure only one owner is responsible for releasing the resource."),
    "invalid_free": ("Invalid memory release", "The program attempted to release memory it did not validly own.", "Release only resources owned by this code, and release each resource once."),
    "out_of_bounds_read": ("Out-of-bounds read", "The program read outside the valid range of an array.", "Check the index against the valid bounds before reading the element."),
    "out_of_bounds_write": ("Out-of-bounds write", "The program wrote outside the valid range of an array or allocation.", "Check the index against the valid bounds before writing the element."),
    "heap_buffer_overflow": ("Heap buffer overflow", "The program accessed outside a heap allocation.", "Check indices and allocation sizes before accessing the buffer."),
    "stack_buffer_overflow": ("Stack buffer overflow", "The program accessed outside a local array.", "Check indices against the local array bounds."),
    "global_buffer_overflow": ("Global buffer overflow", "The program accessed outside a global array.", "Check indices against the global array bounds."),
    "null_pointer_access": ("Null pointer access", "The program attempted to use a null pointer.", "Check that the pointer refers to a valid object before dereferencing it."),
    "uninitialized_read": ("Uninitialized value used", "A value affected control flow before receiving a reliable value.", "Initialize the variable or object member before it is read."),
    "uninitialized_value": ("Uninitialized value used", "A value was read before being assigned a reliable value.", "Initialize the variable or object member before it is read."),
    "mismatched_allocation_deallocation": ("Mismatched memory cleanup", "The allocation and cleanup methods do not match.", "Match new with delete, new[] with delete[], and malloc-family allocation with free."),
    "overlapping_memory_operation": ("Overlapping memory operation", "A memory operation used source and destination ranges that overlap unsafely.", "Use an operation that explicitly supports overlapping ranges."),
    "invalid_pointer_arithmetic": ("Invalid pointer arithmetic", "Pointer arithmetic moved outside the valid object or allocation.", "Keep pointer arithmetic within the valid allocation bounds."),
    "resource_overwrite": ("Resource overwritten", "An owning-looking pointer may be replaced before its previous resource is released.", "Release, replace, or swap the current resource before taking new ownership."),
    "ownership_aliasing": ("Shared raw ownership", "More than one object may be responsible for the same raw resource.", "Give the resource one clear owner or make an independent copy."),
    "lifetime_error": ("Object lifetime error", "Memory was accessed outside the lifetime of its object.", "Do not retain references or pointers after the referenced object has ended."),
    "undefined_behaviour": ("Undefined behaviour", "The runtime detected an operation with undefined behaviour.", "Review the reported operation and ensure its preconditions are satisfied."),
    "unknown_memory_failure": ("Memory failure", "The memory checker detected a failure it could not classify more precisely.", "Review the technical evidence and the reported source location."),
}


def build_memory_diagnosis(
    finding: MemoryFinding,
    location: SourceLocation | None,
) -> MemoryDiagnosis:
    title, summary, direction = _PRESENTATION.get(
        finding.category,
        (
            "Memory issue",
            "The memory checker found a problem that needs review.",
            "Review resource ownership and object lifetime around the reported operation.",
        ),
    )
    if finding.category == "memory_leak" and finding.exception_active:
        title = "Memory leak after exception"
        summary = "Allocated memory remained active when the function exited through an exception."
    elif (
        finding.category == "memory_leak"
        and finding.operation_context == "move_assignment"
    ):
        title = "Resource overwritten during move assignment"
        summary = "The target's previous resource appears to have been replaced before it was released."
        direction = "Release, replace, or swap the target's current resource before taking ownership from the source."
    elif (
        finding.category == "memory_leak"
        and finding.operation_context == "copy_assignment"
    ):
        title = "Memory leak during copy assignment"
        summary = "A resource remained allocated after the target's state was replaced."
    elif (
        finding.category == "memory_leak"
        and finding.operation_context == "destructor"
    ):
        title = "Memory leak during object cleanup"
        summary = "An owned resource remained allocated when the object was destroyed."
    return MemoryDiagnosis(
        category=finding.category,
        title=title,
        confidence=finding.confidence,
        summary=summary,
        likely_cause=None,
        location=location,
        suggested_direction=direction,
        related_operation=finding.related_operation,
        confirmed_by=finding.evidence,
        technical_details=tuple(
            detail
            for detail in (
                f"Runtime tool: {finding.runtime_tool}",
                f"Process phase: {finding.process_phase}",
                (
                    f"Buffer evidence: {finding.subtype}"
                    if finding.subtype
                    in {
                        "heap_buffer_overflow",
                        "stack_buffer_overflow",
                        "global_buffer_overflow",
                    }
                    else None
                ),
                (
                    f"Leaked bytes: {finding.leaked_bytes}"
                    if finding.leaked_bytes is not None
                    else None
                ),
                (
                    f"Allocations: {finding.allocation_count}"
                    if finding.allocation_count is not None
                    else None
                ),
            )
            if detail
        ),
    )
