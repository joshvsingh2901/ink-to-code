"""Validate AI-generated test models against capability metadata and normalize
into FunctionTestCase / ObjectScenarioTestCase instances.

Imports three one-directional private helpers from test_execution.py:
  _safe_literal, _container_literal, _parse_iterator_argument
These are the authoritative value validators; never duplicate their logic here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.schemas.ai_tests import (
    AiModelFunctionTest,
    AiModelScenarioTest,
)
from app.schemas.test_execution import (
    FunctionMutationExpectation,
    FunctionTestCase,
    ObjectScenarioObject,
    ObjectScenarioStep,
    ObjectScenarioTestCase,
)
from app.services.ai_test_capability import AiCapabilityResult
from app.services.function_analysis import FunctionParameter, FunctionSignature
from app.services.object_analysis import ObjectClass

# One-directional imports — ai_test_validation → test_execution (no cycle).
from app.services.test_execution import (
    _container_literal,
    _parse_iterator_argument,
    _safe_literal,
)


@dataclass
class ValidatedAiTest:
    test_case: FunctionTestCase | ObjectScenarioTestCase
    ai_test: AiModelFunctionTest | AiModelScenarioTest


@dataclass
class AiTestRejection:
    test_name: str
    reason_code: str
    detail: str


# ---------------------------------------------------------------------------
# Argument-level helpers
# ---------------------------------------------------------------------------


def _validate_iterator_arg(
    param: FunctionParameter,
    raw: str,
    head_payloads: dict[int | None, list | None],
) -> str:
    vt = param.value_type
    label = f"Argument '{param.name}'"
    group_idx = vt.iterator_group_index
    is_tail = vt.iterator_role == "range_end"
    head_payload = head_payloads.get(group_idx) if is_tail else None

    payload = _parse_iterator_argument(
        raw,
        vt,
        label,
        is_tail=is_tail,
        head_container_payload=head_payload,
    )
    if not is_tail and group_idx is not None:
        head_payloads[group_idx] = payload.get("container")
    # Iterator args stored as raw JSON; test_execution.py re-parses them.
    return raw


def _validate_argument(
    param: FunctionParameter,
    raw: str,
    head_payloads: dict[int | None, list | None],
) -> str:
    vt = param.value_type
    label = f"Argument '{param.name}'"

    if vt.kind == "iterator":
        return _validate_iterator_arg(param, raw, head_payloads)
    if vt.kind in {"vector", "array", "container"}:
        _container_literal(vt, raw, label)  # raises on invalid input
        return raw  # store raw; test_execution.py converts to C++ later
    if vt.scalar_type is not None:
        _safe_literal(vt.scalar_type, raw, label)  # raises on invalid input
        return raw  # store raw; test_execution.py converts to C++ later
    raise ValueError(f"{label} has an unsupported value type.")


# ---------------------------------------------------------------------------
# Function-test validation
# ---------------------------------------------------------------------------


def _behavior_key(tc: FunctionTestCase) -> tuple:
    return (
        tuple(tc.arguments),
        tc.expected_outcome,
        tc.expected_return,
        tc.expected_exception_type,
    )


def validate_function_test(
    ai_test: AiModelFunctionTest,
    capability: AiCapabilityResult,
    fn_sig: FunctionSignature,
) -> ValidatedAiTest | AiTestRejection:
    # 1. Argument count
    if len(ai_test.arguments) != len(fn_sig.parameters):
        return AiTestRejection(
            test_name=ai_test.name,
            reason_code="wrong_argument_count",
            detail=(
                f"Expected {len(fn_sig.parameters)} argument(s), "
                f"got {len(ai_test.arguments)}."
            ),
        )

    # 2. Validate and normalise arguments
    validated_args: list[str] = []
    head_payloads: dict[int | None, list | None] = {}
    for param, raw in zip(fn_sig.parameters, ai_test.arguments):
        try:
            validated_args.append(_validate_argument(param, raw, head_payloads))
        except ValueError as exc:
            return AiTestRejection(
                test_name=ai_test.name,
                reason_code="invalid_argument_value",
                detail=str(exc),
            )

    # 3. Mutation expectations
    mutation_capable = set(capability.mutation_capable_parameters)
    for mut in ai_test.expected_mutations:
        if mut.parameter_name not in mutation_capable:
            return AiTestRejection(
                test_name=ai_test.name,
                reason_code="invalid_mutation_target",
                detail=(
                    f"Parameter '{mut.parameter_name}' is not mutation-capable. "
                    f"Mutation-capable parameters: "
                    f"{sorted(mutation_capable) or 'none'}."
                ),
            )

    # 4. Return-expectation consistency
    is_void = fn_sig.return_value_type.kind == "void"
    if is_void and ai_test.expected_outcome == "return_value":
        return AiTestRejection(
            test_name=ai_test.name,
            reason_code="return_expectation_on_void",
            detail="Cannot expect a return value from a void function.",
        )

    if ai_test.expected_outcome == "throws" and ai_test.expected_return is not None:
        return AiTestRejection(
            test_name=ai_test.name,
            reason_code="contradictory_expectations",
            detail="expected_return and expected_outcome='throws' cannot be combined.",
        )

    # 5. Build FunctionTestCase
    mutations: list[FunctionMutationExpectation] | None = None
    if ai_test.expected_mutations:
        mutations = [
            FunctionMutationExpectation(
                parameter_id=m.parameter_name,
                expected_final_value=m.expected_final_value,
            )
            for m in ai_test.expected_mutations
        ]

    check_stdout: bool | None = True if ai_test.expected_stdout is not None else None

    try:
        test_case = FunctionTestCase(
            name=ai_test.name,
            arguments=validated_args,
            expected_return=ai_test.expected_return,
            expected_stdout=ai_test.expected_stdout,
            check_stdout=check_stdout,
            expected_mutations=mutations,
            expected_outcome=ai_test.expected_outcome,
            expected_exception_type=ai_test.expected_exception_type,
            exception_message_rule=ai_test.exception_message_rule,
            expected_exception_message=ai_test.expected_exception_message,
        )
    except Exception as exc:
        return AiTestRejection(
            test_name=ai_test.name,
            reason_code="schema_validation_failed",
            detail=str(exc),
        )

    return ValidatedAiTest(test_case=test_case, ai_test=ai_test)


def validate_and_deduplicate_function_tests(
    ai_tests: list[AiModelFunctionTest],
    capability: AiCapabilityResult,
    fn_sig: FunctionSignature,
) -> tuple[list[ValidatedAiTest], list[AiTestRejection]]:
    # Pre-pass: contradictory names (same name but different expectations).
    name_counts = Counter(t.name for t in ai_tests)
    contradictory_names = {name for name, cnt in name_counts.items() if cnt > 1}

    accepted: list[ValidatedAiTest] = []
    rejected: list[AiTestRejection] = []
    seen_behavior_keys: dict[tuple, str] = {}

    for ai_test in ai_tests:
        if ai_test.name in contradictory_names:
            rejected.append(
                AiTestRejection(
                    test_name=ai_test.name,
                    reason_code="contradictory_duplicate",
                    detail=(
                        f"Multiple tests named '{ai_test.name}' — all instances rejected."
                    ),
                )
            )
            continue

        result = validate_function_test(ai_test, capability, fn_sig)
        if isinstance(result, AiTestRejection):
            rejected.append(result)
            continue

        key = _behavior_key(result.test_case)
        if key in seen_behavior_keys:
            rejected.append(
                AiTestRejection(
                    test_name=ai_test.name,
                    reason_code="behavioral_duplicate",
                    detail=(
                        f"This test has the same inputs and expected outcome as "
                        f"'{seen_behavior_keys[key]}'."
                    ),
                )
            )
            continue

        seen_behavior_keys[key] = ai_test.name
        accepted.append(result)

    return accepted, rejected


# ---------------------------------------------------------------------------
# Object-scenario validation
# ---------------------------------------------------------------------------


def validate_object_test(
    ai_test: AiModelScenarioTest,
    capability: AiCapabilityResult,
    obj_class: ObjectClass,
) -> ValidatedAiTest | AiTestRejection:
    allowed_ctors = set(capability.object_constructors)
    allowed_methods = set(capability.object_methods)

    defined_object_ids: set[str] = set()
    scenario_objects: list[ObjectScenarioObject] = []

    for obj in ai_test.objects:
        if obj.constructor_id not in allowed_ctors:
            return AiTestRejection(
                test_name=ai_test.name,
                reason_code="unsupported_constructor",
                detail=(
                    f"Constructor '{obj.constructor_id}' is not in the supported "
                    f"constructors list for '{obj_class.name}'."
                ),
            )
        defined_object_ids.add(obj.name)
        scenario_objects.append(
            ObjectScenarioObject(
                object_id=obj.name,
                name=obj.name,
                class_id=obj_class.name,
                constructor_id=obj.constructor_id,
                arguments=list(obj.arguments),
                expected_outcome=obj.expected_outcome,
                expected_exception_type=obj.expected_exception_type,
            )
        )

    scenario_steps: list[ObjectScenarioStep] = []
    for step in ai_test.steps:
        if step.target_object_name not in defined_object_ids:
            return AiTestRejection(
                test_name=ai_test.name,
                reason_code="unknown_object_reference",
                detail=(
                    f"Step references object '{step.target_object_name}' "
                    f"which was not declared in the objects list."
                ),
            )
        if step.method_id not in allowed_methods:
            return AiTestRejection(
                test_name=ai_test.name,
                reason_code="unsupported_method",
                detail=(
                    f"Method '{step.method_id}' is not in the supported methods list "
                    f"for '{obj_class.name}'."
                ),
            )
        scenario_steps.append(
            ObjectScenarioStep(
                step_type=step.step_type,
                method_id=step.method_id,
                target_object_id=step.target_object_name,
                arguments=list(step.arguments),
                expected_outcome=step.expected_outcome,
                expected_return=step.expected_return,
                check_stdout=step.check_stdout,
                expected_stdout=step.expected_stdout,
                expected_exception_type=step.expected_exception_type,
                exception_message_rule=step.exception_message_rule,
                expected_exception_message=step.expected_exception_message,
            )
        )

    try:
        test_case = ObjectScenarioTestCase(
            name=ai_test.name,
            objects=scenario_objects,
            steps=scenario_steps,
        )
    except Exception as exc:
        return AiTestRejection(
            test_name=ai_test.name,
            reason_code="schema_validation_failed",
            detail=str(exc),
        )

    return ValidatedAiTest(test_case=test_case, ai_test=ai_test)


def validate_and_deduplicate_object_tests(
    ai_tests: list[AiModelScenarioTest],
    capability: AiCapabilityResult,
    obj_class: ObjectClass,
) -> tuple[list[ValidatedAiTest], list[AiTestRejection]]:
    name_counts = Counter(t.name for t in ai_tests)
    contradictory_names = {name for name, cnt in name_counts.items() if cnt > 1}

    accepted: list[ValidatedAiTest] = []
    rejected: list[AiTestRejection] = []
    seen_names: set[str] = set()

    for ai_test in ai_tests:
        if ai_test.name in contradictory_names:
            rejected.append(
                AiTestRejection(
                    test_name=ai_test.name,
                    reason_code="contradictory_duplicate",
                    detail=(
                        f"Multiple tests named '{ai_test.name}' — all instances rejected."
                    ),
                )
            )
            continue

        result = validate_object_test(ai_test, capability, obj_class)
        if isinstance(result, AiTestRejection):
            rejected.append(result)
            continue

        seen_names.add(ai_test.name)
        accepted.append(result)

    return accepted, rejected
