import assert from "node:assert/strict";
import test from "node:test";

import {
  appendScenarioStep,
  createInitialObjectScenario,
  emptyScenarioCollections,
  isObjectScenarioReady,
  removeScenarioObject,
  removeScenarioStep,
  visibleScenarioStepNumber,
} from "../lib/objectScenarioState.ts";

const constructorStep = {
  id: "constructor-step",
  step_type: "create_object",
  target_object_id: "",
  method_id: "",
  operator_id: "",
  special_member_id: "",
  result_name: "badNumber",
  result_object_id: "bad-number",
  class_id: "number-class",
  constructor_id: "number-int",
};

test("new scenario collections start without setup objects", () => {
  assert.deepEqual(emptyScenarioCollections(), { objects: [], steps: [] });
  assert.deepEqual(createInitialObjectScenario(), {
    id: "scenario-1",
    name: "Scenario 1",
    objects: [],
    steps: [],
  });
});

test("constructor-only scenario is ready without setup objects", () => {
  assert.equal(
    isObjectScenarioReady({ objects: [], steps: [constructorStep] }),
    true,
  );
});

test("constructor-only payload keeps an empty setup-object array", () => {
  const scenario = { objects: [], steps: [constructorStep] };
  const payload = {
    objects: scenario.objects.map((object) => object),
    steps: scenario.steps,
  };
  assert.deepEqual(payload.objects, []);
  assert.equal(payload.steps[0].id, "constructor-step");
});

test("setup objects can be added and the final object can be removed", () => {
  const setup = { id: "setup-one", name: "setup" };
  const added = [...emptyScenarioCollections().objects, setup];
  const removed = removeScenarioObject(added, setup.id);
  assert.equal(added.length, 1);
  assert.deepEqual(removed, []);
});

test("removing setup objects preserves scenario steps and surviving IDs", () => {
  const first = { id: "setup-one", name: "one" };
  const second = { id: "setup-two", name: "two" };
  const scenario = {
    objects: [first, second],
    steps: [constructorStep],
  };
  const next = {
    ...scenario,
    objects: removeScenarioObject(scenario.objects, first.id),
  };
  assert.strictEqual(next.steps, scenario.steps);
  assert.strictEqual(next.objects[0], second);
});

test("removing scenario steps preserves setup objects", () => {
  const setup = { id: "setup-one", name: "setup" };
  const scenario = {
    objects: [setup],
    steps: [constructorStep],
  };
  const next = {
    ...scenario,
    steps: removeScenarioStep(scenario.steps, constructorStep.id),
  };
  assert.strictEqual(next.objects, scenario.objects);
  assert.deepEqual(next.steps, []);
});

test("existing valid setup-object scenarios remain ready", () => {
  assert.equal(
    isObjectScenarioReady({
      objects: [
        {
          name: "setup",
          class_id: "number-class",
          constructor_id: "number-int",
        },
      ],
      steps: [
        {
          ...constructorStep,
          step_type: "method",
          target_object_id: "setup-one",
          method_id: "get-method",
        },
      ],
    }),
    true,
  );
});

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
    "create_object",
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
  const result = removeScenarioStep(original, "kind-4");

  assert.deepEqual(
    result.map((step) => step.step_type),
    [
      "create_object",
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

test("polymorphism steps keep stable IDs through deletion and reordering", () => {
  const steps = [
    { id: "derived", step_type: "create_object", value: "Dog" },
    {
      id: "base-ref",
      step_type: "create_base_reference",
      source_object_id: "dog",
      base_class_id: "Animal",
      value: "animalRef",
    },
    {
      id: "dispatch",
      step_type: "polymorphic_method",
      target_object_id: "animal-ref",
      value: "sound",
    },
  ];
  const remaining = removeScenarioStep(steps, "derived");
  assert.deepEqual(
    remaining.map((step) => step.id),
    ["base-ref", "dispatch"],
  );
  const reordered = [remaining[1], remaining[0]];
  assert.equal(reordered[0].id, "dispatch");
  assert.equal(reordered[1].source_object_id, "dog");
  assert.equal(reordered[1].base_class_id, "Animal");
});

test("constructor-free polymorphism scenario readiness validates each shape", () => {
  const common = {
    objects: [],
    steps: [
      {
        step_type: "create_base_reference",
        target_object_id: "",
        method_id: "",
        operator_id: "",
        special_member_id: "",
        result_name: "animalRef",
        result_object_id: "animal-ref",
        class_id: "",
        constructor_id: "",
        source_object_id: "dog",
        base_class_id: "Animal",
      },
    ],
  };
  assert.equal(isObjectScenarioReady(common), true);
  assert.equal(
    isObjectScenarioReady({
      ...common,
      steps: [{ ...common.steps[0], base_class_id: "" }],
    }),
    false,
  );
});
