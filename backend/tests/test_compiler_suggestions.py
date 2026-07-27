import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.compilation import CompilerDiagnostic
from app.services.compiler_suggestions import (
    extract_compiler_suggestion,
    get_compiler_suggestions,
)


def diagnostic(
    message: str,
    *,
    line: int = 1,
    column: int = 1,
    severity: str = "error",
) -> CompilerDiagnostic:
    return CompilerDiagnostic(
        line=line,
        column=column,
        severity=severity,
        message=message,
    )


def test_explicit_compiler_replacement_targets_only_the_reported_token():
    code = "int maxValue;\nmaxvalue = maxvalue;\n"
    issue = diagnostic(
        "use of undeclared identifier 'maxvalue'; did you mean 'maxValue'?",
        line=2,
        column=1,
    )

    suggestion = extract_compiler_suggestion(code, issue, 0)

    assert suggestion is not None
    assert suggestion.source == "compiler"
    assert suggestion.original_text == "maxvalue"
    assert suggestion.replacement_text == "maxValue"
    assert suggestion.start_line == suggestion.end_line == 2
    assert suggestion.start_column == 1
    assert suggestion.end_column == 9
    updated = (
        code[: len("int maxValue;\n")]
        + suggestion.replacement_text
        + code[len("int maxValue;\nmaxvalue") :]
    )
    assert updated == "int maxValue;\nmaxValue = maxvalue;\n"


def test_missing_brace_has_no_automatic_suggestion():
    result = get_compiler_suggestions(
        "int main() {",
        [diagnostic("expected '}'", column=13)],
    )
    assert result.suggestions == []


def test_unknown_type_typo_without_explicit_replacement_has_no_suggestion():
    result = get_compiler_suggestions(
        "retum value;",
        [diagnostic("unknown type name 'retum'")],
    )
    assert result.suggestions == []


def test_missing_semicolon_has_no_automatic_suggestion():
    result = get_compiler_suggestions(
        "return value",
        [diagnostic("expected ';' after return statement", column=13)],
    )
    assert result.suggestions == []


def test_unrelated_did_you_mean_message_is_not_treated_as_safe():
    issue = diagnostic(
        "invalid conversion from 'value'; did you mean 'other'?",
    )
    assert extract_compiler_suggestion("value", issue, 0) is None


def test_source_mismatch_invalidates_compiler_replacement():
    issue = diagnostic(
        "use of undeclared identifier 'maxvalue'; did you mean 'maxValue'?",
    )
    assert extract_compiler_suggestion("different", issue, 0) is None


def test_non_ascii_source_line_is_not_given_a_replacement():
    issue = diagnostic(
        "use of undeclared identifier 'maxvalue'; did you mean 'maxValue'?",
    )
    assert extract_compiler_suggestion("maxvalue // π", issue, 0) is None


def test_note_diagnostic_is_not_given_a_suggestion():
    issue = diagnostic(
        "use of undeclared identifier 'maxvalue'; did you mean 'maxValue'?",
        severity="note",
    )
    assert extract_compiler_suggestion("maxvalue", issue, 0) is None


def test_endpoint_returns_only_compiler_suggestion():
    async def request():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(
                "/api/compiler-suggestions",
                json={
                    "code": "int maxValue;\nmaxvalue = 1;",
                    "language": "cpp",
                    "diagnostics": [
                        {
                            "line": 2,
                            "column": 1,
                            "severity": "error",
                            "message": (
                                "use of undeclared identifier 'maxvalue'; "
                                "did you mean 'maxValue'?"
                            ),
                        },
                        {
                            "line": 2,
                            "column": 14,
                            "severity": "error",
                            "message": "expected '}'",
                        },
                    ],
                },
            )

    response = asyncio.run(request())
    assert response.status_code == 200
    body = response.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["source"] == "compiler"
    assert "fallback_error" not in body
