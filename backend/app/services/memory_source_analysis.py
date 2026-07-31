import hashlib
import re

from app.services.memory_diagnosis_models import (
    MemoryFinding,
    RuntimeFrame,
)


_ALLOCATION = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*(?:new(?:\s*\[\s*\])?|"
    r"(?:malloc|calloc|realloc)\s*\()"
)
_OVERWRITE = re.compile(
    r"\b(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<source>[A-Za-z_]\w*)\."
    r"(?P=name)\s*;"
)


def _line_number(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def analyze_memory_source(source: str) -> list[MemoryFinding]:
    """Return bounded suspicions only; static evidence never confirms a failure."""
    findings: list[MemoryFinding] = []
    smart_ownership = any(
        token in source
        for token in ("std::unique_ptr", "std::shared_ptr", "std::vector")
    )
    if smart_ownership:
        return findings

    for match in _OVERWRITE.finditer(source):
        name = match.group("name")
        prefix = source[: match.start()]
        if not re.search(
            rf"\b{name}\s*(?:=|\{{)\s*new\b|\bdelete(?:\s*\[\s*\])?\s+{name}\b",
            source,
        ):
            continue
        previous_statement = prefix.rsplit(";", 1)[-1]
        if re.search(rf"\bdelete(?:\s*\[\s*\])?\s+{name}\b", previous_statement):
            continue
        line = _line_number(source, match.start())
        operation = (
            "move_assignment"
            if re.search(r"operator\s*=\s*\([^)]*&&", prefix[-1000:])
            else "copy_assignment"
        )
        digest = hashlib.sha256(
            f"overwrite:{line}:{name}".encode()
        ).hexdigest()[:12]
        findings.append(
            MemoryFinding(
                finding_id=f"source-{digest}",
                category="resource_overwrite",
                subtype="owning_pointer_overwrite",
                severity="warning",
                runtime_tool="process",
                confirmed=False,
                confidence="possible",
                process_phase="unknown",
                operation_context=operation,
                frames=(
                    RuntimeFrame(
                        file="solution.cpp",
                        line=line,
                        column=None,
                        function=None,
                        student_source=True,
                    ),
                ),
                raw_summary="Owning-looking pointer assignment",
                evidence=("Conservative source-pattern analysis",),
                related_operation=operation,
            )
        )
    return findings[:8]
