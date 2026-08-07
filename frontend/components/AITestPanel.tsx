"use client";

import { useRef, useState } from "react";
import type {
  FunctionDescriptor,
  ObjectClass,
  TemplateParameter,
} from "@/lib/testExecution";
import type { EditableTemplateArgumentValue } from "@/lib/templateTesting";
import { templateArgumentsPayload } from "@/lib/templateTesting";
import {
  runAiTests,
  rerunAiTests,
  type AiTestRunResponse,
  type AiStoredTest,
  type AiScore,
} from "@/lib/aiTests";
import {
  signatureHash,
  templateKey,
  runButtonGate,
  shapeResultRows,
  friendlyStatusMessage,
  type AiResultRowDisplay,
} from "@/lib/aiTestState";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TargetKind = "function" | "object" | "program" | null;

type AiPanelProps = {
  code: string;
  questionText: string;
  targetKind: TargetKind;
  targetId: string | null;
  selectedFunction: FunctionDescriptor | null;
  selectedClass: ObjectClass | null;
  templateArgumentMode: "deduced" | "explicit";
  templateArgumentValues: Record<string, EditableTemplateArgumentValue>;
  compileReady: boolean;
};

type AiRunPhase =
  | "idle"
  | "generating"
  | "executing"
  | "done"
  | "failed";

/** Context snapshot recorded alongside each result set. */
type ContextKey = {
  targetId: string;
  sigHash: string;
  tmplKey: string;
};

type AiResultSet = {
  contextKey: ContextKey;
  score: AiScore | null;
  rows: AiResultRowDisplay[];
  storedTests: AiStoredTest[];
  skippedTopics: string[];
  generationNote: string | null;
  disclaimer: string;
  status: AiTestRunResponse["status"];
  message: string | null;
  unsupportedReason: string | null;
  supportedTargets: string[];
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function describePhase(phase: AiRunPhase): string {
  switch (phase) {
    case "generating":
      return "Generating test cases…";
    case "executing":
      return "Running tests…";
    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ScoreSummary({
  score,
  priorScore,
}: {
  score: AiScore;
  priorScore: { passed: number; executed: number } | null;
}) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        Practice Score
      </p>
      <p className="mt-1 text-lg font-semibold text-slate-900">
        {score.passed} of {score.executed} passed
        <span className="ml-2 text-base font-normal text-slate-600">
          · {score.percentage}%
        </span>
      </p>
      {priorScore != null && (
        <p className="mt-1 text-xs text-slate-500">
          Previous run: {priorScore.passed} of {priorScore.executed}
        </p>
      )}
    </div>
  );
}

function AiTestRow({ row }: { row: AiResultRowDisplay }) {
  const [expanded, setExpanded] = useState(row.defaultExpanded);

  return (
    <li
      className={`rounded-md border p-3 ${
        row.passed ? "border-emerald-100" : "border-rose-100"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`shrink-0 text-[11px] font-semibold ${
                row.passed ? "text-emerald-700" : "text-rose-700"
              }`}
            >
              {row.passed ? "PASS" : "FAIL"}
            </span>
            <span className="text-sm font-medium text-slate-800">
              {row.name}
            </span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
              {row.category.replace(/_/g, " ")}
            </span>
            <span className="text-[11px] text-slate-500">{row.reason}</span>
          </div>
        </div>
        {!row.passed && (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((e) => !e)}
            className="shrink-0 text-[11px] font-medium text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            {expanded ? "Hide" : "Details"}
          </button>
        )}
      </div>

      {expanded && !row.passed && (
        <div className="mt-3 space-y-2 border-t border-slate-200 pt-3">
          {row.inputSummary && (
            <div>
              <p className="text-[11px] font-medium text-slate-500">Input</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-[11px] leading-5 text-slate-800">
                {row.inputSummary}
              </pre>
            </div>
          )}
          {row.expectedSummary && (
            <div>
              <p className="text-[11px] font-medium text-slate-500">Expected</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-[11px] leading-5 text-slate-800">
                {row.expectedSummary}
              </pre>
            </div>
          )}
          {row.actualSummary && (
            <div>
              <p className="text-[11px] font-medium text-slate-500">Actual</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-[11px] leading-5 text-slate-800">
                {row.actualSummary}
              </pre>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AITestPanel({
  code,
  questionText,
  targetKind,
  targetId,
  selectedFunction,
  selectedClass,
  templateArgumentMode,
  templateArgumentValues,
  compileReady,
}: AiPanelProps) {
  const [phase, setPhase] = useState<AiRunPhase>("idle");
  const [resultSet, setResultSet] = useState<AiResultSet | null>(null);
  const [priorScore, setPriorScore] = useState<{
    passed: number;
    executed: number;
  } | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorContextKey, setErrorContextKey] = useState<ContextKey | null>(null);

  const isMountedRef = useRef(true);

  // ---------------------------------------------------------------------------
  // Current context key (derived from props, not state)
  // ---------------------------------------------------------------------------

  const currentSigHash =
    selectedFunction != null
      ? signatureHash(selectedFunction)
      : selectedClass != null
        ? signatureHash(selectedClass)
        : "";

  const currentTmplKey =
    selectedFunction?.template_kind === "function_template"
      ? templateKey(
          templateArgumentMode,
          getTemplateArgs(
            selectedFunction.template_parameters,
            templateArgumentValues,
          ),
        )
      : "";

  // The result set is only "active" when its context matches the current props.
  // This avoids calling setState in an effect just to reset on target change.
  const contextMatches =
    resultSet !== null &&
    targetId !== null &&
    resultSet.contextKey.targetId === targetId &&
    resultSet.contextKey.sigHash === currentSigHash &&
    resultSet.contextKey.tmplKey === currentTmplKey;

  const hasResults =
    contextMatches && resultSet?.status === "completed";

  const showAdvisoryUnsupported =
    contextMatches &&
    resultSet?.status === "unsupported" &&
    phase !== "generating" &&
    phase !== "executing";

  // Error message is shown only when the error was produced for the current context.
  // Uses a separate key (not resultSet) so first-run failures are always visible.
  const errorContextMatches =
    errorContextKey !== null &&
    targetId !== null &&
    errorContextKey.targetId === targetId &&
    errorContextKey.sigHash === currentSigHash &&
    errorContextKey.tmplKey === currentTmplKey;

  const activeError = errorContextMatches ? errorMessage : null;

  // ---------------------------------------------------------------------------
  // Gate check
  // ---------------------------------------------------------------------------

  const effectiveTargetMode: "function" | "object" | "program" | "unsupported" | null =
    targetKind === "program"
      ? "program"
      : targetKind === "function"
        ? "function"
        : targetKind === "object"
          ? "object"
          : null;

  const gate = runButtonGate({
    questionText,
    compileReady,
    targetMode: effectiveTargetMode,
  });

  const isInFlight = phase === "generating" || phase === "executing";

  // ---------------------------------------------------------------------------
  // Build request helpers
  // ---------------------------------------------------------------------------

  function buildRunRequest() {
    if (!targetId || !targetKind || targetKind === "program") return null;
    const tArgs =
      selectedFunction?.template_kind === "function_template"
        ? templateArgumentsPayload(
            selectedFunction.template_parameters,
            templateArgumentValues,
          )
        : [];
    return {
      code,
      language: "cpp" as const,
      question_text: questionText,
      target_kind: targetKind as "function" | "object",
      target_id: targetId,
      template_argument_mode:
        selectedFunction?.template_kind === "function_template"
          ? templateArgumentMode
          : null,
      template_arguments: tArgs.map((a) => ({
        parameter_name: a.parameter_name,
        kind: a.kind as "type" | "non_type",
        value: a.value,
      })),
    };
  }

  function buildRerunRequest() {
    if (!targetId || !targetKind || targetKind === "program") return null;
    const stored = resultSet?.storedTests;
    if (!stored?.length) return null;
    const tArgs =
      selectedFunction?.template_kind === "function_template"
        ? templateArgumentsPayload(
            selectedFunction.template_parameters,
            templateArgumentValues,
          )
        : [];
    return {
      code,
      language: "cpp" as const,
      target_kind: targetKind as "function" | "object",
      target_id: targetId,
      template_argument_mode:
        selectedFunction?.template_kind === "function_template"
          ? templateArgumentMode
          : null,
      template_arguments: tArgs.map((a) => ({
        parameter_name: a.parameter_name,
        kind: a.kind as "type" | "non_type",
        value: a.value,
      })),
      tests: stored,
    };
  }

  function makeContextKey(): ContextKey {
    return {
      targetId: targetId ?? "",
      sigHash: currentSigHash,
      tmplKey: currentTmplKey,
    };
  }

  // ---------------------------------------------------------------------------
  // Run / rerun handlers
  // ---------------------------------------------------------------------------

  async function handleRunAiTests() {
    const request = buildRunRequest();
    if (!request) return;

    isMountedRef.current = true;
    setPhase("generating");
    setErrorMessage(null);
    setErrorContextKey(null);

    try {
      const response = await runAiTests(request);
      if (!isMountedRef.current) return;

      const rows = shapeResultRows(response.tests);
      const newSet: AiResultSet = {
        contextKey: makeContextKey(),
        score: response.score,
        rows,
        storedTests: response.stored_tests,
        skippedTopics: response.skipped_topics,
        generationNote: response.generation_note,
        disclaimer: response.disclaimer,
        status: response.status,
        message: response.message,
        unsupportedReason: response.unsupported_reason,
        supportedTargets: response.supported_targets,
      };

      if (
        response.status === "completed" ||
        response.status === "infrastructure_failed" ||
        response.status === "unsupported"
      ) {
        setResultSet(newSet);
      } else {
        setErrorMessage(
          friendlyStatusMessage(response.status, response.message),
        );
        setErrorContextKey(makeContextKey());
      }

      setPhase(
        response.status === "completed" || response.status === "infrastructure_failed"
          ? "done"
          : "failed",
      );
    } catch (err) {
      if (!isMountedRef.current) return;
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Tests could not be generated right now.",
      );
      setErrorContextKey(makeContextKey());
      setPhase("failed");
    }
  }

  async function handleRerunAiTests() {
    const request = buildRerunRequest();
    if (!request) return;

    const prevScore = resultSet?.score
      ? { passed: resultSet.score.passed, executed: resultSet.score.executed }
      : null;

    isMountedRef.current = true;
    setPhase("executing");
    setErrorMessage(null);
    setErrorContextKey(null);

    try {
      const response = await rerunAiTests(request);
      if (!isMountedRef.current) return;

      const rows = shapeResultRows(response.tests);
      const newSet: AiResultSet = {
        contextKey: makeContextKey(),
        score: response.score,
        rows,
        storedTests: response.stored_tests.length
          ? response.stored_tests
          : (resultSet?.storedTests ?? []),
        skippedTopics: response.skipped_topics,
        generationNote: response.generation_note,
        disclaimer: response.disclaimer,
        status: response.status,
        message: response.message,
        unsupportedReason: response.unsupported_reason,
        supportedTargets: response.supported_targets,
      };

      if (response.status === "completed") {
        setPriorScore(prevScore);
        setResultSet(newSet);
        setPhase("done");
      } else {
        setErrorMessage(
          friendlyStatusMessage(response.status, response.message),
        );
        setErrorContextKey(makeContextKey());
        setPhase("failed");
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "The rerun failed. Please try again.",
      );
      setErrorContextKey(makeContextKey());
      setPhase("failed");
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const canRerun =
    hasResults && !!resultSet?.storedTests.length && compileReady;

  return (
    <section aria-label="AI Tests" className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-800">AI Tests</h3>
        {!hasResults && !isInFlight && phase === "idle" && (
          <p className="text-xs text-slate-500">
            Generate tests from your assignment question.
          </p>
        )}
      </div>

      {/* Gate message */}
      {gate.blocked && (
        <p className="mt-2 text-xs text-rose-600">
          {gate.reason === "missing_question"
            ? "Add an assignment question before running AI tests."
            : gate.reason === "compile_not_ready"
              ? "Compile the current code before running AI tests."
              : "AI testing currently supports function and object targets."}
        </p>
      )}

      {/* Advisory unsupported */}
      {showAdvisoryUnsupported && (
        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50/40 p-3">
          <p className="text-xs font-medium text-amber-800">
            AI testing is not available for this target yet.
          </p>
          {resultSet?.unsupportedReason && (
            <p className="mt-1 text-xs text-amber-700">
              {resultSet.unsupportedReason}
            </p>
          )}
          {resultSet?.supportedTargets.length ? (
            <div className="mt-2">
              <p className="text-[11px] font-medium text-slate-600">
                Supported targets in this file:
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {resultSet.supportedTargets.map((t) => (
                  <li key={t} className="font-mono text-[11px] text-slate-700">
                    {t}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}

      {/* Error banner */}
      {phase === "failed" && activeError && (
        <div
          role="alert"
          className="mt-2 rounded-md border border-rose-200 bg-rose-50/40 p-3"
        >
          <p className="text-xs font-medium text-rose-800">AI tests could not be generated</p>
          <p className="mt-0.5 text-xs text-rose-700">{activeError}</p>
        </div>
      )}

      {/* Progress */}
      {isInFlight && (
        <p
          role="status"
          aria-live="polite"
          className="mt-2 text-xs text-slate-500"
        >
          {describePhase(phase)}
        </p>
      )}

      {/* Run button (shown when no active results) */}
      {!hasResults && (
        <button
          type="button"
          onClick={() => void handleRunAiTests()}
          disabled={gate.blocked || isInFlight}
          className="mt-3 w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isInFlight ? describePhase(phase) : "Run AI Tests"}
        </button>
      )}

      {/* Results region */}
      {hasResults && resultSet && (
        <div className="mt-3 space-y-3">
          {resultSet.score && (
            <ScoreSummary score={resultSet.score} priorScore={priorScore} />
          )}

          {resultSet.generationNote && (
            <p className="text-[11px] text-slate-500">
              {resultSet.generationNote}
            </p>
          )}

          {resultSet.rows.length > 0 && (
            <ul className="space-y-2" aria-label="AI test results">
              {resultSet.rows.map((row) => (
                <AiTestRow key={row.id} row={row} />
              ))}
            </ul>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={() => void handleRerunAiTests()}
              disabled={!canRerun || isInFlight}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase === "executing" ? "Running…" : "Rerun Same Tests"}
            </button>
            <button
              type="button"
              onClick={() => void handleRunAiTests()}
              disabled={gate.blocked || isInFlight}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase === "generating" ? "Generating…" : "Generate Fresh AI Tests"}
            </button>
          </div>

          {/* Infrastructure failure note */}
          {resultSet.status === "infrastructure_failed" && (
            <p className="text-[11px] text-amber-700">
              {resultSet.message ??
                "The tests were generated, but the code runner was unavailable. Try running the same tests again."}
            </p>
          )}

          {/* Skipped topics */}
          {resultSet.skippedTopics.length > 0 && (
            <details className="border-t border-slate-200 pt-2">
              <summary className="cursor-pointer text-[11px] font-medium text-slate-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                Not tested ({resultSet.skippedTopics.length})
              </summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11px] leading-5 text-slate-500">
                {resultSet.skippedTopics.map((topic) => (
                  <li key={topic}>{topic}</li>
                ))}
              </ul>
            </details>
          )}

          {/* Disclaimer */}
          <p className="text-[10px] leading-4 text-slate-400">
            {resultSet.disclaimer}
          </p>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

function getTemplateArgs(
  parameters: TemplateParameter[],
  values: Record<string, EditableTemplateArgumentValue>,
): Array<{ parameter_name: string; kind: string; value: string }> {
  return parameters.map((p) => ({
    parameter_name: p.name,
    kind: p.kind,
    value: values[p.name]?.value ?? "",
  }));
}
