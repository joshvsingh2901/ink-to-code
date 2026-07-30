export type IdentifiedScenarioStep = {
  id: string;
};

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
