export type IdentifiedScenarioStep = {
  id: string;
};

export type IdentifiedScenarioObject = {
  id: string;
};

export function emptyScenarioCollections() {
  return { objects: [], steps: [] };
}

export function createInitialObjectScenario() {
  return {
    id: "scenario-1",
    name: "Scenario 1",
    ...emptyScenarioCollections(),
  };
}

export function removeScenarioObject<T extends IdentifiedScenarioObject>(
  objects: readonly T[],
  objectId: string,
): T[] {
  return objects.filter((object) => object.id !== objectId);
}

export function isObjectScenarioReady(scenario: {
  objects: Array<{
    name: string;
    class_id: string;
    constructor_id: string;
  }>;
  steps: Array<{
    step_type: string;
    target_object_id: string;
    method_id: string;
    operator_id: string;
    special_member_id: string;
    result_name: string;
    result_object_id: string;
    class_id: string;
    constructor_id: string;
  }>;
}): boolean {
  return (
    scenario.objects.every(
      (object) =>
        Boolean(object.name) &&
        Boolean(object.class_id) &&
        Boolean(object.constructor_id),
    ) &&
    scenario.steps.length > 0 &&
    scenario.steps.every((step) =>
      step.step_type === "create_object"
        ? Boolean(
            step.result_name &&
              step.result_object_id &&
              step.class_id &&
              step.constructor_id,
          )
        : Boolean(
            step.target_object_id &&
              (["method", "observer"].includes(step.step_type)
                ? step.method_id
                : step.step_type === "operator"
                  ? step.operator_id
                  : step.special_member_id),
          ),
    )
  );
}

export function removeScenarioStep<T extends IdentifiedScenarioStep>(
  steps: readonly T[],
  stepId: string,
): T[] {
  return steps.filter((step) => step.id !== stepId);
}

export function appendScenarioStep<T extends IdentifiedScenarioStep>(
  steps: readonly T[],
  step: T,
): T[] {
  return [...steps, step];
}

export function visibleScenarioStepNumber(index: number): number {
  return index + 1;
}
