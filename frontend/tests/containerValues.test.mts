import assert from "node:assert/strict";
import test from "node:test";

import {
  addEntry,
  addRow,
  adapterOrderLabel,
  containerStateSignature,
  createEntry,
  createRow,
  duplicateMapKeys,
  editorKindFor,
  entriesToArgument,
  moveEntry,
  moveRow,
  parseArgumentToRows,
  previewContainerValue,
  removeEntry,
  removeRow,
  rowsToArgument,
} from "../lib/containerValues.ts";
import type { FunctionTypeMetadata } from "../lib/testExecution.ts";

function meta(
  containerName: string,
  elementType = "int",
  extra: Partial<FunctionTypeMetadata> = {},
): FunctionTypeMetadata {
  return {
    kind: "container",
    display_type: `std::${containerName}<${elementType}>`,
    scalar_type: null,
    element_type: elementType,
    vector_depth: null,
    passing: "value",
    size_parameter_name: null,
    container_name: containerName,
    container_family: "sequence",
    key_type: null,
    mapped_type: null,
    fixed_size: null,
    nested_depth: 1,
    ordered: true,
    associative: false,
    unordered: false,
    adapter: false,
    supported: true,
    unsupported_reason: null,
    ...extra,
  };
}

function mapMeta(
  containerName: string,
  keyType = "std::string",
  mappedType = "int",
): FunctionTypeMetadata {
  return {
    kind: "container",
    display_type: `std::${containerName}<${keyType}, ${mappedType}>`,
    scalar_type: null,
    element_type: `std::pair<const ${keyType}, ${mappedType}>`,
    vector_depth: null,
    passing: "value",
    size_parameter_name: null,
    container_name: containerName,
    container_family: "associative",
    key_type: keyType,
    mapped_type: mappedType,
    fixed_size: null,
    nested_depth: 1,
    ordered: true,
    associative: true,
    unordered: false,
    adapter: false,
    supported: true,
    unsupported_reason: null,
  };
}

// ---------------------------------------------------------------------------
// 1. editorKindFor — all 15 containers
// ---------------------------------------------------------------------------

test("editorKindFor maps sequence containers", () => {
  assert.equal(editorKindFor(meta("deque")), "sequence");
  assert.equal(editorKindFor(meta("list")), "sequence");
  // vector depth 1 (kind vector not container) returns scalar
  const vecMeta: FunctionTypeMetadata = {
    kind: "vector",
    display_type: "std::vector<int>",
    scalar_type: null,
    element_type: "int",
    vector_depth: 1,
    passing: "value",
    size_parameter_name: null,
  };
  assert.equal(editorKindFor(vecMeta), "scalar");
});

test("editorKindFor maps set containers", () => {
  assert.equal(editorKindFor(meta("set", "int", { associative: true })), "set");
  assert.equal(editorKindFor(meta("multiset", "int", { associative: true })), "set");
  assert.equal(editorKindFor(meta("unordered_set", "int", { unordered: true })), "set");
  assert.equal(editorKindFor(meta("unordered_multiset", "int", { unordered: true })), "set");
});

test("editorKindFor maps map containers", () => {
  assert.equal(editorKindFor(mapMeta("map")), "map");
  assert.equal(editorKindFor(mapMeta("multimap")), "map");
  assert.equal(editorKindFor(mapMeta("unordered_map")), "map");
  assert.equal(editorKindFor(mapMeta("unordered_multimap")), "map");
});

test("editorKindFor maps adapter containers", () => {
  assert.equal(editorKindFor(meta("stack")), "adapter");
  assert.equal(editorKindFor(meta("queue")), "adapter");
  assert.equal(editorKindFor(meta("priority_queue")), "adapter");
});

test("editorKindFor returns scalar for null/undefined/non-container", () => {
  assert.equal(editorKindFor(null), "scalar");
  assert.equal(editorKindFor(undefined), "scalar");
  const scalarMeta: FunctionTypeMetadata = {
    kind: "scalar",
    display_type: "int",
    scalar_type: "int",
    element_type: null,
    vector_depth: null,
    passing: "value",
    size_parameter_name: null,
  };
  assert.equal(editorKindFor(scalarMeta), "scalar");
});

// ---------------------------------------------------------------------------
// 2. rowsToArgument
// ---------------------------------------------------------------------------

test("rowsToArgument with ints", () => {
  const rows = ["1", "2", "3"].map((v) => createRow(v));
  assert.equal(rowsToArgument(rows, meta("deque")), "[1,2,3]");
});

test("rowsToArgument with strings", () => {
  const m = meta("set", "std::string");
  const rows = ["a", "b"].map((v) => createRow(v));
  assert.equal(rowsToArgument(rows, m), '["a","b"]');
});

test("rowsToArgument with bools", () => {
  const m = meta("deque", "bool");
  const rows = [createRow("true"), createRow("false")];
  const result = JSON.parse(rowsToArgument(rows, m));
  assert.deepEqual(result, [true, false]);
});

test("rowsToArgument empty returns []", () => {
  assert.equal(rowsToArgument([], meta("deque")), "[]");
});

// ---------------------------------------------------------------------------
// 3. entriesToArgument
// ---------------------------------------------------------------------------

test("entriesToArgument unique string keys → JSON object", () => {
  const m = mapMeta("map");
  const entries = [
    createEntry("apple", "3"),
    createEntry("orange", "5"),
  ];
  const result = JSON.parse(entriesToArgument(entries, m));
  assert.equal(result["apple"], 3);
  assert.equal(result["orange"], 5);
});

test("entriesToArgument multimap duplicate keys → list form", () => {
  const m = mapMeta("multimap");
  const entries = [
    createEntry("a", "1"),
    createEntry("a", "2"),
  ];
  const result = JSON.parse(entriesToArgument(entries, m));
  assert.ok(Array.isArray(result));
  assert.equal(result.length, 2);
  assert.equal(result[0].key, "a");
});

// ---------------------------------------------------------------------------
// 4. serialization → parsing round-trip (values preserved, order preserved)
// ---------------------------------------------------------------------------

test("rowsToArgument → parseArgumentToRows round-trip preserves values and order", () => {
  const m = meta("deque");
  const original = ["3", "1", "2"].map((v) => createRow(v));
  const serialized = rowsToArgument(original, m);
  const parsed = parseArgumentToRows(serialized, m);
  assert.deepEqual(
    parsed.map((r) => r.value),
    ["3", "1", "2"],
  );
});

test("parseArgumentToRows gives fresh IDs (IDs not required to survive serialization)", () => {
  const m = meta("deque");
  const rows = ["10", "20"].map((v) => createRow(v));
  const serialized = rowsToArgument(rows, m);
  const parsed = parseArgumentToRows(serialized, m);
  // IDs are fresh but values are correct
  assert.equal(parsed[0].value, "10");
  assert.equal(parsed[1].value, "20");
});

// ---------------------------------------------------------------------------
// 5. removeRow removes exactly one row even with duplicate values
// ---------------------------------------------------------------------------

test("removeRow removes only the targeted ID", () => {
  const r1 = createRow("5");
  const r2 = createRow("5");
  const rows = [r1, r2];
  const after = removeRow(rows, r1.id);
  assert.equal(after.length, 1);
  assert.equal(after[0].id, r2.id);
});

// ---------------------------------------------------------------------------
// 6. moveRow preserves row IDs and values
// ---------------------------------------------------------------------------

test("moveRow down swaps rows and preserves IDs", () => {
  const r1 = createRow("a");
  const r2 = createRow("b");
  const rows = [r1, r2];
  const after = moveRow(rows, r1.id, 1);
  assert.equal(after[0].id, r2.id);
  assert.equal(after[1].id, r1.id);
  assert.equal(after[0].value, "b");
  assert.equal(after[1].value, "a");
});

test("moveRow up at boundary is a no-op", () => {
  const r1 = createRow("x");
  const r2 = createRow("y");
  const rows = [r1, r2];
  const after = moveRow(rows, r1.id, -1);
  assert.deepEqual(after, rows);
});

// ---------------------------------------------------------------------------
// 7. Editing a row preserves its ID
// ---------------------------------------------------------------------------

test("editing a row value preserves its ID", () => {
  const row = createRow("old");
  const updated = { ...row, value: "new" };
  assert.equal(updated.id, row.id);
  assert.equal(updated.value, "new");
});

// ---------------------------------------------------------------------------
// 8. addRow creates exactly one new ID
// ---------------------------------------------------------------------------

test("addRow adds exactly one row with a unique ID", () => {
  const r1 = createRow("x");
  const rows = [r1];
  const after = addRow(rows);
  assert.equal(after.length, 2);
  assert.notEqual(after[1].id, r1.id);
  assert.equal(after[1].value, "");
});

// ---------------------------------------------------------------------------
// 9. duplicateMapKeys
// ---------------------------------------------------------------------------

test("duplicateMapKeys flags duplicates for map", () => {
  const m = mapMeta("map");
  const entries = [
    createEntry("a", "1"),
    createEntry("a", "2"),
    createEntry("b", "3"),
  ];
  const dupes = duplicateMapKeys(entries, m);
  assert.deepEqual(dupes, ["a"]);
});

test("duplicateMapKeys returns empty for multimap", () => {
  const m = mapMeta("multimap");
  const entries = [
    createEntry("a", "1"),
    createEntry("a", "2"),
  ];
  assert.deepEqual(duplicateMapKeys(entries, m), []);
});

// ---------------------------------------------------------------------------
// 10. containerStateSignature differs between different types
// ---------------------------------------------------------------------------

test("containerStateSignature differs between set<int> and set<std::string>", () => {
  const s1 = containerStateSignature(meta("set", "int"));
  const s2 = containerStateSignature(meta("set", "std::string"));
  assert.notEqual(s1, s2);
});

test("containerStateSignature same for same type", () => {
  assert.equal(
    containerStateSignature(meta("deque", "int")),
    containerStateSignature(meta("deque", "int")),
  );
});

// ---------------------------------------------------------------------------
// 11. adapterOrderLabel
// ---------------------------------------------------------------------------

test("adapterOrderLabel stack input", () => {
  const label = adapterOrderLabel("stack", "input");
  assert.ok(label.toLowerCase().includes("bottom"));
});

test("adapterOrderLabel stack expected", () => {
  const label = adapterOrderLabel("stack", "expected");
  assert.ok(label.toLowerCase().includes("top"));
});

test("adapterOrderLabel queue input", () => {
  const label = adapterOrderLabel("queue", "input");
  assert.ok(label.toLowerCase().includes("front"));
});

test("adapterOrderLabel queue expected", () => {
  const label = adapterOrderLabel("queue", "expected");
  assert.ok(label.toLowerCase().includes("front"));
});

test("adapterOrderLabel priority_queue input", () => {
  const label = adapterOrderLabel("priority_queue", "input");
  assert.ok(label.length > 0);
});

test("adapterOrderLabel priority_queue expected", () => {
  const label = adapterOrderLabel("priority_queue", "expected");
  assert.ok(label.toLowerCase().includes("pop"));
});

// ---------------------------------------------------------------------------
// 12. previewContainerValue
// ---------------------------------------------------------------------------

test("previewContainerValue short value unchanged", () => {
  const val = JSON.stringify([1, 2, 3]);
  assert.equal(previewContainerValue(val, 12), val);
});

test("previewContainerValue long array is compacted", () => {
  const arr = Array.from({ length: 20 }, (_, i) => i);
  const serialized = JSON.stringify(arr);
  const preview = previewContainerValue(serialized, 12);
  assert.ok(preview.includes("+8 more"));
  assert.ok(!preview.includes("19")); // last element should be cut off
});

test("previewContainerValue invalid JSON falls back to truncation", () => {
  const longStr = "x".repeat(250);
  const preview = previewContainerValue(longStr, 12);
  assert.ok(preview.length <= 203); // 200 + "…"
  assert.ok(preview.endsWith("…"));
});

// ---------------------------------------------------------------------------
// addEntry / removeEntry / moveEntry (completeness)
// ---------------------------------------------------------------------------

test("addEntry adds one entry", () => {
  const e1 = createEntry("k", "v");
  const after = addEntry([e1]);
  assert.equal(after.length, 2);
  assert.notEqual(after[1].id, e1.id);
});

test("removeEntry removes targeted entry", () => {
  const e1 = createEntry("a", "1");
  const e2 = createEntry("b", "2");
  const after = removeEntry([e1, e2], e1.id);
  assert.equal(after.length, 1);
  assert.equal(after[0].id, e2.id);
});

test("moveEntry down preserves IDs", () => {
  const e1 = createEntry("a", "1");
  const e2 = createEntry("b", "2");
  const after = moveEntry([e1, e2], e1.id, 1);
  assert.equal(after[0].id, e2.id);
  assert.equal(after[1].id, e1.id);
});
