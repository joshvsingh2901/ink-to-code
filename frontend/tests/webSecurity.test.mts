import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, it } from "node:test";

import {
  buildContentSecurityPolicy,
  buildSecurityHeaders,
  mockTranscriptionEnabled,
} from "../lib/webSecurity.ts";


const FRONTEND_ROOT = path.resolve(import.meta.dirname, "..");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const resolved = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(resolved);
    return /\.(?:ts|tsx|js|jsx|mjs)$/.test(entry.name) ? [resolved] : [];
  });
}

describe("production security headers", () => {
  it("includes the required CSP directives without development eval", () => {
    const policy = buildContentSecurityPolicy(
      "production",
      "https://api.example.com/v1",
    );
    assert.match(policy, /default-src 'self'/);
    assert.match(policy, /object-src 'none'/);
    assert.match(policy, /frame-ancestors 'none'/);
    assert.match(policy, /worker-src 'self' blob:/);
    assert.match(policy, /connect-src 'self' https:\/\/api\.example\.com/);
    assert.doesNotMatch(policy, /'unsafe-eval'/);
  });

  it("adds nosniff, referrer, permissions, and frame headers", () => {
    const headers = new Map(
      buildSecurityHeaders({
        environment: "production",
        apiBaseUrl: "https://api.example.com",
        enableHsts: false,
      }).map((header) => [header.key, header.value]),
    );
    assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
    assert.equal(
      headers.get("Referrer-Policy"),
      "strict-origin-when-cross-origin",
    );
    assert.match(headers.get("Permissions-Policy") ?? "", /camera=\(\)/);
    assert.equal(headers.get("X-Frame-Options"), "DENY");
  });

  it("emits HSTS only for explicitly enabled production HTTPS", () => {
    const production = buildSecurityHeaders({
      environment: "production",
      apiBaseUrl: "https://api.example.com",
      enableHsts: true,
    });
    const development = buildSecurityHeaders({
      environment: "development",
      apiBaseUrl: "http://localhost:8000",
      enableHsts: true,
    });
    assert.ok(
      production.some((header) => header.key === "Strict-Transport-Security"),
    );
    assert.ok(
      development.every(
        (header) => header.key !== "Strict-Transport-Security",
      ),
    );
  });
});

describe("HTML and runtime safety", () => {
  it("React renders compiler/user/model strings as escaped text", () => {
    const hostile = '<img src=x onerror="globalThis.pwned=true"><script>x</script>';
    const markup = renderToStaticMarkup(React.createElement("pre", null, hostile));
    assert.doesNotMatch(markup, /<script>|<img/);
    assert.match(markup, /&lt;script&gt;/);
    assert.match(markup, /&lt;img/);
  });

  it("application sources contain no direct HTML injection sinks", () => {
    const files = [
      ...sourceFiles(path.join(FRONTEND_ROOT, "app")),
      ...sourceFiles(path.join(FRONTEND_ROOT, "components")),
      ...sourceFiles(path.join(FRONTEND_ROOT, "lib")),
    ];
    const combined = files.map((file) => readFileSync(file, "utf8")).join("\n");
    for (const unsafeSink of [
      "dangerouslySetInnerHTML",
      ".innerHTML",
      ".outerHTML",
      "insertAdjacentHTML",
      "document.write",
    ]) {
      assert.equal(combined.includes(unsafeSink), false, unsafeSink);
    }
  });

  it("mock transcription cannot be enabled in production", () => {
    assert.equal(mockTranscriptionEnabled("production", "true"), false);
    assert.equal(mockTranscriptionEnabled("development", "true"), true);
    assert.equal(mockTranscriptionEnabled("development", "false"), false);
  });
});
