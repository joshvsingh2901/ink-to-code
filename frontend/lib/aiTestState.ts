/**
 * AI test state helpers: hashing, staleness classification,
 * question upload fingerprinting, extraction guard, and run-button gate.
 *
 * Pure functions only — no React state here.
 * Do NOT import from manual-test state modules (testExecution.ts, testCaseNames.ts, etc.).
 */
import type { FunctionDescriptor, ObjectClass } from "./testExecution.ts";
import type { AiTestRunResponseStatus } from "./aiTests.ts";

// ---------------------------------------------------------------------------
// Re-exported backend disclaimer (must match exactly)
// ---------------------------------------------------------------------------

export const PRACTICE_DISCLAIMER =
  "This is a practice score based on AI-generated tests, not an official course grade.";

// ---------------------------------------------------------------------------
// Signature hash
// ---------------------------------------------------------------------------

/**
 * Stable string key capturing target identity and parameter shape.
 * Computed as JSON.stringify of [targetId, returnDisplay, params] where
 * params = [[name, display_type, passing], ...].
 */
export function signatureHash(
  descriptor: FunctionDescriptor | ObjectClass,
): string {
  if ("parameters" in descriptor && "return_type_metadata" in descriptor) {
    // FunctionDescriptor
    const fn = descriptor as FunctionDescriptor;
    const params = fn.parameters.map((p) => [
      p.name,
      p.type_metadata.display_type,
      p.type_metadata.passing,
    ]);
    return JSON.stringify([fn.id, fn.return_type, params]);
  }
  // ObjectClass: hash constructors + methods to detect signature changes.
  const cls = descriptor as ObjectClass;
  const ctors = cls.constructors.map((c) => c.id);
  const methods = cls.methods.map((m) => m.id);
  return JSON.stringify([cls.id, ctors, methods]);
}

// ---------------------------------------------------------------------------
// Question hash — cheap non-crypto content fingerprint
// ---------------------------------------------------------------------------

export function questionHash(text: string): string {
  // Simple stable hash: JSON.stringify the normalised text.
  return JSON.stringify(text.trim());
}

// ---------------------------------------------------------------------------
// Template key
// ---------------------------------------------------------------------------

export function templateKey(
  mode: "deduced" | "explicit" | null | undefined,
  args: Array<{ parameter_name: string; kind: string; value: string }>,
): string {
  return JSON.stringify({ mode: mode ?? null, args });
}

// ---------------------------------------------------------------------------
// Staleness classification
// ---------------------------------------------------------------------------

export type StalenessKind =
  | "different_target"
  | "incompatible"
  | "question_changed"
  | "results_stale"
  | "current";

export type AiContext = {
  targetId: string;
  sigHash: string;
  questionTextHash: string;
  tmplKey: string;
  compileVersion: number;
};

export function classifyStaleness(
  prior: AiContext,
  current: AiContext,
): StalenessKind {
  if (prior.targetId !== current.targetId) return "different_target";
  if (prior.sigHash !== current.sigHash) return "incompatible";
  if (prior.tmplKey !== current.tmplKey) return "incompatible";
  if (prior.questionTextHash !== current.questionTextHash)
    return "question_changed";
  if (prior.compileVersion !== current.compileVersion) return "results_stale";
  return "current";
}

// ---------------------------------------------------------------------------
// Question upload fingerprint
// ---------------------------------------------------------------------------

/**
 * Structural subset of UploadState — avoids importing from a component file.
 * Compatible with `UploadState` from `@/components/ImageUploadCard`.
 */
export type UploadForFingerprint = {
  mode: string;
  pages: Array<{ id: string }>;
};

/**
 * Stable fingerprint for the current question page set.
 * Changes when pages are added, removed, or reordered.
 * Does NOT incorporate questionText — text edits don't trigger re-extraction.
 */
export function questionUploadFingerprint(upload: UploadForFingerprint): string {
  return `${upload.mode}:${upload.pages.map((p) => p.id).join(",")}`;
}

// ---------------------------------------------------------------------------
// Extraction guard
// ---------------------------------------------------------------------------

export type ExtractionStatus = "idle" | "loading" | "done" | "failed";

export type ExtractionState = {
  /** Fingerprint of the page set for which we last attempted extraction. */
  fingerprint: string | null;
  status: ExtractionStatus;
  /** Text retrieved by the last successful extraction. */
  extractedText: string | null;
  errorMessage: string | null;
};

export const INITIAL_EXTRACTION_STATE: ExtractionState = {
  fingerprint: null,
  status: "idle",
  extractedText: null,
  errorMessage: null,
};

export type ExtractionAction =
  | { type: "start"; fingerprint: string }
  | { type: "success"; fingerprint: string; text: string }
  | { type: "failure"; fingerprint: string; message: string }
  | { type: "reset" };

export function extractionReducer(
  state: ExtractionState,
  action: ExtractionAction,
): ExtractionState {
  switch (action.type) {
    case "start":
      return {
        ...state,
        fingerprint: action.fingerprint,
        status: "loading",
        errorMessage: null,
      };
    case "success":
      // Discard late responses for stale fingerprints.
      if (state.fingerprint !== action.fingerprint) return state;
      return {
        fingerprint: action.fingerprint,
        status: "done",
        extractedText: action.text,
        errorMessage: null,
      };
    case "failure":
      if (state.fingerprint !== action.fingerprint) return state;
      return {
        ...state,
        status: "failed",
        errorMessage: action.message,
      };
    case "reset":
      return INITIAL_EXTRACTION_STATE;
    default:
      return state;
  }
}

export type ExtractionGuardState = {
  upload: UploadForFingerprint;
  extraction: ExtractionState;
};

/**
 * Returns true when the frontend should trigger a question-extraction call.
 * False prevents duplicate extraction for the same page set.
 */
export function shouldExtractQuestion(state: ExtractionGuardState): boolean {
  const { upload, extraction } = state;
  if (upload.pages.length === 0) return false;
  if (extraction.status === "loading") return false;
  const fp = questionUploadFingerprint(upload);
  if (extraction.fingerprint === fp) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Replace-from-image availability
// ---------------------------------------------------------------------------

/**
 * "Replace from image" is available only when:
 * - Extraction status is "done" (we have an extracted text)
 * - The user has edited the question text since the extraction
 *   (current text ≠ extracted text)
 */
export function canReplaceFromImage(
  extraction: ExtractionState,
  currentText: string,
): boolean {
  return (
    extraction.status === "done" &&
    extraction.extractedText !== null &&
    extraction.extractedText !== currentText
  );
}

// ---------------------------------------------------------------------------
// Run-button gate
// ---------------------------------------------------------------------------

export type RunGateInput = {
  questionText: string;
  compileReady: boolean;
  targetMode: "function" | "object" | "program" | "unsupported" | null;
};

export type RunGateResult =
  | { blocked: true; reason: "missing_question" | "compile_not_ready" | "program_mode" }
  | { blocked: false; advisoryReason?: string };

/**
 * Exactly three hard blocks:
 * 1. Empty question text
 * 2. Compile not current (still compiling, failed, or source changed)
 * 3. Program-mode target
 *
 * An inconclusive support judgement does NOT block the button.
 * A proven-unsupported reason is advisory only — the button stays enabled.
 */
export function runButtonGate(input: RunGateInput): RunGateResult {
  if (!input.questionText.trim()) {
    return { blocked: true, reason: "missing_question" };
  }
  if (!input.compileReady) {
    return { blocked: true, reason: "compile_not_ready" };
  }
  if (input.targetMode === "program") {
    return { blocked: true, reason: "program_mode" };
  }
  return { blocked: false };
}

// ---------------------------------------------------------------------------
// AI test run progress enum
// ---------------------------------------------------------------------------

export type AiRunProgress =
  | "idle"
  | "generating"
  | "validating"
  | "executing"
  | "done"
  | "failed";

/**
 * Rerun path skips generating and validating phases entirely.
 */
export const RERUN_PHASES: Set<AiRunProgress> = new Set([
  "executing",
  "done",
  "failed",
]);

// ---------------------------------------------------------------------------
// Result row shaping (display only)
// ---------------------------------------------------------------------------

export type AiResultRowDisplay = {
  id: string;
  name: string;
  category: string;
  reason: string;
  passed: boolean;
  /** Failing rows expanded by default; passing rows collapsed. */
  defaultExpanded: boolean;
  inputSummary: string;
  expectedSummary: string;
  actualSummary: string;
};

export type AiTestResultRowRaw = {
  id: string;
  name: string;
  category: string;
  reason: string;
  passed: boolean;
  input_summary: string;
  expected_summary: string;
  actual_summary: string;
};

export function shapeResultRows(
  rows: AiTestResultRowRaw[],
): AiResultRowDisplay[] {
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    category: r.category,
    reason: r.reason,
    passed: r.passed,
    defaultExpanded: !r.passed,
    inputSummary: r.input_summary,
    expectedSummary: r.expected_summary,
    actualSummary: r.actual_summary,
  }));
}

// ---------------------------------------------------------------------------
// Fresh-failure reducer for the results panel
// ---------------------------------------------------------------------------

export type AiTestSet = {
  tests: AiTestResultRowRaw[];
  stored: unknown[];
  score: { passed: number; executed: number; percentage: number } | null;
  skippedTopics: string[];
  disclaimer: string;
};

export type AiPanelState = {
  activeSet: AiTestSet | null;
  lastCompletedSet: AiTestSet | null;
  progress: AiRunProgress;
  failureMessage: string | null;
};

export type AiPanelAction =
  | { type: "run_start" }
  | { type: "rerun_start" }
  | { type: "success"; set: AiTestSet }
  | { type: "failure"; message: string; status: string; partialSet: AiTestSet | null };

export function aiPanelReducer(
  state: AiPanelState,
  action: AiPanelAction,
): AiPanelState {
  switch (action.type) {
    case "run_start":
      return { ...state, progress: "generating", failureMessage: null };
    case "rerun_start":
      return { ...state, progress: "executing", failureMessage: null };
    case "success":
      return {
        activeSet: action.set,
        lastCompletedSet: action.set,
        progress: "done",
        failureMessage: null,
      };
    case "failure":
      // On failure: preserve the previous active set; retain partial stored tests
      // for infrastructure failures (handled by caller via partialSet).
      return {
        ...state,
        progress: "failed",
        failureMessage: action.message,
        // Do NOT replace activeSet on failure — prior results stay displayed.
      };
    default:
      return state;
  }
}

export const INITIAL_AI_PANEL_STATE: AiPanelState = {
  activeSet: null,
  lastCompletedSet: null,
  progress: "idle",
  failureMessage: null,
};

// ---------------------------------------------------------------------------
// Rerun request builder
// ---------------------------------------------------------------------------

export type StoredAiTest = {
  id: string;
  name: string;
  category: string;
  reason: string;
  function_test?: unknown;
  scenario_test?: unknown;
};

export type AiTestRerunRequestPayload = {
  code: string;
  language: "cpp";
  target_kind: "function" | "object";
  target_id: string;
  template_argument_mode?: "deduced" | "explicit" | null;
  template_arguments?: unknown[];
  tests: StoredAiTest[];
};

// ---------------------------------------------------------------------------
// Status → human-readable message (used in the error banner)
// ---------------------------------------------------------------------------

/**
 * Maps an AI test run status and optional backend message to a display string.
 * Never surfaces transcription-service wording — all messages are AI-test-specific.
 */
export function friendlyStatusMessage(
  status: AiTestRunResponseStatus,
  message: string | null,
): string {
  switch (status) {
    case "missing_question":
      return "Add an assignment question before running AI tests.";
    case "compile_failed":
      return "Compile the current code before running AI tests.";
    case "unsupported":
      return "AI testing is not available for this target yet.";
    case "source_too_large":
      return (
        message ??
        "This file is too large for AI testing. AI testing supports single-exercise files up to 20,000 characters."
      );
    case "generation_timeout":
      return "AI test generation timed out. Please try again.";
    case "generation_rate_limited":
      return "AI test generation is temporarily rate limited. Please wait and try again.";
    case "generation_unavailable":
      return message ?? "The AI test generation service is currently unavailable.";
    case "generation_failed":
      return message ?? "AI tests could not be generated right now.";
    case "no_useful_tests":
      return message ?? "AI test generation did not produce any valid tests.";
    case "incompatible":
      return message ?? "The target changed. Generate fresh AI tests.";
    default:
      return (
        message ??
        "Tests could not be generated right now. Your manual tests are unchanged."
      );
  }
}

// ---------------------------------------------------------------------------


/**
 * Build a rerun request from stored tests.
 * Contains no question_text and no generation fields — zero Gemini calls.
 */
export function buildRerunRequest(
  storedTests: StoredAiTest[],
  code: string,
  language: "cpp",
  targetKind: "function" | "object",
  targetId: string,
  templateArgumentMode: "deduced" | "explicit" | null | undefined,
  templateArguments: unknown[],
): AiTestRerunRequestPayload {
  return {
    code,
    language,
    target_kind: targetKind,
    target_id: targetId,
    template_argument_mode: templateArgumentMode ?? null,
    template_arguments: templateArguments,
    tests: storedTests,
  };
}
