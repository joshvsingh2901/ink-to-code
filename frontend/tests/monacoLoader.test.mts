import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";

import { describeMonacoInitializationError } from "../lib/monacoLoader.ts";

function listSourceFiles(dir: string): string[] {
  const entries = readdirSync(dir);
  const files: string[] = [];
  for (const entry of entries) {
    const fullPath = path.join(dir, entry);
    if (statSync(fullPath).isDirectory()) {
      files.push(...listSourceFiles(fullPath));
    } else if (/\.tsx?$/.test(entry)) {
      files.push(fullPath);
    }
  }
  return files;
}

describe("Monaco initialization diagnostics", () => {
  it("loads Monaco and its editor worker from local bundled modules", () => {
    const source = readFileSync(
      path.resolve(import.meta.dirname, "../lib/monacoLoader.ts"),
      "utf8",
    );
    const workerSource = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../workers/monacoEditor.worker.ts",
      ),
      "utf8",
    );

    assert.match(source, /import\("monaco-editor"\)/);
    assert.match(source, /new Worker\(/);
    assert.doesNotMatch(source, /cdn\.jsdelivr|unpkg|unsafe-eval/);
    assert.match(workerSource, /monaco-editor\/editor\/editor\.worker\.js/);
  });

  it("turns a script loading event into an actionable message", () => {
    const message = describeMonacoInitializationError({
      type: "error",
      target: {
        tagName: "SCRIPT",
        src: "https://example.invalid/secret.js?token=do-not-display",
      },
    });

    assert.equal(
      message,
      "The code editor could not load a required script (error event).",
    );
    assert.doesNotMatch(message, /example|secret|token/);
  });

  it("preserves an ordinary Error message without stringifying objects", () => {
    assert.equal(
      describeMonacoInitializationError(new Error("Worker startup failed")),
      "The code editor could not initialize: Worker startup failed",
    );
    assert.doesNotMatch(describeMonacoInitializationError({}), /\[object Object\]/);
  });

  it("configures the local monaco instance before initializing the loader", () => {
    const source = readFileSync(
      path.resolve(import.meta.dirname, "../lib/monacoLoader.ts"),
      "utf8",
    );
    const configIndex = source.indexOf("loader.config(");
    const initIndex = source.indexOf("loader.init(");

    assert.ok(configIndex > -1, "loader.config(...) call not found");
    assert.ok(initIndex > -1, "loader.init(...) call not found");
    assert.ok(
      configIndex < initIndex,
      "loader.config({ monaco }) must run before loader.init(), or Monaco falls back to the CDN loader",
    );
  });

  it("mounts Monaco only through the local loader wrapper", () => {
    const root = path.resolve(import.meta.dirname, "..");
    const searchDirs = ["app", "components", "lib"].map((dir) =>
      path.join(root, dir),
    );
    const files = searchDirs.flatMap((dir) => listSourceFiles(dir));

    // A value import of `Editor` bypasses monacoLoader's local configuration
    // and reintroduces @monaco-editor/react's default CDN-backed loader.init().
    const valueImportPattern =
      /import\s+(?!type\s)[\s\S]*?from\s+["']@monaco-editor\/react["']/;
    const typeOnlyImportPattern =
      /import\s*\{\s*type\s+\w+(\s*,\s*type\s+\w+)*\s*\}\s*from\s+["']@monaco-editor\/react["']/;

    const valueImporters = files.filter((file) => {
      if (file.endsWith(path.join("components", "LocalMonacoEditor.tsx")))
        return false;
      if (file.endsWith(path.join("lib", "monacoLoader.ts"))) return false;

      const text = readFileSync(file, "utf8");
      if (!text.includes("@monaco-editor/react")) return false;
      if (typeOnlyImportPattern.test(text)) return false;
      return valueImportPattern.test(text);
    });

    assert.deepEqual(
      valueImporters,
      [],
      "only components/LocalMonacoEditor.tsx may import Editor/loader as a value from @monaco-editor/react",
    );
  });
});
