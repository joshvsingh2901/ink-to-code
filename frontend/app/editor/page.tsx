"use client";

import Editor, { type OnMount } from "@monaco-editor/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";

type SidebarTab = "compiler" | "tests";

type MockCompilerError = {
  line: number;
  column: number;
  title: string;
  explanation: string;
  message: string;
};

const MOCK_COMPILER_ERRORS: MockCompilerError[] = [
  {
    line: 6,
    column: 10,
    title: "Missing semicolon",
    explanation: "The declaration needs a semicolon before the next statement.",
    message: "error: expected ';' after declaration",
  },
  {
    line: 8,
    column: 5,
    title: "Undeclared identifier: count",
    explanation: "The name 'count' is not declared in this scope.",
    message: "error: use of undeclared identifier 'count'",
  },
];

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

export default function EditorPage() {
  const router = useRouter();
  const { reviewedCode, setReviewedCode } = useUploads();
  const [code, setCode] = useState(reviewedCode ?? "");
  const [filename, setFilename] = useState("solution.cpp");
  const [activeTab, setActiveTab] = useState<SidebarTab>("compiler");
  const [hasCompiled, setHasCompiled] = useState(false);
  const [hasRunTests, setHasRunTests] = useState(false);
  const [isEdited, setIsEdited] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const initialCodeRef = useRef(reviewedCode ?? "");
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
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

  function applyMockMarkers() {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    const model = editor?.getModel();
    if (!model || !monaco) return;

    monaco.editor.setModelMarkers(model, "inktocode-mock-compiler", []);
    monaco.editor.setModelMarkers(
      model,
      "inktocode-mock-compiler",
      MOCK_COMPILER_ERRORS.map((error) => ({
        startLineNumber: error.line,
        startColumn: error.column,
        endLineNumber: error.line,
        endColumn: error.column + 1,
        severity: monaco.MarkerSeverity.Error,
        message: error.message,
      })),
    );
  }

  function handleCompile() {
    setActiveTab("compiler");
    setHasCompiled(true);
    applyMockMarkers();
  }

  function focusCompilerError(error: MockCompilerError) {
    const editor = editorRef.current;
    if (!editor) return;

    editor.revealLineInCenter(error.line);
    editor.setPosition({ lineNumber: error.line, column: error.column });
    editor.focus();
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
                className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Compile
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
                (hasCompiled ? (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      Mock compiler result
                    </p>
                    <div className="mt-3 space-y-3">
                      {MOCK_COMPILER_ERRORS.map((error) => (
                        <button
                          key={`${error.line}-${error.title}`}
                          type="button"
                          onClick={() => focusCompilerError(error)}
                          className="w-full rounded-lg border border-slate-200 p-3 text-left hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                        >
                          <span className="text-xs font-semibold text-slate-500">
                            Line {error.line}
                          </span>
                          <span className="mt-1 block text-sm font-semibold text-slate-900">
                            {error.title}
                          </span>
                          <span className="mt-1 block text-sm text-slate-600">
                            {error.explanation}
                          </span>
                          <code className="mt-2 block break-words text-xs text-red-700">
                            {error.message}
                          </code>
                        </button>
                      ))}
                    </div>
                  </div>
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
