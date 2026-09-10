import { it, describe } from "node:test";
import assert from "node:assert/strict";

import {
  signatureHash,
  questionHash,
  templateKey,
  classifyStaleness,
  runButtonGate,
  questionUploadFingerprint,
  shouldExtractQuestion,
  extractionReducer,
  canReplaceFromImage,
  shapeResultRows,
  buildRerunRequest,
  aiPanelReducer,
  friendlyStatusMessage,
  INITIAL_AI_PANEL_STATE,
  PRACTICE_DISCLAIMER,
  RERUN_PHASES,
  classifyAiSetStaleness,
  deriveAiPanelAffordances,
  canRerunAiTests,
  type AiContext,
  type AiGenerationContext,
  type ExtractionState,
  type AiTestResultRowRaw,
} from "../lib/aiTestState.ts";
import type { AiTestRunResponseStatus } from "../lib/aiTests.ts";
import type { FunctionDescriptor, ObjectClass } from "../lib/testExecution.ts";

// ---------------------------------------------------------------------------
// Helpers to build minimal descriptors for testing
// ---------------------------------------------------------------------------

function makeFnDescriptor(overrides: Partial<FunctionDescriptor> = {}): FunctionDescriptor {
  return {
    id: "fn_foo",
    name: "foo",
    return_type: "int",
    return_type_metadata: {
      kind: "scalar",
      display_type: "int",
      scalar_type: "int",
      element_type: null,
      vector_depth: null,
      passing: "value",
      size_parameter_name: null,
    },
    parameters: [
      {
        name: "n",
        type: "int",
        type_metadata: {
          kind: "scalar",
          display_type: "int",
          scalar_type: "int",
          element_type: null,
          vector_depth: null,
          passing: "value",
          size_parameter_name: null,
        },
      },
    ],
    display: "foo(int n)",
    template_kind: "none",
    template_parameters: [],
    template_argument_mode: null,
    effective_template_arguments: [],
    concrete_instantiation: null,
    specialization_selected: false,
    explicit_specializations: [],
    source_line: 1,
    ...overrides,
  } as FunctionDescriptor;
}

function makeObjectClass(overrides: Partial<ObjectClass> = {}): ObjectClass {
  return {
    id: "cls_Stack",
    name: "Stack",
    kind: "class",
    constructors: [{ id: "ctor_0", display: "Stack()", parameters: [] }],
    methods: [{ id: "m_push", name: "push", display: "push(int)", parameters: [], return_type: "void", return_type_metadata: { kind: "void", display_type: "void", scalar_type: null, element_type: null, vector_depth: null, passing: "value", size_parameter_name: null }, is_const: false, is_virtual: false, is_pure_virtual: false, is_override: false, is_final: false, overrides_method_id: null, override_mismatch_reason: null }],
    operators: [],
    special_members: [],
    base_class_id: null,
    inheritance_access: null,
    inheritance_supported: false,
    is_abstract: false,
    has_virtual_destructor: false,
    derived_class_ids: [],
    inheritance_depth: 0,
    template_kind: "none",
    template_parameters: [],
    effective_template_arguments: [],
    concrete_type: null,
    ...overrides,
  } as ObjectClass;
}

function makeAiContext(overrides: Partial<AiContext> = {}): AiContext {
  return {
    targetId: "fn_foo",
    sigHash: "hash-a",
    questionTextHash: "qhash-1",
    tmplKey: "",
    compileVersion: 1,
    ...overrides,
  };
}

function makeExtractionState(overrides: Partial<ExtractionState> = {}): ExtractionState {
  return {
    fingerprint: null,
    status: "idle",
    extractedText: null,
    errorMessage: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// signatureHash
// ---------------------------------------------------------------------------

describe("signatureHash", () => {
  it("is stable across body-only changes (same descriptor → same hash)", () => {
    const a = makeFnDescriptor();
    const b = makeFnDescriptor(); // identical
    assert.equal(signatureHash(a), signatureHash(b));
  });

  it("changes when a parameter type changes", () => {
    const a = makeFnDescriptor();
    const b = makeFnDescriptor({
      parameters: [
        {
          name: "n",
          type: "double",
          type_metadata: {
            kind: "scalar",
            display_type: "double",
            scalar_type: "double",
            element_type: null,
            vector_depth: null,
            passing: "value",
            size_parameter_name: null,
          },
        },
      ],
    });
    assert.notEqual(signatureHash(a), signatureHash(b));
  });

  it("changes when a parameter name changes", () => {
    const a = makeFnDescriptor();
    const b = makeFnDescriptor({
      parameters: [
        {
          name: "x",
          type: "int",
          type_metadata: {
            kind: "scalar",
            display_type: "int",
            scalar_type: "int",
            element_type: null,
            vector_depth: null,
            passing: "value",
            size_parameter_name: null,
          },
        },
      ],
    });
    assert.notEqual(signatureHash(a), signatureHash(b));
  });

  it("works for ObjectClass descriptors", () => {
    const cls = makeObjectClass();
    const hash = signatureHash(cls);
    assert.equal(typeof hash, "string");
    assert.ok(hash.length > 0);
  });

  it("ObjectClass hash changes when a method is added", () => {
    const a = makeObjectClass();
    const b = makeObjectClass({
      methods: [
        ...a.methods,
        { id: "m_pop", name: "pop", display: "pop()", parameters: [], return_type: "int", return_type_metadata: { kind: "scalar", display_type: "int", scalar_type: "int", element_type: null, vector_depth: null, passing: "value", size_parameter_name: null }, is_const: false, is_virtual: false, is_pure_virtual: false, is_override: false, is_final: false, overrides_method_id: null, override_mismatch_reason: null },
      ],
    });
    assert.notEqual(signatureHash(a), signatureHash(b));
  });
});

// ---------------------------------------------------------------------------
// classifyStaleness
// ---------------------------------------------------------------------------

describe("classifyStaleness", () => {
  it("returns different_target on target switch", () => {
    const prior = makeAiContext({ targetId: "fn_foo" });
    const current = makeAiContext({ targetId: "fn_bar" });
    assert.equal(classifyStaleness(prior, current), "different_target");
  });

  it("returns incompatible on signature change", () => {
    const prior = makeAiContext({ sigHash: "hash-a" });
    const current = makeAiContext({ sigHash: "hash-b" });
    assert.equal(classifyStaleness(prior, current), "incompatible");
  });

  it("returns incompatible on template selection change", () => {
    const prior = makeAiContext({ tmplKey: '{"mode":"deduced","args":[]}' });
    const current = makeAiContext({ tmplKey: '{"mode":"explicit","args":[]}' });
    assert.equal(classifyStaleness(prior, current), "incompatible");
  });

  it("returns question_changed on question edit", () => {
    const prior = makeAiContext({ questionTextHash: '"hello"' });
    const current = makeAiContext({ questionTextHash: '"hello world"' });
    assert.equal(classifyStaleness(prior, current), "question_changed");
  });

  it("returns results_stale on body-only recompile (compileVersion advances)", () => {
    const prior = makeAiContext({ compileVersion: 1 });
    const current = makeAiContext({ compileVersion: 2 });
    assert.equal(classifyStaleness(prior, current), "results_stale");
  });

  it("returns current when nothing changed", () => {
    const ctx = makeAiContext();
    assert.equal(classifyStaleness(ctx, ctx), "current");
  });
});

// ---------------------------------------------------------------------------
// run-button gate
// ---------------------------------------------------------------------------

describe("runButtonGate", () => {
  it("is blocked when question text is empty", () => {
    const result = runButtonGate({
      questionText: "",
      compileReady: true,
      targetMode: "function",
    });
    assert.ok(result.blocked);
    assert.equal((result as { blocked: true; reason: string }).reason, "missing_question");
  });

  it("is blocked when question text is whitespace only", () => {
    const result = runButtonGate({
      questionText: "   \n\t  ",
      compileReady: true,
      targetMode: "function",
    });
    assert.ok(result.blocked);
  });

  it("is blocked when compile is not ready", () => {
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: false,
      targetMode: "function",
    });
    assert.ok(result.blocked);
    assert.equal((result as { blocked: true; reason: string }).reason, "compile_not_ready");
  });

  it("is blocked for program-mode target", () => {
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: "program",
    });
    assert.ok(result.blocked);
    assert.equal((result as { blocked: true; reason: string }).reason, "program_mode");
  });

  it("is NOT blocked when analysis metadata is inconclusive about support", () => {
    // targetMode null = analysis still loading, not conclusive
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: null,
    });
    assert.ok(!result.blocked);
  });

  it("is blocked with 'no_target' once analysis conclusively resolves to no target", () => {
    // isAnalyzing: false = analysis has finished and there is structurally no target
    // (e.g. a lifecycle-only class with no supported public instance method).
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: null,
      isAnalyzing: false,
    });
    assert.ok(result.blocked);
    assert.equal((result as { blocked: true; reason: string }).reason, "no_target");
  });

  it("is NOT blocked for an 'unsupported' targetMode while analysis is still in flight", () => {
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: "unsupported",
      isAnalyzing: true,
    });
    assert.ok(!result.blocked);
  });

  it("is blocked with 'no_target' for a conclusively 'unsupported' targetMode", () => {
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: "unsupported",
      isAnalyzing: false,
    });
    assert.ok(result.blocked);
    assert.equal((result as { blocked: true; reason: string }).reason, "no_target");
  });

  it("is NOT blocked for function mode (a proven-unsupported reason is advisory)", () => {
    // The gate has no 'unsupported' parameter — the button stays enabled.
    // Advisory display is handled in the component, not in the gate.
    const result = runButtonGate({
      questionText: "Sort an array.",
      compileReady: true,
      targetMode: "function",
    });
    assert.ok(!result.blocked);
  });

  it("is NOT blocked for object mode", () => {
    const result = runButtonGate({
      questionText: "Model a stack.",
      compileReady: true,
      targetMode: "object",
    });
    assert.ok(!result.blocked);
  });
});

// ---------------------------------------------------------------------------
// questionUploadFingerprint
// ---------------------------------------------------------------------------

describe("questionUploadFingerprint", () => {
  it("is stable for an unchanged page set", () => {
    const upload = { mode: "images", pages: [{ id: "p1" }, { id: "p2" }] };
    assert.equal(
      questionUploadFingerprint(upload),
      questionUploadFingerprint(upload),
    );
  });

  it("changes when a page is added", () => {
    const a = { mode: "images", pages: [{ id: "p1" }] };
    const b = { mode: "images", pages: [{ id: "p1" }, { id: "p2" }] };
    assert.notEqual(questionUploadFingerprint(a), questionUploadFingerprint(b));
  });

  it("changes when a page is removed", () => {
    const a = { mode: "images", pages: [{ id: "p1" }, { id: "p2" }] };
    const b = { mode: "images", pages: [{ id: "p2" }] };
    assert.notEqual(questionUploadFingerprint(a), questionUploadFingerprint(b));
  });

  it("changes when pages are reordered", () => {
    const a = { mode: "images", pages: [{ id: "p1" }, { id: "p2" }] };
    const b = { mode: "images", pages: [{ id: "p2" }, { id: "p1" }] };
    assert.notEqual(questionUploadFingerprint(a), questionUploadFingerprint(b));
  });

  it("is unchanged when only questionText is edited (not passed to this function)", () => {
    const upload = { mode: "images", pages: [{ id: "p1" }] };
    // questionText is not an input — the fingerprint is solely from upload
    const fp1 = questionUploadFingerprint(upload);
    const fp2 = questionUploadFingerprint(upload);
    assert.equal(fp1, fp2);
  });
});

// ---------------------------------------------------------------------------
// shouldExtractQuestion
// ---------------------------------------------------------------------------

describe("shouldExtractQuestion", () => {
  it("returns true for a new page set with no matching extraction", () => {
    const upload = { mode: "images", pages: [{ id: "p1" }] };
    const extraction = makeExtractionState({ fingerprint: null, status: "idle" });
    assert.equal(shouldExtractQuestion({ upload, extraction }), true);
  });

  it("returns false when the fingerprint already matches (no repeat extraction)", () => {
    const upload = { mode: "images", pages: [{ id: "p1" }] };
    const fp = questionUploadFingerprint(upload);
    const extraction = makeExtractionState({ fingerprint: fp, status: "done" });
    assert.equal(shouldExtractQuestion({ upload, extraction }), false);
  });

  it("returns false while an extraction is already loading", () => {
    const upload = { mode: "images", pages: [{ id: "p1" }] };
    const extraction = makeExtractionState({ fingerprint: null, status: "loading" });
    assert.equal(shouldExtractQuestion({ upload, extraction }), false);
  });

  it("returns false when there are no question pages", () => {
    const upload = { mode: "empty", pages: [] };
    const extraction = makeExtractionState();
    assert.equal(shouldExtractQuestion({ upload, extraction }), false);
  });
});

// ---------------------------------------------------------------------------
// extractionReducer
// ---------------------------------------------------------------------------

describe("extractionReducer", () => {
  it("success writes text and marks done for that fingerprint", () => {
    const state = makeExtractionState({ fingerprint: "fp-1", status: "loading" });
    const next = extractionReducer(state, {
      type: "success",
      fingerprint: "fp-1",
      text: "Write a sort function.",
    });
    assert.equal(next.status, "done");
    assert.equal(next.extractedText, "Write a sort function.");
    assert.equal(next.fingerprint, "fp-1");
  });

  it("failure preserves existing fingerprint and exposes retry", () => {
    const state = makeExtractionState({ fingerprint: "fp-1", status: "loading" });
    const next = extractionReducer(state, {
      type: "failure",
      fingerprint: "fp-1",
      message: "Network error",
    });
    assert.equal(next.status, "failed");
    assert.equal(next.errorMessage, "Network error");
    // extractedText unchanged (was null)
    assert.equal(next.extractedText, null);
  });

  it("a late response for a stale fingerprint is discarded", () => {
    // Extraction started for fp-1, then pages changed and fp-2 is loading
    const state = makeExtractionState({ fingerprint: "fp-2", status: "loading" });
    const next = extractionReducer(state, {
      type: "success",
      fingerprint: "fp-1", // stale
      text: "Old text",
    });
    // State unchanged
    assert.equal(next.fingerprint, "fp-2");
    assert.equal(next.status, "loading");
    assert.equal(next.extractedText, null);
  });
});

// ---------------------------------------------------------------------------
// canReplaceFromImage
// ---------------------------------------------------------------------------

describe("canReplaceFromImage", () => {
  it("is available only when status is done and the text has been edited since extraction", () => {
    const extraction = makeExtractionState({
      status: "done",
      extractedText: "Original question",
    });
    // User has edited the text
    assert.equal(canReplaceFromImage(extraction, "Edited question"), true);
    // Text unchanged — no need to replace
    assert.equal(canReplaceFromImage(extraction, "Original question"), false);
  });

  it("is unavailable when status is not done", () => {
    const extraction = makeExtractionState({ status: "loading", extractedText: "x" });
    assert.equal(canReplaceFromImage(extraction, "different"), false);
  });

  it("is unavailable when extractedText is null", () => {
    const extraction = makeExtractionState({ status: "done", extractedText: null });
    assert.equal(canReplaceFromImage(extraction, "anything"), false);
  });
});

// ---------------------------------------------------------------------------
// shapeResultRows
// ---------------------------------------------------------------------------

describe("shapeResultRows", () => {
  it("passing rows are marked collapsed (defaultExpanded false)", () => {
    const raw: AiTestResultRowRaw[] = [
      {
        id: "ai-1",
        name: "Normal case",
        category: "normal",
        reason: "Tests typical input.",
        passed: true,
        input_summary: "n=5",
        expected_summary: "return 10",
        actual_summary: "return 10",
      },
    ];
    const rows = shapeResultRows(raw);
    assert.equal(rows[0].defaultExpanded, false);
  });

  it("failing rows are marked expanded (defaultExpanded true)", () => {
    const raw: AiTestResultRowRaw[] = [
      {
        id: "ai-2",
        name: "Zero case",
        category: "zero",
        reason: "Tests zero input.",
        passed: false,
        input_summary: "n=0",
        expected_summary: "return 0",
        actual_summary: "return 1",
      },
    ];
    const rows = shapeResultRows(raw);
    assert.equal(rows[0].defaultExpanded, true);
  });

  it("labels, categories, and reasons are preserved verbatim", () => {
    const raw: AiTestResultRowRaw[] = [
      {
        id: "ai-3",
        name: "Boundary case",
        category: "boundary",
        reason: "Tests at the exact boundary.",
        passed: true,
        input_summary: "n=100",
        expected_summary: "return 200",
        actual_summary: "return 200",
      },
    ];
    const [row] = shapeResultRows(raw);
    assert.equal(row.id, "ai-3");
    assert.equal(row.name, "Boundary case");
    assert.equal(row.category, "boundary");
    assert.equal(row.reason, "Tests at the exact boundary.");
    assert.equal(row.inputSummary, "n=100");
    assert.equal(row.expectedSummary, "return 200");
    assert.equal(row.actualSummary, "return 200");
  });
});

// ---------------------------------------------------------------------------
// buildRerunRequest
// ---------------------------------------------------------------------------

describe("buildRerunRequest", () => {
  it("contains stored tests unchanged and no generation fields", () => {
    const storedTests = [
      {
        id: "ai-1",
        name: "Normal",
        category: "normal",
        reason: "Tests typical input.",
        function_test: { name: "Normal", arguments: ["5"], expected_outcome: "return_value", expected_return: "10" },
      },
    ];
    const request = buildRerunRequest(
      storedTests,
      "int foo(int n) { return n*2; }",
      "cpp",
      "function",
      "fn_foo",
      "deduced",
      [],
    );
    assert.deepEqual(request.tests, storedTests);
    assert.equal(request.code, "int foo(int n) { return n*2; }");
    assert.equal(request.language, "cpp");
    assert.equal(request.target_kind, "function");
    assert.equal(request.target_id, "fn_foo");
    // No question_text field
    assert.ok(!("question_text" in request));
  });
});

// ---------------------------------------------------------------------------
// aiPanelReducer (fresh-failure reducer)
// ---------------------------------------------------------------------------

describe("aiPanelReducer (fresh-failure reducer)", () => {
  it("previous set and outcome are retained on failure status", () => {
    const activeSet = {
      tests: [],
      stored: [],
      score: { passed: 3, executed: 5, percentage: 60 },
      skippedTopics: [],
      disclaimer: PRACTICE_DISCLAIMER,
    };
    const state = {
      ...INITIAL_AI_PANEL_STATE,
      activeSet,
      lastCompletedSet: activeSet,
      progress: "done" as const,
    };
    const next = aiPanelReducer(state, {
      type: "failure",
      message: "Rate limited.",
      status: "generation_rate_limited",
      partialSet: null,
    });
    // Prior active set is preserved
    assert.equal(next.activeSet, activeSet);
    assert.equal(next.progress, "failed");
    assert.equal(next.failureMessage, "Rate limited.");
  });
});

// ---------------------------------------------------------------------------
// Manual tests untouched: AI state module exports nothing from manual-test
// state modules. This is a compile-time invariant checked by reviewing imports.
// ---------------------------------------------------------------------------

it("disclaimer constant matches the backend string", () => {
  assert.equal(
    PRACTICE_DISCLAIMER,
    "This is a practice score based on AI-generated tests, not an official course grade.",
  );
});

// ---------------------------------------------------------------------------
// Progress enum: rerun path never enters generating/validating phases
// ---------------------------------------------------------------------------

it("progress enum: rerun path never enters generating/validating phases", () => {
  // RERUN_PHASES does not include 'generating' or 'validating'
  assert.ok(!RERUN_PHASES.has("generating"));
  assert.ok(!RERUN_PHASES.has("validating" as never));
  assert.ok(RERUN_PHASES.has("executing"));
  assert.ok(RERUN_PHASES.has("done"));
  assert.ok(RERUN_PHASES.has("failed"));
});

// ---------------------------------------------------------------------------
// templateKey
// ---------------------------------------------------------------------------

describe("templateKey", () => {
  it("returns consistent JSON for the same mode and args", () => {
    const a = templateKey("deduced", []);
    const b = templateKey("deduced", []);
    assert.equal(a, b);
  });

  it("differs for different modes", () => {
    const a = templateKey("deduced", []);
    const b = templateKey("explicit", []);
    assert.notEqual(a, b);
  });
});

// ---------------------------------------------------------------------------
// questionHash
// ---------------------------------------------------------------------------

describe("questionHash", () => {
  it("trims whitespace for comparison", () => {
    // Two questions differing only in surrounding whitespace should hash the same
    // (we trim before hashing for equality purposes)
    const a = questionHash("  Sort an array.  ");
    const b = questionHash("Sort an array.");
    assert.equal(a, b);
  });

  it("returns different hashes for different content", () => {
    const a = questionHash("Sort an array.");
    const b = questionHash("Reverse a string.");
    assert.notEqual(a, b);
  });
});

// ---------------------------------------------------------------------------
// friendlyStatusMessage
// ---------------------------------------------------------------------------

describe("friendlyStatusMessage", () => {
  it("generation_failed returns the backend message when provided", () => {
    const msg = friendlyStatusMessage("generation_failed", "AI tests could not be generated right now.");
    assert.equal(msg, "AI tests could not be generated right now.");
  });

  it("generation_failed fallback does not mention 'transcription'", () => {
    const msg = friendlyStatusMessage("generation_failed", null);
    assert.ok(
      !msg.toLowerCase().includes("transcription"),
      `Must not mention 'transcription', got: ${msg}`,
    );
    assert.ok(msg.length > 0);
  });

  it("generation_unavailable returns an AI-specific message without mentioning transcription", () => {
    const msg = friendlyStatusMessage("generation_unavailable", null);
    assert.ok(msg.length > 0);
    assert.ok(
      !msg.toLowerCase().includes("transcription"),
      `Must not mention 'transcription', got: ${msg}`,
    );
  });

  it("unsupported returns the advisory 'AI testing is not available' message", () => {
    const msg = friendlyStatusMessage("unsupported", null);
    assert.ok(
      msg.toLowerCase().includes("ai testing"),
      `Expected AI testing advisory, got: ${msg}`,
    );
  });

  it("unknown status falls back to a safe generic message", () => {
    const msg = friendlyStatusMessage("completely_unknown" as AiTestRunResponseStatus, null);
    assert.ok(msg.length > 0);
  });

  it("no_useful_tests returns an AI-specific message without mentioning transcription", () => {
    const msg = friendlyStatusMessage("no_useful_tests", null);
    assert.ok(msg.length > 0);
    assert.ok(
      !msg.toLowerCase().includes("transcription"),
      `Must not mention 'transcription', got: ${msg}`,
    );
  });
});

// ---------------------------------------------------------------------------
// classifyAiSetStaleness / deriveAiPanelAffordances / canRerunAiTests
//
// Covers the generated-set / run-result invalidation matrix from
// AI_WORKFLOW_REFINEMENT_PLAN.md §3 and §8 (items 1-6).
// ---------------------------------------------------------------------------

function makeGenerationContext(
  overrides: Partial<AiGenerationContext> = {},
): AiGenerationContext {
  return {
    targetId: "fn_foo",
    sigHash: "hash-a",
    tmplKey: "",
    questionTextHash: "qhash-1",
    ...overrides,
  };
}

describe("classifyAiSetStaleness", () => {
  it("source-edit context (compileVersion differs, all else equal) -> results_stale", () => {
    const generationContext = makeGenerationContext();
    const current = makeAiContext({ compileVersion: 2 });
    // The set was last executed at compileVersion 1.
    const staleness = classifyAiSetStaleness(generationContext, 1, current);
    assert.equal(staleness, "results_stale");

    const affordances = deriveAiPanelAffordances(staleness);
    assert.equal(affordances.generatedSetUsable, true);
    assert.equal(affordances.runResultCurrent, false);
    assert.equal(affordances.regenerationRecommended, false);
  });

  it("question-text change -> question_changed, keep set, clear run, recommend regeneration", () => {
    const generationContext = makeGenerationContext({
      questionTextHash: '"old question"',
    });
    const current = makeAiContext({
      questionTextHash: '"new question"',
      compileVersion: 1,
    });
    const staleness = classifyAiSetStaleness(generationContext, 1, current);
    assert.equal(staleness, "question_changed");

    const affordances = deriveAiPanelAffordances(staleness);
    assert.equal(affordances.generatedSetUsable, true);
    assert.equal(affordances.runResultCurrent, false);
    assert.equal(affordances.regenerationRecommended, true);
  });

  it("signature change -> incompatible, discard the generated set", () => {
    const generationContext = makeGenerationContext({ sigHash: "hash-a" });
    const current = makeAiContext({ sigHash: "hash-b", compileVersion: 1 });
    const staleness = classifyAiSetStaleness(generationContext, 1, current);
    assert.equal(staleness, "incompatible");

    const affordances = deriveAiPanelAffordances(staleness);
    assert.equal(affordances.generatedSetUsable, false);
    assert.equal(affordances.runResultCurrent, false);
  });

  it("target change -> different_target, discard the generated set", () => {
    const generationContext = makeGenerationContext({ targetId: "fn_foo" });
    const current = makeAiContext({ targetId: "fn_bar", compileVersion: 1 });
    const staleness = classifyAiSetStaleness(generationContext, 1, current);
    assert.equal(staleness, "different_target");

    const affordances = deriveAiPanelAffordances(staleness);
    assert.equal(affordances.generatedSetUsable, false);
    assert.equal(affordances.runResultCurrent, false);
  });

  it("identical context -> current, no change", () => {
    const generationContext = makeGenerationContext();
    const current = makeAiContext({ compileVersion: 1 });
    const staleness = classifyAiSetStaleness(generationContext, 1, current);
    assert.equal(staleness, "current");

    const affordances = deriveAiPanelAffordances(staleness);
    assert.equal(affordances.generatedSetUsable, true);
    assert.equal(affordances.runResultCurrent, true);
    assert.equal(affordances.regenerationRecommended, false);
  });

  it("null executedAtCodeVersion (never run) is treated as matching current compileVersion", () => {
    const generationContext = makeGenerationContext();
    const current = makeAiContext({ compileVersion: 7 });
    const staleness = classifyAiSetStaleness(generationContext, null, current);
    assert.equal(staleness, "current");
  });
});

describe("deriveAiPanelAffordances", () => {
  it("with no prior staleness verdict (no generated set yet) reports first-run state", () => {
    const affordances = deriveAiPanelAffordances(null);
    assert.equal(affordances.generatedSetUsable, false);
    assert.equal(affordances.runResultCurrent, false);
    assert.equal(affordances.regenerationRecommended, false);
  });
});

describe("canRerunAiTests", () => {
  it("requires a usable generated set, at least one stored test, and a current compile", () => {
    const usable = deriveAiPanelAffordances("current");
    assert.equal(canRerunAiTests(usable, 3, true), true);
  });

  it("is false when the generated set is not usable, even with stored tests and compileReady", () => {
    const discarded = deriveAiPanelAffordances("different_target");
    assert.equal(canRerunAiTests(discarded, 3, true), false);
  });

  it("is false when there are no stored tests", () => {
    const usable = deriveAiPanelAffordances("current");
    assert.equal(canRerunAiTests(usable, 0, true), false);
  });

  it("is false when the code does not currently compile", () => {
    const usable = deriveAiPanelAffordances("results_stale");
    assert.equal(canRerunAiTests(usable, 3, false), false);
  });
});
