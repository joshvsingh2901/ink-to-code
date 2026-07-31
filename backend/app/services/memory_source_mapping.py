from app.services.memory_diagnosis_models import (
    MemoryFinding,
    SourceLocation,
)


MAX_EXCERPT_CHARS = 500


def map_finding_to_source(
    finding: MemoryFinding,
    source: str,
) -> SourceLocation | None:
    """Choose the smallest useful student frame; harness frames stay technical."""
    preferred_roles = {
        "memory_leak": ("allocation", "other"),
        "use_after_free": ("access", "other"),
        "double_free": ("deallocation", "other"),
        "invalid_free": ("deallocation", "other"),
        "out_of_bounds_read": ("access", "other"),
        "out_of_bounds_write": ("access", "other"),
        "heap_buffer_overflow": ("access", "other"),
        "stack_buffer_overflow": ("access", "other"),
        "global_buffer_overflow": ("access", "other"),
    }.get(finding.category, ("other", "access", "allocation", "deallocation"))
    student_frames = [frame for frame in finding.frames if frame.student_source and frame.line]
    frame = next(
        (
            candidate
            for role in preferred_roles
            for candidate in student_frames
            if candidate.role == role
        ),
        student_frames[0] if student_frames else None,
    )
    if frame is None or frame.line is None:
        return None
    lines = source.splitlines()
    if frame.line < 1 or frame.line > len(lines):
        return None
    excerpt = lines[frame.line - 1][:MAX_EXCERPT_CHARS]
    return SourceLocation(
        start_line=frame.line,
        end_line=frame.line,
        excerpt=excerpt,
        label=f"Line {frame.line}",
        confidence="likely",
    )
