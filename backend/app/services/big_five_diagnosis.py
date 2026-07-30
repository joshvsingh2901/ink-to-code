import re
from dataclasses import dataclass

from app.schemas.test_execution import (
    BigFiveDiagnosis,
    ObjectScenarioTestCase,
    ObjectScenarioTestResult,
    SuspiciousSourceRange,
)
from app.services.function_analysis import _mask_non_code


@dataclass(frozen=True)
class SpecialMemberBody:
    operation: str
    body: str
    body_start: int
    parameter_name: str | None = None


_POINTER_MEMBER = re.compile(
    r"\b(?:bool|double|int|long(?:\s+long)?|float|char|[A-Za-z_]\w*)"
    r"\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*;"
)
_SAFE_REPLACEMENT = re.compile(
    r"\b(?:swap|exchange|reset|release|clear|cleanup|destroy|"
    r"release_resource)\s*\(",
    re.IGNORECASE,
)


def _matching_brace(masked_source: str, opening: int) -> int | None:
    depth = 0
    for position in range(opening, len(masked_source)):
        if masked_source[position] == "{":
            depth += 1
        elif masked_source[position] == "}":
            depth -= 1
            if depth == 0:
                return position
    return None


def _special_member_body(
    source: str,
    class_name: str,
    operation: str,
) -> SpecialMemberBody | None:
    masked = _mask_non_code(source)
    escaped = re.escape(class_name)
    patterns = {
        "copy_assignment": re.compile(
            rf"operator\s*=\s*\(\s*const\s+{escaped}\s*&\s*"
            r"(?P<parameter>[A-Za-z_]\w*)\s*\)[^{;]*\{"
        ),
        "move_assignment": re.compile(
            rf"operator\s*=\s*\(\s*{escaped}\s*&&\s*"
            r"(?P<parameter>[A-Za-z_]\w*)\s*\)[^{;]*\{"
        ),
        "move_constructor": re.compile(
            rf"\b{escaped}\s*\(\s*{escaped}\s*&&\s*"
            r"(?P<parameter>[A-Za-z_]\w*)\s*\)[^{;]*\{"
        ),
        "copy_constructor": re.compile(
            rf"\b{escaped}\s*\(\s*const\s+{escaped}\s*&\s*"
            r"(?P<parameter>[A-Za-z_]\w*)\s*\)[^{;]*\{"
        ),
        "destructor": re.compile(
            rf"~{escaped}\s*\(\s*\)\s*[^{{;]*\{{"
        ),
    }
    pattern = patterns.get(operation)
    if pattern is None:
        return None
    match = pattern.search(masked)
    if match is None:
        return None
    opening = masked.find("{", match.start(), match.end())
    closing = _matching_brace(masked, opening)
    if closing is None:
        return None
    return SpecialMemberBody(
        operation=operation,
        body=source[opening + 1 : closing],
        body_start=opening + 1,
        parameter_name=(
            match.groupdict().get("parameter")
            if "parameter" in match.groupdict()
            else None
        ),
    )


def _source_range(
    source: str,
    body: SpecialMemberBody,
    relevant_text: str,
    reason: str,
) -> SuspiciousSourceRange | None:
    offset = body.body.find(relevant_text)
    if offset < 0:
        return None
    start_offset = body.body_start + offset
    start_line = source.count("\n", 0, start_offset) + 1
    line_count = min(relevant_text.count("\n") + 1, 6)
    end_line = start_line + line_count - 1
    lines = source.splitlines()
    return SuspiciousSourceRange(
        start_line=start_line,
        end_line=end_line,
        snippet="\n".join(lines[start_line - 1 : end_line]),
        reason=reason,
    )


def _owning_pointer_names(source: str) -> set[str]:
    if "std::unique_ptr" in source or "std::shared_ptr" in source:
        return set()
    names = {
        match.group("name") for match in _POINTER_MEMBER.finditer(source)
    }
    return {
        name
        for name in names
        if (
            re.search(rf"\b{re.escape(name)}\s*(?:=|\{{)\s*new\b", source)
            or re.search(rf"\bdelete(?:\s*\[\s*\])?\s+{re.escape(name)}\b", source)
        )
    }


def _unsafe_pointer_transfer(
    source: str,
    class_name: str,
    operation: str,
) -> tuple[str, SpecialMemberBody, str] | None:
    body = _special_member_body(source, class_name, operation)
    if body is None or body.parameter_name is None:
        return None
    if _SAFE_REPLACEMENT.search(body.body):
        return None
    for member in _owning_pointer_names(source):
        assignment = re.search(
            rf"\b{re.escape(member)}\s*=\s*"
            rf"{re.escape(body.parameter_name)}\.{re.escape(member)}\s*;",
            body.body,
        )
        if assignment is None:
            continue
        before_assignment = body.body[: assignment.start()]
        if re.search(
            rf"\bdelete(?:\s*\[\s*\])?\s+{re.escape(member)}\b",
            before_assignment,
        ):
            continue
        unknown_helper = re.search(
            r"\b(?!if\b|for\b|while\b|sizeof\b|return\b)"
            r"[A-Za-z_]\w*\s*\(",
            before_assignment,
        )
        if unknown_helper:
            continue
        transfer_text = assignment.group(0)
        if operation == "move_assignment":
            relinquish = re.search(
                rf"\b{re.escape(body.parameter_name)}\."
                rf"{re.escape(member)}\s*=\s*(?:nullptr|0)\s*;",
                body.body[assignment.end() :],
            )
            if relinquish is None:
                continue
            transfer_text += body.body[
                assignment.end() : assignment.end() + relinquish.end()
            ]
        return member, body, transfer_text.strip()
    return None


def _operation_present(
    test: ObjectScenarioTestCase,
    step_type: str,
) -> bool:
    return any(step.step_type == step_type for step in test.steps)


def _shallow_copy_evidence(
    test: ObjectScenarioTestCase,
    result: ObjectScenarioTestResult,
) -> list[str] | None:
    copied_ids: dict[str, str] = {}
    mutated_copies: set[str] = set()
    for request_step, result_step in zip(
        test.steps, result.steps, strict=True
    ):
        if (
            request_step.step_type == "copy_construct"
            and request_step.result_object_id
            and request_step.source_object_id
        ):
            copied_ids[
                request_step.result_object_id
            ] = request_step.source_object_id
        elif (
            request_step.step_type == "method"
            and request_step.target_object_id in copied_ids
            and result_step.status == "completed"
        ):
            mutated_copies.add(request_step.target_object_id or "")
        elif (
            request_step.step_type == "observer"
            and not result_step.passed
            and request_step.target_object_id
            in {
                copied_ids[copy_id]
                for copy_id in mutated_copies
                if copy_id in copied_ids
            }
        ):
            return [
                "A copied object was created.",
                "Only the copied object was mutated before the observation.",
                "The original object's observer returned an unexpected value.",
            ]
    return None


def diagnose_big_five(
    source: str,
    test: ObjectScenarioTestCase,
    result: ObjectScenarioTestResult,
) -> BigFiveDiagnosis | None:
    shallow_evidence = _shallow_copy_evidence(test, result)
    if shallow_evidence:
        return BigFiveDiagnosis(
            title="Copied objects appear to share the same resource",
            confidence="confirmed",
            summary=(
                "Changing the copied object also changed the original. "
                "The copy did not behave independently."
            ),
            evidence=shallow_evidence,
            suggested_direction=(
                "Review how the copy operation creates independent state. "
                "Use the ownership strategy appropriate for the class."
            ),
            related_operation="copy_constructor",
        )

    if _operation_present(test, "self_assign") and (
        result.destruction_failed
        or result.memory_status
        in {"use_after_free", "double_free", "invalid_free"}
        or any(
            step.step_type == "self_assign" and not step.passed
            for step in result.steps
        )
    ):
        return BigFiveDiagnosis(
            title="Copy assignment does not safely handle self-assignment",
            confidence="confirmed",
            summary=(
                "The same object was used as both source and target, and the "
                "operation left it invalid or caused a runtime failure."
            ),
            evidence=[
                "The scenario assigned an object to itself.",
                "Runtime or observer evidence showed the object was not preserved.",
            ],
            suggested_direction=(
                "Ensure assignment remains valid when source and target are "
                "the same object. An identity check is one option, but not "
                "the only valid design."
            ),
            related_operation="self_assignment",
        )

    if result.memory_status in {"double_free", "invalid_free"}:
        if _operation_present(test, "move_construct"):
            return BigFiveDiagnosis(
                title=(
                    "Move construction may leave both objects owning the "
                    "same resource"
                ),
                confidence="confirmed",
                summary=(
                    "The move completed, but cleanup reported duplicate or "
                    "invalid ownership."
                ),
                evidence=[
                    "A move-construction step completed.",
                    result.memory_summary or "The sanitizer reported a cleanup failure.",
                ],
                suggested_direction=(
                    "After transferring ownership, leave the source in a "
                    "valid non-owning state."
                ),
                related_operation="move_constructor",
            )
        if _operation_present(test, "move_assign"):
            return BigFiveDiagnosis(
                title=(
                    "Move assignment may leave source and target owning the "
                    "same resource"
                ),
                confidence="confirmed",
                summary=(
                    "Cleanup reported duplicate or invalid ownership after "
                    "move assignment."
                ),
                evidence=[
                    "A move-assignment step completed.",
                    result.memory_summary or "The sanitizer reported a cleanup failure.",
                ],
                suggested_direction=(
                    "Transfer ownership so only one object remains responsible "
                    "for the resource."
                ),
                related_operation="move_assignment",
            )

    if _operation_present(test, "move_assign"):
        transfer = _unsafe_pointer_transfer(
            source, result.class_name, "move_assignment"
        )
        if result.memory_status == "leak" or (
            result.leak_status == "unavailable" and transfer is not None
        ):
            suspicious_ranges = []
            if transfer is not None:
                _, body, text = transfer
                source_range = _source_range(
                    source,
                    body,
                    text,
                    (
                        "The target's previous pointer appears to be "
                        "overwritten before its old resource is safely replaced."
                    ),
                )
                if source_range:
                    suspicious_ranges.append(source_range)
            confirmed = result.memory_status == "leak"
            return BigFiveDiagnosis(
                title=(
                    "Memory leak detected in move assignment"
                    if confirmed
                    else "Likely memory leak in move assignment"
                ),
                confidence="confirmed" if confirmed else "likely",
                summary=(
                    "LeakSanitizer reported a leaked allocation after move "
                    "assignment."
                    if confirmed
                    else (
                        "The target appears to replace an owning resource "
                        "without first releasing or safely replacing its old "
                        "resource. Leak checking is unavailable, so this is "
                        "based on the code pattern and scenario."
                    )
                ),
                evidence=[
                    "The target was constructed with its own state.",
                    "Move assignment completed.",
                    *(
                        [result.memory_summary or "LeakSanitizer reported a leak."]
                        if confirmed
                        else [
                            "An owning-looking raw pointer is overwritten.",
                            "The source relinquishes that pointer.",
                            "Leak checking is unavailable on this runtime.",
                        ]
                    ),
                ],
                suspicious_ranges=suspicious_ranges,
                suggested_direction=(
                    "Safely release, replace, or swap the target's existing "
                    "resource before taking ownership from the source."
                ),
                related_operation="move_assignment",
            )

    if _operation_present(test, "copy_assign"):
        transfer = _unsafe_pointer_transfer(
            source, result.class_name, "copy_assignment"
        )
        if result.memory_status == "leak" or transfer is not None:
            suspicious_ranges = []
            if transfer is not None:
                _, body, text = transfer
                source_range = _source_range(
                    source,
                    body,
                    text,
                    (
                        "The target's previous pointer appears to be "
                        "overwritten before its old resource is safely replaced."
                    ),
                )
                if source_range:
                    suspicious_ranges.append(source_range)
            confirmed = result.memory_status == "leak"
            return BigFiveDiagnosis(
                title=(
                    "Memory leak detected in copy assignment"
                    if confirmed
                    else "Copy assignment may lose the target's old resource"
                ),
                confidence="confirmed" if confirmed else "likely",
                summary=(
                    "LeakSanitizer reported a leaked allocation after copy "
                    "assignment."
                    if confirmed
                    else (
                        "An owning-looking raw pointer appears to be replaced "
                        "from the source without a visible safe replacement "
                        "of the target's prior resource."
                    )
                ),
                evidence=[
                    "A copy-assignment step was present.",
                    *(
                        [result.memory_summary or "LeakSanitizer reported a leak."]
                        if confirmed
                        else [
                            "The pointer has allocation or cleanup evidence.",
                            "No recognized release, reset, helper, or swap occurs before overwrite.",
                        ]
                    ),
                ],
                suspicious_ranges=suspicious_ranges,
                suggested_direction=(
                    "Release or safely replace the target's existing resource "
                    "before storing the copied resource."
                ),
                related_operation="copy_assignment",
            )

    if (
        result.destruction_failed
        and result.memory_status
        in {"double_free", "invalid_free", "use_after_free", "leak"}
    ):
        return BigFiveDiagnosis(
            title="Object cleanup reported a memory ownership problem",
            confidence="confirmed",
            summary=(
                "The scenario steps completed, but sanitizer evidence showed "
                "a failure during object cleanup."
            ),
            evidence=[result.memory_summary or "Sanitizer cleanup failure."],
            suggested_direction=(
                "Review which object owns each resource and ensure cleanup "
                "happens exactly once."
            ),
            related_operation="destructor",
        )
    return None
