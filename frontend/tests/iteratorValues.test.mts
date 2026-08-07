import { it } from "node:test";
import assert from "node:assert/strict";

import {
  containerJsonFromHeadPayload,
  elementCountOf,
  formatIteratorResult,
  headArgumentPayload,
  headPayloadFromContainerJson,
  iteratorBackingMetadata,
  iteratorStateSignature,
  parseHeadArgument,
  parseTailArgument,
  positionHelperText,
  rangeElementsPreview,
  tailArgumentPayload,
  validatePosition,
} from "../lib/iteratorValues.ts";
import type { FunctionTypeMetadata } from "../lib/testExecution.ts";

// ── Head payload ─────────────────────────────────────────────────────────────

it("head payload round-trips through headArgumentPayload and parseHeadArgument", () => {
  const state = { container: ["1", "2", "3"], position: 1 };
  const raw = headArgumentPayload(state);
  const parsed = parseHeadArgument(raw);
  assert.deepEqual(parsed, state);
});

it("head payload contains both container and position keys", () => {
  const raw = headArgumentPayload({ container: ["10"], position: 0 });
  const obj = JSON.parse(raw) as Record<string, unknown>;
  assert.ok("container" in obj, "must have container key");
  assert.ok("position" in obj, "must have position key");
});

// ── Tail payload ─────────────────────────────────────────────────────────────

it("tail payload round-trips through tailArgumentPayload and parseTailArgument", () => {
  const raw = tailArgumentPayload(3);
  const parsed = parseTailArgument(raw);
  assert.deepEqual(parsed, { position: 3 });
});

it("tail payload contains no container key", () => {
  const raw = tailArgumentPayload(2);
  const obj = JSON.parse(raw) as Record<string, unknown>;
  assert.ok(!("container" in obj), "tail must not have container key");
});

it("parseTailArgument rejects a head payload (has container key)", () => {
  const headRaw = headArgumentPayload({ container: ["1"], position: 0 });
  assert.equal(parseTailArgument(headRaw), null);
});

// ── elementCountOf ────────────────────────────────────────────────────────────

it("elementCountOf returns correct count for a populated container", () => {
  const raw = headArgumentPayload({ container: ["a", "b", "c", "d"], position: 0 });
  assert.equal(elementCountOf(raw), 4);
});

it("elementCountOf returns 0 for an empty container", () => {
  const raw = headArgumentPayload({ container: [], position: 0 });
  assert.equal(elementCountOf(raw), 0);
});

it("elementCountOf returns 0 for unparseable input", () => {
  assert.equal(elementCountOf("not json"), 0);
  assert.equal(elementCountOf(tailArgumentPayload(2)), 0);
});

// ── validatePosition ──────────────────────────────────────────────────────────

it("validatePosition accepts position 0", () => {
  assert.equal(validatePosition(0, 5), null);
});

it("validatePosition accepts a position equal to containerSize (end)", () => {
  assert.equal(validatePosition(5, 5), null);
});

it("validatePosition rejects -1", () => {
  assert.notEqual(validatePosition(-1, 5), null);
});

it("validatePosition rejects count plus one", () => {
  assert.notEqual(validatePosition(6, 5), null);
});

it("validatePosition rejects non-integer input", () => {
  assert.notEqual(validatePosition(1.5, 5), null);
});

// ── rangeElementsPreview ─────────────────────────────────────────────────────

it("rangeElementsPreview respects half-open [begin, end) semantics", () => {
  const head = headArgumentPayload({ container: ["10", "20", "30", "40", "50"], position: 1 });
  const tail = tailArgumentPayload(4);
  const preview = rangeElementsPreview(head, tail);
  assert.equal(preview, "[20, 30, 40]");
});

it("rangeElementsPreview returns (empty range) for [0, 0) on an empty container", () => {
  const head = headArgumentPayload({ container: [], position: 0 });
  const tail = tailArgumentPayload(0);
  assert.equal(rangeElementsPreview(head, tail), "(empty range)");
});

// ── positionHelperText and iteratorStateSignature and formatIteratorResult ───

it("positionHelperText produces end() wording at the boundary", () => {
  const text = positionHelperText(3, 3);
  assert.ok(text.includes("end()"), `expected end() wording, got: ${text}`);
});

it("iteratorStateSignature differs between vector<int> and list<int> iterators", () => {
  const vectorMeta: Partial<FunctionTypeMetadata> = {
    kind: "iterator",
    iterator_container: "vector",
    element_type: "int",
    iterator_const: false,
    iterator_role: "single",
  };
  const listMeta: Partial<FunctionTypeMetadata> = {
    kind: "iterator",
    iterator_container: "list",
    element_type: "int",
    iterator_const: false,
    iterator_role: "single",
  };
  const sig1 = iteratorStateSignature(vectorMeta as FunctionTypeMetadata);
  const sig2 = iteratorStateSignature(listMeta as FunctionTypeMetadata);
  assert.notEqual(sig1, sig2);
});

it('formatIteratorResult maps "end" to end() wording and 2 to Index 2', () => {
  assert.ok(formatIteratorResult("end").includes("end()"));
  assert.equal(formatIteratorResult("2"), "Index 2");
});

// ── Wire-format regression tests ──────────────────────────────────────────────

it("headPayloadFromContainerJson with int values serializes as JSON numbers not strings", () => {
  // ContainerValueEditor produces "[1, 2, 3, 4, 5]" for a vector<int>
  const containerJson = "[1, 2, 3, 4, 5]";
  const payload = headPayloadFromContainerJson(containerJson, 1);
  const parsed = JSON.parse(payload) as Record<string, unknown>;
  const container = parsed.container as unknown[];
  assert.ok(Array.isArray(container), "container must be an array");
  assert.equal(container.length, 5);
  // Elements must be numbers, not strings
  assert.strictEqual(typeof container[0], "number", `element 0 must be number, got ${typeof container[0]}`);
  assert.strictEqual(container[0], 1);
  assert.strictEqual(container[4], 5);
  assert.strictEqual(parsed.position, 1);
});

it("head payload is {container: [1,2,3,4,5], position: 1}", () => {
  const payload = headPayloadFromContainerJson("[1,2,3,4,5]", 1);
  const parsed = JSON.parse(payload) as { container: number[]; position: number };
  assert.deepEqual(parsed.container, [1, 2, 3, 4, 5]);
  assert.equal(parsed.position, 1);
});

it("tail payload is {position: 4} and contains no container field", () => {
  const payload = tailArgumentPayload(4);
  const parsed = JSON.parse(payload) as Record<string, unknown>;
  assert.equal(parsed.position, 4);
  assert.ok(!("container" in parsed), "tail payload must not have container key");
});

it("containerJsonFromHeadPayload extracts container as typed JSON array", () => {
  // Simulates a head payload that the backend would have constructed with numbers
  const headPayload = JSON.stringify({ container: [10, 20, 30], position: 0 });
  const containerJson = containerJsonFromHeadPayload(headPayload);
  const arr = JSON.parse(containerJson) as unknown[];
  assert.deepEqual(arr, [10, 20, 30]);
  // Values must be numbers, not strings
  assert.strictEqual(typeof arr[0], "number");
});

it("std::string element containers remain JSON strings after round-trip", () => {
  // String containers: elements should stay as strings
  const containerJson = '["hello", "world"]';
  const payload = headPayloadFromContainerJson(containerJson, 0);
  const parsed = JSON.parse(payload) as { container: unknown[] };
  assert.deepEqual(parsed.container, ["hello", "world"]);
  assert.strictEqual(typeof parsed.container[0], "string");
});

it("iteratorBackingMetadata produces kind=container suitable for ContainerValueEditor", () => {
  const iterMeta: Partial<FunctionTypeMetadata> = {
    kind: "iterator",
    iterator_container: "vector",
    element_type: "int",
    iterator_const: false,
    iterator_role: "range_begin",
    fixed_size: null,
  };
  const backing = iteratorBackingMetadata(iterMeta as FunctionTypeMetadata);
  assert.equal(backing.kind, "container");
  assert.equal(backing.container_name, "vector");
  assert.equal(backing.element_type, "int");
});

it("iteratorBackingMetadata for list container produces container_name=list", () => {
  const iterMeta: Partial<FunctionTypeMetadata> = {
    kind: "iterator",
    iterator_container: "list",
    element_type: "int",
    iterator_const: false,
    iterator_role: "single",
    fixed_size: null,
  };
  const backing = iteratorBackingMetadata(iterMeta as FunctionTypeMetadata);
  assert.equal(backing.container_name, "list");
});

// ── Head initialization conditions (Bug 1) ───────────────────────────────────

it("parseHeadArgument returns null for empty string triggering head initialization", () => {
  assert.equal(parseHeadArgument(""), null);
});

it("parseHeadArgument returns null for bare whitespace", () => {
  assert.equal(parseHeadArgument("   "), null);
});

it("parseHeadArgument returns non-null for a valid head payload so initialization is skipped", () => {
  const payload = headPayloadFromContainerJson("[]", 0);
  assert.notEqual(parseHeadArgument(payload), null);
});

it("default head initialization payload is {container:[], position:0}", () => {
  const payload = headPayloadFromContainerJson("[]", 0);
  const parsed = JSON.parse(payload) as { container: unknown[]; position: number };
  assert.deepEqual(parsed.container, []);
  assert.equal(parsed.position, 0);
});
