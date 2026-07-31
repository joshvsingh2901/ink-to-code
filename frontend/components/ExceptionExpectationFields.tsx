"use client";

import type {
  ExceptionMessageRule,
  ExpectedOutcomeKind,
  SupportedExceptionType,
} from "@/lib/testExecution";
import {
  normalizeExpectedOutcome,
  type EditableExceptionExpectation,
} from "@/lib/exceptionTestState";

export const EXCEPTION_TYPES: Array<{
  value: SupportedExceptionType;
  label: string;
}> = [
  { value: "any_std_exception", label: "Any std::exception" },
  { value: "std::exception", label: "std::exception" },
  { value: "std::runtime_error", label: "std::runtime_error" },
  { value: "std::logic_error", label: "std::logic_error" },
  { value: "std::invalid_argument", label: "std::invalid_argument" },
  { value: "std::domain_error", label: "std::domain_error" },
  { value: "std::length_error", label: "std::length_error" },
  { value: "std::out_of_range", label: "std::out_of_range" },
  { value: "std::overflow_error", label: "std::overflow_error" },
  { value: "std::underflow_error", label: "std::underflow_error" },
  { value: "std::range_error", label: "std::range_error" },
  { value: "std::bad_alloc", label: "std::bad_alloc" },
  { value: "std::bad_cast", label: "std::bad_cast" },
  { value: "std::bad_typeid", label: "std::bad_typeid" },
  { value: "std::bad_function_call", label: "std::bad_function_call" },
];

export type { EditableExceptionExpectation } from "@/lib/exceptionTestState";

export function ExceptionExpectationFields({
  id,
  value,
  supportsReturnValue,
  onChange,
}: {
  id: string;
  value: EditableExceptionExpectation;
  supportsReturnValue: boolean;
  onChange: (value: EditableExceptionExpectation) => void;
}) {
  return (
    <div className="mt-3 space-y-2">
      <label
        htmlFor={`${id}-outcome`}
        className="block text-xs font-medium text-slate-600"
      >
        Expected outcome
      </label>
      <select
        id={`${id}-outcome`}
        value={value.expected_outcome}
        onChange={(event) =>
          onChange(
            normalizeExpectedOutcome(
              value,
              event.target.value as ExpectedOutcomeKind,
            ),
          )
        }
        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
      >
        {supportsReturnValue && (
          <option value="return_value">Returns a value</option>
        )}
        {!supportsReturnValue && (
          <option value="return_void">Completes normally</option>
        )}
        <option value="throws">Throws an exception</option>
      </select>
      {value.expected_outcome === "throws" && (
        <>
          <label
            htmlFor={`${id}-exception-type`}
            className="block text-xs font-medium text-slate-600"
          >
            Exception type
          </label>
          <select
            id={`${id}-exception-type`}
            value={value.expected_exception_type}
            onChange={(event) =>
              onChange({
                ...value,
                expected_exception_type: event.target
                  .value as SupportedExceptionType,
              })
            }
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="">Choose an exception type</option>
            {EXCEPTION_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <label
            htmlFor={`${id}-message-rule`}
            className="block text-xs font-medium text-slate-600"
          >
            Message matching
          </label>
          <select
            id={`${id}-message-rule`}
            value={value.exception_message_rule}
            onChange={(event) => {
              const rule = event.target.value as ExceptionMessageRule;
              onChange({
                ...value,
                exception_message_rule: rule,
                expected_exception_message:
                  rule === "ignore"
                    ? ""
                    : value.expected_exception_message,
              });
            }}
            className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="ignore">Ignore</option>
            <option value="exact">Exact</option>
            <option value="contains">Contains</option>
          </select>
          {value.exception_message_rule !== "ignore" && (
            <>
              <label
                htmlFor={`${id}-expected-message`}
                className="block text-xs font-medium text-slate-600"
              >
                Expected message
              </label>
              <input
                id={`${id}-expected-message`}
                value={value.expected_exception_message}
                maxLength={1_000}
                onChange={(event) =>
                  onChange({
                    ...value,
                    expected_exception_message: event.target.value,
                  })
                }
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
