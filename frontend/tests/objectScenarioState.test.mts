import assert from "node:assert/strict";
import test from "node:test";

import {
  appendScenarioStep,
  removeScenarioStep,
  visibleScenarioStepNumber,
} from "../lib/objectScenarioState.ts";

type Step = {
  id: string;
  value: string;
  step_type: string;
};

function steps(count: number): Step[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `stable-${index + 1}`,
    value: `configured-${index + 1}`,
    step_type: index % 2 === 0 ? "method" : "observer",
  }));
}

test("deleting a middle step removes only that step", () => {
  const original = steps(6);
  const result = removeScenarioStep(original, "stable-4");

  assert.deepEqual(
    result.map((step) => step.id),
    ["stable-1", "stable-2", "stable-3", "stable-5", "stable-6"],
  );
  assert.equal(original.length, 6);

  const secondResult = removeScenarioStep(result, "stable-2");
  assert.deepEqual(
    secondResult.map((step) => step.id),
    ["stable-1", "stable-3", "stable-5", "stable-6"],
  );
});

test("deleting the first step preserves all later steps", () => {
  const result = removeScenarioStep(steps(4), "stable-1");
  assert.deepEqual(
    result.map((step) => step.id),
    ["stable-2", "stable-3", "stable-4"],
  );
});

test("deleting the final step preserves earlier steps", () => {
  const result = removeScenarioStep(steps(4), "stable-4");
  assert.deepEqual(
    result.map((step) => step.id),
    ["stable-1", "stable-2", "stable-3"],
  );
});

test("deleting one of six steps leaves five", () => {
  assert.equal(removeScenarioStep(steps(6), "stable-4").length, 5);
});

test("surviving values and stable IDs are unchanged", () => {
  const original = steps(5);
  const result = removeScenarioStep(original, "stable-3");

  assert.strictEqual(result[0], original[0]);
  assert.strictEqual(result[1], original[1]);
  assert.strictEqual(result[2], original[3]);
  assert.strictEqual(result[3], original[4]);
  assert.deepEqual(
    result.map(({ id, value }) => ({ id, value })),
    [
      { id: "stable-1", value: "configured-1" },
      { id: "stable-2", value: "configured-2" },
      { id: "stable-4", value: "configured-4" },
      { id: "stable-5", value: "configured-5" },
    ],
  );
});

test("visible step numbers are recalculated from current order", () => {
  const result = removeScenarioStep(steps(4), "stable-2");
  assert.deepEqual(
    result.map((_, index) => visibleScenarioStepNumber(index)),
    [1, 2, 3],
  );
});

test("deleting and then adding a step preserves order", () => {
  const remaining = removeScenarioStep(steps(3), "stable-2");
  const added = appendScenarioStep(remaining, {
    id: "stable-new",
    value: "new value",
    step_type: "copy_construct",
  });
  assert.deepEqual(
    added.map((step) => step.id),
    ["stable-1", "stable-3", "stable-new"],
  );
});

test("deleting the last remaining step leaves an empty optional step list", () => {
  assert.deepEqual(removeScenarioStep(steps(1), "stable-1"), []);
});

test("removal preserves every supported configured step kind", () => {
  const original = [
    "method",
    "observer",
    "copy_construct",
    "copy_assign",
    "move_construct",
    "move_assign",
    "operator",
  ].map((step_type, index) => ({
    id: `kind-${index}`,
    value: `value-${index}`,
    step_type,
  }));
  const result = removeScenarioStep(original, "kind-3");

  assert.deepEqual(
    result.map((step) => step.step_type),
    [
      "method",
      "observer",
      "copy_construct",
      "move_construct",
      "move_assign",
      "operator",
    ],
  );
});

test("scenario payload order contains exactly the surviving steps", () => {
  const remaining = removeScenarioStep(steps(6), "stable-4");
  const payloadSteps = remaining.map(({ id, step_type, value }) => ({
    id,
    step_type,
    value,
  }));

  assert.deepEqual(
    payloadSteps.map((step) => step.id),
    ["stable-1", "stable-2", "stable-3", "stable-5", "stable-6"],
  );
});
