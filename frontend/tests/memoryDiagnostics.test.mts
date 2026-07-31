import assert from "node:assert/strict";
import test from "node:test";

import { presentMemoryDiagnoses } from "../lib/memoryDiagnostics.ts";
import type { MemoryDiagnosis } from "../lib/testExecution.ts";

function diagnosis(
  title: string,
  confidence: MemoryDiagnosis["confidence"] = "confirmed",
): MemoryDiagnosis {
  return {
    category: "memory_leak",
    title,
    confidence,
    summary: "Allocated memory remained active.",
    likely_cause: null,
    source_range: {
      start_line: 5,
      end_line: 5,
      excerpt: '<script>alert("not markup")</script>',
      label: "Line 5",
      confidence: "likely",
    },
    suggested_direction: "Ensure cleanup happens on every exit path.",
    related_operation: null,
    confirmed_by: ["LSAN runtime report"],
    technical_details: ["Runtime tool: lsan"],
    supporting_findings: [],
  };
}

test("primary diagnosis is visible and secondary diagnoses are bounded", () => {
  const result = presentMemoryDiagnoses([
    diagnosis("Use after free"),
    diagnosis("Memory leak"),
    diagnosis("Undefined behaviour"),
    diagnosis("Fourth symptom"),
  ]);
  assert.equal(result.primary?.title, "Use after free");
  assert.deepEqual(
    result.secondary.map((item) => item.title),
    ["Memory leak", "Undefined behaviour"],
  );
  assert.equal(
    result.likelyAccess,
    '<script>alert("not markup")</script>',
  );
});

test("confidence labels distinguish confirmed, likely, and possible", () => {
  assert.equal(
    presentMemoryDiagnoses([diagnosis("A", "confirmed")]).confidenceLabel,
    "Confirmed issue",
  );
  assert.equal(
    presentMemoryDiagnoses([diagnosis("A", "likely")]).confidenceLabel,
    "Likely issue",
  );
  assert.equal(
    presentMemoryDiagnoses([diagnosis("A", "possible")]).confidenceLabel,
    "Possible issue",
  );
});

test("source excerpt remains plain data for React text rendering", () => {
  const excerpt = presentMemoryDiagnoses([diagnosis("Leak")]).primary
    ?.source_range?.excerpt;
  assert.equal(excerpt, '<script>alert("not markup")</script>');
});

test("empty and legacy payloads remain supported", () => {
  assert.deepEqual(presentMemoryDiagnoses(undefined), {
    primary: null,
    secondary: [],
    confidenceLabel: null,
    likelyAccess: null,
  });
});

test("specific out-of-bounds diagnosis stays primary without generic UB", () => {
  const specific = {
    ...diagnosis("Out-of-bounds read"),
    category: "out_of_bounds_read",
    summary: "The program read outside the valid range of an array.",
    suggested_direction:
      "Check the index against the valid bounds before reading the element.",
  };
  const result = presentMemoryDiagnoses([specific]);
  assert.equal(result.primary?.title, "Out-of-bounds read");
  assert.equal(result.primary?.category, "out_of_bounds_read");
  assert.equal(
    result.secondary.some(
      (item) => item.category === "undefined_behaviour",
    ),
    false,
  );
  assert.match(result.primary?.suggested_direction ?? "", /valid bounds/);
});
