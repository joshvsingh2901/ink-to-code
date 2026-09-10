import assert from "node:assert/strict";
import test from "node:test";

import { deriveCompileGate } from "../lib/compileGate.ts";
import type { CompileResult } from "../lib/compiler.ts";

function baseInput(overrides: Partial<Parameters<typeof deriveCompileGate>[0]> = {}) {
  return {
    compiledVersion: null,
    codeVersion: 0,
    isCompiling: false,
    compileResult: null,
    checkError: null,
    compileError: null,
    ...overrides,
  };
}

function cleanSuccess(): CompileResult {
  return { success: true, stdout: "", stderr: "", exit_code: 0, diagnostics: [] };
}

test("deriveCompileGate", async (t) => {
  await t.test("never compiled, not compiling -> never_compiled", () => {
    const state = deriveCompileGate(baseInput());
    assert.equal(state, "never_compiled");
  });

  await t.test("never compiled, compiling -> compiling", () => {
    const state = deriveCompileGate(
      baseInput({ isCompiling: true }),
    );
    assert.equal(state, "compiling");
  });

  await t.test(
    "compiledVersion behind codeVersion -> stale, even with a clean success",
    () => {
      const state = deriveCompileGate(
        baseInput({
          compiledVersion: 1,
          codeVersion: 2,
          compileResult: cleanSuccess(),
        }),
      );
      assert.equal(state, "stale");
    },
  );

  await t.test(
    "compiledVersion matches codeVersion, clean success -> ready",
    () => {
      const state = deriveCompileGate(
        baseInput({
          compiledVersion: 3,
          codeVersion: 3,
          compileResult: cleanSuccess(),
        }),
      );
      assert.equal(state, "ready");
    },
  );

  await t.test("matching version, success: false -> failed", () => {
    const state = deriveCompileGate(
      baseInput({
        compiledVersion: 1,
        codeVersion: 1,
        compileResult: {
          success: false,
          stdout: "",
          stderr: "error",
          exit_code: 1,
          diagnostics: [],
        },
      }),
    );
    assert.equal(state, "failed");
  });

  await t.test("matching version, non-empty diagnostics -> failed", () => {
    const state = deriveCompileGate(
      baseInput({
        compiledVersion: 1,
        codeVersion: 1,
        compileResult: {
          success: true,
          stdout: "",
          stderr: "",
          exit_code: 0,
          diagnostics: [
            {
              line: 1,
              column: 1,
              severity: "error",
              message: "boom",
              explanation: null,
            },
          ],
        },
      }),
    );
    assert.equal(state, "failed");
  });

  await t.test("matching version, non-zero exit_code -> failed", () => {
    const state = deriveCompileGate(
      baseInput({
        compiledVersion: 1,
        codeVersion: 1,
        compileResult: {
          success: true,
          stdout: "",
          stderr: "",
          exit_code: 1,
          diagnostics: [],
        },
      }),
    );
    assert.equal(state, "failed");
  });

  await t.test(
    "checkError with a retained prior success -> unknown, never ready",
    () => {
      const state = deriveCompileGate(
        baseInput({
          compiledVersion: 1,
          codeVersion: 2,
          compileResult: cleanSuccess(),
          checkError: "The compiler backend could not complete the request.",
        }),
      );
      assert.equal(state, "unknown");
    },
  );

  await t.test("compileError, never compiled -> unknown", () => {
    const state = deriveCompileGate(
      baseInput({
        compileError: "The compiler backend could not complete the request.",
      }),
    );
    assert.equal(state, "unknown");
  });

  await t.test(
    "compiling while a previous version compiled cleanly -> compiling, not ready",
    () => {
      const state = deriveCompileGate(
        baseInput({
          compiledVersion: 1,
          codeVersion: 2,
          isCompiling: true,
          compileResult: cleanSuccess(),
        }),
      );
      assert.equal(state, "compiling");
    },
  );
});
