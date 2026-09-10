import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { apiErrorCode, apiErrorMessage } from "../lib/apiErrors.ts";


describe("apiErrorMessage", () => {
  it("never displays an unexpected 500 body and safely includes correlation", () => {
    const requestId = "123e4567-e89b-42d3-a456-426614174000";
    const message = apiErrorMessage(
      500,
      { error: { message: "Traceback: /private/tmp/secret.py" } },
      "fallback",
      "compiler",
      requestId,
    );
    assert.doesNotMatch(message, /Traceback|private\/tmp/);
    assert.match(message, new RegExp(requestId));
    assert.doesNotMatch(
      apiErrorMessage(500, null, "fallback", "compiler", "bad\nheader"),
      /bad/,
    );
  });

  it("preserves detailed backend validation messages", () => {
    assert.equal(
      apiErrorMessage(
        422,
        { error: { code: "source_too_large", message: "Source is too large." } },
        "fallback",
        "compiler",
      ),
      "Source is too large.",
    );
  });

  it("maps rate, capacity, and request-size statuses when no envelope is available", () => {
    assert.equal(
      apiErrorMessage(429, null, "fallback", "compiler"),
      "Too many requests. Try again shortly.",
    );
    assert.equal(
      apiErrorMessage(503, null, "fallback", "compiler"),
      "The compiler is busy. Try again in a moment.",
    );
    assert.equal(
      apiErrorMessage(503, null, "fallback", "ai"),
      "AI service is busy. Try again in a moment.",
    );
    assert.equal(
      apiErrorMessage(413, null, "fallback", "ai"),
      "This request is too large to process.",
    );
  });

  it("retains structured codes for test-run handling", () => {
    assert.equal(
      apiErrorCode({ error: { code: "test_value_too_large" } }),
      "test_value_too_large",
    );
  });
});
