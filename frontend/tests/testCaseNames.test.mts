import { it } from "node:test";
import assert from "node:assert/strict";

import { nextTestName } from "../lib/testCaseNames.ts";

it("nextTestName returns Test 1 for an empty list", () => {
  assert.equal(nextTestName([]), "Test 1");
});

it("nextTestName returns Test 1 after all tests are deleted", () => {
  // Simulate adding two tests then deleting both
  const after = [] as { name: string }[];
  assert.equal(nextTestName(after), "Test 1");
});

it("nextTestName returns Test 3 when Test 1 and Test 2 exist", () => {
  const tests = [{ name: "Test 1" }, { name: "Test 2" }];
  assert.equal(nextTestName(tests), "Test 3");
});

it("nextTestName fills gap when Test 1 is deleted from [Test 1, Test 2]", () => {
  const tests = [{ name: "Test 2" }];
  assert.equal(nextTestName(tests), "Test 1");
});

it("nextTestName fills gap when Test 2 is deleted from [Test 1, Test 2, Test 3]", () => {
  const tests = [{ name: "Test 1" }, { name: "Test 3" }];
  assert.equal(nextTestName(tests), "Test 2");
});

it("nextTestName ignores custom-named tests when finding next default slot", () => {
  const tests = [{ name: "My custom test" }, { name: "Test 1" }];
  assert.equal(nextTestName(tests), "Test 2");
});

it("nextTestName returns Test 1 when only custom-named tests exist", () => {
  const tests = [{ name: "Edge case" }, { name: "Boundary" }];
  assert.equal(nextTestName(tests), "Test 1");
});
