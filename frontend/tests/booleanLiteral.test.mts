import assert from "node:assert/strict";
import test from "node:test";

import { normalizeBooleanLiteral } from "../lib/booleanLiteral.ts";

test("normalizeBooleanLiteral", async (t) => {
  await t.test("lowercases accepted case-insensitive boolean literals", () => {
    assert.equal(normalizeBooleanLiteral("true"), "true");
    assert.equal(normalizeBooleanLiteral("True"), "true");
    assert.equal(normalizeBooleanLiteral("TRUE"), "true");
    assert.equal(normalizeBooleanLiteral("false"), "false");
    assert.equal(normalizeBooleanLiteral("False"), "false");
    assert.equal(normalizeBooleanLiteral("FALSE"), "false");
  });

  await t.test("trims surrounding whitespace before matching", () => {
    assert.equal(normalizeBooleanLiteral("  True  "), "true");
  });

  await t.test("leaves non-boolean values unchanged", () => {
    assert.equal(normalizeBooleanLiteral("maybe"), "maybe");
    assert.equal(normalizeBooleanLiteral(""), "");
    assert.equal(normalizeBooleanLiteral("1"), "1");
  });
});
