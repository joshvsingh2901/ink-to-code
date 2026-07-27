import re

from app.schemas.compilation import CompilerDiagnostic


_QUOTED_IDENTIFIER = r"(?:'|‘)(?P<token>[A-Za-z_][A-Za-z0-9_]*)(?:'|’)"
_UNDECLARED_IDENTIFIER = re.compile(
    rf"(?:undeclared identifier\s+{_QUOTED_IDENTIFIER}|"
    rf"{_QUOTED_IDENTIFIER.replace('token', 'gcc_token')}\s+was not declared "
    r"in this scope)",
    re.IGNORECASE,
)
_UNKNOWN_TYPE = re.compile(
    rf"unknown type name\s+{_QUOTED_IDENTIFIER}",
    re.IGNORECASE,
)
_MATCHING_OPEN_BRACE_NOTE = re.compile(
    r"^to match this\s+(?:'|‘)\{(?:'|’)$",
    re.IGNORECASE,
)


def _captured_token(match: re.Match[str] | None) -> str | None:
    if match is None:
        return None
    return match.groupdict().get("token") or match.groupdict().get("gcc_token")


def explanation_for_message(message: str) -> str | None:
    """Translate only recognized compiler messages without proposing a fix."""

    normalized = message.lower()

    undeclared = _captured_token(_UNDECLARED_IDENTIFIER.search(message))
    if undeclared:
        return (
            f"`{undeclared}` has not been declared or is not visible at this "
            "point in the program."
        )

    unknown_type = _captured_token(_UNKNOWN_TYPE.search(message))
    if unknown_type:
        return f"`{unknown_type}` is not recognized as a type."

    if "expected expression" in normalized:
        return (
            "The compiler could not understand the syntax at this location. "
            "Check this line and the code immediately before it."
        )

    if re.search(r"\bexpected\s+(?:'|‘)\}(?:'|’)", message, re.IGNORECASE):
        return (
            "A closing `}` is missing somewhere in the surrounding block "
            "structure."
        )

    if re.search(r"\bexpected\s+(?:'|‘);(?:'|’)", message, re.IGNORECASE):
        return "The compiler expected a semicolon near this location."

    if re.search(r"\bexpected\s+(?:'|‘)\)(?:'|’)", message, re.IGNORECASE):
        return "The compiler expected a closing `)` near this location."

    if re.search(r"\bexpected\s+(?:'|‘)\](?:'|’)", message, re.IGNORECASE):
        return "The compiler expected a closing `]` near this location."

    if "invalid operands" in normalized or "invalid operand" in normalized:
        return (
            "The values or expressions used with this operator are not "
            "compatible."
        )

    if "redefinition" in normalized or "redeclaration" in normalized:
        return (
            "This name has already been declared or defined in a conflicting "
            "way."
        )

    return None


def add_compiler_explanations(
    diagnostics: list[CompilerDiagnostic],
) -> list[CompilerDiagnostic]:
    """Add conservative explanations while retaining every parsed diagnostic."""

    enriched: list[CompilerDiagnostic] = []

    for index, diagnostic in enumerate(diagnostics):
        explanation = (
            explanation_for_message(diagnostic.message)
            if diagnostic.severity != "note"
            else None
        )

        if explanation and "closing `}` is missing" in explanation:
            for related in diagnostics[index + 1 :]:
                if related.severity != "note":
                    break
                if _MATCHING_OPEN_BRACE_NOTE.fullmatch(related.message):
                    explanation += (
                        " The compiler is matching an opening `{` from "
                        f"line {related.line}."
                    )
                    break

        enriched.append(
            diagnostic.model_copy(update={"explanation": explanation})
        )

    return enriched
