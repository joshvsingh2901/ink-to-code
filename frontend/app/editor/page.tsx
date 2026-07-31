"use client";

import Editor, { type OnMount } from "@monaco-editor/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ObjectScenarioTests,
  type EditableObjectScenario,
} from "@/components/ObjectScenarioTests";
import {
  ExceptionExpectationFields,
  type EditableExceptionExpectation,
} from "@/components/ExceptionExpectationFields";
import { useUploads } from "@/components/UploadProvider";
import { exceptionExpectationPayload } from "@/lib/exceptionTestState";
import {
  compileCpp,
  type CompileDiagnostic,
  type CompileResult,
} from "@/lib/compiler";
import {
  analyzeTestMode,
  runCppTests,
  RunTestsRequestError,
  type FunctionCombinedTestResult,
  type FunctionDescriptor,
  type ExceptionOutcomeResult,
  type FunctionMutationTestResult,
  type ObjectScenarioTestResult,
  type FunctionOutputTestResult,
  type FunctionTestResult,
  type ProgramTestResult,
  type RunTestsResult,
  type TestModeAnalysis,
} from "@/lib/testExecution";
import { presentMemoryDiagnoses } from "@/lib/memoryDiagnostics";
import {
  createInitialObjectScenario,
  isObjectScenarioReady,
} from "@/lib/objectScenarioState";
import { getObjectScenarioSummary } from "@/lib/objectScenarioSummary";

type SidebarTab = "compiler" | "tests";
type PrimaryDiagnostic = CompileDiagnostic & {
  severity: "error" | "warning";
};
type EditorInstance = Parameters<OnMount>[0];
type DecorationsCollection = ReturnType<
  EditorInstance["createDecorationsCollection"]
>;
type IssueCategory =
  | "Identifier issue"
  | "Syntax issue"
  | "Brace issue"
  | "Semicolon issue"
  | "Type issue"
  | "Declaration issue"
  | "Operator issue"
  | "Warning"
  | "Other issue";
type EditableTestCase = EditableExceptionExpectation & {
  id: string;
  name: string;
  stdin: string;
  expected_stdout: string;
  arguments: string[];
  expected_return: string;
  expected_final_arguments: Record<string, string>;
  check_stdout: boolean;
};
type TestTargetKind = "program" | "function" | "object";
type TestResult =
  | ProgramTestResult
  | FunctionTestResult
  | FunctionOutputTestResult
  | FunctionMutationTestResult
  | FunctionCombinedTestResult
  | ObjectScenarioTestResult;
type ResultPresentation = {
  label: "PASS" | "FAIL" | "MEMORY ISSUE" | "CHECK INCOMPLETE";
  behaviorText: string;
  memoryText: string | null;
  tone: "success" | "failure" | "warning";
};

const COMPILER_MARKER_OWNER = "inktocode-compiler";
const AUTO_COMPILE_DEBOUNCE_MS = 900;
const ISSUE_HIGHLIGHT_DURATION_MS = 1500;

const MAX_TEST_CASES = 10;
const INITIAL_TEST_CASE: EditableTestCase = {
  id: "test-1",
  name: "Test 1",
  stdin: "",
  expected_stdout: "",
  arguments: [],
  expected_return: "",
  expected_final_arguments: {},
  check_stdout: false,
  expected_outcome: "return_value",
  expected_exception_type: "",
  exception_message_rule: "ignore",
  expected_exception_message: "",
};
const INITIAL_OBJECT_SCENARIO: EditableObjectScenario =
  createInitialObjectScenario();

function mutableParameters(functionDescriptor: FunctionDescriptor) {
  return functionDescriptor.parameters.filter(
    (parameter) =>
      parameter.type_metadata.passing === "mutable_reference" ||
      parameter.type_metadata.passing === "scalar_pointer" ||
      parameter.type_metadata.passing === "array_pointer",
  );
}

function defaultOutputCheck(functionDescriptor: FunctionDescriptor | null) {
  return (
    functionDescriptor?.return_type_metadata.kind === "void" &&
    mutableParameters(functionDescriptor).length === 0
  );
}

function sanitizeFilename(filename: string) {
  const withoutExtension = filename.replace(/\.cpp$/i, "");
  const safeBase = withoutExtension
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/^\.+/, "")
    .slice(0, 80);

  return `${safeBase || "solution"}.cpp`;
}

function isPrimaryDiagnostic(
  diagnostic: CompileDiagnostic,
): diagnostic is PrimaryDiagnostic {
  return diagnostic.severity === "error" || diagnostic.severity === "warning";
}

function isFunctionResult(
  result:
    | ProgramTestResult
    | FunctionTestResult
    | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
    | ObjectScenarioTestResult,
): result is FunctionTestResult | FunctionOutputTestResult {
  return "arguments" in result && !("mutation_results" in result);
}

function isFunctionReturnResult(
  result: FunctionTestResult | FunctionOutputTestResult,
): result is FunctionTestResult {
  return "expected_return" in result;
}

function isFunctionMutationResult(
  result:
    | ProgramTestResult
    | FunctionTestResult
    | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
    | ObjectScenarioTestResult,
): result is FunctionMutationTestResult {
  return "actual_final_arguments" in result;
}

function isFunctionCombinedResult(
  result:
    | ProgramTestResult
    | FunctionTestResult
    | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
    | ObjectScenarioTestResult,
): result is FunctionCombinedTestResult {
  return "mutation_results" in result;
}

function isObjectScenarioResult(
  result:
    | ProgramTestResult
    | FunctionTestResult
    | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
    | ObjectScenarioTestResult,
): result is ObjectScenarioTestResult {
  return "steps" in result && "constructor_completed" in result;
}

function didBehaviorPass(result: TestResult) {
  if (result.timed_out || result.output_limited) return false;
  if (isObjectScenarioResult(result)) {
    const constructorPassed =
      result.constructor_exception_result?.expectation_passed ??
      result.constructor_completed;
    return (
      constructorPassed &&
      result.steps.every(
        (step) => step.status === "not_executed" || step.passed,
      )
    );
  }
  if (isFunctionCombinedResult(result)) {
    return (
      (result.exception_result?.expectation_passed ?? true) &&
      (result.return_result?.passed ?? true) &&
      (result.stdout_result?.passed ?? true) &&
      result.mutation_results.every((mutation) => mutation.passed)
    );
  }
  if (result.exception_result && !result.exception_result.expectation_passed) {
    return false;
  }
  if (isFunctionMutationResult(result)) {
    return Object.keys(result.mismatch_details).length === 0;
  }
  return (
    result.match_type === "exact" ||
    result.match_type === "whitespace_normalized"
  );
}

function getResultPresentation(result: TestResult): ResultPresentation {
  const behaviorPassed = didBehaviorPass(result);
  if (!behaviorPassed) {
    return {
      label: "FAIL",
      behaviorText: "Expected behaviour did not match",
      memoryText: null,
      tone: "failure",
    };
  }
  if (!result.memory_check_enabled) {
    return {
      label: "PASS",
      behaviorText: "Behaviour passed",
      memoryText: null,
      tone: "success",
    };
  }

  const hasMemoryFailure =
    result.memory_status === "leak" ||
    result.memory_status === "use_after_free" ||
    result.memory_status === "double_free" ||
    result.memory_status === "invalid_free" ||
    result.memory_status === "buffer_overflow" ||
    result.memory_status === "undefined_behavior" ||
    result.memory_status === "runtime_error" ||
    result.memory_status === "unknown_memory_error" ||
    result.memory_access_status === "failed" ||
    result.undefined_behavior_status === "failed" ||
    result.leak_status === "failed";
  if (hasMemoryFailure) {
    return {
      label: "MEMORY ISSUE",
      behaviorText: "Behaviour passed",
      memoryText: "Memory check failed",
      tone: "failure",
    };
  }

  const isIncomplete =
    result.memory_status === "partial" ||
    result.memory_status === "unavailable" ||
    result.memory_access_status === "unavailable" ||
    result.undefined_behavior_status === "unavailable" ||
    result.leak_status === "unavailable" ||
    result.memory_access_status === "possible" ||
    result.undefined_behavior_status === "possible" ||
    result.leak_status === "possible";
  if (isIncomplete) {
    return {
      label: "CHECK INCOMPLETE",
      behaviorText: "Behaviour passed",
      memoryText: "Memory diagnostics unavailable",
      tone: "warning",
    };
  }
  return {
    label: "PASS",
    behaviorText: "Behaviour passed",
    memoryText: "Memory checks passed",
    tone: "success",
  };
}

function ExpandableResultSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-3">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
        className="text-xs font-medium text-slate-600 underline decoration-slate-300 underline-offset-4 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
      >
        {expanded
          ? label === "Show code"
            ? "Hide code"
            : `Hide ${label.toLowerCase()}`
          : label}
      </button>
      {expanded && <div className="mt-2">{children}</div>}
    </div>
  );
}

function MemoryResultDetails({ result }: { result: TestResult }) {
  if (!result.memory_check_enabled) return null;

  const memoryDiagnoses = result.memory_diagnoses ?? [];
  const {
    primary: primaryMemoryDiagnosis,
    secondary: secondaryMemoryDiagnoses,
    confidenceLabel,
    likelyAccess,
  } = presentMemoryDiagnoses(memoryDiagnoses);
  const diagnosis = isObjectScenarioResult(result)
    ? primaryMemoryDiagnosis
      ? null
      : result.big_five_diagnosis
    : null;
  const memoryLine =
    result.memory_status === "clean"
      ? ["Passed", "No memory issues detected"] as const
      : result.memory_status === "leak"
        ? ["Failed", "Leak detected"] as const
      : result.memory_status === "partial" ||
          result.memory_status === "unavailable"
        ? ["Incomplete", "Leak checking unavailable"] as const
        : ["Failed", result.memory_summary ?? "Memory issue detected"] as const;
  const firstRange = diagnosis?.suspicious_ranges[0] ?? null;
  const statusLabel = (status: string) =>
    status === "clean"
      ? "Clean"
      : status === "failed"
        ? "Failed"
        : status === "unavailable"
          ? "Unavailable"
          : status === "possible"
            ? "Possible issue"
            : "Not run";

  return (
    <>
      <div className="mt-3 border-t border-slate-200 pt-3 text-xs">
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="font-medium text-slate-700">Memory check</span>
          <span
            className={
              memoryLine[0] === "Passed"
                ? "font-medium text-emerald-700"
                : memoryLine[0] === "Failed"
                  ? "font-medium text-rose-700"
                  : "font-medium text-amber-700"
            }
          >
            {memoryLine[0]}
          </span>
          <span className="text-slate-500">{memoryLine[1]}</span>
        </p>
      </div>

      {primaryMemoryDiagnosis && (
        <section
          aria-label="Primary memory diagnosis"
          className={`mt-3 rounded-md border p-3 ${
            primaryMemoryDiagnosis.confidence === "confirmed"
              ? "border-rose-200"
              : "border-amber-200"
          }`}
        >
          <p
            className={`text-[11px] font-semibold uppercase tracking-wide ${
              primaryMemoryDiagnosis.confidence === "confirmed"
                ? "text-rose-700"
                : "text-amber-700"
            }`}
          >
            {confidenceLabel}
          </p>
          <h4 className="mt-1 text-sm font-semibold text-slate-800">
            {primaryMemoryDiagnosis.title}
          </h4>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {primaryMemoryDiagnosis.summary}
          </p>
          {primaryMemoryDiagnosis.source_range && (
            <div className="mt-2 text-xs text-slate-600">
              <p className="font-medium">Likely access:</p>
              <code className="mt-1 block max-w-full overflow-x-auto whitespace-pre-wrap break-words font-mono text-slate-800">
                {likelyAccess}
              </code>
            </div>
          )}
          <p className="mt-2 text-xs leading-5 text-slate-600">
            <span className="font-medium text-slate-700">
              Suggested direction:
            </span>{" "}
            {primaryMemoryDiagnosis.suggested_direction}
          </p>
          {primaryMemoryDiagnosis.source_range && (
            <ExpandableResultSection label="Show code">
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
                {primaryMemoryDiagnosis.source_range.excerpt}
              </pre>
            </ExpandableResultSection>
          )}
          {secondaryMemoryDiagnoses.length > 0 && (
            <ul className="mt-3 space-y-2 border-t border-slate-200 pt-3">
              {secondaryMemoryDiagnoses.map((item) => (
                <li key={`${item.category}-${item.title}`}>
                  <p className="text-xs font-medium text-slate-700">
                    {item.title}
                  </p>
                  <p className="text-xs leading-5 text-slate-500">
                    {item.summary}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {diagnosis && (
        <section
          aria-label="Big Five diagnosis"
          className={`mt-3 rounded-md border p-3 ${
            diagnosis.confidence === "confirmed"
              ? "border-rose-200"
              : "border-amber-200"
          }`}
        >
          <p
            className={`text-[11px] font-semibold uppercase tracking-wide ${
              diagnosis.confidence === "confirmed"
                ? "text-rose-700"
                : "text-amber-700"
            }`}
          >
            {diagnosis.confidence === "confirmed"
              ? "Confirmed issue"
              : diagnosis.confidence === "likely"
                ? "Likely issue"
                : "Possible issue"}
          </p>
          <h4 className="mt-1 text-sm font-semibold text-slate-800">
            {diagnosis.title}
          </h4>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            {diagnosis.summary}
          </p>
          {firstRange && (
            <p className="mt-2 text-xs font-medium text-slate-600">
              Location: line {firstRange.start_line}
              {firstRange.end_line !== firstRange.start_line
                ? `–${firstRange.end_line}`
                : ""}
            </p>
          )}
          <p className="mt-2 text-xs leading-5 text-slate-600">
            <span className="font-medium text-slate-700">Next step:</span>{" "}
            {diagnosis.suggested_direction}
          </p>
          {firstRange && (
            <ExpandableResultSection label="Show code">
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
                {firstRange.snippet}
              </pre>
            </ExpandableResultSection>
          )}
        </section>
      )}

      <ExpandableResultSection label="Technical details">
        <dl className="grid gap-1 text-xs text-slate-600">
          <div className="flex justify-between gap-3">
            <dt>Memory access check</dt>
            <dd>{statusLabel(result.memory_access_status)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Undefined behaviour check</dt>
            <dd>{statusLabel(result.undefined_behavior_status)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Leak check</dt>
            <dd>{statusLabel(result.leak_status)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Provider</dt>
            <dd>{result.execution_provider}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Tool</dt>
            <dd>{result.memory_tool}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt>Exit code</dt>
            <dd>{result.exit_code ?? "Not available"}</dd>
          </div>
          {isObjectScenarioResult(result) && (
            <div className="flex justify-between gap-3">
              <dt>Cleanup/destruction</dt>
              <dd>{result.destruction_failed ? "Failed" : "Completed"}</dd>
            </div>
          )}
        </dl>
        {diagnosis && diagnosis.evidence.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-medium text-slate-700">Evidence</p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">
              {diagnosis.evidence.map((evidence) => (
                <li key={evidence}>{evidence}</li>
              ))}
            </ul>
          </div>
        )}
        {memoryDiagnoses.flatMap((item) => item.technical_details).length >
          0 && (
          <div className="mt-3">
            <p className="text-xs font-medium text-slate-700">
              Classification evidence
            </p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">
              {memoryDiagnoses
                .flatMap((item) => item.technical_details)
                .map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
            </ul>
          </div>
        )}
        {diagnosis && diagnosis.suspicious_ranges.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-medium text-slate-700">
              Source locations
            </p>
            <ul className="mt-1 space-y-1 text-xs leading-5 text-slate-600">
              {diagnosis.suspicious_ranges.map((range) => (
                <li key={`${range.start_line}-${range.end_line}`}>
                  Line {range.start_line}
                  {range.end_line !== range.start_line
                    ? `–${range.end_line}`
                    : ""}
                  : {range.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
        {result.leaked_bytes !== null &&
          result.leaked_allocations !== null && (
            <p className="mt-3 text-xs leading-5 text-slate-600">
              {result.leak_kind === "possible"
                ? "Possibly lost"
                : "Definitely lost"}
              : {result.leaked_bytes} bytes in {result.leaked_allocations}{" "}
              allocation{result.leaked_allocations === 1 ? "" : "s"}
            </p>
          )}
        {result.memory_diagnostics && (
          <ExpandableResultSection label="Raw memory output">
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
              {result.memory_diagnostics}
            </pre>
          </ExpandableResultSection>
        )}
        {result.stderr && (
          <ExpandableResultSection label="Runtime stderr">
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
              {result.stderr}
            </pre>
          </ExpandableResultSection>
        )}
      </ExpandableResultSection>
    </>
  );
}

function ObjectScenarioSteps({ result }: { result: ObjectScenarioTestResult }) {
  const renderStep = (step: ObjectScenarioTestResult["steps"][number]) => (
    <div
      key={`${result.name}-step-${step.index}`}
      className="border-t border-slate-200 pt-2"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Step {step.index + 1}
          </p>
          <p className="mt-0.5 break-words font-mono text-xs text-slate-800">
            {step.expression || step.method}
            {step.result_object_name ? ` → ${step.result_object_name}` : ""}
          </p>
        </div>
        <span
          className={`shrink-0 text-[11px] font-medium ${
            step.status === "not_executed"
              ? "text-slate-500"
              : step.passed
                ? "text-emerald-700"
                : "text-rose-700"
          }`}
        >
          {step.status === "not_executed"
            ? "NOT EXECUTED"
            : step.passed
              ? "PASS"
              : "FAIL"}
        </span>
      </div>
      {step.exception_result && (
        <ExceptionOutcomeSummary result={step.exception_result} />
      )}
      {[step.return_result, step.stdout_result]
        .filter(
          (
            channel,
          ): channel is NonNullable<typeof channel> => channel !== null,
        )
        .map((channel, channelIndex) => (
          <div key={channelIndex} className="mt-2">
            <p className="text-[11px] font-medium text-slate-500">
              {channel === step.return_result ? "Return value" : "Method output"}
            </p>
            <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
              <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                Expected: {channel.expected || "(empty)"}
              </pre>
              <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                Actual: {channel.actual || "(empty)"}
              </pre>
            </div>
          </div>
        ))}
    </div>
  );
  const passedSteps = result.steps.filter(
    (step) => step.status === "completed" && step.passed,
  );
  const visibleSteps = result.steps.filter(
    (step) => step.status !== "completed" || !step.passed,
  );

  return (
    <>
      {visibleSteps.map(renderStep)}
      {passedSteps.length > 0 && (
        <details className="border-t border-slate-200 pt-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
            Show {passedSteps.length} passed step
            {passedSteps.length === 1 ? "" : "s"}
          </summary>
          <div className="mt-2 space-y-2">{passedSteps.map(renderStep)}</div>
        </details>
      )}
    </>
  );
}

function ExceptionOutcomeSummary({
  result,
}: {
  result: ExceptionOutcomeResult;
}) {
  const unexpectedStandard =
    result.expected_outcome !== "throws" &&
    result.actual_outcome === "threw_standard";
  const wrongType =
    result.expected_outcome === "throws" &&
    result.actual_outcome === "threw_standard" &&
    result.type_matched === false;
  const wrongMessage =
    result.expected_outcome === "throws" &&
    result.type_matched === true &&
    result.message_matched === false;
  const expectedButReturned =
    result.expected_outcome === "throws" &&
    result.actual_outcome === "returned";

  if (
    result.expected_outcome !== "throws" &&
    result.actual_outcome === "returned"
  ) {
    return null;
  }

  return (
    <div className="mt-2 border-l-2 border-slate-200 pl-2 text-xs leading-5 text-slate-600">
      <p className="font-medium text-slate-800">
        {result.expectation_passed
          ? "Expected exception matched"
          : wrongType
            ? "Wrong exception type"
            : wrongMessage
              ? "Exception message did not match"
              : expectedButReturned
                ? "Expected an exception, but the function returned normally."
                : result.actual_outcome === "threw_non_standard"
                  ? "Non-standard exception thrown"
                  : unexpectedStandard
                    ? "Unexpected exception"
                    : result.actual_outcome === "timed_out"
                      ? "Program timed out before producing the expected result."
                      : "Program crashed before producing the expected result."}
      </p>
      {result.expected_outcome === "throws" && (
        <p>
          Expected:{" "}
          <span className="font-mono">
            {result.expected_exception_type === "any_std_exception"
              ? "Any std::exception"
              : result.expected_exception_type}
          </span>
        </p>
      )}
      {result.actual_exception_type && (
        <p>
          Actual:{" "}
          <span className="font-mono">{result.actual_exception_type}</span>
        </p>
      )}
      {result.actual_outcome === "threw_non_standard" && (
        <p>The code threw a value that is not derived from std::exception.</p>
      )}
      {result.expected_outcome === "throws" &&
        result.expected_message_rule !== "ignore" && (
          <p>
            Expected message:{" "}
            <span className="font-mono">{result.expected_message}</span>
          </p>
        )}
      {result.actual_message && (
        <p>
          Actual message:{" "}
          <span className="font-mono">{result.actual_message}</span>
        </p>
      )}
      {result.expectation_passed &&
        result.expected_message_rule !== "ignore" && <p>Message matched</p>}
    </div>
  );
}

function getIssueCategory(diagnostic: PrimaryDiagnostic): IssueCategory {
  if (diagnostic.severity === "warning") return "Warning";

  const message = diagnostic.message.toLowerCase();

  if (
    message.includes("expected ';'") ||
    message.includes("expected ‘;’") ||
    message.includes("semicolon")
  ) {
    return "Semicolon issue";
  }
  if (
    message.includes("expected '}'") ||
    message.includes("expected ‘}’") ||
    message.includes("expected '{'") ||
    message.includes("expected ‘{’") ||
    message.includes("unmatched brace") ||
    message.includes("missing brace")
  ) {
    return "Brace issue";
  }
  if (
    message.includes("undeclared identifier") ||
    message.includes("use of undeclared") ||
    message.includes("was not declared in this scope") ||
    message.includes("unknown identifier")
  ) {
    return "Identifier issue";
  }
  if (
    message.includes("invalid operands") ||
    message.includes("invalid operand") ||
    message.includes("no match for 'operator") ||
    message.includes("no match for ‘operator") ||
    message.includes("overloaded operator")
  ) {
    return "Operator issue";
  }
  if (
    message.includes("unknown type name") ||
    message.includes("does not name a type") ||
    message.includes("invalid conversion") ||
    message.includes("cannot convert") ||
    message.includes("incompatible type") ||
    message.includes("incomplete type")
  ) {
    return "Type issue";
  }
  if (
    message.includes("redefinition") ||
    message.includes("redeclaration") ||
    message.includes("conflicting declaration") ||
    message.includes("previous declaration")
  ) {
    return "Declaration issue";
  }
  if (
    message.includes("syntax error") ||
    message.includes("parse error") ||
    message.includes("expected expression") ||
    message.includes("expected primary-expression") ||
    message.startsWith("expected ")
  ) {
    return "Syntax issue";
  }

  return "Other issue";
}

export default function EditorPage() {
  const router = useRouter();
  const { reviewedCode, setReviewedCode } = useUploads();
  const [code, setCode] = useState(reviewedCode ?? "");
  const [filename, setFilename] = useState("solution.cpp");
  const [activeTab, setActiveTab] = useState<SidebarTab>("compiler");
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [testCases, setTestCases] = useState<EditableTestCase[]>([
    INITIAL_TEST_CASE,
  ]);
  const [testRunResult, setTestRunResult] = useState<RunTestsResult | null>(
    null,
  );
  const [testRunError, setTestRunError] = useState<string | null>(null);
  const [testRunErrorCode, setTestRunErrorCode] = useState<string | null>(null);
  const [isRunningTests, setIsRunningTests] = useState(false);
  const [comparisonMode, setComparisonMode] = useState<
    "whitespace_tolerant" | "exact"
  >("whitespace_tolerant");
  const [runMemoryChecks, setRunMemoryChecks] = useState(false);
  const [testMode, setTestMode] = useState<TestModeAnalysis | null>(null);
  const [testTarget, setTestTarget] = useState<TestTargetKind | null>(null);
  const [objectScenarios, setObjectScenarios] = useState<
    EditableObjectScenario[]
  >([INITIAL_OBJECT_SCENARIO]);
  const [selectedFunctionId, setSelectedFunctionId] = useState<string | null>(
    null,
  );
  const [testModeError, setTestModeError] = useState<string | null>(null);
  const [isAnalyzingTests, setIsAnalyzingTests] = useState(true);
  const [isEdited, setIsEdited] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const initialCodeRef = useRef(reviewedCode ?? "");
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
  const currentSourceRef = useRef(reviewedCode ?? "");
  const codeVersionRef = useRef(0);
  const nextTestIdRef = useRef(2);
  const selectedFunctionIdRef = useRef<string | null>(null);
  const latestCompileRequestRef = useRef(0);
  const isCompileInFlightRef = useRef(false);
  const hasCompletedCompileRef = useRef(false);
  const autoCompileTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const issueHighlightRef = useRef<DecorationsCollection | null>(null);
  const issueHighlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isMountedRef = useRef(true);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (reviewedCode === null) {
      router.replace("/");
    }
  }, [reviewedCode, router]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      if (autoCompileTimerRef.current) {
        clearTimeout(autoCompileTimerRef.current);
      }
      if (issueHighlightTimerRef.current) {
        clearTimeout(issueHighlightTimerRef.current);
      }
      issueHighlightRef.current?.clear();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setIsAnalyzingTests(true);
      setTestModeError(null);
      void analyzeTestMode(code, controller.signal)
        .then((analysis) => {
          if (controller.signal.aborted) return;
          setTestMode(analysis);
          setTestTarget((current) => {
            if (current && analysis.available_modes.includes(current)) {
              return current;
            }
            return analysis.available_modes.length === 1
              ? analysis.available_modes[0]
              : analysis.mode === "unsupported"
                ? null
                : analysis.mode;
          });
          if (analysis.functions.length > 0) {
            const previousId = selectedFunctionIdRef.current;
            const nextId =
              analysis.functions.length === 1
                ? analysis.functions[0].id
                : analysis.functions.some(
                      (candidate) => candidate.id === previousId,
                    )
                  ? previousId
                  : null;
            const nextFunction =
              analysis.functions.find(
                (candidate) => candidate.id === nextId,
              ) ?? null;
            selectedFunctionIdRef.current = nextId;
            setSelectedFunctionId(nextId);
            setTestCases((current) =>
              current.map((test) => ({
                ...test,
                arguments: nextFunction
                  ? nextFunction.parameters.map(
                      (_, index) =>
                        nextId === previousId
                          ? (test.arguments[index] ?? "")
                          : "",
                    )
                  : [],
                expected_return:
                  nextId === previousId ? test.expected_return : "",
                expected_stdout:
                  nextId === previousId ? test.expected_stdout : "",
                expected_final_arguments:
                  nextId === previousId
                    ? test.expected_final_arguments
                    : {},
                check_stdout:
                  nextId === previousId
                    ? test.check_stdout
                    : defaultOutputCheck(nextFunction),
                expected_outcome:
                  nextId === previousId
                    ? test.expected_outcome
                    : nextFunction?.return_type_metadata.kind === "void"
                      ? "return_void"
                      : "return_value",
                expected_exception_type:
                  nextId === previousId
                    ? test.expected_exception_type
                    : "",
                exception_message_rule:
                  nextId === previousId
                    ? test.exception_message_rule
                    : "ignore",
                expected_exception_message:
                  nextId === previousId
                    ? test.expected_exception_message
                    : "",
              })),
            );
          } else {
            selectedFunctionIdRef.current = null;
            setSelectedFunctionId(null);
          }
          setObjectScenarios((current) =>
            current.map((scenario) => {
              return {
                ...scenario,
                objects: scenario.objects.map((object) => {
                  const objectClass =
                    analysis.classes.find(
                      (candidate) => candidate.id === object.class_id,
                    ) ??
                    (analysis.classes.length === 1
                      ? analysis.classes[0]
                      : null);
                  const constructor =
                    objectClass?.constructors.find(
                      (candidate) =>
                        candidate.id === object.constructor_id,
                    ) ??
                    (objectClass?.constructors.length === 1
                      ? objectClass.constructors[0]
                      : null);
                  const unchanged =
                    constructor?.id === object.constructor_id;
                  return {
                    ...object,
                    class_id: objectClass?.id ?? "",
                    constructor_id: constructor?.id ?? "",
                    arguments:
                      constructor?.parameters.map((_, index) =>
                        unchanged ? (object.arguments[index] ?? "") : "",
                      ) ?? [],
                  };
                }),
                steps: scenario.steps,
              };
            }),
          );
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setTestMode(null);
          setTestTarget(null);
          setTestModeError(
            error instanceof Error
              ? error.message
              : "The test mode could not be determined.",
          );
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setIsAnalyzingTests(false);
          }
        });
    }, 400);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [code]);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    issueHighlightRef.current = editor.createDecorationsCollection();
  };

  function clearCompilerMarkers() {
    const model = editorRef.current?.getModel();
    if (model && monacoRef.current) {
      monacoRef.current.editor.setModelMarkers(
        model,
        COMPILER_MARKER_OWNER,
        [],
      );
    }
  }

  function getSafeLocation(diagnostic: CompileDiagnostic) {
    const model = editorRef.current?.getModel();
    if (!model) return null;

    const line = Math.min(
      Math.max(Math.trunc(diagnostic.line), 1),
      model.getLineCount(),
    );
    const maxColumn = model.getLineMaxColumn(line);
    const column = Math.min(
      Math.max(Math.trunc(diagnostic.column), 1),
      maxColumn,
    );
    return { line, column };
  }

  function applyCompilerMarkers(diagnostics: CompileDiagnostic[]) {
    const model = editorRef.current?.getModel();
    const monaco = monacoRef.current;
    if (!model || !monaco) return;

    const severityByType = {
      error: monaco.MarkerSeverity.Error,
      warning: monaco.MarkerSeverity.Warning,
    };

    monaco.editor.setModelMarkers(
      model,
      COMPILER_MARKER_OWNER,
      diagnostics.filter(isPrimaryDiagnostic).flatMap((diagnostic) => {
        const location = getSafeLocation(diagnostic);
        if (!location) return [];

        return [
          {
            startLineNumber: location.line,
            startColumn: location.column,
            endLineNumber: location.line,
            endColumn: location.column,
            message: diagnostic.message,
            severity: severityByType[diagnostic.severity],
          },
        ];
      }),
    );
  }

  function focusDiagnostic(diagnostic: CompileDiagnostic) {
    const editor = editorRef.current;
    const location = getSafeLocation(diagnostic);
    if (!editor || !location) return;

    editor.setPosition({
      lineNumber: location.line,
      column: location.column,
    });
    editor.revealLineInCenter(location.line);
    editor.focus();

    if (issueHighlightTimerRef.current) {
      clearTimeout(issueHighlightTimerRef.current);
    }
    issueHighlightRef.current?.set([
      {
        range: {
          startLineNumber: location.line,
          startColumn: 1,
          endLineNumber: location.line,
          endColumn: 1,
        },
        options: {
          isWholeLine: true,
          className: "compiler-issue-line-highlight",
        },
      },
    ]);
    issueHighlightTimerRef.current = setTimeout(() => {
      issueHighlightRef.current?.clear();
      issueHighlightTimerRef.current = null;
    }, ISSUE_HIGHLIGHT_DURATION_MS);
  }

  function cancelPendingAutoCompile() {
    if (autoCompileTimerRef.current) {
      clearTimeout(autoCompileTimerRef.current);
      autoCompileTimerRef.current = null;
    }
  }

  async function runCompile(sourceOverride?: string) {
    const requestId = latestCompileRequestRef.current + 1;
    latestCompileRequestRef.current = requestId;
    clearCompilerMarkers();
    setActiveTab("compiler");
    setCompileError(null);
    setCheckError(null);
    if (hasCompletedCompileRef.current) {
      setIsChecking(true);
    }
    setIsCompiling(true);
    isCompileInFlightRef.current = true;
    const submittedVersion = codeVersionRef.current;

    try {
      const currentCode =
        sourceOverride ?? editorRef.current?.getValue() ?? code;
      const result = await compileCpp(currentCode);
      if (
        !isMountedRef.current ||
        requestId !== latestCompileRequestRef.current ||
        submittedVersion !== codeVersionRef.current
      ) {
        return;
      }

      hasCompletedCompileRef.current = true;
      setCompileResult(result);
      setIsChecking(false);
      setCheckError(null);
      applyCompilerMarkers(result.diagnostics);
    } catch (error) {
      if (
        !isMountedRef.current ||
        requestId !== latestCompileRequestRef.current ||
        submittedVersion !== codeVersionRef.current
      ) {
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "The compiler backend could not complete the request.";
      if (hasCompletedCompileRef.current) {
        setCheckError(message);
        setIsChecking(false);
      } else {
        setCompileError(message);
      }
    } finally {
      if (
        isMountedRef.current &&
        requestId === latestCompileRequestRef.current
      ) {
        isCompileInFlightRef.current = false;
        setIsCompiling(false);
      }
    }
  }

  function handleCompile() {
    cancelPendingAutoCompile();
    void runCompile();
  }

  async function handleRunTests() {
    if (
      isRunningTests ||
      !testMode ||
      !testTarget
    ) {
      setActiveTab("tests");
      return;
    }
    const selectedFunction =
      testTarget === "function"
        ? (testMode.functions.find(
            (candidate) => candidate.id === selectedFunctionIdRef.current,
          ) ?? null)
        : null;
    if (testTarget === "function" && !selectedFunction) {
      setActiveTab("tests");
      return;
    }
    const invalidExceptionExpectation = (
      expectation: EditableExceptionExpectation,
    ) =>
      expectation.expected_outcome === "throws" &&
      (!expectation.expected_exception_type ||
        (expectation.exception_message_rule !== "ignore" &&
          !expectation.expected_exception_message));
    if (
      (testTarget === "function" &&
        testCases.some(invalidExceptionExpectation)) ||
      (testTarget === "object" &&
        objectScenarios.some(
          (scenario) =>
            scenario.objects.some(invalidExceptionExpectation) ||
            scenario.steps.some(invalidExceptionExpectation),
        ))
    ) {
      setActiveTab("tests");
      setTestRunError(
        "Choose an exception type and provide a message for exact or contains matching.",
      );
      return;
    }
    setActiveTab("tests");
    setIsRunningTests(true);
    setTestRunError(null);
    setTestRunErrorCode(null);
    setTestRunResult(null);

    try {
      const currentCode = editorRef.current?.getValue() ?? code;
      const mutableParameters = selectedFunction?.parameters.filter(
        (parameter) =>
          parameter.type_metadata.passing === "mutable_reference" ||
          parameter.type_metadata.passing === "scalar_pointer" ||
          parameter.type_metadata.passing === "array_pointer",
      );
      const request =
        testTarget === "function"
          ? {
              mode: "function" as const,
              code: currentCode,
              language: "cpp" as const,
              target_function: selectedFunction!.id,
              comparison_mode: comparisonMode,
              run_memory_checks: runMemoryChecks,
              tests: testCases.map((test) => ({
                name: test.name,
                arguments: test.arguments,
                ...exceptionExpectationPayload(test),
                check_stdout:
                  test.expected_outcome === "throws"
                    ? false
                    : test.check_stdout,
                ...(test.expected_outcome === "return_value"
                  ? { expected_return: test.expected_return }
                  : {}),
                ...(test.expected_outcome !== "throws" && test.check_stdout
                  ? { expected_stdout: test.expected_stdout }
                  : {}),
                ...(test.expected_outcome !== "throws" &&
                mutableParameters?.length
                  ? {
                      expected_mutations: mutableParameters.map(
                        (parameter) => ({
                          parameter_id: parameter.name,
                          expected_final_value:
                            test.expected_final_arguments[
                              parameter.name
                            ] ?? "",
                        }),
                      ),
                    }
                  : {}),
              })),
            }
          : testTarget === "object"
            ? {
                mode: "object" as const,
                code: currentCode,
                language: "cpp" as const,
                comparison_mode: comparisonMode,
                run_memory_checks: runMemoryChecks,
                tests: objectScenarios.map((scenario) => {
                  const classByObjectId = new Map(
                    scenario.objects.map((object) => [
                      object.id,
                      object.class_id,
                    ]),
                  );
                  return {
                    name: scenario.name,
                    objects: scenario.objects.map((object) => ({
                      object_id: object.id,
                      name: object.name,
                      class_id: object.class_id,
                      constructor_id: object.constructor_id,
                      arguments: object.arguments,
                      ...exceptionExpectationPayload(object),
                    })),
                    steps: scenario.steps.map((step) => {
                      const operator = testMode.classes
                        .flatMap((item) => item.operators)
                        .find((item) => item.id === step.operator_id);
                      const targetClassId = classByObjectId.get(
                        step.target_object_id,
                      );
                      const targetClass = testMode.classes.find(
                        (item) => item.id === targetClassId,
                      );
                      const method = targetClass?.methods.find(
                        (item) => item.id === step.method_id,
                      );
                      const isMethodStep = ["method", "observer"].includes(
                        step.step_type,
                      );
                      const expectation =
                        exceptionExpectationPayload(step);
                      if (step.step_type === "create_object") {
                        if (
                          step.expected_outcome !== "throws" &&
                          step.result_object_id
                        ) {
                          classByObjectId.set(
                            step.result_object_id,
                            step.class_id,
                          );
                        }
                        return {
                          ...expectation,
                          step_type: step.step_type,
                          class_id: step.class_id,
                          constructor_id: step.constructor_id,
                          arguments: step.arguments,
                          result_object_id: step.result_object_id,
                          result_name: step.result_name,
                        };
                      }
                      if (
                        step.expected_outcome !== "throws" &&
                        step.result_object_id
                      ) {
                        const resultClassId =
                          step.step_type === "operator"
                            ? operator?.return_object_class_id
                            : classByObjectId.get(step.source_object_id);
                        if (resultClassId) {
                          classByObjectId.set(
                            step.result_object_id,
                            resultClassId,
                          );
                        }
                      }
                      if (isMethodStep) {
                        return {
                          ...expectation,
                          step_type: step.step_type,
                          target_object_id: step.target_object_id,
                          method_id: step.method_id,
                          arguments: step.arguments,
                          check_stdout: step.check_stdout,
                          ...(step.expected_outcome === "return_value" &&
                          method?.return_type_metadata.kind !== "void"
                            ? { expected_return: step.expected_return }
                            : {}),
                          ...(step.check_stdout
                            ? { expected_stdout: step.expected_stdout }
                            : {}),
                        };
                      }
                      if (step.step_type === "operator") {
                        return {
                          ...expectation,
                          step_type: step.step_type,
                          target_object_id: step.target_object_id,
                              operator_id: step.operator_id,
                              operands: step.operands,
                          check_stdout: step.check_stdout,
                              ...(operator?.return_kind === "object_value"
                                ? {
                                    result_object_id: step.result_object_id,
                                    result_name: step.result_name,
                                  }
                                : {}),
                          ...(step.expected_outcome === "return_value" &&
                          operator?.return_kind === "value"
                            ? { expected_return: step.expected_return }
                            : {}),
                          ...(step.check_stdout
                          ? { expected_stdout: step.expected_stdout }
                          : {}),
                        };
                      }
                      return {
                        ...expectation,
                        step_type: step.step_type,
                        target_object_id: step.target_object_id,
                        special_member_id: step.special_member_id,
                        source_object_id: step.source_object_id,
                        ...(step.result_object_id
                          ? {
                              result_object_id: step.result_object_id,
                              result_name: step.result_name,
                            }
                          : {}),
                      };
                    }),
                  };
                }),
              }
            : {
              mode: "program" as const,
              code: currentCode,
              language: "cpp" as const,
              comparison_mode: comparisonMode,
              run_memory_checks: runMemoryChecks,
              tests: testCases.map(({ name, stdin, expected_stdout }) => ({
                name,
                stdin,
                expected_stdout,
              })),
            };
      const result = await runCppTests(request);
      if (!isMountedRef.current) return;
      setTestRunResult(result);
    } catch (error) {
      if (!isMountedRef.current) return;
      setTestRunError(
        error instanceof Error
          ? error.message
          : "The backend could not run the tests.",
      );
      setTestRunErrorCode(
        error instanceof RunTestsRequestError ? error.code : null,
      );
    } finally {
      if (isMountedRef.current) {
        setIsRunningTests(false);
      }
    }
  }

  function updateTestCase(
    id: string,
    field:
      | "name"
      | "stdin"
      | "expected_stdout"
      | "expected_return",
    value: string,
  ) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id ? { ...test, [field]: value } : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateTestArgument(id: string, index: number, value: string) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id
          ? {
              ...test,
              arguments: test.arguments.map((argument, argumentIndex) =>
                argumentIndex === index ? value : argument,
              ),
            }
          : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function addTestCase() {
    if (testCases.length >= MAX_TEST_CASES) return;
    const sequence = nextTestIdRef.current;
    nextTestIdRef.current += 1;
    setTestCases((current) => [
      ...current,
      {
        id: `test-${sequence}`,
        name: `Test ${sequence}`,
        stdin: "",
        expected_stdout: "",
        arguments:
          testTarget === "function" && selectedFunction
            ? selectedFunction.parameters.map(() => "")
            : [],
        expected_return: "",
        expected_final_arguments: {},
        check_stdout: defaultOutputCheck(selectedFunction),
        expected_outcome:
          selectedFunction?.return_type_metadata.kind === "void"
            ? "return_void"
            : "return_value",
        expected_exception_type: "",
        exception_message_rule: "ignore",
        expected_exception_message: "",
      },
    ]);
    setTestRunResult(null);
    setTestRunError(null);
  }

  function selectFunction(functionId: string) {
    const nextId = functionId || null;
    const nextFunction =
      testMode
        ? (testMode.functions.find(
            (candidate) => candidate.id === nextId,
          ) ?? null)
        : null;
    selectedFunctionIdRef.current = nextId;
    setSelectedFunctionId(nextId);
    setTestCases((current) =>
      current.map((test) => ({
        ...test,
        arguments: nextFunction
          ? nextFunction.parameters.map(() => "")
          : [],
        expected_return: "",
        expected_stdout: "",
        expected_final_arguments: {},
        check_stdout: defaultOutputCheck(nextFunction),
        expected_outcome:
          nextFunction?.return_type_metadata.kind === "void"
            ? "return_void"
            : "return_value",
        expected_exception_type: "",
        exception_message_rule: "ignore",
        expected_exception_message: "",
      })),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function removeTestCase(id: string) {
    setTestCases((current) => current.filter((test) => test.id !== id));
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateComparisonMode(
    mode: "whitespace_tolerant" | "exact",
  ) {
    setComparisonMode(mode);
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateExpectedFinalArgument(
    id: string,
    parameterName: string,
    value: string,
  ) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id
          ? {
              ...test,
              expected_final_arguments: {
                ...test.expected_final_arguments,
                [parameterName]: value,
              },
            }
          : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateOutputCheck(id: string, checked: boolean) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id ? { ...test, check_stdout: checked } : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopyStatus("Code copied");
    } catch {
      setCopyStatus("Could not copy code");
    }

    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopyStatus(null), 2000);
  }

  function handleDownload() {
    const downloadName = sanitizeFilename(filename);
    const blobUrl = URL.createObjectURL(
      new Blob([code], { type: "text/x-c++src;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = downloadName;
    link.click();
    URL.revokeObjectURL(blobUrl);
    setFilename(downloadName);
  }

  if (reviewedCode === null) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
        <div className="text-center">
          <p className="font-semibold text-slate-900">No reviewed code found.</p>
          <button
            type="button"
            onClick={() => router.push("/")}
            className="mt-4 rounded-lg bg-slate-900 px-5 py-2.5 font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Return to Upload
          </button>
        </div>
      </main>
    );
  }

  const primaryDiagnostics =
    compileResult?.diagnostics.filter(isPrimaryDiagnostic) ?? [];
  const selectedFunction =
    testMode && testTarget === "function"
      ? (testMode.functions.find(
          (candidate) => candidate.id === selectedFunctionId,
        ) ?? null)
      : null;
  const mutableParameters = selectedFunction?.parameters.filter(
    (parameter) =>
      parameter.type_metadata.passing === "mutable_reference" ||
      parameter.type_metadata.passing === "scalar_pointer" ||
      parameter.type_metadata.passing === "array_pointer",
  );
  const objectScenariosReady =
    objectScenarios.length > 0 &&
    objectScenarios.every(
      (scenario) => isObjectScenarioReady(scenario),
    );
  const isCleanCompileSuccess =
    compileResult?.success === true &&
    compileResult.exit_code === 0 &&
    compileResult.diagnostics.length === 0;
  const hasUnstructuredCompilerOutput =
    Boolean(compileResult) &&
    !isCleanCompileSuccess &&
    primaryDiagnostics.length === 0 &&
    Boolean(compileResult?.stderr.trim() || compileResult?.stdout.trim());

  return (
    <main className="min-h-screen bg-slate-100 p-3 sm:p-5">
      <div className="mx-auto max-w-[1600px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="border-b border-slate-200 px-4 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <p className="mr-2 font-bold tracking-tight text-slate-950">InkToCode</p>
            <div className="flex min-w-48 flex-1 items-center gap-2 sm:flex-none">
              <label htmlFor="editor-filename" className="text-sm font-medium text-slate-600">
                Filename
              </label>
              <input
                id="editor-filename"
                value={filename}
                onChange={(event) => setFilename(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-300 sm:w-44"
              />
            </div>
            <span className="rounded-md bg-slate-100 px-2.5 py-1.5 text-sm font-semibold text-slate-600">
              C++17
            </span>
            <span className="text-xs font-medium text-slate-500">
              {isEdited ? "Edited locally" : "Unchanged"}
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Copy Code
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Download
              </button>
              <button
                type="button"
                onClick={handleCompile}
                disabled={isCompiling}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCompiling ? "Compiling..." : "Compile"}
              </button>
              <button
                type="button"
                onClick={() => void handleRunTests()}
                disabled={
                  isRunningTests ||
                  isAnalyzingTests ||
                  !testMode ||
                  !testTarget ||
                  (testTarget !== "object" && testCases.length === 0) ||
                  (testTarget === "object" && !objectScenariosReady) ||
                  (testTarget === "function" && !selectedFunction)
                }
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRunningTests ? "Running Tests..." : "Run Tests"}
              </button>
            </div>
          </div>
          <div aria-live="polite" className="mt-2 min-h-5 text-right text-sm text-slate-600">
            {copyStatus}
          </div>
        </header>

        <div className="grid lg:grid-cols-[minmax(0,1fr)_22rem]">
          <section aria-label="C++ source editor" className="min-w-0 bg-[#1e1e1e]">
            <Editor
              height="65vh"
              defaultLanguage="cpp"
              value={code}
              onChange={(value) => {
                const nextCode = value ?? "";
                if (nextCode === currentSourceRef.current) return;
                currentSourceRef.current = nextCode;
                codeVersionRef.current += 1;
                cancelPendingAutoCompile();
                clearCompilerMarkers();
                if (issueHighlightTimerRef.current) {
                  clearTimeout(issueHighlightTimerRef.current);
                  issueHighlightTimerRef.current = null;
                }
                issueHighlightRef.current?.clear();
                setTestRunResult(null);
                setTestRunError(null);
                setIsAnalyzingTests(true);
                setTestModeError(null);
                if (
                  hasCompletedCompileRef.current ||
                  isCompileInFlightRef.current
                ) {
                  if (hasCompletedCompileRef.current) {
                    setIsChecking(true);
                  }
                  setCheckError(null);
                  autoCompileTimerRef.current = setTimeout(() => {
                    autoCompileTimerRef.current = null;
                    void runCompile(nextCode);
                  }, AUTO_COMPILE_DEBOUNCE_MS);
                } else {
                  setCompileError(null);
                }
                setCode(nextCode);
                setReviewedCode(nextCode);
                setIsEdited(nextCode !== initialCodeRef.current);
              }}
              onMount={handleEditorMount}
              loading={
                <p className="p-6 text-sm text-slate-300">Loading code editor…</p>
              }
              options={{
                automaticLayout: true,
                fontSize: 14,
                lineNumbers: "on",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                tabSize: 4,
                wordWrap: "off",
              }}
              theme="vs-dark"
            />
          </section>

          <aside className="min-h-72 border-t border-slate-200 bg-white lg:border-l lg:border-t-0">
            <div role="tablist" aria-label="Editor results" className="flex border-b border-slate-200">
              {(["compiler", "tests"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  aria-controls={`${tab}-panel`}
                  id={`${tab}-tab`}
                  onClick={() => setActiveTab(tab)}
                  className={`flex-1 border-b-2 px-4 py-3 text-sm font-semibold capitalize focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-slate-900 ${
                    activeTab === tab
                      ? "border-slate-900 text-slate-950"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div
              id={`${activeTab}-panel`}
              role="tabpanel"
              aria-labelledby={`${activeTab}-tab`}
              className="p-4"
            >
              {activeTab === "compiler" &&
                (isCompiling && !compileResult ? (
                  <p className="text-sm leading-6 text-slate-600" aria-live="polite">
                    Compiling current editor contents...
                  </p>
                ) : compileError ? (
                  <div role="alert" className="border-l-2 border-rose-300 pl-3">
                    <p className="text-sm font-medium text-slate-800">
                      Compiler unavailable
                    </p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      {compileError}
                    </p>
                  </div>
                ) : compileResult ? (
                  isCleanCompileSuccess ? (
                    isChecking ? (
                      <div role="status" aria-live="polite">
                        <p className="text-sm font-medium text-slate-700">
                          Checking…
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          Running the C++17 compiler check.
                        </p>
                      </div>
                    ) : checkError ? (
                      <div
                        role="alert"
                        className="border-l-2 border-rose-300 pl-3"
                      >
                        <p className="text-sm font-medium text-slate-800">
                          Latest check unavailable
                        </p>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {checkError}
                        </p>
                      </div>
                    ) : (
                      <div role="status">
                        <p className="flex items-center gap-2 text-sm font-medium text-slate-800">
                          <span
                            aria-hidden="true"
                            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-emerald-200 text-emerald-700"
                          >
                            <svg
                              viewBox="0 0 20 20"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              className="h-3.5 w-3.5"
                            >
                              <path
                                d="m5 10 3 3 7-7"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </span>
                          Compilation successful
                        </p>
                        <p className="mt-3 text-sm text-slate-700">
                          No compiler issues found.
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          Your code passed the C++17 compiler check.
                        </p>
                      </div>
                    )
                  ) : (
                    <div role="status">
                      {primaryDiagnostics.length > 0 ? (
                        <>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <h3 className="text-sm font-medium text-slate-800">
                                Compilation Issues
                              </h3>
                              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium tabular-nums text-slate-600">
                                {primaryDiagnostics.length}
                              </span>
                            </div>
                            {isChecking && (
                              <span
                                aria-live="polite"
                                className="text-xs text-slate-500"
                              >
                                Checking…
                              </span>
                            )}
                          </div>
                          <ul
                            className={`mt-2 divide-y divide-slate-200 border-y border-slate-200 transition-opacity ${
                              isChecking ? "opacity-70" : ""
                            }`}
                          >
                            {primaryDiagnostics.map((diagnostic, index) => {
                              return (
                                <li
                                  key={`${diagnostic.line}-${diagnostic.column}-${index}`}
                                  className="py-2 first:pt-0 last:pb-0"
                                >
                                  <div className="rounded-md border border-rose-100 bg-white">
                                    <button
                                      type="button"
                                      onClick={() => focusDiagnostic(diagnostic)}
                                      className="w-full cursor-pointer rounded-md px-2 py-2.5 text-left transition-colors hover:bg-slate-50 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                                      aria-label={`Go to ${diagnostic.severity} on line ${diagnostic.line}, column ${diagnostic.column}: ${diagnostic.message}`}
                                    >
                                      <span className="flex items-center justify-between gap-3">
                                        <span className="text-xs font-medium text-slate-700">
                                          {getIssueCategory(diagnostic)}
                                        </span>
                                        <span className="shrink-0 text-xs tabular-nums text-slate-500">
                                          Line {diagnostic.line}
                                        </span>
                                      </span>
                                      <span className="mt-1.5 block break-words font-mono text-xs leading-5 text-slate-800">
                                        {diagnostic.message}
                                      </span>
                                      {diagnostic.explanation && (
                                        <span className="mt-2 block text-xs leading-5 text-slate-500">
                                          <span className="sr-only">
                                            Explanation:{" "}
                                          </span>
                                          {diagnostic.explanation}
                                        </span>
                                      )}
                                    </button>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                          {checkError && (
                            <p
                              role="status"
                              className="mt-2 text-xs leading-5 text-slate-600"
                            >
                              Latest check failed: {checkError}
                            </p>
                          )}
                        </>
                      ) : hasUnstructuredCompilerOutput ? (
                        <p className="text-sm font-medium text-slate-700">
                          Compiler output needs review
                        </p>
                      ) : (
                        <p className="text-sm font-medium text-slate-700">
                          Compilation did not complete successfully.
                        </p>
                      )}
                      {(compileResult.stderr || compileResult.stdout) ? (
                        <details className="mt-3">
                          <summary className="cursor-pointer text-xs font-semibold text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                            Show raw compiler output
                          </summary>
                          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">
                            {compileResult.stderr || compileResult.stdout}
                          </pre>
                        </details>
                      ) : (
                        <p className="mt-3 text-sm text-slate-600">
                          The compiler returned no diagnostic output.
                        </p>
                      )}
                      <p className="mt-2 text-xs text-slate-500">
                        Compiler exit code: {compileResult.exit_code}
                      </p>
                    </div>
                  )
                ) : (
                  <p className="text-sm leading-6 text-slate-600">
                    Compile your code to view compiler errors.
                  </p>
                ))}

              {activeTab === "tests" && (
                <div>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-medium text-slate-800">
                        {testTarget === "function"
                          ? "Function Tests"
                          : testTarget === "object"
                            ? "Object Scenario Tests"
                            : "Program Tests"}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        {isAnalyzingTests
                          ? "Determining test mode…"
                          : testTarget === "function" && selectedFunction
                            ? `Function: ${selectedFunction.display}`
                            : testTarget === "function"
                              ? "Choose a function to test."
                            : testTarget === "object"
                              ? "Construct one object and call its methods in order."
                            : testTarget === "program"
                              ? "Use standard input and expected output."
                              : "Testing is unavailable."}
                      </p>
                    </div>
                    {testTarget !== "object" && (
                      <button
                        type="button"
                        onClick={addTestCase}
                        disabled={
                          isRunningTests ||
                          isAnalyzingTests ||
                          !testTarget ||
                          (testTarget === "function" && !selectedFunction) ||
                          testCases.length >= MAX_TEST_CASES
                        }
                        className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Add Test
                      </button>
                    )}
                  </div>

                  {testModeError && (
                    <div
                      role="alert"
                      className="mt-3 border-l-2 border-rose-300 pl-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Test mode unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testModeError}
                      </p>
                    </div>
                  )}
                  {testMode?.mode === "unsupported" && (
                    <div
                      role="status"
                      className="mt-3 rounded-md border border-slate-200 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Function testing unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testMode.message}
                      </p>
                    </div>
                  )}

                  {testMode && testMode.available_modes.length > 0 && (
                    <div className="mt-3">
                      <label
                        htmlFor="test-target-kind"
                        className="block text-xs font-medium text-slate-600"
                      >
                        Test target
                      </label>
                      <select
                        id="test-target-kind"
                        value={testTarget ?? ""}
                        disabled={isRunningTests}
                        onChange={(event) => {
                          setTestTarget(
                            event.target.value as TestTargetKind,
                          );
                          setTestRunResult(null);
                          setTestRunError(null);
                        }}
                        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-60"
                      >
                        {testMode.available_modes.includes("program") && (
                          <option value="program">Full program</option>
                        )}
                        {testMode.available_modes.includes("function") && (
                          <option value="function">Function</option>
                        )}
                        {testMode.available_modes.includes("object") && (
                          <option value="object">Object scenario</option>
                        )}
                      </select>
                    </div>
                  )}

                  {(testTarget === "program" ||
                    testTarget === "object" ||
                    selectedFunction?.return_type_metadata.kind === "void") && (
                    <div className="mt-3">
                      <label
                        htmlFor="output-comparison-mode"
                        className="block text-xs font-medium text-slate-600"
                      >
                        Output comparison
                      </label>
                      <select
                        id="output-comparison-mode"
                        value={comparisonMode}
                        disabled={isRunningTests}
                        onChange={(event) =>
                          updateComparisonMode(
                            event.target.value as
                              | "whitespace_tolerant"
                              | "exact",
                          )
                        }
                        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-700 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <option value="whitespace_tolerant">
                          Ignore whitespace differences
                        </option>
                        <option value="exact">Exact match</option>
                      </select>
                    </div>
                  )}

                  <label className="mt-3 flex items-start gap-2 rounded-md border border-slate-200 p-2.5">
                    <input
                      type="checkbox"
                      checked={runMemoryChecks}
                      disabled={isRunningTests}
                      onChange={(event) => {
                        setRunMemoryChecks(event.target.checked);
                        setTestRunResult(null);
                        setTestRunError(null);
                      }}
                      className="mt-0.5 h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-2 focus:ring-slate-300"
                    />
                    <span>
                      <span className="block text-xs font-medium text-slate-700">
                        Run memory checks
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-4 text-slate-500">
                        Runs C++ memory diagnostics in an isolated Linux
                        environment. This may take longer.
                      </span>
                    </span>
                  </label>

                  {testTarget === "function" &&
                    testMode &&
                    testMode.functions.length > 1 && (
                      <div className="mt-3">
                        <label
                          htmlFor="test-target-function"
                          className="block text-xs font-medium text-slate-600"
                        >
                          Function to test
                        </label>
                        <select
                          id="test-target-function"
                          value={selectedFunctionId ?? ""}
                          disabled={isRunningTests}
                          onChange={(event) =>
                            selectFunction(event.target.value)
                          }
                          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <option value="">Choose a function</option>
                          {testMode.functions.map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>
                              {candidate.display} → {candidate.return_type}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                  {testMode && testTarget === "object" && (
                    <ObjectScenarioTests
                      classes={testMode.classes}
                      scenarios={objectScenarios}
                      disabled={isRunningTests}
                      onChange={(scenarios) => {
                        setObjectScenarios(scenarios);
                        setTestRunResult(null);
                        setTestRunError(null);
                      }}
                    />
                  )}

                  {testMode && testTarget && testTarget !== "object" && (
                  <div className="mt-3 space-y-3">
                    {(testTarget === "program" || selectedFunction) &&
                      testCases.map((test, index) => (
                      <fieldset
                        key={test.id}
                        disabled={isRunningTests}
                        className="rounded-md border border-slate-200 p-3"
                      >
                        <legend className="sr-only">
                          Test case {index + 1}
                        </legend>
                        <div className="flex items-center gap-2">
                          <label
                            htmlFor={`${test.id}-name`}
                            className="sr-only"
                          >
                            Test name
                          </label>
                          <input
                            id={`${test.id}-name`}
                            value={test.name}
                            maxLength={100}
                            onChange={(event) =>
                              updateTestCase(
                                test.id,
                                "name",
                                event.target.value,
                              )
                            }
                            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                          />
                          <button
                            type="button"
                            onClick={() => removeTestCase(test.id)}
                            className="rounded-md px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                            aria-label={`Remove ${test.name || `test ${index + 1}`}`}
                          >
                            Remove
                          </button>
                        </div>
                        {testTarget === "function" &&
                        selectedFunction ? (
                          <>
                            <p className="mt-3 text-xs font-medium text-slate-600">
                              Arguments
                            </p>
                            <div className="mt-1.5 space-y-2">
                              {selectedFunction.parameters.map(
                                (parameter, parameterIndex) => (
                                  <div
                                    key={`${test.id}-${parameter.name}`}
                                    className="min-w-0"
                                  >
                                    <label
                                      htmlFor={`${test.id}-argument-${parameterIndex}`}
                                      className="block min-w-0 text-xs font-medium text-slate-600"
                                    >
                                      <span className="block">
                                        {parameter.name}
                                      </span>
                                      <span className="mt-0.5 block break-words text-[11px] font-normal text-slate-400">
                                        {parameter.type}
                                      </span>
                                    </label>
                                    <div className="mt-1 min-w-0">
                                      {mutableParameters?.some(
                                        (candidate) =>
                                          candidate.name === parameter.name,
                                      ) && (
                                        <p className="mb-1 text-[11px] font-medium text-slate-500">
                                          Initial value
                                        </p>
                                      )}
                                      {parameter.type_metadata.vector_depth ===
                                      2 ? (
                                        <textarea
                                          id={`${test.id}-argument-${parameterIndex}`}
                                          value={
                                            test.arguments[parameterIndex] ?? ""
                                          }
                                          maxLength={1_000}
                                          rows={4}
                                          placeholder={
                                            parameter.type_metadata
                                              .element_type === "std::string"
                                              ? '[["hello"], ["world"]]'
                                              : "[[1, 2], [3, 4]]"
                                          }
                                          onChange={(event) =>
                                            updateTestArgument(
                                              test.id,
                                              parameterIndex,
                                              event.target.value,
                                            )
                                          }
                                          className="w-full min-w-0 resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                        />
                                      ) : (
                                        <input
                                          id={`${test.id}-argument-${parameterIndex}`}
                                          value={
                                            test.arguments[parameterIndex] ?? ""
                                          }
                                          maxLength={1_000}
                                          placeholder={
                                            parameter.type_metadata.kind ===
                                              "vector" ||
                                            parameter.type_metadata.kind ===
                                              "array"
                                              ? parameter.type_metadata
                                                  .element_type ===
                                                "std::string"
                                                ? '["hello", "world"]'
                                                : "[1, 2, 3]"
                                              : undefined
                                          }
                                          onChange={(event) =>
                                            updateTestArgument(
                                              test.id,
                                              parameterIndex,
                                              event.target.value,
                                            )
                                          }
                                          className="w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                        />
                                      )}
                                      {(parameter.type_metadata.kind ===
                                        "vector" ||
                                        parameter.type_metadata.kind ===
                                          "array") && (
                                        <p className="mt-1 text-[11px] text-slate-500">
                                          {parameter.type_metadata
                                            .vector_depth === 2
                                            ? "Enter rows like [[1, 2], [3, 4]]"
                                            : parameter.type_metadata
                                                  .element_type ===
                                                "std::string"
                                              ? 'Enter values like ["hello", "world"]'
                                              : "Enter values like [1, 2, 3]"}
                                          </p>
                                      )}
                                    </div>
                                  </div>
                                ),
                              )}
                              {selectedFunction.parameters.length === 0 && (
                                <p className="text-xs text-slate-500">
                                  This function takes no arguments.
                                </p>
                              )}
                            </div>
                            <ExceptionExpectationFields
                              id={test.id}
                              value={test}
                              supportsReturnValue={
                                selectedFunction.return_type_metadata.kind !==
                                "void"
                              }
                              onChange={(expectation) => {
                                setTestCases((current) =>
                                  current.map((item) =>
                                    item.id === test.id
                                      ? {
                                          ...item,
                                          ...expectation,
                                          expected_return:
                                            expectation.expected_outcome ===
                                            "return_value"
                                              ? item.expected_return
                                              : "",
                                          check_stdout:
                                            expectation.expected_outcome ===
                                            "throws"
                                              ? false
                                              : item.check_stdout,
                                          expected_stdout:
                                            expectation.expected_outcome ===
                                            "throws"
                                              ? ""
                                              : item.expected_stdout,
                                          expected_final_arguments:
                                            expectation.expected_outcome ===
                                            "throws"
                                              ? {}
                                              : item.expected_final_arguments,
                                        }
                                      : item,
                                  ),
                                );
                                setTestRunResult(null);
                                setTestRunError(null);
                              }}
                            />
                            {selectedFunction.return_type_metadata.kind !==
                              "void" &&
                              test.expected_outcome === "return_value" && (
                              <>
                                <label
                                  htmlFor={`${test.id}-expected-return`}
                                  className="mt-3 block text-xs font-medium text-slate-600"
                                >
                                  Expected return —{" "}
                                  {
                                    selectedFunction.return_type_metadata
                                      .display_type
                                  }
                                </label>
                                {selectedFunction.return_type_metadata
                                  .vector_depth === 2 ? (
                                  <textarea
                                    id={`${test.id}-expected-return`}
                                    value={test.expected_return}
                                    placeholder="[[1, 2], [3, 4]]"
                                    maxLength={1_000}
                                    rows={4}
                                    onChange={(event) =>
                                      updateTestCase(
                                        test.id,
                                        "expected_return",
                                        event.target.value,
                                      )
                                    }
                                    className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                  />
                                ) : (
                                  <input
                                    id={`${test.id}-expected-return`}
                                    value={test.expected_return}
                                    placeholder={
                                      selectedFunction.return_type_metadata
                                        .kind === "vector"
                                        ? selectedFunction.return_type_metadata
                                            .element_type === "std::string"
                                          ? '["hello", "world"]'
                                          : "[1, 2, 3]"
                                        : undefined
                                    }
                                    maxLength={1_000}
                                    onChange={(event) =>
                                      updateTestCase(
                                        test.id,
                                        "expected_return",
                                        event.target.value,
                                      )
                                    }
                                    className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                  />
                                )}
                                {selectedFunction.return_type_metadata.kind ===
                                  "vector" && (
                                  <p className="mt-1 text-[11px] text-slate-500">
                                    {selectedFunction.return_type_metadata
                                      .element_type === "std::string"
                                      ? 'Enter values like ["hello", "world"]'
                                      : "Enter values like [1, 2, 3]"}
                                  </p>
                                )}
                              </>
                            )}
                            {test.expected_outcome !== "throws" && (
                            <label className="mt-3 flex items-center gap-2 text-xs font-medium text-slate-600">
                              <input
                                type="checkbox"
                                checked={test.check_stdout}
                                onChange={(event) =>
                                  updateOutputCheck(
                                    test.id,
                                    event.target.checked,
                                  )
                                }
                                className="size-3.5 rounded border-slate-300 text-slate-800 focus:ring-slate-300"
                              />
                              Check function output
                            </label>
                            )}
                            {test.expected_outcome !== "throws" &&
                              test.check_stdout && (
                              <>
                                <label
                                  htmlFor={`${test.id}-expected-output`}
                                  className="mt-2 block text-xs font-medium text-slate-600"
                                >
                                  Expected output
                                </label>
                                <textarea
                                  id={`${test.id}-expected-output`}
                                  value={test.expected_stdout}
                                  maxLength={64 * 1024}
                                  rows={3}
                                  onChange={(event) =>
                                    updateTestCase(
                                      test.id,
                                      "expected_stdout",
                                      event.target.value,
                                    )
                                  }
                                  className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                />
                              </>
                            )}
                            {test.expected_outcome !== "throws" &&
                              mutableParameters &&
                              mutableParameters.length > 0 && (
                              <>
                                <p className="mt-3 text-xs font-medium text-slate-600">
                                  Expected mutations
                                </p>
                                <div className="mt-1.5 space-y-2">
                                  {mutableParameters.map((parameter) => {
                                    const parameterIndex =
                                      selectedFunction.parameters.findIndex(
                                        (candidate) =>
                                          candidate.name === parameter.name,
                                      );
                                    return (
                                      <div
                                        key={`${test.id}-expected-${parameter.name}`}
                                        className="min-w-0"
                                      >
                                        <label
                                          htmlFor={`${test.id}-expected-final-${parameterIndex}`}
                                          className="block min-w-0 text-xs font-medium text-slate-600"
                                        >
                                          <span className="block">
                                            {parameter.name}
                                          </span>
                                          <span className="mt-0.5 block text-[11px] font-normal text-slate-500">
                                            Expected final value
                                          </span>
                                        </label>
                                        {parameter.type_metadata
                                          .vector_depth === 2 ? (
                                          <textarea
                                            id={`${test.id}-expected-final-${parameterIndex}`}
                                            value={
                                              test.expected_final_arguments[
                                                parameter.name
                                              ] ?? ""
                                            }
                                            maxLength={1_000}
                                            rows={4}
                                            placeholder="[[1, 2], [3, 4]]"
                                            onChange={(event) =>
                                              updateExpectedFinalArgument(
                                                test.id,
                                                parameter.name,
                                                event.target.value,
                                              )
                                            }
                                            className="mt-1 w-full min-w-0 resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                          />
                                        ) : (
                                          <input
                                            id={`${test.id}-expected-final-${parameterIndex}`}
                                            value={
                                              test.expected_final_arguments[
                                                parameter.name
                                              ] ?? ""
                                            }
                                            maxLength={1_000}
                                            onChange={(event) =>
                                              updateExpectedFinalArgument(
                                                test.id,
                                                parameter.name,
                                                event.target.value,
                                              )
                                            }
                                            className="mt-1 w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                          />
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </>
                            )}
                          </>
                        ) : (
                          <>
                            <label
                              htmlFor={`${test.id}-stdin`}
                              className="mt-3 block text-xs font-medium text-slate-600"
                            >
                              Standard input
                            </label>
                            <textarea
                              id={`${test.id}-stdin`}
                              value={test.stdin}
                              maxLength={64 * 1024}
                              rows={3}
                              onChange={(event) =>
                                updateTestCase(
                                  test.id,
                                  "stdin",
                                  event.target.value,
                                )
                              }
                              className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                            />
                            <label
                              htmlFor={`${test.id}-expected`}
                              className="mt-3 block text-xs font-medium text-slate-600"
                            >
                              Expected output
                            </label>
                            <textarea
                              id={`${test.id}-expected`}
                              value={test.expected_stdout}
                              maxLength={64 * 1024}
                              rows={3}
                              onChange={(event) =>
                                updateTestCase(
                                  test.id,
                                  "expected_stdout",
                                  event.target.value,
                                )
                              }
                              className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                            />
                          </>
                        )}
                      </fieldset>
                    ))}
                  </div>
                  )}

                  {testTarget !== "object" && testCases.length === 0 && (
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                      Add at least one test before running the program.
                    </p>
                  )}
                  {testTarget !== "object" &&
                    testCases.length >= MAX_TEST_CASES && (
                    <p className="mt-2 text-xs text-slate-500">
                      Maximum of {MAX_TEST_CASES} tests reached.
                    </p>
                  )}
                  {isRunningTests && (
                    <p
                      role="status"
                      aria-live="polite"
                      className="mt-4 text-sm text-slate-600"
                    >
                      Compiling and running tests…
                    </p>
                  )}
                  {testRunError && (
                    <div
                      role="alert"
                      className="mt-4 border-l-2 border-rose-300 pl-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {testRunErrorCode === "memory_compile_timeout"
                          ? "Memory-check compilation timed out"
                          : "Test runner unavailable"}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testRunError}
                      </p>
                    </div>
                  )}
                  {testRunResult?.compile_error && (
                    <div
                      role="alert"
                      className="mt-4 rounded-md border border-rose-100 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Tests could not run
                      </p>
                      <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-600">
                        {testRunResult.compile_error}
                      </pre>
                    </div>
                  )}
                  {(testRunResult?.input_error ||
                    testRunResult?.unsupported_error) && (
                    <div
                      role="alert"
                      className="mt-4 rounded-md border border-slate-200 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {testRunResult.unsupported_error
                          ? "Function testing unavailable"
                          : "Check test values"}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testRunResult.unsupported_error ||
                          testRunResult.input_error}
                      </p>
                    </div>
                  )}
                  {testRunResult?.memory_status === "unavailable" &&
                    testRunResult.tests.length === 0 && (
                    <div
                      role="status"
                      className="mt-4 rounded-md border border-amber-200 p-3"
                    >
                      <p className="text-sm font-medium text-amber-700">
                        CHECK INCOMPLETE — Scenario 1
                      </p>
                      <p className="mt-2 text-xs text-slate-600">
                        Behaviour passed
                      </p>
                      <p className="text-xs text-slate-600">
                        Memory diagnostics unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testRunResult.memory_summary ??
                          "The current compiler does not support the required sanitizer flags."}
                      </p>
                    </div>
                  )}
                  {testRunResult && testRunResult.tests.length > 0 && (
                    <ul className="mt-4 space-y-3" aria-label="Test results">
                      {testRunResult.tests.map((result, index) => {
                        const presentation = getResultPresentation(result);
                        const scenarioSummary = isObjectScenarioResult(result)
                          ? getObjectScenarioSummary(result)
                          : null;
                        return (
                        <li
                          key={`${result.name}-${index}`}
                          className={`rounded-md border p-3 ${
                            presentation.tone === "success"
                              ? "border-emerald-100"
                              : presentation.tone === "warning"
                                ? "border-amber-200"
                                : "border-rose-100"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-medium text-slate-800">
                              <span
                                className={
                                  presentation.tone === "success"
                                    ? "text-emerald-700"
                                    : presentation.tone === "warning"
                                      ? "text-amber-700"
                                      : "text-rose-700"
                                }
                              >
                                {presentation.label}
                              </span>
                              {" — "}
                              {result.name}
                            </p>
                            {!result.memory_check_enabled &&
                              !result.timed_out &&
                              result.exit_code !== null && (
                                <span className="text-xs tabular-nums text-slate-500">
                                  Exit {result.exit_code}
                                </span>
                              )}
                          </div>
                          {result.memory_check_enabled && (
                            <div className="mt-2 text-xs leading-5 text-slate-600">
                              <p>{presentation.behaviorText}</p>
                              {presentation.memoryText && (
                                <p>{presentation.memoryText}</p>
                              )}
                            </div>
                          )}
                          {result.exception_result && (
                            <ExceptionOutcomeSummary
                              result={result.exception_result}
                            />
                          )}
                          {isObjectScenarioResult(result) && (
                            <div className="mt-3 space-y-2">
                              <div className="min-w-0 rounded bg-slate-50 p-2 text-xs leading-5">
                                <p className="font-medium text-slate-800">
                                  {scenarioSummary?.title}
                                </p>
                                {scenarioSummary?.detail && (
                                  <p className="break-words font-mono text-slate-700">
                                    {scenarioSummary.detail}
                                  </p>
                                )}
                                {scenarioSummary?.supporting && (
                                  <p className="text-slate-600">
                                    {scenarioSummary.supporting}
                                  </p>
                                )}
                                {result.moved_from_objects.map((item) => (
                                  <p
                                    key={`moved-${item}`}
                                    className="text-slate-500"
                                  >
                                    {item} — moved from
                                  </p>
                                ))}
                              </div>
                              <ObjectScenarioSteps result={result} />
                              {result.destruction_failed &&
                                !result.memory_check_enabled && (
                                <p className="border-t border-slate-200 pt-2 text-xs font-medium text-rose-700">
                                  Scenario steps completed, but object
                                  destruction failed.
                                </p>
                                )}
                            </div>
                          )}
                          {isFunctionCombinedResult(result) && (
                            <div className="mt-3 space-y-3">
                              {result.return_result && (
                                <div>
                                  <div className="flex items-center justify-between gap-2">
                                    <p className="text-xs font-medium text-slate-500">
                                      Return value
                                    </p>
                                    <span
                                      className={`text-[11px] font-medium ${
                                        result.return_result.passed
                                          ? "text-emerald-700"
                                          : "text-rose-700"
                                      }`}
                                    >
                                      {result.return_result.passed
                                        ? "PASS"
                                        : "FAIL"}
                                    </span>
                                  </div>
                                  <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                                      Expected:{" "}
                                      {result.return_result.expected ||
                                        "(empty)"}
                                    </pre>
                                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                                      Actual:{" "}
                                      {result.return_result.actual || "(empty)"}
                                    </pre>
                                  </div>
                                  {result.return_result.mismatch_detail && (
                                    <p className="mt-1 text-[11px] text-rose-700">
                                      {result.return_result.mismatch_detail}
                                    </p>
                                  )}
                                  {result.stdout_result?.match_type ===
                                    "whitespace_normalized" && (
                                    <p className="mt-1 text-[11px] text-slate-500">
                                      Formatting differences ignored
                                    </p>
                                  )}
                                  {result.stdout_result?.match_type ===
                                    "formatting_mismatch" && (
                                    <p className="mt-1 text-[11px] text-slate-600">
                                      Output values match, but formatting
                                      differs.
                                    </p>
                                  )}
                                </div>
                              )}
                              {result.stdout_result && (
                                <div>
                                  <div className="flex items-center justify-between gap-2">
                                    <p className="text-xs font-medium text-slate-500">
                                      Function output
                                    </p>
                                    <span
                                      className={`text-[11px] font-medium ${
                                        result.stdout_result.passed
                                          ? "text-emerald-700"
                                          : "text-rose-700"
                                      }`}
                                    >
                                      {result.stdout_result.passed
                                        ? "PASS"
                                        : "FAIL"}
                                    </span>
                                  </div>
                                  <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                                      Expected:{" "}
                                      {result.stdout_result.expected ||
                                        "(empty)"}
                                    </pre>
                                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs text-slate-800">
                                      Actual:{" "}
                                      {result.stdout_result.actual || "(empty)"}
                                    </pre>
                                  </div>
                                </div>
                              )}
                              {result.mutation_results.length > 0 && (
                                <div>
                                  <p className="text-xs font-medium text-slate-500">
                                    Mutations
                                  </p>
                                  <div className="mt-1 space-y-2">
                                    {result.mutation_results.map(
                                      (mutation) => (
                                        <dl
                                          key={mutation.parameter}
                                          className="font-mono text-xs text-slate-700"
                                        >
                                          <dt className="font-semibold">
                                            {mutation.parameter}
                                            <span
                                              className={`ml-2 text-[11px] font-sans font-medium ${
                                                mutation.passed
                                                  ? "text-emerald-700"
                                                  : "text-rose-700"
                                              }`}
                                            >
                                              {mutation.passed
                                                ? "PASS"
                                                : "FAIL"}
                                            </span>
                                          </dt>
                                          <dd>Initial: {mutation.initial}</dd>
                                          <dd>
                                            Expected final:{" "}
                                            {mutation.expected_final}
                                          </dd>
                                          <dd>
                                            Actual final:{" "}
                                            {mutation.actual_final}
                                          </dd>
                                          {mutation.mismatch_detail && (
                                            <dd className="mt-1 font-sans text-[11px] text-rose-700">
                                              {mutation.mismatch_detail}
                                            </dd>
                                          )}
                                        </dl>
                                      ),
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                          {isFunctionMutationResult(result) && (
                            <div className="mt-3 space-y-2">
                              {Object.entries(
                                result.expected_final_arguments,
                              ).map(([parameterName, expectedValue]) => (
                                <div key={parameterName}>
                                  <p className="text-xs font-medium text-slate-500">
                                    {parameterName}
                                  </p>
                                  <dl className="mt-1 grid gap-1 font-mono text-xs text-slate-700">
                                    <div className="flex gap-2">
                                      <dt>Initial:</dt>
                                      <dd className="break-all">
                                        {result.initial_arguments[
                                          parameterName
                                        ] ?? "(empty)"}
                                      </dd>
                                    </div>
                                    <div className="flex gap-2">
                                      <dt>Expected final:</dt>
                                      <dd className="break-all">
                                        {expectedValue || "(empty)"}
                                      </dd>
                                    </div>
                                    <div className="flex gap-2">
                                      <dt>Actual final:</dt>
                                      <dd className="break-all">
                                        {result.actual_final_arguments[
                                          parameterName
                                        ] ?? "(empty)"}
                                      </dd>
                                    </div>
                                    {result.mismatch_details[parameterName] && (
                                      <div className="font-sans text-[11px] text-rose-700">
                                        {
                                          result.mismatch_details[
                                            parameterName
                                          ]
                                        }
                                      </div>
                                    )}
                                  </dl>
                                </div>
                              ))}
                            </div>
                          )}
                          {isFunctionResult(result) && (
                            <div className="mt-3 grid gap-3">
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Arguments
                                </p>
                                <dl className="mt-1 space-y-1 font-mono text-xs text-slate-700">
                                  {testRunResult.function?.parameters.map(
                                    (parameter, parameterIndex) => (
                                      <div
                                        key={`${result.name}-${parameter.name}`}
                                        className="flex gap-2"
                                      >
                                        <dt>{parameter.name} =</dt>
                                        <dd className="break-all">
                                          {result.arguments[parameterIndex]}
                                        </dd>
                                      </div>
                                    ),
                                  )}
                                  {result.arguments.length === 0 && (
                                    <div>No arguments</div>
                                  )}
                                </dl>
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <p className="text-xs font-medium text-slate-500">
                                    {isFunctionReturnResult(result)
                                      ? "Expected return"
                                      : "Expected output"}
                                  </p>
                                  <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                    {(isFunctionReturnResult(result)
                                      ? result.expected_return
                                      : result.expected_stdout) || "(empty)"}
                                  </pre>
                                </div>
                                <div>
                                  <p className="text-xs font-medium text-slate-500">
                                    {isFunctionReturnResult(result)
                                      ? "Actual return"
                                      : "Actual output"}
                                  </p>
                                  <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                    {(isFunctionReturnResult(result)
                                      ? result.actual_return
                                      : result.actual_stdout) || "(empty)"}
                                  </pre>
                                </div>
                              </div>
                              {isFunctionReturnResult(result) &&
                                result.mismatch_detail && (
                                  <p className="text-[11px] text-rose-700">
                                    {result.mismatch_detail}
                                  </p>
                                )}
                            </div>
                          )}
                          {result.timed_out ? (
                            <p className="mt-2 text-xs font-medium text-rose-700">
                              Timed out
                            </p>
                          ) : result.output_limited ? (
                            <p className="mt-2 text-xs font-medium text-rose-700">
                              Output limit exceeded
                            </p>
                          ) : result.match_type ===
                            "whitespace_normalized" ? (
                            <p className="mt-2 text-xs text-slate-500">
                              Formatting differences ignored
                            </p>
                          ) : result.match_type === "formatting_mismatch" ? (
                            <p className="mt-2 text-xs text-slate-600">
                              Output values match, but formatting differs.
                            </p>
                          ) : null}
                          <MemoryResultDetails result={result} />
                          {isObjectScenarioResult(result) &&
                            result.big_five_diagnosis &&
                            !result.memory_check_enabled && (
                              <section
                                aria-label="Big Five diagnosis"
                                className={`mt-3 rounded-md border p-3 ${
                                  result.big_five_diagnosis.confidence ===
                                  "confirmed"
                                    ? "border-rose-200 bg-rose-50/30"
                                    : result.big_five_diagnosis.confidence ===
                                        "likely"
                                      ? "border-amber-200 bg-amber-50/30"
                                      : "border-slate-200 bg-slate-50/50"
                                }`}
                              >
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                                  {result.big_five_diagnosis.confidence ===
                                  "confirmed"
                                    ? "Confirmed issue"
                                    : result.big_five_diagnosis.confidence ===
                                        "likely"
                                      ? "Likely issue"
                                      : "Possible issue"}
                                </p>
                                <h4 className="mt-1 text-sm font-semibold text-slate-800">
                                  {result.big_five_diagnosis.title}
                                </h4>
                                <p className="mt-2 text-xs leading-5 text-slate-600">
                                  {result.big_five_diagnosis.summary}
                                </p>
                                {result.big_five_diagnosis.suspicious_ranges.map(
                                  (range) => (
                                    <div
                                      key={`${range.start_line}-${range.end_line}`}
                                      className="mt-3"
                                    >
                                      <p className="text-xs font-medium text-slate-600">
                                        Suspicious code — line{" "}
                                        {range.start_line}
                                        {range.end_line !== range.start_line
                                          ? `–${range.end_line}`
                                          : ""}
                                      </p>
                                      <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
                                        {range.snippet}
                                      </pre>
                                      <p className="mt-1 text-[11px] leading-4 text-slate-500">
                                        {range.reason}
                                      </p>
                                    </div>
                                  ),
                                )}
                                <p className="mt-3 text-xs leading-5 text-slate-600">
                                  <span className="font-medium text-slate-700">
                                    Suggested direction:
                                  </span>{" "}
                                  {
                                    result.big_five_diagnosis
                                      .suggested_direction
                                  }
                                </p>
                                {result.big_five_diagnosis.evidence.length >
                                  0 && (
                                  <details className="mt-2">
                                    <summary className="cursor-pointer text-xs font-medium text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                                      Why InkToCode thinks this
                                    </summary>
                                    <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5 text-slate-600">
                                      {result.big_five_diagnosis.evidence.map(
                                        (evidence) => (
                                          <li key={evidence}>{evidence}</li>
                                        ),
                                      )}
                                    </ul>
                                  </details>
                                )}
                              </section>
                            )}
                          {!result.timed_out &&
                            !result.output_limited &&
                            !result.passed &&
                            !isObjectScenarioResult(result) &&
                            !isFunctionMutationResult(result) &&
                            !isFunctionCombinedResult(result) &&
                            !isFunctionResult(result) && (
                            <div className="mt-3 grid gap-3">
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Expected
                                </p>
                                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                  {result.expected_stdout || "(empty)"}
                                </pre>
                              </div>
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Actual
                                </p>
                                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                  {result.actual_stdout || "(empty)"}
                                </pre>
                              </div>
                            </div>
                          )}
                          {result.stderr && !result.memory_check_enabled && (
                            <details className="mt-3">
                              <summary className="cursor-pointer text-xs font-medium text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                                Show runtime stderr
                              </summary>
                              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
                                {result.stderr}
                              </pre>
                            </details>
                          )}
                        </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </aside>
        </div>

        <footer className="border-t border-slate-200 px-4 py-3 sm:px-5">
          <button
            type="button"
            onClick={() => router.push("/review")}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Back to Review
          </button>
        </footer>
      </div>
    </main>
  );
}
