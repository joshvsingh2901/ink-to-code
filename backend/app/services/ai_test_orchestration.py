"""Orchestration for AI test generation, execution, and scoring.

Flow for run_ai_tests:
  1. Whitespace-only question → missing_question
  2. compile_cpp → compile_failed
  3. assess_ai_capability → unsupported
  4. select_source_context → source_too_large
  5. generate_function/object_tests (Gemini call #1)
  6. validate + deduplicate
  7. Optional single repair call (Gemini call #2) if below minimum
  8. run_test_request (execution, no Gemini)
  9. zip results + score → AiTestRunResponse
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.config import Settings
from app.schemas.ai_tests import (
    AiScore,
    AiStoredTest,
    AiTestResultRow,
    AiTestRunRequest,
    AiTestRunResponse,
    AiTestRerunRequest,
    AiTestServiceError,
    PRACTICE_DISCLAIMER,
)
from app.schemas.test_execution import (
    FunctionCombinedTestResult,
    FunctionRunTestsRequest,
    FunctionTestCase,
    ObjectScenarioRunTestsRequest,
    ObjectScenarioTestCase,
    ObjectScenarioTestResult,
    RunTestsResponse,
)
from app.services.ai_test_capability import AiCapabilityResult, assess_ai_capability
from app.services.ai_test_generation import (
    generate_function_tests,
    generate_object_tests,
    select_source_context,
)
from app.services.ai_test_validation import (
    AiTestRejection,
    ValidatedAiTest,
    validate_and_deduplicate_function_tests,
    validate_and_deduplicate_object_tests,
)
from app.services.compiler import CompilerServiceError, compile_cpp
from app.services.function_analysis import FunctionSignature, analyze_test_mode
from app.services.object_analysis import ObjectClass, analyze_object_scenarios
from app.services.test_execution import run_test_request

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# The repair call triggers only when ALL tests were rejected (0 accepted).
# "Partial" sets (some accepted) run without repair and note the omissions.
_REPAIR_MINIMUM = 1


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------


def _input_summary(arguments: list[str]) -> str:
    if not arguments:
        return "(no args)"
    preview = [a[:30] for a in arguments[:3]]
    ellipsis = "…" if len(arguments) > 3 else ""
    return f"({', '.join(preview)}{ellipsis})"


def _expected_summary_fn(test_case: FunctionTestCase) -> str:
    if test_case.expected_outcome == "throws":
        exc = test_case.expected_exception_type or "exception"
        return f"throws {exc}"
    if test_case.expected_return is not None:
        val = test_case.expected_return[:50]
        return f"returns {val}"
    return "void"


def _actual_summary_fn(result: FunctionCombinedTestResult) -> str:
    if result.timed_out:
        return "timed out"
    if result.exception_result is not None:
        exc = result.exception_result
        what = getattr(exc, "actual_exception_type", None) or "exception"
        return f"threw {what}"
    if result.return_result is not None:
        actual = getattr(result.return_result, "actual", None)
        if actual is not None:
            return f"returned {str(actual)[:50]}"
    return "no return"


def _actual_summary_obj(result: ObjectScenarioTestResult) -> str:
    if not result.constructor_completed:
        return "constructor failed"
    steps = getattr(result, "steps", []) or []
    for step in steps:
        if not step.passed:
            return f"step {step.index} failed"
    if not result.passed:
        return "scenario failed"
    return "all steps passed"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_results(results: list) -> AiScore | None:
    if not results:
        return None
    executed = len(results)
    passed = sum(1 for r in results if getattr(r, "passed", False))
    percentage = round(100 * passed / executed) if executed else 0
    return AiScore(passed=passed, executed=executed, percentage=percentage)


# ---------------------------------------------------------------------------
# Result row assembly
# ---------------------------------------------------------------------------


def _build_function_result_rows(
    accepted: list[ValidatedAiTest],
    exec_results: list,
    test_ids: list[str],
) -> list[AiTestResultRow]:
    rows: list[AiTestResultRow] = []
    for i, (vt, result, tid) in enumerate(zip(accepted, exec_results, test_ids)):
        tc = vt.test_case
        ai_test = vt.ai_test
        row = AiTestResultRow(
            id=tid,
            name=ai_test.name,
            category=ai_test.category,
            reason=ai_test.reason,
            passed=result.passed,
            input_summary=_input_summary(tc.arguments),
            expected_summary=_expected_summary_fn(tc),
            actual_summary=_actual_summary_fn(result) if isinstance(result, FunctionCombinedTestResult) else str(result.passed),
            detail=result if isinstance(result, (FunctionCombinedTestResult, ObjectScenarioTestResult)) else None,
        )
        rows.append(row)
    return rows


def _build_object_result_rows(
    accepted: list[ValidatedAiTest],
    exec_results: list,
    test_ids: list[str],
) -> list[AiTestResultRow]:
    rows: list[AiTestResultRow] = []
    for vt, result, tid in zip(accepted, exec_results, test_ids):
        ai_test = vt.ai_test
        row = AiTestResultRow(
            id=tid,
            name=ai_test.name,
            category=ai_test.category,
            reason=ai_test.reason,
            passed=result.passed,
            input_summary="(object scenario)",
            expected_summary="scenario passes",
            actual_summary=_actual_summary_obj(result) if isinstance(result, ObjectScenarioTestResult) else str(result.passed),
            detail=result if isinstance(result, (FunctionCombinedTestResult, ObjectScenarioTestResult)) else None,
        )
        rows.append(row)
    return rows


def _build_stored_tests(
    accepted: list[ValidatedAiTest],
    test_ids: list[str],
    is_function: bool,
) -> list[AiStoredTest]:
    stored: list[AiStoredTest] = []
    for vt, tid in zip(accepted, test_ids):
        ai_test = vt.ai_test
        if is_function:
            stored.append(
                AiStoredTest(
                    id=tid,
                    name=ai_test.name,
                    category=ai_test.category,
                    reason=ai_test.reason,
                    function_test=vt.test_case,
                )
            )
        else:
            stored.append(
                AiStoredTest(
                    id=tid,
                    name=ai_test.name,
                    category=ai_test.category,
                    reason=ai_test.reason,
                    scenario_test=vt.test_case,
                )
            )
    return stored


def _unsupported_response(cap: AiCapabilityResult) -> AiTestRunResponse:
    return AiTestRunResponse(
        status="unsupported",
        message="AI testing is not available for this target yet.",
        unsupported_reason=cap.unsupported_reason,
        unsupported_parameters=list(map(list, cap.unsupported_parameters)),
        supported_targets=list(cap.supported_sibling_targets),
    )


def _input_error_response(
    exec_response: RunTestsResponse,
    stored_tests: list[AiStoredTest],
    skipped_topics: list[str] | None = None,
) -> AiTestRunResponse:
    return AiTestRunResponse(
        status="no_useful_tests",
        message=exec_response.input_error,
        stored_tests=stored_tests,
        skipped_topics=skipped_topics or [],
    )


# ---------------------------------------------------------------------------
# Repair policy helpers
# ---------------------------------------------------------------------------


def _should_repair(
    accepted: list[ValidatedAiTest],
    rejected: list[AiTestRejection],
    lo: int = 0,
) -> bool:
    return bool(rejected) and len(accepted) < _REPAIR_MINIMUM


def _rejected_as_repair_input(
    rejected: list[AiTestRejection],
) -> list[tuple[str, str, str]]:
    return [(r.test_name, r.reason_code, r.detail) for r in rejected]


# ---------------------------------------------------------------------------
# Function-test run path
# ---------------------------------------------------------------------------


def _run_function_path(
    request: AiTestRunRequest,
    cap: AiCapabilityResult,
    fn_sig: FunctionSignature,
    settings: Settings,
    *,
    client,
) -> AiTestRunResponse:
    from app.services.ai_test_generation import _compute_suggested_range_function

    lo, hi = _compute_suggested_range_function(cap, fn_sig)

    # Gemini call #1
    try:
        plan = generate_function_tests(
            request.code,
            request.question_text,
            request.target_id,
            cap,
            request.template_argument_mode,
            list(request.template_arguments),
            settings,
            client=client,
        )
    except AiTestServiceError as exc:
        return AiTestRunResponse(status=exc.code, message=exc.message)

    accepted, rejected = validate_and_deduplicate_function_tests(
        plan.tests, cap, fn_sig
    )

    generation_note: str | None = None
    if rejected:
        generation_note = (
            f"{len(rejected)} test(s) were omitted due to validation issues."
        )

    # Optional repair call
    if _should_repair(accepted, rejected, lo):
        repair_input = _rejected_as_repair_input(rejected)
        try:
            repair_plan = generate_function_tests(
                request.code,
                request.question_text,
                request.target_id,
                cap,
                request.template_argument_mode,
                list(request.template_arguments),
                settings,
                client=client,
                rejected_tests=repair_input,
            )
        except AiTestServiceError as exc:
            if not accepted:
                return AiTestRunResponse(status=exc.code, message=exc.message)
            # Partial: proceed with what we have.
            generation_note = (generation_note or "") + " Repair attempt failed."
        else:
            repair_accepted, repair_rejected = validate_and_deduplicate_function_tests(
                repair_plan.tests, cap, fn_sig
            )
            # Merge repair results, avoiding behavioral duplicates.
            from app.services.ai_test_validation import _behavior_key
            existing_keys = {_behavior_key(v.test_case) for v in accepted}
            for vt in repair_accepted:
                key = _behavior_key(vt.test_case)
                if key not in existing_keys:
                    accepted.append(vt)
                    existing_keys.add(key)

    if not accepted:
        return AiTestRunResponse(
            status="no_useful_tests",
            message="AI test generation did not produce any valid tests.",
            skipped_topics=plan.skipped_topics,
        )

    test_ids = [f"ai-{i + 1}" for i in range(len(accepted))]
    stored = _build_stored_tests(accepted, test_ids, is_function=True)

    # Execute
    exec_request = FunctionRunTestsRequest(
        mode="function",
        code=request.code,
        language="cpp",
        target_function=request.target_id,
        template_argument_mode=request.template_argument_mode,
        template_arguments=request.template_arguments,
        comparison_mode="whitespace_tolerant",
        run_memory_checks=False,
        tests=[v.test_case for v in accepted],
    )
    try:
        exec_response = run_test_request(exec_request)
    except CompilerServiceError as exc:
        return AiTestRunResponse(
            status="infrastructure_failed",
            message="The tests were generated, but the code runner was unavailable. Try running the same tests again.",
            stored_tests=stored,
            skipped_topics=plan.skipped_topics,
        )

    if exec_response.compile_error:
        return AiTestRunResponse(
            status="compile_failed",
            message=exec_response.compile_error,
            stored_tests=stored,
        )
    if exec_response.input_error:
        return _input_error_response(exec_response, stored, plan.skipped_topics)

    rows = _build_function_result_rows(accepted, exec_response.tests, test_ids)
    score = score_results(exec_response.tests)

    return AiTestRunResponse(
        status="completed",
        score=score,
        tests=rows,
        stored_tests=stored,
        skipped_topics=plan.skipped_topics,
        generation_note=generation_note,
        memory_status="not_run",
        disclaimer=PRACTICE_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# Object-test run path
# ---------------------------------------------------------------------------


def _run_object_path(
    request: AiTestRunRequest,
    cap: AiCapabilityResult,
    obj_class: ObjectClass,
    settings: Settings,
    *,
    client,
) -> AiTestRunResponse:
    lo, hi = 4, 8

    try:
        plan = generate_object_tests(
            request.code,
            request.question_text,
            request.target_id,
            cap,
            settings,
            client=client,
        )
    except AiTestServiceError as exc:
        return AiTestRunResponse(status=exc.code, message=exc.message)

    accepted, rejected = validate_and_deduplicate_object_tests(
        plan.tests, cap, obj_class
    )

    generation_note: str | None = None
    if rejected:
        generation_note = f"{len(rejected)} test(s) were omitted due to validation issues."

    if _should_repair(accepted, rejected, lo):
        repair_input = _rejected_as_repair_input(rejected)
        try:
            repair_plan = generate_object_tests(
                request.code,
                request.question_text,
                request.target_id,
                cap,
                settings,
                client=client,
                rejected_tests=repair_input,
            )
        except AiTestServiceError as exc:
            if not accepted:
                return AiTestRunResponse(status=exc.code, message=exc.message)
        else:
            repair_accepted, _ = validate_and_deduplicate_object_tests(
                repair_plan.tests, cap, obj_class
            )
            seen_names = {v.ai_test.name for v in accepted}
            for vt in repair_accepted:
                if vt.ai_test.name not in seen_names:
                    accepted.append(vt)
                    seen_names.add(vt.ai_test.name)

    if not accepted:
        return AiTestRunResponse(
            status="no_useful_tests",
            message="AI test generation did not produce any valid tests.",
            skipped_topics=plan.skipped_topics,
        )

    test_ids = [f"ai-{i + 1}" for i in range(len(accepted))]
    stored = _build_stored_tests(accepted, test_ids, is_function=False)

    exec_request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=request.code,
        language="cpp",
        comparison_mode="whitespace_tolerant",
        run_memory_checks=False,
        tests=[v.test_case for v in accepted],
    )
    try:
        exec_response = run_test_request(exec_request)
    except CompilerServiceError:
        return AiTestRunResponse(
            status="infrastructure_failed",
            message="The tests were generated, but the code runner was unavailable. Try running the same tests again.",
            stored_tests=stored,
            skipped_topics=plan.skipped_topics,
        )

    if exec_response.compile_error:
        return AiTestRunResponse(
            status="compile_failed",
            message=exec_response.compile_error,
            stored_tests=stored,
        )
    if exec_response.input_error:
        return _input_error_response(exec_response, stored, plan.skipped_topics)

    rows = _build_object_result_rows(accepted, exec_response.tests, test_ids)
    score = score_results(exec_response.tests)

    return AiTestRunResponse(
        status="completed",
        score=score,
        tests=rows,
        stored_tests=stored,
        skipped_topics=plan.skipped_topics,
        generation_note=generation_note,
        memory_status="not_run",
        disclaimer=PRACTICE_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_ai_tests(
    request: AiTestRunRequest,
    settings: Settings,
    *,
    client=None,
) -> AiTestRunResponse:
    # 1. Whitespace-only question.
    if not request.question_text.strip():
        return AiTestRunResponse(
            status="missing_question",
            message="A question is required before running AI tests.",
        )

    # 2. Pre-compile.
    compile_result = compile_cpp(request.code)
    if not compile_result.success:
        return AiTestRunResponse(
            status="compile_failed",
            message=compile_result.stderr or "Compilation failed.",
        )

    # 3. Capability gate.
    cap = assess_ai_capability(request.code, request.target_kind, request.target_id)
    if not cap.supported:
        return _unsupported_response(cap)

    # 4. Source size (also checked inside generation, but guard here for zero calls).
    try:
        select_source_context(request.code)
    except AiTestServiceError as exc:
        return AiTestRunResponse(status=exc.code, message=exc.message)

    # 5–9. Target-specific paths.
    if request.target_kind == "function":
        analysis = analyze_test_mode(request.code)
        fn_sig: FunctionSignature | None = next(
            (fn for fn in analysis.functions if fn.id == request.target_id), None
        )
        if fn_sig is None:
            return AiTestRunResponse(
                status="generation_failed",
                message=f"Target function '{request.target_id}' not found after compile check.",
            )
        return _run_function_path(request, cap, fn_sig, settings, client=client)
    else:
        obj_analysis = analyze_object_scenarios(request.code)
        obj_class: ObjectClass | None = next(
            (cls for cls in obj_analysis.classes if cls.id == request.target_id), None
        )
        if obj_class is None:
            return AiTestRunResponse(
                status="generation_failed",
                message=f"Target class '{request.target_id}' not found after compile check.",
            )
        return _run_object_path(request, cap, obj_class, settings, client=client)


def rerun_ai_tests(
    request: AiTestRerunRequest,
    settings: Settings,
) -> AiTestRunResponse:
    """Re-execute stored AI tests against the current code; makes zero Gemini calls."""

    # 1. Pre-compile.
    compile_result = compile_cpp(request.code)
    if not compile_result.success:
        return AiTestRunResponse(
            status="compile_failed",
            message=compile_result.stderr or "Compilation failed.",
        )

    # 2. Capability gate — detect signature changes.
    cap = assess_ai_capability(request.code, request.target_kind, request.target_id)
    if not cap.supported:
        return AiTestRunResponse(
            status="incompatible",
            message="The target changed. Generate fresh AI tests.",
        )

    # 3. Compatibility re-validation.
    is_function = request.target_kind == "function"
    if is_function:
        analysis = analyze_test_mode(request.code)
        fn_sig: FunctionSignature | None = next(
            (fn for fn in analysis.functions if fn.id == request.target_id), None
        )
        if fn_sig is None:
            return AiTestRunResponse(
                status="incompatible",
                message="The target changed. Generate fresh AI tests.",
            )
        param_count = len(fn_sig.parameters)
        mutation_capable = set(cap.mutation_capable_parameters)

        for stored in request.tests:
            if stored.function_test is None:
                return AiTestRunResponse(
                    status="incompatible",
                    message="The target changed. Generate fresh AI tests.",
                )
            tc = stored.function_test
            if len(tc.arguments) != param_count:
                return AiTestRunResponse(
                    status="incompatible",
                    message="The target changed. Generate fresh AI tests.",
                )
            if tc.expected_mutations:
                for mut in tc.expected_mutations:
                    if mut.parameter_id not in mutation_capable:
                        return AiTestRunResponse(
                            status="incompatible",
                            message="The target changed. Generate fresh AI tests.",
                        )
    else:
        allowed_methods = set(cap.object_methods)
        for stored in request.tests:
            if stored.scenario_test is None:
                return AiTestRunResponse(
                    status="incompatible",
                    message="The target changed. Generate fresh AI tests.",
                )
            tc = stored.scenario_test
            for step in tc.steps:
                if step.method_id and step.method_id not in allowed_methods:
                    return AiTestRunResponse(
                        status="incompatible",
                        message="The target changed. Generate fresh AI tests.",
                    )

    # 4. Execute.
    test_ids = [s.id for s in request.tests]
    if is_function:
        test_cases: list[FunctionTestCase] = [
            s.function_test for s in request.tests if s.function_test
        ]
        exec_request = FunctionRunTestsRequest(
            mode="function",
            code=request.code,
            language="cpp",
            target_function=request.target_id,
            template_argument_mode=request.template_argument_mode,
            template_arguments=request.template_arguments,
            comparison_mode="whitespace_tolerant",
            run_memory_checks=False,
            tests=test_cases,
        )
    else:
        scenario_cases: list[ObjectScenarioTestCase] = [
            s.scenario_test for s in request.tests if s.scenario_test
        ]
        exec_request = ObjectScenarioRunTestsRequest(
            mode="object",
            code=request.code,
            language="cpp",
            comparison_mode="whitespace_tolerant",
            run_memory_checks=False,
            tests=scenario_cases,
        )

    try:
        exec_response = run_test_request(exec_request)
    except CompilerServiceError:
        return AiTestRunResponse(
            status="infrastructure_failed",
            message="The tests were generated, but the code runner was unavailable. Try running the same tests again.",
            stored_tests=list(request.tests),
        )

    if exec_response.compile_error:
        return AiTestRunResponse(
            status="compile_failed",
            message=exec_response.compile_error,
        )
    if exec_response.input_error:
        return _input_error_response(exec_response, list(request.tests))

    # 5. Build result rows.
    rows: list[AiTestResultRow] = []
    for stored_test, result, tid in zip(request.tests, exec_response.tests, test_ids):
        if is_function and stored_test.function_test:
            tc = stored_test.function_test
            row = AiTestResultRow(
                id=tid,
                name=stored_test.name,
                category=stored_test.category,
                reason=stored_test.reason,
                passed=result.passed,
                input_summary=_input_summary(tc.arguments),
                expected_summary=_expected_summary_fn(tc),
                actual_summary=_actual_summary_fn(result) if isinstance(result, FunctionCombinedTestResult) else str(result.passed),
                detail=result if isinstance(result, (FunctionCombinedTestResult, ObjectScenarioTestResult)) else None,
            )
        else:
            row = AiTestResultRow(
                id=tid,
                name=stored_test.name,
                category=stored_test.category,
                reason=stored_test.reason,
                passed=result.passed,
                input_summary="(object scenario)",
                expected_summary="scenario passes",
                actual_summary=_actual_summary_obj(result) if isinstance(result, ObjectScenarioTestResult) else str(result.passed),
                detail=result if isinstance(result, (FunctionCombinedTestResult, ObjectScenarioTestResult)) else None,
            )
        rows.append(row)

    score = score_results(exec_response.tests)
    return AiTestRunResponse(
        status="completed",
        score=score,
        tests=rows,
        stored_tests=list(request.tests),
        memory_status="not_run",
        disclaimer=PRACTICE_DISCLAIMER,
    )
