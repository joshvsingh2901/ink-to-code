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
  type AiTestRunResponseStatus,
  type AiStoredTest,
  type AiScore,
} from "@/lib/aiTests";
import {
  signatureHash,
  templateKey,
  questionHash,
  runButtonGate,
  shapeResultRows,
  friendlyStatusMessage,
  classifyAiSetStaleness,
  deriveAiPanelAffordances,
  canRerunAiTests,
  type AiResultRowDisplay,
  type AiContext,
  type AiGenerationContext,
} from "@/lib/aiTestState";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TargetKind = "function" | "object" | "program" | null;

/** WHAT the tests are. Survives source edits — see AI_WORKFLOW_REFINEMENT_PLAN.md §3. */
export type AiGeneratedSet = {
  storedTests: AiStoredTest[];
  generationContext: AiGenerationContext;
  skippedTopics: string[];
  generationNote: string | null;
  disclaimer: string;
};

/** HOW they did last time. Invalidated by source edits. */
export type AiRunResult = {
  rows: AiResultRowDisplay[];
  score: AiScore | null;
  status: AiTestRunResponseStatus;
  message: string | null;
  executedAtCodeVersion: number;
};

export type AiRunPhase =
  | "idle"
  | "generating"
  | "executing"
  | "done"
  | "failed";

export type AiPriorScore = { passed: number; executed: number } | null;

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
  /** Mirrors editor/page.tsx's isAnalyzingTests — target analysis still in flight. */
  isAnalyzing: boolean;
  /** Specific reason no target is available (from testMode.message), when targetKind is null. */
  unsupportedTargetReason: string | null;
  /** Reactive edit counter — see codeVersion in app/editor/page.tsx. */
  codeVersion: number;
  /** Lifted AI state (survives this component's own unmount on tab switch). */
  generatedSet: AiGeneratedSet | null;
  onGeneratedSetChange: (next: AiGeneratedSet | null) => void;
  runResult: AiRunResult | null;
  onRunResultChange: (next: AiRunResult | null) => void;
  phase: AiRunPhase;
  onPhaseChange: (next: AiRunPhase) => void;
  priorScore: AiPriorScore;
  onPriorScoreChange: (next: AiPriorScore) => void;
};

/** Context snapshot recorded alongside errors/advisories (per-attempt, not per-set). */
type ContextKey = {
  targetId: string;
  sigHash: string;
  tmplKey: string;
};

type AdvisoryUnsupported = {
  contextKey: ContextKey;
  reason: string | null;
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

// Same disclosure idiom as editor/page.tsx's ExpandableResultSection —
// duplicated locally rather than imported across the page/component
// boundary, since it is a small, self-contained ~15-line pattern and this
// keeps each file's Phase 3 footprint independent.
function ExpandableSection({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-t border-slate-200 pt-2">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
        className="text-xs font-medium text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
      >
        {expanded ? `Hide ${label.toLowerCase()}` : label}
      </button>
      {expanded && <div className="mt-1">{children}</div>}
    </div>
  );
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
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Practice Score
      </p>
      <p className="mt-1 font-mono text-lg font-medium text-slate-900">
        {score.passed} of {score.executed} passed
        <span className="ml-2 text-base font-normal text-slate-600">
          · {score.percentage}%
        </span>
      </p>
      {priorScore != null && (
        <p className="mt-1 font-mono text-xs text-slate-500">
          Previous run: {priorScore.passed} of {priorScore.executed}
        </p>
      )}
    </div>
  );
}

function AiRowStatusIcon({ passed }: { passed: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${
        passed ? "text-[var(--status-ok-fg)]" : "text-[var(--status-fail-fg)]"
      }`}
    >
      <svg
        viewBox="0 0 20 20"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="h-3.5 w-3.5"
      >
        {passed ? (
          <path d="m5 10 3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
        ) : (
          <path d="M6 6l8 8M14 6l-8 8" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
    </span>
  );
}

function AiTestRow({ row }: { row: AiResultRowDisplay }) {
  const [expanded, setExpanded] = useState(row.defaultExpanded);
  const toneWash = row.passed
    ? "bg-[var(--status-ok-bg)]"
    : "bg-[var(--status-fail-bg)]";
  const toneEdges = row.passed
    ? "border-t-[var(--border-subtle)] border-r-[var(--border-subtle)] border-b-[var(--border-subtle)] border-l-[var(--status-ok-border)]"
    : "border-t-[var(--border-subtle)] border-r-[var(--border-subtle)] border-b-[var(--border-subtle)] border-l-[var(--status-fail-border)]";
  const toneText = row.passed
    ? "text-[var(--status-ok-fg)]"
    : "text-[var(--status-fail-fg)]";

  return (
    <li className={`rounded-md border border-l-2 p-3 ${toneWash} ${toneEdges}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <AiRowStatusIcon passed={row.passed} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={`shrink-0 text-xs font-semibold ${toneText}`}>
                {row.passed ? "PASS" : "FAIL"}
              </span>
              <span className="text-sm font-medium text-slate-800">
                {row.name}
              </span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600">
                {row.category.replace(/_/g, " ")}
              </span>
              <span className="text-xs text-slate-500">{row.reason}</span>
            </div>
          </div>
        </div>
        {!row.passed && (
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded((e) => !e)}
            className="shrink-0 text-xs font-medium text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            {expanded ? "Hide" : "Details"}
          </button>
        )}
      </div>

      {expanded && !row.passed && (
        <div className="mt-3 space-y-2 border-t border-slate-200 pt-3">
          {row.inputSummary && (
            <div>
              <p className="text-xs font-medium text-slate-500">Input</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                {row.inputSummary}
              </pre>
            </div>
          )}
          {row.expectedSummary && (
            <div>
              <p className="text-xs font-medium text-slate-500">Expected</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                {row.expectedSummary}
              </pre>
            </div>
          )}
          {row.actualSummary && (
            <div>
              <p className="text-xs font-medium text-slate-500">Actual</p>
              <pre className="mt-0.5 overflow-auto whitespace-pre-wrap break-words rounded border border-[var(--status-fail-border)] bg-[var(--status-fail-bg)] p-2 font-mono text-xs leading-5 text-[var(--status-fail-fg)]">
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
  isAnalyzing,
  unsupportedTargetReason,
  codeVersion,
  generatedSet,
  onGeneratedSetChange,
  runResult,
  onRunResultChange,
  phase,
  onPhaseChange,
  priorScore,
  onPriorScoreChange,
}: AiPanelProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorContextKey, setErrorContextKey] = useState<ContextKey | null>(null);
  const [advisoryUnsupported, setAdvisoryUnsupported] =
    useState<AdvisoryUnsupported | null>(null);

  const isMountedRef = useRef(true);

  // ---------------------------------------------------------------------------
  // Current context (derived from props, not state)
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

  const currentGenContext: AiGenerationContext = {
    targetId: targetId ?? "",
    sigHash: currentSigHash,
    tmplKey: currentTmplKey,
    questionTextHash: questionHash(questionText),
  };
  const currentAiContext: AiContext = {
    ...currentGenContext,
    compileVersion: codeVersion,
  };

  // Staleness of the generated set + its last run result against the current
  // target/signature/template/question/compile context. classifyAiSetStaleness
  // synthesizes a prior AiContext from generatedSet.generationContext plus
  // runResult.executedAtCodeVersion, so there is exactly one place (imported
  // from lib/aiTestState) that encodes the five-way verdict.
  const staleness =
    targetId !== null && generatedSet !== null
      ? classifyAiSetStaleness(
          generatedSet.generationContext,
          runResult?.executedAtCodeVersion ?? null,
          currentAiContext,
        )
      : null;
  const affordances = deriveAiPanelAffordances(staleness);

  const hasResults = affordances.runResultCurrent && runResult?.status === "completed";

  // Advisory (not error) message when this exact target/signature/template
  // is confirmed unsupported. Tracked separately from generatedSet — an
  // "unsupported" outcome generates nothing, so it doesn't belong in the
  // persisted test-definition set.
  const advisoryContextMatches =
    advisoryUnsupported !== null &&
    targetId !== null &&
    advisoryUnsupported.contextKey.targetId === targetId &&
    advisoryUnsupported.contextKey.sigHash === currentSigHash &&
    advisoryUnsupported.contextKey.tmplKey === currentTmplKey;

  const showAdvisoryUnsupported =
    advisoryContextMatches && phase !== "generating" && phase !== "executing";

  // Error message is shown only when the error was produced for the current context.
  // Uses a separate key (not the generated set) so first-run failures are always visible.
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
    isAnalyzing,
  });

  function gateBlockedMessage(): string {
    if (gate.blocked && gate.reason === "program_mode") {
      return "AI testing currently supports function and object targets.";
    }
    if (gate.blocked && gate.reason === "no_target") {
      return unsupportedTargetReason ?? "AI testing is not available for this source.";
    }
    if (gate.blocked && gate.reason === "missing_question") {
      return "Add an assignment question before running AI tests.";
    }
    return "Compile the current code before running AI tests.";
  }

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
    const stored = generatedSet?.storedTests;
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
    if (!request) {
      setErrorMessage(gateBlockedMessage());
      setErrorContextKey(makeContextKey());
      onPhaseChange("failed");
      return;
    }

    isMountedRef.current = true;
    onPhaseChange("generating");
    setErrorMessage(null);
    setErrorContextKey(null);
    setAdvisoryUnsupported(null);

    try {
      const response = await runAiTests(request);
      if (!isMountedRef.current) return;

      if (
        response.status === "completed" ||
        response.status === "infrastructure_failed"
      ) {
        const rows = shapeResultRows(response.tests);
        onGeneratedSetChange({
          storedTests: response.stored_tests,
          generationContext: currentGenContext,
          skippedTopics: response.skipped_topics,
          generationNote: response.generation_note,
          disclaimer: response.disclaimer,
        });
        onRunResultChange({
          rows,
          score: response.score,
          status: response.status,
          message: response.message,
          executedAtCodeVersion: codeVersion,
        });
      } else if (response.status === "unsupported") {
        setAdvisoryUnsupported({
          contextKey: makeContextKey(),
          reason: response.unsupported_reason,
          supportedTargets: response.supported_targets,
        });
      } else {
        setErrorMessage(
          friendlyStatusMessage(response.status, response.message),
        );
        setErrorContextKey(makeContextKey());
      }

      onPhaseChange(
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
      onPhaseChange("failed");
    }
  }

  async function handleRerunAiTests() {
    const request = buildRerunRequest();
    if (!request) {
      setErrorMessage(
        gate.blocked
          ? gateBlockedMessage()
          : "There are no stored tests to rerun for this target.",
      );
      setErrorContextKey(makeContextKey());
      onPhaseChange("failed");
      return;
    }

    const prevScore = runResult?.score
      ? { passed: runResult.score.passed, executed: runResult.score.executed }
      : null;

    isMountedRef.current = true;
    onPhaseChange("executing");
    setErrorMessage(null);
    setErrorContextKey(null);

    try {
      const response = await rerunAiTests(request);
      if (!isMountedRef.current) return;

      if (response.status === "completed") {
        const rows = shapeResultRows(response.tests);
        // Fall back to the lifted generated set (not the previous run
        // result) when the backend returns an empty stored_tests list —
        // see AI_WORKFLOW_REFINEMENT_PLAN.md §12.7.
        const storedTests = response.stored_tests.length
          ? response.stored_tests
          : (generatedSet?.storedTests ?? []);
        onPriorScoreChange(prevScore);
        onGeneratedSetChange({
          storedTests,
          generationContext: currentGenContext,
          skippedTopics: response.skipped_topics,
          generationNote: response.generation_note,
          disclaimer: response.disclaimer,
        });
        onRunResultChange({
          rows,
          score: response.score,
          status: response.status,
          message: response.message,
          executedAtCodeVersion: codeVersion,
        });
        onPhaseChange("done");
      } else {
        setErrorMessage(
          friendlyStatusMessage(response.status, response.message),
        );
        setErrorContextKey(makeContextKey());
        onPhaseChange("failed");
      }
    } catch (err) {
      if (!isMountedRef.current) return;
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "The rerun failed. Please try again.",
      );
      setErrorContextKey(makeContextKey());
      onPhaseChange("failed");
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const canRerun = canRerunAiTests(
    affordances,
    generatedSet?.storedTests.length ?? 0,
    compileReady,
  );

  return (
    <section aria-label="AI Tests" className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-slate-800">AI Tests</h3>
        {!affordances.generatedSetUsable && !isInFlight && phase === "idle" && (
          <p className="text-xs text-slate-500">
            Generate tests from your assignment question.
          </p>
        )}
      </div>

      {/* Gate message. A prerequisite (missing question, not compiled yet)
          is not an error — it renders as neutral help text next to the
          disabled action. A genuine gate violation (this target/mode isn't
          supported at all, not just "not yet") keeps failure styling. */}
      {gate.blocked &&
        (gate.reason === "program_mode" ? (
          <p className="mt-2 text-xs text-[var(--status-fail-fg)]">
            {gateBlockedMessage()}
          </p>
        ) : (
          <p className="mt-2 text-xs text-[var(--ink-tertiary)]">
            {gateBlockedMessage()}
          </p>
        ))}

      {/* Advisory unsupported */}
      {showAdvisoryUnsupported && (
        <div className="mt-2 rounded-md border border-amber-200 bg-amber-50/40 p-3">
          <p className="text-xs font-medium text-amber-800">
            AI testing is not available for this target yet.
          </p>
          {advisoryUnsupported?.reason && (
            <p className="mt-1 text-xs text-amber-700">
              {advisoryUnsupported.reason}
            </p>
          )}
          {advisoryUnsupported?.supportedTargets.length ? (
            <div className="mt-2">
              <p className="text-xs font-medium text-slate-600">
                Supported targets in this file:
              </p>
              <ul className="mt-0.5 space-y-0.5">
                {advisoryUnsupported.supportedTargets.map((t) => (
                  <li key={t} className="font-mono text-xs text-slate-700">
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

      {/* Run button — shown only in the true first-run state: no usable
          generated set exists yet for this target/signature/template.
          Primary action of this workflow: accent-filled, sized to its own
          content — not full-width, and not louder than an enabled primary
          elsewhere while disabled. */}
      {!affordances.generatedSetUsable && (
        <button
          type="button"
          onClick={() => void handleRunAiTests()}
          disabled={gate.blocked || isInFlight}
          className="mt-3 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)] hover:bg-[var(--accent-emphasis)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:bg-[var(--surface-sunken)] disabled:text-[var(--ink-tertiary)]"
        >
          {isInFlight ? describePhase(phase) : "Run AI Tests"}
        </button>
      )}

      {/* Generated-set region — shown whenever a usable set of test
          definitions exists, even when the last run result is stale (the
          source changed, or the question changed). Rerun Same Tests /
          Generate Fresh AI Tests stay available without resetting to the
          first-run state; only the pass/fail rows themselves are cleared,
          matching how manual test results are cleared on a source edit. */}
      {affordances.generatedSetUsable && generatedSet && (
        <div className="mt-3 space-y-3">
          {hasResults && runResult?.score && (
            <ScoreSummary score={runResult.score} priorScore={priorScore} />
          )}

          {/* Action buttons — directly beneath the score/summary area so
              the next iteration action never requires scrolling past the
              result list. Rerun Same Tests is the primary next step
              (zero-Gemini, reuses stored tests); Generate Fresh AI Tests
              is secondary. */}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void handleRerunAiTests()}
              disabled={!canRerun || isInFlight}
              className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-[var(--accent-foreground)] hover:bg-[var(--accent-emphasis)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:bg-[var(--surface-sunken)] disabled:text-[var(--ink-tertiary)]"
            >
              {phase === "executing" ? "Running…" : "Rerun Same Tests"}
            </button>
            <button
              type="button"
              onClick={() => void handleRunAiTests()}
              disabled={gate.blocked || isInFlight}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase === "generating" ? "Generating…" : "Generate Fresh AI Tests"}
            </button>
          </div>

          {hasResults ? (
            runResult && runResult.rows.length > 0 ? (
              <ul className="space-y-2" aria-label="AI test results">
                {runResult.rows.map((row) => (
                  <AiTestRow key={row.id} row={row} />
                ))}
              </ul>
            ) : (
              runResult?.status === "completed" && (
                <p
                  role="status"
                  className="rounded-md border border-[var(--border-subtle)] bg-[var(--surface-code)] p-3 text-xs leading-5 text-slate-600"
                >
                  This run completed but produced no test cases to show. Try
                  Generate Fresh AI Tests, or add more detail to the assignment
                  question so there is more to test against.
                </p>
              )
            )
          ) : (
            !isInFlight && (
              <p
                role="status"
                className="rounded-md border border-[var(--border-subtle)] bg-[var(--surface-code)] p-3 text-xs leading-5 text-[var(--ink-tertiary)]"
              >
                {affordances.regenerationRecommended
                  ? "The assignment question changed since these tests last ran. Rerun to check them against the current question, or generate fresh tests."
                  : "Your code changed since these tests last ran. Rerun Same Tests to check the current version."}
              </p>
            )
          )}

          {generatedSet.generationNote && (
            <p className="text-xs text-slate-500">
              {generatedSet.generationNote}
            </p>
          )}

          {/* Infrastructure failure note */}
          {affordances.runResultCurrent &&
            runResult?.status === "infrastructure_failed" && (
              <p className="text-xs text-amber-700">
                {runResult.message ??
                  "The tests were generated, but the code runner was unavailable. Try running the same tests again."}
              </p>
            )}

          {/* Skipped topics */}
          {generatedSet.skippedTopics.length > 0 && (
            <ExpandableSection
              label={`Not tested (${generatedSet.skippedTopics.length})`}
            >
              <ul className="list-disc space-y-0.5 pl-4 text-xs leading-5 text-slate-500">
                {generatedSet.skippedTopics.map((topic) => (
                  <li key={topic}>{topic}</li>
                ))}
              </ul>
            </ExpandableSection>
          )}

          {/* Disclaimer */}
          <p className="text-xs leading-4 text-slate-400">
            {generatedSet.disclaimer}
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
