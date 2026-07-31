import assert from "node:assert/strict";
import test from "node:test";

import { getObjectScenarioSummary } from "../lib/objectScenarioSummary.ts";
import type {
  ExceptionOutcomeResult,
  FunctionChannelResult,
} from "../lib/testExecution.ts";

function exception(
  overrides: Partial<ExceptionOutcomeResult> = {},
): ExceptionOutcomeResult {
  return {
    expected_outcome: "throws",
    actual_outcome: "threw_standard",
    expected_exception_type: "std::invalid_argument",
    actual_exception_type: "std::invalid_argument",
    expected_message_rule: "ignore",
    expected_message: null,
    actual_message: "value must be non-negative",
    type_matched: true,
    message_matched: true,
    expectation_passed: true,
    execution_continued: false,
    ...overrides,
  };
}

function step(overrides: {
  step_type?: "create_object" | "method";
  passed?: boolean;
  result_object_name?: string | null;
  exception_result?: ExceptionOutcomeResult | null;
  return_result?: FunctionChannelResult | null;
} = {}) {
  return {
    status: "completed" as const,
    passed: true,
    step_type: "create_object" as const,
    result_object_name: "gg",
    exception_result: null,
    return_result: null,
    ...overrides,
  };
}

test("successful construction names the constructed object", () => {
  assert.equal(
    getObjectScenarioSummary({
      passed: true,
      constructed_objects: [],
      steps: [step()],
    }).title,
    "Constructed gg",
  );
});

test("expected constructor exception is visible without saying constructed", () => {
  const summary = getObjectScenarioSummary({
    passed: true,
    constructed_objects: [],
    steps: [step({ exception_result: exception() })],
  });
  assert.equal(summary.title, "Expected exception matched");
  assert.equal(summary.detail, "std::invalid_argument");
  assert.doesNotMatch(summary.title, /Constructed/);
});

test("wrong constructor exception is summarized while collapsed", () => {
  const summary = getObjectScenarioSummary({
    passed: false,
    constructed_objects: [],
    steps: [
      step({
        passed: false,
        exception_result: exception({
          actual_exception_type: "std::runtime_error",
          type_matched: false,
          expectation_passed: false,
        }),
      }),
    ],
  });
  assert.deepEqual(summary, {
    title: "Wrong exception type",
    detail: "Expected: std::invalid_argument",
    supporting: "Actual: std::runtime_error",
  });
});

test("normal constructor completion when throw expected is summarized", () => {
  assert.equal(
    getObjectScenarioSummary({
      passed: false,
      constructed_objects: [],
      steps: [
        step({
          passed: false,
          exception_result: exception({
            actual_outcome: "returned",
            actual_exception_type: null,
            type_matched: false,
            message_matched: false,
            expectation_passed: false,
          }),
        }),
      ],
    }).title,
    "Expected an exception, but construction completed normally.",
  );
});

test("method return and multi-step results have concise summaries", () => {
  const returnResult: FunctionChannelResult = {
    expected: "5",
    actual: "5",
    passed: true,
    match_type: "exact",
    mismatch_detail: null,
  };
  assert.deepEqual(
    getObjectScenarioSummary({
      passed: true,
      constructed_objects: [],
      steps: [
        step({
          step_type: "method",
          result_object_name: null,
          return_result: returnResult,
        }),
      ],
    }),
    {
      title: "Returned expected value",
      detail: "Actual: 5",
      supporting: null,
    },
  );
  assert.equal(
    getObjectScenarioSummary({
      passed: true,
      constructed_objects: [],
      steps: [step(), step({ step_type: "method" })],
    }).title,
    "All 2 steps passed",
  );
});

test("important exception keeps additional passed-step count concise", () => {
  const summary = getObjectScenarioSummary({
    passed: true,
    constructed_objects: [],
    steps: [
      step({ exception_result: exception() }),
      step({ step_type: "method" }),
    ],
  });
  assert.equal(summary.title, "Expected exception matched");
  assert.equal(summary.supporting, "1 additional step passed");
});
