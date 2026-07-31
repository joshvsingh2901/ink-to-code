import hashlib
import re

from app.services.memory_diagnosis_models import (
    MemoryCategory,
    MemoryFinding,
    RuntimeFrame,
)


MAX_DIAGNOSTIC_CHARS = 256_000
MAX_FINDINGS = 32
MAX_FRAMES_PER_FINDING = 24

_FRAME = re.compile(
    r"(?:#\d+\s+.*?\s+in\s+(?P<function>.*?)\s+)?"
    r"(?P<file>(?:[A-Za-z]:)?[^()\s]+?\.(?:cpp|cc|cxx|h|hpp))"
    r":(?P<line>\d+)(?::(?P<column>\d+))?"
)
_ACCESS_SIZE = re.compile(r"\b(?:READ|WRITE) of size (?P<size>\d+)\b")
_BOUNDS_OPERATION = re.compile(
    r"\b(?P<operation>READ|WRITE)\s+of\s+size\b|"
    r"\b(?P<load_store>load|store)\s+(?:of|to)\s+(?:address|value)\b",
    re.IGNORECASE,
)
_LEAK_SIZE = re.compile(
    r"(?P<bytes>\d+)\s+byte\(s\).*?(?P<count>\d+)\s+object\(s\)"
)
_VALGRIND_LOSS = re.compile(
    r"(?P<bytes>[\d,]+) bytes in (?P<count>[\d,]+) blocks"
)

# Order matters: more specific runtime signatures precede broad fallbacks.
_TOOL_PATTERNS: tuple[
    tuple[re.Pattern[str], MemoryCategory, str, str], ...
] = (
    (re.compile(r"heap-use-after-free", re.I), "use_after_free", "heap", "asan"),
    (re.compile(r"stack-use-after-(?:scope|return)", re.I), "lifetime_error", "stack", "asan"),
    (re.compile(r"attempting double-free|double free", re.I), "double_free", "repeated_release", "asan"),
    (re.compile(r"attempting free on address which was not malloc|invalid free|InvalidFree", re.I), "invalid_free", "non_owned_release", "asan"),
    (re.compile(r"alloc-dealloc-mismatch|mismatched free|MismatchedFree", re.I), "mismatched_allocation_deallocation", "allocation_form", "asan"),
    (re.compile(r"heap-buffer-overflow", re.I), "heap_buffer_overflow", "heap_buffer_overflow", "asan"),
    (re.compile(r"stack-buffer-overflow", re.I), "stack_buffer_overflow", "stack_buffer_overflow", "asan"),
    (re.compile(r"global-buffer-overflow", re.I), "global_buffer_overflow", "global_buffer_overflow", "asan"),
    (re.compile(r"invalid read", re.I), "out_of_bounds_read", "invalid_read", "valgrind"),
    (re.compile(r"invalid write", re.I), "out_of_bounds_write", "invalid_write", "valgrind"),
    (
        re.compile(
            r"(?:index\s+.+?\s+out of bounds|"
            r"runtime error:\s*index\s+.+?\s+out of bounds|"
            r"(?:load of|store to) address .+? with insufficient space|"
            r"address is located .+? past the end|"
            r"one-past-(?:the-)?end(?:\s+dereference)?)",
            re.I | re.S,
        ),
        "out_of_bounds_read",
        "bounds_violation",
        "ubsan",
    ),
    (re.compile(r"conditional jump.*uninitiali[sz]ed", re.I), "uninitialized_read", "conditional", "valgrind"),
    (re.compile(r"use of uninitiali[sz]ed value", re.I), "uninitialized_value", "value", "valgrind"),
    (re.compile(r"overlap(?:ping|s)", re.I), "overlapping_memory_operation", "overlap", "valgrind"),
    (re.compile(r"detected memory leaks|definitely lost:", re.I), "memory_leak", "confirmed", "lsan"),
    (re.compile(r"null pointer|load of null|store to null", re.I), "null_pointer_access", "null", "ubsan"),
    (re.compile(r"pointer overflow|outside the bounds of an object", re.I), "invalid_pointer_arithmetic", "pointer_arithmetic", "ubsan"),
    (re.compile(r"runtime error:", re.I), "undefined_behaviour", "runtime_error", "ubsan"),
    (re.compile(r"AddressSanitizer:.*(?:SEGV|DEADLYSIGNAL)", re.I), "unknown_memory_failure", "signal", "asan"),
)


def _bounds_access_category(
    text: str,
    default: MemoryCategory,
) -> MemoryCategory:
    operation = _BOUNDS_OPERATION.search(text)
    if operation:
        value = (
            operation.group("operation")
            or operation.group("load_store")
            or ""
        ).lower()
        return (
            "out_of_bounds_write"
            if value in {"write", "store"}
            else "out_of_bounds_read"
        )
    return default


def _student_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith("/solution.cpp") or normalized.endswith("/main.cpp") or normalized in {"solution.cpp", "main.cpp"}


def _frames(text: str) -> tuple[RuntimeFrame, ...]:
    frames: list[RuntimeFrame] = []
    role: RuntimeFrame.__annotations__["role"] = "other"  # type: ignore[assignment]
    for line in text.splitlines():
        lowered = line.lower()
        if "allocated by" in lowered:
            role = "allocation"
        elif "freed by" in lowered:
            role = "deallocation"
        match = _FRAME.search(line)
        if not match:
            continue
        frames.append(
            RuntimeFrame(
                file=match.group("file"),
                line=int(match.group("line")),
                column=(
                    int(match.group("column"))
                    if match.group("column")
                    else None
                ),
                function=(match.group("function") or "").strip() or None,
                role=role,
                student_source=_student_file(match.group("file")),
            )
        )
        if len(frames) >= MAX_FRAMES_PER_FINDING:
            break
    return tuple(frames)


def parse_memory_runtime(
    diagnostics: str,
    *,
    provider: str = "host",
    process_phase: str = "run",
) -> list[MemoryFinding]:
    """Normalize bounded, untrusted tool output without student-facing wording."""
    text = diagnostics[:MAX_DIAGNOSTIC_CHARS]
    findings: list[MemoryFinding] = []
    for pattern, category, subtype, tool in _TOOL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if category in {
            "heap_buffer_overflow",
            "stack_buffer_overflow",
            "global_buffer_overflow",
            "out_of_bounds_read",
            "out_of_bounds_write",
        }:
            category = _bounds_access_category(text, category)
        access_match = _ACCESS_SIZE.search(text)
        leak_match = _LEAK_SIZE.search(text) or _VALGRIND_LOSS.search(text)
        digest = hashlib.sha256(
            f"{category}:{subtype}:{match.start()}".encode()
        ).hexdigest()[:12]
        findings.append(
            MemoryFinding(
                finding_id=f"memory-{digest}",
                category=category,
                subtype=subtype,
                severity="error",
                runtime_tool=tool,  # type: ignore[arg-type]
                confirmed=True,
                confidence="confirmed",
                process_phase=process_phase,  # type: ignore[arg-type]
                frames=_frames(text),
                leaked_bytes=(
                    int(leak_match.group("bytes").replace(",", ""))
                    if leak_match
                    else None
                ),
                allocation_count=(
                    int(leak_match.group("count").replace(",", ""))
                    if leak_match
                    else None
                ),
                access_size=(
                    int(access_match.group("size")) if access_match else None
                ),
                raw_summary=match.group(0)[:300],
                evidence=(f"{tool.upper()} runtime report",),
                provider="docker" if provider == "docker" else "host",
            )
        )
        if len(findings) >= MAX_FINDINGS:
            break
    return findings
