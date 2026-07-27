import re

from app.schemas.compilation import CompilerDiagnostic
from app.schemas.compiler_suggestions import (
    CompilerSuggestionResponse,
    FixSuggestion,
)


_IDENTIFIER_SUGGESTION = re.compile(
    r"(?:'|‘)(?P<original>[A-Za-z_][A-Za-z0-9_]*)(?:'|’)"
    r".{0,240}?\bdid you mean\s+"
    r"(?:'|‘)(?P<replacement>[A-Za-z_][A-Za-z0-9_]*)(?:'|’)",
    re.IGNORECASE,
)
_SUPPORTED_DIAGNOSTIC_MARKERS = (
    "use of undeclared identifier",
    "undeclared identifier",
    "was not declared in this scope",
)


def extract_compiler_suggestion(
    code: str,
    diagnostic: CompilerDiagnostic,
    diagnostic_index: int,
) -> FixSuggestion | None:
    """Return only an explicit, source-verified compiler token replacement."""

    if diagnostic.severity not in {"error", "warning"}:
        return None

    normalized_message = diagnostic.message.lower()
    if not any(
        marker in normalized_message
        for marker in _SUPPORTED_DIAGNOSTIC_MARKERS
    ):
        return None

    match = _IDENTIFIER_SUGGESTION.search(diagnostic.message)
    if match is None:
        return None

    original = match.group("original")
    replacement = match.group("replacement")
    if original == replacement:
        return None

    lines = code.split("\n")
    if not 1 <= diagnostic.line <= len(lines):
        return None
    line = lines[diagnostic.line - 1]
    if not line.isascii() or not 1 <= diagnostic.column <= len(line):
        return None

    start_column = diagnostic.column
    end_column = start_column + len(original)
    if line[start_column - 1 : end_column - 1] != original:
        return None

    return FixSuggestion(
        diagnostic_index=diagnostic_index,
        source="compiler",
        start_line=diagnostic.line,
        start_column=start_column,
        end_line=diagnostic.line,
        end_column=end_column,
        original_text=original,
        replacement_text=replacement,
        explanation=f"The compiler suggests the declared identifier '{replacement}'.",
    )


def get_compiler_suggestions(
    code: str,
    diagnostics: list[CompilerDiagnostic],
) -> CompilerSuggestionResponse:
    suggestions = [
        suggestion
        for index, diagnostic in enumerate(diagnostics)
        if (
            suggestion := extract_compiler_suggestion(
                code, diagnostic, index
            )
        )
        is not None
    ]
    return CompilerSuggestionResponse(suggestions=suggestions)
