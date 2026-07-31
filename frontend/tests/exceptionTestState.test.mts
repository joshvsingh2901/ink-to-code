import assert from "node:assert/strict";
import test from "node:test";

import {
  exceptionExpectationPayload,
  normalizeExpectedOutcome,
  type EditableExceptionExpectation,
} from "../lib/exceptionTestState.ts";

const throwing: EditableExceptionExpectation = {
  expected_outcome: "throws",
  expected_exception_type: "std::invalid_argument",
  exception_message_rule: "exact",
  expected_exception_message: "division by zero",
};

test("switching to throws preserves configured exception controls", () => {
  assert.deepEqual(normalizeExpectedOutcome(throwing, "throws"), throwing);
});

test("switching from throws to return clears stale exception fields", () => {
  assert.deepEqual(normalizeExpectedOutcome(throwing, "return_value"), {
    expected_outcome: "return_value",
    expected_exception_type: "",
    exception_message_rule: "ignore",
    expected_exception_message: "",
  });
});

test("ignore message rule omits expected message from payload", () => {
  const payload = exceptionExpectationPayload({
    ...throwing,
    exception_message_rule: "ignore",
    expected_exception_message: "",
  });
  assert.deepEqual(payload, {
    expected_outcome: "throws",
    expected_exception_type: "std::invalid_argument",
    exception_message_rule: "ignore",
  });
});

test("exact and contains payloads include expected message", () => {
  for (const rule of ["exact", "contains"] as const) {
    assert.equal(
      exceptionExpectationPayload({
        ...throwing,
        exception_message_rule: rule,
      }).expected_exception_message,
      "division by zero",
    );
  }
});

test("normal outcomes omit every exception field", () => {
  assert.deepEqual(
    exceptionExpectationPayload(
      normalizeExpectedOutcome(throwing, "return_void"),
    ),
    { expected_outcome: "return_void" },
  );
});

test("stable step state preserves exception configuration through deletion", () => {
  const steps = [
    { id: "one", ...throwing },
    { id: "two", ...throwing, expected_exception_message: "second" },
    { id: "three", ...throwing, expected_exception_message: "third" },
  ];
  const remaining = steps.filter((step) => step.id !== "two");
  assert.strictEqual(remaining[0], steps[0]);
  assert.strictEqual(remaining[1], steps[2]);
  assert.equal(remaining[1].expected_exception_message, "third");
});

test("reordering preserves stable IDs and exception configuration", () => {
  const steps = [
    { id: "one", ...throwing },
    { id: "two", ...throwing, expected_exception_message: "second" },
  ];
  const reordered = [steps[1], steps[0]];
  assert.equal(reordered[0].id, "two");
  assert.equal(reordered[0].expected_exception_message, "second");
  assert.strictEqual(reordered[1], steps[0]);
});

test("constructor-step state survives deletion and reordering", () => {
  const constructorStep = {
    id: "constructor-step",
    step_type: "create_object",
    class_id: "class-number",
    constructor_id: "constructor-number-int",
    result_object_id: "bad-number",
    result_name: "badNumber",
    arguments: ["-1"],
    ...throwing,
  };
  const ordinaryStep = { id: "ordinary", step_type: "method" };
  const afterDeletion = [ordinaryStep, constructorStep].filter(
    (step) => step.id !== ordinaryStep.id,
  );
  const reordered = [afterDeletion[0]];

  assert.strictEqual(reordered[0], constructorStep);
  assert.equal(reordered[0].result_name, "badNumber");
  assert.equal(reordered[0].expected_exception_type, "std::invalid_argument");
});
