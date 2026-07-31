import type {
  ExceptionOutcomeResult,
  ObjectScenarioTestResult,
} from "./testExecution.ts";

export type ObjectScenarioSummary = {
  title: string;
  detail: string | null;
  supporting: string | null;
};

type ScenarioSummaryInput = Pick<
  ObjectScenarioTestResult,
  "passed" | "constructed_objects"
> & {
  steps: Array<
    Pick<
      ObjectScenarioTestResult["steps"][number],
      | "status"
      | "passed"
      | "step_type"
      | "result_object_name"
      | "return_result"
      | "exception_result"
    >
  >;
};

function exceptionSummary(
  exception: ExceptionOutcomeResult,
): ObjectScenarioSummary {
  if (exception.expectation_passed) {
    return {
      title: "Expected exception matched",
      detail: exception.actual_exception_type,
      supporting:
        exception.expected_message_rule === "ignore"
          ? null
          : "Message matched",
    };
  }
  if (
    exception.expected_outcome === "throws" &&
    exception.actual_outcome === "returned"
  ) {
    return {
      title: "Expected an exception, but construction completed normally.",
      detail: null,
      supporting: null,
    };
  }
  if (
    exception.expected_outcome === "throws" &&
    exception.actual_outcome === "threw_standard" &&
    exception.type_matched === false
  ) {
    return {
      title: "Wrong exception type",
      detail: `Expected: ${exception.expected_exception_type}`,
      supporting: `Actual: ${exception.actual_exception_type}`,
    };
  }
  if (
    exception.expected_outcome === "throws" &&
    exception.message_matched === false
  ) {
    return {
      title: "Exception message did not match",
      detail: `Expected: ${exception.expected_message ?? "(empty)"}`,
      supporting: `Actual: ${exception.actual_message ?? "(empty)"}`,
    };
  }
  if (exception.actual_outcome === "threw_non_standard") {
    return {
      title: "Non-standard exception thrown",
      detail: null,
      supporting: null,
    };
  }
  if (exception.actual_outcome === "threw_standard") {
    return {
      title: "Unexpected exception",
      detail: exception.actual_exception_type,
      supporting: exception.actual_message,
    };
  }
  return {
    title:
      exception.actual_outcome === "timed_out"
        ? "Program timed out."
        : "Program crashed before producing the expected result.",
    detail: null,
    supporting: null,
  };
}

export function getObjectScenarioSummary(
  result: ScenarioSummaryInput,
): ObjectScenarioSummary {
  const completedSteps = result.steps.filter(
    (step) => step.status === "completed",
  );
  const importantFailure = completedSteps.find((step) => !step.passed);
  if (importantFailure?.exception_result) {
    return exceptionSummary(importantFailure.exception_result);
  }

  const exceptionStep = completedSteps.find(
    (step) =>
      step.exception_result?.expected_outcome === "throws" ||
      step.exception_result?.actual_outcome.startsWith("threw_"),
  );
  if (exceptionStep?.exception_result) {
    const summary = exceptionSummary(exceptionStep.exception_result);
    const additionalPassed = completedSteps.filter(
      (step) => step !== exceptionStep && step.passed,
    ).length;
    return {
      ...summary,
      supporting:
        additionalPassed > 0
          ? `${additionalPassed} additional step${
              additionalPassed === 1 ? "" : "s"
            } passed`
          : summary.supporting,
    };
  }

  if (
    completedSteps.length > 1 &&
    completedSteps.every((step) => step.passed)
  ) {
    return {
      title: `All ${completedSteps.length} steps passed`,
      detail: null,
      supporting: null,
    };
  }

  const onlyStep = completedSteps[0];
  if (onlyStep?.step_type === "create_object" && onlyStep.passed) {
    return {
      title: `Constructed ${onlyStep.result_object_name ?? "object"}`,
      detail: null,
      supporting: null,
    };
  }
  if (onlyStep?.return_result?.passed) {
    return {
      title: "Returned expected value",
      detail: `Actual: ${onlyStep.return_result.actual || "(empty)"}`,
      supporting: null,
    };
  }
  if (result.constructed_objects.length > 0) {
    const names = result.constructed_objects.map(
      (item) => item.split(" = ", 1)[0],
    );
    return {
      title: `Constructed ${names.join(", ")}`,
      detail: null,
      supporting: null,
    };
  }
  return {
    title: result.passed ? "Scenario checks passed" : "Scenario failed",
    detail: null,
    supporting: null,
  };
}
