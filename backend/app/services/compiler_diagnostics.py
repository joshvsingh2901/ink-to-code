"""Parse compiler output into editor-friendly diagnostics."""

import re

from app.schemas.compilation import CompilerDiagnostic


_DIAGNOSTIC_PATTERN = re.compile(
    r"^.+?:(?P<line>\d+):(?P<column>\d+):\s*"
    r"(?P<severity>fatal error|error|warning|note):\s*"
    r"(?P<message>.+)$"
)


def parse_compiler_diagnostics(stderr: str) -> list[CompilerDiagnostic]:
    """Extract diagnostics without interpreting compiler messages."""

    diagnostics: list[CompilerDiagnostic] = []

    for output_line in stderr.splitlines():
        match = _DIAGNOSTIC_PATTERN.match(output_line)
        if match is None:
            continue

        severity = match.group("severity")
        diagnostics.append(
            CompilerDiagnostic(
                line=int(match.group("line")),
                column=int(match.group("column")),
                severity="error" if severity == "fatal error" else severity,
                message=match.group("message"),
            )
        )

    return diagnostics
