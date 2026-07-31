import type {
  ExceptionMessageRule,
  ExpectedOutcomeKind,
  SupportedExceptionType,
} from "./testExecution.ts";

export type EditableExceptionExpectation = {
  expected_outcome: ExpectedOutcomeKind;
  expected_exception_type: SupportedExceptionType | "";
  exception_message_rule: ExceptionMessageRule;
  expected_exception_message: string;
};

export function normalizeExpectedOutcome<T extends EditableExceptionExpectation>(
  value: T,
  expected_outcome: ExpectedOutcomeKind,
): T {
  return {
    ...value,
    expected_outcome,
    expected_exception_type:
      expected_outcome === "throws" ? value.expected_exception_type : "",
    exception_message_rule:
      expected_outcome === "throws"
        ? value.exception_message_rule
        : "ignore",
    expected_exception_message:
      expected_outcome === "throws" &&
      value.exception_message_rule !== "ignore"
        ? value.expected_exception_message
        : "",
  };
}

export function exceptionExpectationPayload(
  value: EditableExceptionExpectation,
) {
  return {
    expected_outcome: value.expected_outcome,
    ...(value.expected_outcome === "throws"
      ? {
          expected_exception_type:
            value.expected_exception_type || undefined,
          exception_message_rule: value.exception_message_rule,
          ...(value.exception_message_rule !== "ignore"
            ? {
                expected_exception_message:
                  value.expected_exception_message,
              }
            : {}),
        }
      : {}),
  };
}
