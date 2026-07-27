"use client";

import Editor, { type OnMount } from "@monaco-editor/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import {
  compileCpp,
  type CompileDiagnostic,
  type CompileResult,
} from "@/lib/compiler";

type SidebarTab = "compiler" | "tests";
type PrimaryDiagnostic = CompileDiagnostic & {
  severity: "error" | "warning";
};
type IssueCategory =
  | "Identifier issue"
  | "Syntax issue"
  | "Brace issue"
  | "Semicolon issue"
  | "Type issue"
  | "Declaration issue"
  | "Operator issue"
  | "Warning"
  | "Other issue";

const COMPILER_MARKER_OWNER = "inktocode-compiler";

const MOCK_TESTS = [
  { name: "Test 1", result: "Passed" },
  { name: "Test 2", result: "Failed" },
  { name: "Test 3", result: "Passed" },
  { name: "Test 4", result: "Failed" },
] as const;

function sanitizeFilename(filename: string) {
  const withoutExtension = filename.replace(/\.cpp$/i, "");
  const safeBase = withoutExtension
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/^\.+/, "")
    .slice(0, 80);

  return `${safeBase || "solution"}.cpp`;
}

function isPrimaryDiagnostic(
  diagnostic: CompileDiagnostic,
): diagnostic is PrimaryDiagnostic {
  return diagnostic.severity === "error" || diagnostic.severity === "warning";
}

function getIssueCategory(diagnostic: PrimaryDiagnostic): IssueCategory {
  if (diagnostic.severity === "warning") return "Warning";

  const message = diagnostic.message.toLowerCase();

  if (
    message.includes("expected ';'") ||
    message.includes("expected ‘;’") ||
    message.includes("semicolon")
  ) {
    return "Semicolon issue";
  }
  if (
    message.includes("expected '}'") ||
    message.includes("expected ‘}’") ||
    message.includes("expected '{'") ||
    message.includes("expected ‘{’") ||
    message.includes("unmatched brace") ||
    message.includes("missing brace")
  ) {
    return "Brace issue";
  }
  if (
    message.includes("undeclared identifier") ||
    message.includes("use of undeclared") ||
    message.includes("was not declared in this scope") ||
    message.includes("unknown identifier")
  ) {
    return "Identifier issue";
  }
  if (
    message.includes("invalid operands") ||
    message.includes("invalid operand") ||
    message.includes("no match for 'operator") ||
    message.includes("no match for ‘operator") ||
    message.includes("overloaded operator")
  ) {
    return "Operator issue";
  }
  if (
    message.includes("unknown type name") ||
    message.includes("does not name a type") ||
    message.includes("invalid conversion") ||
    message.includes("cannot convert") ||
    message.includes("incompatible type") ||
    message.includes("incomplete type")
  ) {
    return "Type issue";
  }
  if (
    message.includes("redefinition") ||
    message.includes("redeclaration") ||
    message.includes("conflicting declaration") ||
    message.includes("previous declaration")
  ) {
    return "Declaration issue";
  }
  if (
    message.includes("syntax error") ||
    message.includes("parse error") ||
    message.includes("expected expression") ||
    message.includes("expected primary-expression") ||
    message.startsWith("expected ")
  ) {
    return "Syntax issue";
  }

  return "Other issue";
}

export default function EditorPage() {
  const router = useRouter();
  const { reviewedCode, setReviewedCode } = useUploads();
  const [code, setCode] = useState(reviewedCode ?? "");
  const [filename, setFilename] = useState("solution.cpp");
  const [activeTab, setActiveTab] = useState<SidebarTab>("compiler");
  const [compileResult, setCompileResult] = useState<CompileResult | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [isCompiling, setIsCompiling] = useState(false);
  const [hasRunTests, setHasRunTests] = useState(false);
  const [isEdited, setIsEdited] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const initialCodeRef = useRef(reviewedCode ?? "");
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
  const codeVersionRef = useRef(0);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (reviewedCode === null) {
      router.replace("/");
    }
  }, [reviewedCode, router]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
  };

  function clearCompilerMarkers() {
    const model = editorRef.current?.getModel();
    if (model && monacoRef.current) {
      monacoRef.current.editor.setModelMarkers(
        model,
        COMPILER_MARKER_OWNER,
        [],
      );
    }
  }

  function getSafeLocation(diagnostic: CompileDiagnostic) {
    const model = editorRef.current?.getModel();
    if (!model) return null;

    const line = Math.min(
      Math.max(Math.trunc(diagnostic.line), 1),
      model.getLineCount(),
    );
    const maxColumn = model.getLineMaxColumn(line);
    const column = Math.min(
      Math.max(Math.trunc(diagnostic.column), 1),
      maxColumn,
    );
    return { line, column };
  }

  function applyCompilerMarkers(diagnostics: CompileDiagnostic[]) {
    const model = editorRef.current?.getModel();
    const monaco = monacoRef.current;
    if (!model || !monaco) return;

    const severityByType = {
      error: monaco.MarkerSeverity.Error,
      warning: monaco.MarkerSeverity.Warning,
    };

    monaco.editor.setModelMarkers(
      model,
      COMPILER_MARKER_OWNER,
      diagnostics.filter(isPrimaryDiagnostic).flatMap((diagnostic) => {
        const location = getSafeLocation(diagnostic);
        if (!location) return [];

        return [
          {
            startLineNumber: location.line,
            startColumn: location.column,
            endLineNumber: location.line,
            endColumn: location.column,
            message: diagnostic.message,
            severity: severityByType[diagnostic.severity],
          },
        ];
      }),
    );
  }

  function focusDiagnostic(diagnostic: CompileDiagnostic) {
    const editor = editorRef.current;
    const location = getSafeLocation(diagnostic);
    if (!editor || !location) return;

    editor.setPosition({
      lineNumber: location.line,
      column: location.column,
    });
    editor.revealLineInCenter(location.line);
    editor.focus();
  }

  async function handleCompile() {
    if (isCompiling) return;

    clearCompilerMarkers();
    setActiveTab("compiler");
    setCompileResult(null);
    setCompileError(null);
    setIsCompiling(true);
    const submittedVersion = codeVersionRef.current;

    try {
      const currentCode = editorRef.current?.getValue() ?? code;
      const result = await compileCpp(currentCode);
      if (submittedVersion !== codeVersionRef.current) return;

      setCompileResult(result);
      applyCompilerMarkers(result.diagnostics);
    } catch (error) {
      if (submittedVersion !== codeVersionRef.current) return;
      setCompileError(
        error instanceof Error
          ? error.message
          : "The compiler backend could not complete the request.",
      );
    } finally {
      setIsCompiling(false);
    }
  }

  function handleRunTests() {
    setActiveTab("tests");
    setHasRunTests(true);
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopyStatus("Code copied");
    } catch {
      setCopyStatus("Could not copy code");
    }

    if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    copyTimerRef.current = setTimeout(() => setCopyStatus(null), 2000);
  }

  function handleDownload() {
    const downloadName = sanitizeFilename(filename);
    const blobUrl = URL.createObjectURL(
      new Blob([code], { type: "text/x-c++src;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = downloadName;
    link.click();
    URL.revokeObjectURL(blobUrl);
    setFilename(downloadName);
  }

  if (reviewedCode === null) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
        <div className="text-center">
          <p className="font-semibold text-slate-900">No reviewed code found.</p>
          <button
            type="button"
            onClick={() => router.push("/")}
            className="mt-4 rounded-lg bg-slate-900 px-5 py-2.5 font-semibold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Return to Upload
          </button>
        </div>
      </main>
    );
  }

  const primaryDiagnostics =
    compileResult?.diagnostics.filter(isPrimaryDiagnostic) ?? [];

  return (
    <main className="min-h-screen bg-slate-100 p-3 sm:p-5">
      <div className="mx-auto max-w-[1600px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="border-b border-slate-200 px-4 py-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-3">
            <p className="mr-2 font-bold tracking-tight text-slate-950">InkToCode</p>
            <div className="flex min-w-48 flex-1 items-center gap-2 sm:flex-none">
              <label htmlFor="editor-filename" className="text-sm font-medium text-slate-600">
                Filename
              </label>
              <input
                id="editor-filename"
                value={filename}
                onChange={(event) => setFilename(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-2.5 py-1.5 font-mono text-sm text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-300 sm:w-44"
              />
            </div>
            <span className="rounded-md bg-slate-100 px-2.5 py-1.5 text-sm font-semibold text-slate-600">
              C++17
            </span>
            <span className="text-xs font-medium text-slate-500">
              {isEdited ? "Edited locally" : "Unchanged"}
            </span>
            <div className="ml-auto flex flex-wrap gap-2">
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Copy Code
              </button>
              <button
                type="button"
                onClick={handleDownload}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Download
              </button>
              <button
                type="button"
                onClick={handleCompile}
                disabled={isCompiling}
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isCompiling ? "Compiling..." : "Compile"}
              </button>
              <button
                type="button"
                onClick={handleRunTests}
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Run Tests
              </button>
            </div>
          </div>
          <div aria-live="polite" className="mt-2 min-h-5 text-right text-sm text-slate-600">
            {copyStatus}
          </div>
        </header>

        <div className="grid lg:grid-cols-[minmax(0,1fr)_22rem]">
          <section aria-label="C++ source editor" className="min-w-0 bg-[#1e1e1e]">
            <Editor
              height="65vh"
              defaultLanguage="cpp"
              value={code}
              onChange={(value) => {
                const nextCode = value ?? "";
                codeVersionRef.current += 1;
                clearCompilerMarkers();
                setCompileResult(null);
                setCompileError(null);
                setCode(nextCode);
                setReviewedCode(nextCode);
                setIsEdited(nextCode !== initialCodeRef.current);
              }}
              onMount={handleEditorMount}
              loading={
                <p className="p-6 text-sm text-slate-300">Loading code editor…</p>
              }
              options={{
                automaticLayout: true,
                fontSize: 14,
                lineNumbers: "on",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                tabSize: 4,
                wordWrap: "off",
              }}
              theme="vs-dark"
            />
          </section>

          <aside className="min-h-72 border-t border-slate-200 bg-white lg:border-l lg:border-t-0">
            <div role="tablist" aria-label="Editor results" className="flex border-b border-slate-200">
              {(["compiler", "tests"] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  aria-controls={`${tab}-panel`}
                  id={`${tab}-tab`}
                  onClick={() => setActiveTab(tab)}
                  className={`flex-1 border-b-2 px-4 py-3 text-sm font-semibold capitalize focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-slate-900 ${
                    activeTab === tab
                      ? "border-slate-900 text-slate-950"
                      : "border-transparent text-slate-500 hover:text-slate-800"
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div
              id={`${activeTab}-panel`}
              role="tabpanel"
              aria-labelledby={`${activeTab}-tab`}
              className="p-4"
            >
              {activeTab === "compiler" &&
                (isCompiling ? (
                  <p className="text-sm leading-6 text-slate-600" aria-live="polite">
                    Compiling current editor contents...
                  </p>
                ) : compileError ? (
                  <div role="alert" className="border-l-2 border-rose-300 pl-3">
                    <p className="text-sm font-medium text-slate-800">
                      Compiler unavailable
                    </p>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      {compileError}
                    </p>
                  </div>
                ) : compileResult ? (
                  compileResult.success ? (
                    <div role="status">
                      <p className="flex items-center gap-2 text-sm font-medium text-slate-800">
                        <span
                          aria-hidden="true"
                          className="h-2 w-2 rounded-full bg-emerald-500"
                        />
                        Compilation successful
                      </p>
                      <p className="mt-2 text-xs text-slate-500">
                        Compiler exit code: {compileResult.exit_code}
                      </p>
                    </div>
                  ) : (
                    <div role="status">
                      {primaryDiagnostics.length > 0 ? (
                        <>
                          <div className="flex items-center gap-2">
                            <h3 className="text-sm font-medium text-slate-800">
                              Compilation Issues
                            </h3>
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium tabular-nums text-slate-600">
                              {primaryDiagnostics.length}
                            </span>
                          </div>
                          <ul className="mt-2 divide-y divide-slate-200 border-y border-slate-200">
                            {primaryDiagnostics.map((diagnostic, index) => (
                              <li
                                key={`${diagnostic.line}-${diagnostic.column}-${index}`}
                                className="py-2 first:pt-0 last:pb-0"
                              >
                                <button
                                  type="button"
                                  onClick={() => focusDiagnostic(diagnostic)}
                                  className="w-full cursor-pointer rounded-md border border-rose-100 bg-white px-2 py-2.5 text-left transition-colors hover:border-rose-200 hover:bg-slate-50 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                                  aria-label={`Go to ${diagnostic.severity} on line ${diagnostic.line}, column ${diagnostic.column}: ${diagnostic.message}`}
                                >
                                  <span className="flex items-center justify-between gap-3">
                                    <span className="text-xs font-medium text-slate-700">
                                      {getIssueCategory(diagnostic)}
                                    </span>
                                    <span className="shrink-0 text-xs tabular-nums text-slate-500">
                                      Line {diagnostic.line}
                                    </span>
                                  </span>
                                  <span className="mt-1.5 block break-words font-mono text-xs leading-5 text-slate-800">
                                    {diagnostic.message}
                                  </span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        </>
                      ) : (
                        <p className="text-sm font-medium text-slate-700">
                          Compiler output needs review
                        </p>
                      )}
                      {(compileResult.stderr || compileResult.stdout) ? (
                        <details className="mt-3">
                          <summary className="cursor-pointer text-xs font-semibold text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                            Show raw compiler output
                          </summary>
                          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100">
                            {compileResult.stderr || compileResult.stdout}
                          </pre>
                        </details>
                      ) : (
                        <p className="mt-3 text-sm text-slate-600">
                          The compiler returned no diagnostic output.
                        </p>
                      )}
                      <p className="mt-2 text-xs text-slate-500">
                        Compiler exit code: {compileResult.exit_code}
                      </p>
                    </div>
                  )
                ) : (
                  <p className="text-sm leading-6 text-slate-600">
                    Compile your code to view compiler errors.
                  </p>
                ))}

              {activeTab === "tests" &&
                (hasRunTests ? (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Mock test results
                    </p>
                    <ul className="mt-3 divide-y divide-slate-100">
                      {MOCK_TESTS.map((test) => (
                        <li key={test.name} className="flex items-center justify-between py-3 text-sm">
                          <span className="font-medium text-slate-800">{test.name}</span>
                          <span
                            className={
                              test.result === "Passed" ? "text-emerald-700" : "text-red-700"
                            }
                          >
                            {test.result}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="text-sm leading-6 text-slate-600">
                    Run tests when you are ready to check your solution.
                  </p>
                ))}
            </div>
          </aside>
        </div>

        <footer className="border-t border-slate-200 px-4 py-3 sm:px-5">
          <button
            type="button"
            onClick={() => router.push("/review")}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Back to Review
          </button>
        </footer>
      </div>
    </main>
  );
}
