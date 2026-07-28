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
import {
  analyzeTestMode,
  runCppTests,
  type FunctionOutputTestResult,
  type FunctionTestResult,
  type ProgramTestResult,
  type RunTestsResult,
  type TestModeAnalysis,
} from "@/lib/testExecution";

type SidebarTab = "compiler" | "tests";
type PrimaryDiagnostic = CompileDiagnostic & {
  severity: "error" | "warning";
};
type EditorInstance = Parameters<OnMount>[0];
type DecorationsCollection = ReturnType<
  EditorInstance["createDecorationsCollection"]
>;
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
type EditableTestCase = {
  id: string;
  name: string;
  stdin: string;
  expected_stdout: string;
  arguments: string[];
  expected_return: string;
};

const COMPILER_MARKER_OWNER = "inktocode-compiler";
const AUTO_COMPILE_DEBOUNCE_MS = 900;
const ISSUE_HIGHLIGHT_DURATION_MS = 1500;

const MAX_TEST_CASES = 10;
const INITIAL_TEST_CASE: EditableTestCase = {
  id: "test-1",
  name: "Test 1",
  stdin: "",
  expected_stdout: "",
  arguments: [],
  expected_return: "",
};

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

function isFunctionResult(
  result:
    | ProgramTestResult
    | FunctionTestResult
    | FunctionOutputTestResult,
): result is FunctionTestResult | FunctionOutputTestResult {
  return "arguments" in result;
}

function isFunctionReturnResult(
  result: FunctionTestResult | FunctionOutputTestResult,
): result is FunctionTestResult {
  return "expected_return" in result;
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
  const [isChecking, setIsChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [testCases, setTestCases] = useState<EditableTestCase[]>([
    INITIAL_TEST_CASE,
  ]);
  const [testRunResult, setTestRunResult] = useState<RunTestsResult | null>(
    null,
  );
  const [testRunError, setTestRunError] = useState<string | null>(null);
  const [isRunningTests, setIsRunningTests] = useState(false);
  const [comparisonMode, setComparisonMode] = useState<
    "whitespace_tolerant" | "exact"
  >("whitespace_tolerant");
  const [testMode, setTestMode] = useState<TestModeAnalysis | null>(null);
  const [selectedFunctionId, setSelectedFunctionId] = useState<string | null>(
    null,
  );
  const [testModeError, setTestModeError] = useState<string | null>(null);
  const [isAnalyzingTests, setIsAnalyzingTests] = useState(true);
  const [isEdited, setIsEdited] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const initialCodeRef = useRef(reviewedCode ?? "");
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null);
  const currentSourceRef = useRef(reviewedCode ?? "");
  const codeVersionRef = useRef(0);
  const nextTestIdRef = useRef(2);
  const selectedFunctionIdRef = useRef<string | null>(null);
  const latestCompileRequestRef = useRef(0);
  const isCompileInFlightRef = useRef(false);
  const hasCompletedCompileRef = useRef(false);
  const autoCompileTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const issueHighlightRef = useRef<DecorationsCollection | null>(null);
  const issueHighlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const isMountedRef = useRef(true);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (reviewedCode === null) {
      router.replace("/");
    }
  }, [reviewedCode, router]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      if (autoCompileTimerRef.current) {
        clearTimeout(autoCompileTimerRef.current);
      }
      if (issueHighlightTimerRef.current) {
        clearTimeout(issueHighlightTimerRef.current);
      }
      issueHighlightRef.current?.clear();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setIsAnalyzingTests(true);
      setTestModeError(null);
      void analyzeTestMode(code, controller.signal)
        .then((analysis) => {
          if (controller.signal.aborted) return;
          setTestMode(analysis);
          if (analysis.mode === "function") {
            const previousId = selectedFunctionIdRef.current;
            const nextId =
              analysis.functions.length === 1
                ? analysis.functions[0].id
                : analysis.functions.some(
                      (candidate) => candidate.id === previousId,
                    )
                  ? previousId
                  : null;
            const nextFunction =
              analysis.functions.find(
                (candidate) => candidate.id === nextId,
              ) ?? null;
            selectedFunctionIdRef.current = nextId;
            setSelectedFunctionId(nextId);
            setTestCases((current) =>
              current.map((test) => ({
                ...test,
                arguments: nextFunction
                  ? nextFunction.parameters.map(
                      (_, index) =>
                        nextId === previousId
                          ? (test.arguments[index] ?? "")
                          : "",
                    )
                  : [],
                expected_return:
                  nextId === previousId ? test.expected_return : "",
                expected_stdout:
                  nextId === previousId ? test.expected_stdout : "",
              })),
            );
          } else {
            selectedFunctionIdRef.current = null;
            setSelectedFunctionId(null);
          }
        })
        .catch((error) => {
          if (controller.signal.aborted) return;
          setTestMode(null);
          setTestModeError(
            error instanceof Error
              ? error.message
              : "The test mode could not be determined.",
          );
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setIsAnalyzingTests(false);
          }
        });
    }, 400);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [code]);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    issueHighlightRef.current = editor.createDecorationsCollection();
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

    if (issueHighlightTimerRef.current) {
      clearTimeout(issueHighlightTimerRef.current);
    }
    issueHighlightRef.current?.set([
      {
        range: {
          startLineNumber: location.line,
          startColumn: 1,
          endLineNumber: location.line,
          endColumn: 1,
        },
        options: {
          isWholeLine: true,
          className: "compiler-issue-line-highlight",
        },
      },
    ]);
    issueHighlightTimerRef.current = setTimeout(() => {
      issueHighlightRef.current?.clear();
      issueHighlightTimerRef.current = null;
    }, ISSUE_HIGHLIGHT_DURATION_MS);
  }

  function cancelPendingAutoCompile() {
    if (autoCompileTimerRef.current) {
      clearTimeout(autoCompileTimerRef.current);
      autoCompileTimerRef.current = null;
    }
  }

  async function runCompile(sourceOverride?: string) {
    const requestId = latestCompileRequestRef.current + 1;
    latestCompileRequestRef.current = requestId;
    clearCompilerMarkers();
    setActiveTab("compiler");
    setCompileError(null);
    setCheckError(null);
    if (hasCompletedCompileRef.current) {
      setIsChecking(true);
    }
    setIsCompiling(true);
    isCompileInFlightRef.current = true;
    const submittedVersion = codeVersionRef.current;

    try {
      const currentCode =
        sourceOverride ?? editorRef.current?.getValue() ?? code;
      const result = await compileCpp(currentCode);
      if (
        !isMountedRef.current ||
        requestId !== latestCompileRequestRef.current ||
        submittedVersion !== codeVersionRef.current
      ) {
        return;
      }

      hasCompletedCompileRef.current = true;
      setCompileResult(result);
      setIsChecking(false);
      setCheckError(null);
      applyCompilerMarkers(result.diagnostics);
    } catch (error) {
      if (
        !isMountedRef.current ||
        requestId !== latestCompileRequestRef.current ||
        submittedVersion !== codeVersionRef.current
      ) {
        return;
      }
      const message =
        error instanceof Error
          ? error.message
          : "The compiler backend could not complete the request.";
      if (hasCompletedCompileRef.current) {
        setCheckError(message);
        setIsChecking(false);
      } else {
        setCompileError(message);
      }
    } finally {
      if (
        isMountedRef.current &&
        requestId === latestCompileRequestRef.current
      ) {
        isCompileInFlightRef.current = false;
        setIsCompiling(false);
      }
    }
  }

  function handleCompile() {
    cancelPendingAutoCompile();
    void runCompile();
  }

  async function handleRunTests() {
    if (
      isRunningTests ||
      !testMode ||
      testMode.mode === "unsupported"
    ) {
      setActiveTab("tests");
      return;
    }
    const selectedFunction =
      testMode.mode === "function"
        ? (testMode.functions.find(
            (candidate) => candidate.id === selectedFunctionIdRef.current,
          ) ?? null)
        : null;
    if (testMode.mode === "function" && !selectedFunction) {
      setActiveTab("tests");
      return;
    }
    setActiveTab("tests");
    setIsRunningTests(true);
    setTestRunError(null);
    setTestRunResult(null);

    try {
      const currentCode = editorRef.current?.getValue() ?? code;
      const request =
        testMode.mode === "function"
          ? {
              mode: "function" as const,
              code: currentCode,
              language: "cpp" as const,
              target_function: selectedFunction!.id,
              comparison_mode: comparisonMode,
              tests:
                selectedFunction!.return_type_metadata.kind === "void"
                  ? testCases.map(
                      ({
                        name,
                        arguments: argumentValues,
                        expected_stdout,
                      }) => ({
                        name,
                        arguments: argumentValues,
                        expected_stdout,
                      }),
                    )
                  : testCases.map(
                      ({
                        name,
                        arguments: argumentValues,
                        expected_return,
                      }) => ({
                        name,
                        arguments: argumentValues,
                        expected_return,
                      }),
                    ),
            }
          : {
              mode: "program" as const,
              code: currentCode,
              language: "cpp" as const,
              comparison_mode: comparisonMode,
              tests: testCases.map(({ name, stdin, expected_stdout }) => ({
                name,
                stdin,
                expected_stdout,
              })),
            };
      const result = await runCppTests(request);
      if (!isMountedRef.current) return;
      setTestRunResult(result);
    } catch (error) {
      if (!isMountedRef.current) return;
      setTestRunError(
        error instanceof Error
          ? error.message
          : "The backend could not run the tests.",
      );
    } finally {
      if (isMountedRef.current) {
        setIsRunningTests(false);
      }
    }
  }

  function updateTestCase(
    id: string,
    field:
      | "name"
      | "stdin"
      | "expected_stdout"
      | "expected_return",
    value: string,
  ) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id ? { ...test, [field]: value } : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateTestArgument(id: string, index: number, value: string) {
    setTestCases((current) =>
      current.map((test) =>
        test.id === id
          ? {
              ...test,
              arguments: test.arguments.map((argument, argumentIndex) =>
                argumentIndex === index ? value : argument,
              ),
            }
          : test,
      ),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function addTestCase() {
    if (testCases.length >= MAX_TEST_CASES) return;
    const sequence = nextTestIdRef.current;
    nextTestIdRef.current += 1;
    setTestCases((current) => [
      ...current,
      {
        id: `test-${sequence}`,
        name: `Test ${sequence}`,
        stdin: "",
        expected_stdout: "",
        arguments:
          testMode?.mode === "function" && selectedFunction
            ? selectedFunction.parameters.map(() => "")
            : [],
        expected_return: "",
      },
    ]);
    setTestRunResult(null);
    setTestRunError(null);
  }

  function selectFunction(functionId: string) {
    const nextId = functionId || null;
    const nextFunction =
      testMode?.mode === "function"
        ? (testMode.functions.find(
            (candidate) => candidate.id === nextId,
          ) ?? null)
        : null;
    selectedFunctionIdRef.current = nextId;
    setSelectedFunctionId(nextId);
    setTestCases((current) =>
      current.map((test) => ({
        ...test,
        arguments: nextFunction
          ? nextFunction.parameters.map(() => "")
          : [],
        expected_return: "",
        expected_stdout: "",
      })),
    );
    setTestRunResult(null);
    setTestRunError(null);
  }

  function removeTestCase(id: string) {
    setTestCases((current) => current.filter((test) => test.id !== id));
    setTestRunResult(null);
    setTestRunError(null);
  }

  function updateComparisonMode(
    mode: "whitespace_tolerant" | "exact",
  ) {
    setComparisonMode(mode);
    setTestRunResult(null);
    setTestRunError(null);
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
  const selectedFunction =
    testMode?.mode === "function"
      ? (testMode.functions.find(
          (candidate) => candidate.id === selectedFunctionId,
        ) ?? null)
      : null;
  const isCleanCompileSuccess =
    compileResult?.success === true &&
    compileResult.exit_code === 0 &&
    compileResult.diagnostics.length === 0;
  const hasUnstructuredCompilerOutput =
    Boolean(compileResult) &&
    !isCleanCompileSuccess &&
    primaryDiagnostics.length === 0 &&
    Boolean(compileResult?.stderr.trim() || compileResult?.stdout.trim());

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
                onClick={() => void handleRunTests()}
                disabled={
                  isRunningTests ||
                  isAnalyzingTests ||
                  !testMode ||
                  testCases.length === 0 ||
                  testMode?.mode === "unsupported" ||
                  (testMode?.mode === "function" && !selectedFunction)
                }
                className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isRunningTests ? "Running Tests..." : "Run Tests"}
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
                if (nextCode === currentSourceRef.current) return;
                currentSourceRef.current = nextCode;
                codeVersionRef.current += 1;
                cancelPendingAutoCompile();
                clearCompilerMarkers();
                if (issueHighlightTimerRef.current) {
                  clearTimeout(issueHighlightTimerRef.current);
                  issueHighlightTimerRef.current = null;
                }
                issueHighlightRef.current?.clear();
                setTestRunResult(null);
                setTestRunError(null);
                setIsAnalyzingTests(true);
                setTestModeError(null);
                if (
                  hasCompletedCompileRef.current ||
                  isCompileInFlightRef.current
                ) {
                  if (hasCompletedCompileRef.current) {
                    setIsChecking(true);
                  }
                  setCheckError(null);
                  autoCompileTimerRef.current = setTimeout(() => {
                    autoCompileTimerRef.current = null;
                    void runCompile(nextCode);
                  }, AUTO_COMPILE_DEBOUNCE_MS);
                } else {
                  setCompileError(null);
                }
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
                (isCompiling && !compileResult ? (
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
                  isCleanCompileSuccess ? (
                    isChecking ? (
                      <div role="status" aria-live="polite">
                        <p className="text-sm font-medium text-slate-700">
                          Checking…
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          Running the C++17 compiler check.
                        </p>
                      </div>
                    ) : checkError ? (
                      <div
                        role="alert"
                        className="border-l-2 border-rose-300 pl-3"
                      >
                        <p className="text-sm font-medium text-slate-800">
                          Latest check unavailable
                        </p>
                        <p className="mt-2 text-sm leading-6 text-slate-600">
                          {checkError}
                        </p>
                      </div>
                    ) : (
                      <div role="status">
                        <p className="flex items-center gap-2 text-sm font-medium text-slate-800">
                          <span
                            aria-hidden="true"
                            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-emerald-200 text-emerald-700"
                          >
                            <svg
                              viewBox="0 0 20 20"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              className="h-3.5 w-3.5"
                            >
                              <path
                                d="m5 10 3 3 7-7"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            </svg>
                          </span>
                          Compilation successful
                        </p>
                        <p className="mt-3 text-sm text-slate-700">
                          No compiler issues found.
                        </p>
                        <p className="mt-1 text-xs leading-5 text-slate-500">
                          Your code passed the C++17 compiler check.
                        </p>
                      </div>
                    )
                  ) : (
                    <div role="status">
                      {primaryDiagnostics.length > 0 ? (
                        <>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <h3 className="text-sm font-medium text-slate-800">
                                Compilation Issues
                              </h3>
                              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium tabular-nums text-slate-600">
                                {primaryDiagnostics.length}
                              </span>
                            </div>
                            {isChecking && (
                              <span
                                aria-live="polite"
                                className="text-xs text-slate-500"
                              >
                                Checking…
                              </span>
                            )}
                          </div>
                          <ul
                            className={`mt-2 divide-y divide-slate-200 border-y border-slate-200 transition-opacity ${
                              isChecking ? "opacity-70" : ""
                            }`}
                          >
                            {primaryDiagnostics.map((diagnostic, index) => {
                              return (
                                <li
                                  key={`${diagnostic.line}-${diagnostic.column}-${index}`}
                                  className="py-2 first:pt-0 last:pb-0"
                                >
                                  <div className="rounded-md border border-rose-100 bg-white">
                                    <button
                                      type="button"
                                      onClick={() => focusDiagnostic(diagnostic)}
                                      className="w-full cursor-pointer rounded-md px-2 py-2.5 text-left transition-colors hover:bg-slate-50 focus-visible:relative focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
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
                                      {diagnostic.explanation && (
                                        <span className="mt-2 block text-xs leading-5 text-slate-500">
                                          <span className="sr-only">
                                            Explanation:{" "}
                                          </span>
                                          {diagnostic.explanation}
                                        </span>
                                      )}
                                    </button>
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                          {checkError && (
                            <p
                              role="status"
                              className="mt-2 text-xs leading-5 text-slate-600"
                            >
                              Latest check failed: {checkError}
                            </p>
                          )}
                        </>
                      ) : hasUnstructuredCompilerOutput ? (
                        <p className="text-sm font-medium text-slate-700">
                          Compiler output needs review
                        </p>
                      ) : (
                        <p className="text-sm font-medium text-slate-700">
                          Compilation did not complete successfully.
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

              {activeTab === "tests" && (
                <div>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-medium text-slate-800">
                        {testMode?.mode === "function"
                          ? "Function Tests"
                          : "Program Tests"}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500">
                        {isAnalyzingTests
                          ? "Determining test mode…"
                          : testMode?.mode === "function" && selectedFunction
                            ? `Function: ${selectedFunction.display}`
                            : testMode?.mode === "function"
                              ? "Choose a function to test."
                            : testMode?.mode === "program"
                              ? "Use standard input and expected output."
                              : "Function testing is unavailable."}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={addTestCase}
                      disabled={
                        isRunningTests ||
                        isAnalyzingTests ||
                        testMode?.mode === "unsupported" ||
                        (testMode?.mode === "function" && !selectedFunction) ||
                        testCases.length >= MAX_TEST_CASES
                      }
                      className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Add Test
                    </button>
                  </div>

                  {testModeError && (
                    <div
                      role="alert"
                      className="mt-3 border-l-2 border-rose-300 pl-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Test mode unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testModeError}
                      </p>
                    </div>
                  )}
                  {testMode?.mode === "unsupported" && (
                    <div
                      role="status"
                      className="mt-3 rounded-md border border-slate-200 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Function testing unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testMode.message}
                      </p>
                    </div>
                  )}

                  {(testMode?.mode === "program" ||
                    selectedFunction?.return_type_metadata.kind === "void") && (
                    <div className="mt-3">
                      <label
                        htmlFor="output-comparison-mode"
                        className="block text-xs font-medium text-slate-600"
                      >
                        Output comparison
                      </label>
                      <select
                        id="output-comparison-mode"
                        value={comparisonMode}
                        disabled={isRunningTests}
                        onChange={(event) =>
                          updateComparisonMode(
                            event.target.value as
                              | "whitespace_tolerant"
                              | "exact",
                          )
                        }
                        className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-700 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        <option value="whitespace_tolerant">
                          Ignore whitespace differences
                        </option>
                        <option value="exact">Exact match</option>
                      </select>
                    </div>
                  )}

                  {testMode?.mode === "function" &&
                    testMode.functions.length > 1 && (
                      <div className="mt-3">
                        <label
                          htmlFor="test-target-function"
                          className="block text-xs font-medium text-slate-600"
                        >
                          Function to test
                        </label>
                        <select
                          id="test-target-function"
                          value={selectedFunctionId ?? ""}
                          disabled={isRunningTests}
                          onChange={(event) =>
                            selectFunction(event.target.value)
                          }
                          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          <option value="">Choose a function</option>
                          {testMode.functions.map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>
                              {candidate.display} → {candidate.return_type}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}

                  {testMode && testMode.mode !== "unsupported" && (
                  <div className="mt-3 space-y-3">
                    {(testMode.mode === "program" || selectedFunction) &&
                      testCases.map((test, index) => (
                      <fieldset
                        key={test.id}
                        disabled={isRunningTests}
                        className="rounded-md border border-slate-200 p-3"
                      >
                        <legend className="sr-only">
                          Test case {index + 1}
                        </legend>
                        <div className="flex items-center gap-2">
                          <label
                            htmlFor={`${test.id}-name`}
                            className="sr-only"
                          >
                            Test name
                          </label>
                          <input
                            id={`${test.id}-name`}
                            value={test.name}
                            maxLength={100}
                            onChange={(event) =>
                              updateTestCase(
                                test.id,
                                "name",
                                event.target.value,
                              )
                            }
                            className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                          />
                          <button
                            type="button"
                            onClick={() => removeTestCase(test.id)}
                            className="rounded-md px-2 py-1.5 text-xs font-medium text-slate-500 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                            aria-label={`Remove ${test.name || `test ${index + 1}`}`}
                          >
                            Remove
                          </button>
                        </div>
                        {testMode.mode === "function" &&
                        selectedFunction ? (
                          <>
                            <p className="mt-3 text-xs font-medium text-slate-600">
                              Arguments
                            </p>
                            <div className="mt-1.5 space-y-2">
                              {selectedFunction.parameters.map(
                                (parameter, parameterIndex) => (
                                  <div
                                    key={`${test.id}-${parameter.name}`}
                                    className="min-w-0"
                                  >
                                    <label
                                      htmlFor={`${test.id}-argument-${parameterIndex}`}
                                      className="block min-w-0 text-xs font-medium text-slate-600"
                                    >
                                      <span className="block">
                                        {parameter.name}
                                      </span>
                                      <span className="mt-0.5 block break-words text-[11px] font-normal text-slate-400">
                                        {parameter.type}
                                      </span>
                                    </label>
                                    <div className="mt-1 min-w-0">
                                      <input
                                        id={`${test.id}-argument-${parameterIndex}`}
                                        value={
                                          test.arguments[parameterIndex] ?? ""
                                        }
                                        maxLength={1_000}
                                        placeholder={
                                          parameter.type_metadata.kind ===
                                            "vector" ||
                                          parameter.type_metadata.kind ===
                                            "array"
                                            ? parameter.type_metadata
                                                .element_type === "std::string"
                                              ? '["hello", "world"]'
                                              : "[1, 2, 3]"
                                            : undefined
                                        }
                                        onChange={(event) =>
                                          updateTestArgument(
                                            test.id,
                                            parameterIndex,
                                            event.target.value,
                                          )
                                        }
                                        className="w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                      />
                                      {(parameter.type_metadata.kind ===
                                        "vector" ||
                                        parameter.type_metadata.kind ===
                                          "array") && (
                                        <p className="mt-1 text-[11px] text-slate-500">
                                          {parameter.type_metadata
                                            .element_type === "std::string"
                                            ? 'Enter values like ["hello", "world"]'
                                            : "Enter values like [1, 2, 3]"}
                                        </p>
                                      )}
                                    </div>
                                  </div>
                                ),
                              )}
                              {selectedFunction.parameters.length === 0 && (
                                <p className="text-xs text-slate-500">
                                  This function takes no arguments.
                                </p>
                              )}
                            </div>
                            {selectedFunction.return_type_metadata.kind ===
                            "void" ? (
                              <>
                                <label
                                  htmlFor={`${test.id}-expected-output`}
                                  className="mt-3 block text-xs font-medium text-slate-600"
                                >
                                  Expected output
                                </label>
                                <textarea
                                  id={`${test.id}-expected-output`}
                                  value={test.expected_stdout}
                                  maxLength={64 * 1024}
                                  rows={3}
                                  onChange={(event) =>
                                    updateTestCase(
                                      test.id,
                                      "expected_stdout",
                                      event.target.value,
                                    )
                                  }
                                  className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                />
                              </>
                            ) : (
                              <>
                                <label
                                  htmlFor={`${test.id}-expected-return`}
                                  className="mt-3 block text-xs font-medium text-slate-600"
                                >
                                  Expected return —{" "}
                                  {
                                    selectedFunction.return_type_metadata
                                      .display_type
                                  }
                                </label>
                                <input
                                  id={`${test.id}-expected-return`}
                                  value={test.expected_return}
                                  placeholder={
                                    selectedFunction.return_type_metadata
                                      .kind === "vector"
                                      ? selectedFunction.return_type_metadata
                                          .element_type === "std::string"
                                        ? '["hello", "world"]'
                                        : "[1, 2, 3]"
                                      : undefined
                                  }
                                  maxLength={1_000}
                                  onChange={(event) =>
                                    updateTestCase(
                                      test.id,
                                      "expected_return",
                                      event.target.value,
                                    )
                                  }
                                  className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                />
                                {selectedFunction.return_type_metadata.kind ===
                                  "vector" && (
                                  <p className="mt-1 text-[11px] text-slate-500">
                                    {selectedFunction.return_type_metadata
                                      .element_type === "std::string"
                                      ? 'Enter values like ["hello", "world"]'
                                      : "Enter values like [1, 2, 3]"}
                                  </p>
                                )}
                              </>
                            )}
                          </>
                        ) : (
                          <>
                            <label
                              htmlFor={`${test.id}-stdin`}
                              className="mt-3 block text-xs font-medium text-slate-600"
                            >
                              Standard input
                            </label>
                            <textarea
                              id={`${test.id}-stdin`}
                              value={test.stdin}
                              maxLength={64 * 1024}
                              rows={3}
                              onChange={(event) =>
                                updateTestCase(
                                  test.id,
                                  "stdin",
                                  event.target.value,
                                )
                              }
                              className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                            />
                            <label
                              htmlFor={`${test.id}-expected`}
                              className="mt-3 block text-xs font-medium text-slate-600"
                            >
                              Expected output
                            </label>
                            <textarea
                              id={`${test.id}-expected`}
                              value={test.expected_stdout}
                              maxLength={64 * 1024}
                              rows={3}
                              onChange={(event) =>
                                updateTestCase(
                                  test.id,
                                  "expected_stdout",
                                  event.target.value,
                                )
                              }
                              className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                            />
                          </>
                        )}
                      </fieldset>
                    ))}
                  </div>
                  )}

                  {testCases.length === 0 && (
                    <p className="mt-3 text-sm leading-6 text-slate-600">
                      Add at least one test before running the program.
                    </p>
                  )}
                  {testCases.length >= MAX_TEST_CASES && (
                    <p className="mt-2 text-xs text-slate-500">
                      Maximum of {MAX_TEST_CASES} tests reached.
                    </p>
                  )}
                  {isRunningTests && (
                    <p
                      role="status"
                      aria-live="polite"
                      className="mt-4 text-sm text-slate-600"
                    >
                      Compiling and running tests…
                    </p>
                  )}
                  {testRunError && (
                    <div
                      role="alert"
                      className="mt-4 border-l-2 border-rose-300 pl-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Test runner unavailable
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testRunError}
                      </p>
                    </div>
                  )}
                  {testRunResult?.compile_error && (
                    <div
                      role="alert"
                      className="mt-4 rounded-md border border-rose-100 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        Tests could not run
                      </p>
                      <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-600">
                        {testRunResult.compile_error}
                      </pre>
                    </div>
                  )}
                  {(testRunResult?.input_error ||
                    testRunResult?.unsupported_error) && (
                    <div
                      role="alert"
                      className="mt-4 rounded-md border border-slate-200 p-3"
                    >
                      <p className="text-sm font-medium text-slate-800">
                        {testRunResult.unsupported_error
                          ? "Function testing unavailable"
                          : "Check test values"}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-slate-600">
                        {testRunResult.unsupported_error ||
                          testRunResult.input_error}
                      </p>
                    </div>
                  )}
                  {testRunResult && testRunResult.tests.length > 0 && (
                    <ul className="mt-4 space-y-3" aria-label="Test results">
                      {testRunResult.tests.map((result, index) => (
                        <li
                          key={`${result.name}-${index}`}
                          className={`rounded-md border p-3 ${
                            result.passed
                              ? "border-emerald-100"
                              : "border-rose-100"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-medium text-slate-800">
                              <span
                                className={
                                  result.passed
                                    ? "text-emerald-700"
                                    : "text-rose-700"
                                }
                              >
                                {result.passed ? "PASS" : "FAIL"}
                              </span>
                              {" — "}
                              {result.name}
                            </p>
                            {!result.timed_out &&
                              result.exit_code !== null && (
                                <span className="text-xs tabular-nums text-slate-500">
                                  Exit {result.exit_code}
                                </span>
                              )}
                          </div>
                          {isFunctionResult(result) && (
                            <div className="mt-3 grid gap-3">
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Arguments
                                </p>
                                <dl className="mt-1 space-y-1 font-mono text-xs text-slate-700">
                                  {testRunResult.function?.parameters.map(
                                    (parameter, parameterIndex) => (
                                      <div
                                        key={`${result.name}-${parameter.name}`}
                                        className="flex gap-2"
                                      >
                                        <dt>{parameter.name} =</dt>
                                        <dd className="break-all">
                                          {result.arguments[parameterIndex]}
                                        </dd>
                                      </div>
                                    ),
                                  )}
                                  {result.arguments.length === 0 && (
                                    <div>No arguments</div>
                                  )}
                                </dl>
                              </div>
                              <div className="grid grid-cols-2 gap-2">
                                <div>
                                  <p className="text-xs font-medium text-slate-500">
                                    {isFunctionReturnResult(result)
                                      ? "Expected return"
                                      : "Expected output"}
                                  </p>
                                  <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                    {(isFunctionReturnResult(result)
                                      ? result.expected_return
                                      : result.expected_stdout) || "(empty)"}
                                  </pre>
                                </div>
                                <div>
                                  <p className="text-xs font-medium text-slate-500">
                                    {isFunctionReturnResult(result)
                                      ? "Actual return"
                                      : "Actual output"}
                                  </p>
                                  <pre className="mt-1 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                    {(isFunctionReturnResult(result)
                                      ? result.actual_return
                                      : result.actual_stdout) || "(empty)"}
                                  </pre>
                                </div>
                              </div>
                            </div>
                          )}
                          {result.timed_out ? (
                            <p className="mt-2 text-xs font-medium text-rose-700">
                              Timed out
                            </p>
                          ) : result.output_limited ? (
                            <p className="mt-2 text-xs font-medium text-rose-700">
                              Output limit exceeded
                            </p>
                          ) : result.match_type ===
                            "whitespace_normalized" ? (
                            <p className="mt-2 text-xs text-slate-500">
                              Formatting differences ignored
                            </p>
                          ) : result.match_type === "formatting_mismatch" ? (
                            <p className="mt-2 text-xs text-slate-600">
                              Output values match, but formatting differs.
                            </p>
                          ) : null}
                          {!result.timed_out &&
                            !result.output_limited &&
                            !result.passed &&
                            !isFunctionResult(result) && (
                            <div className="mt-3 grid gap-3">
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Expected
                                </p>
                                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                  {result.expected_stdout || "(empty)"}
                                </pre>
                              </div>
                              <div>
                                <p className="text-xs font-medium text-slate-500">
                                  Actual
                                </p>
                                <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 font-mono text-xs leading-5 text-slate-800">
                                  {result.actual_stdout || "(empty)"}
                                </pre>
                              </div>
                            </div>
                          )}
                          {result.stderr && (
                            <details className="mt-3">
                              <summary className="cursor-pointer text-xs font-medium text-slate-600 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900">
                                Show runtime stderr
                              </summary>
                              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 p-2 font-mono text-xs leading-5 text-slate-100">
                                {result.stderr}
                              </pre>
                            </details>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
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
