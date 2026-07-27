export type CompileDiagnostic = {
  line: number;
  column: number;
  severity: "error" | "warning" | "note";
  message: string;
  explanation: string | null;
};

export type CompileResult = {
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
  diagnostics: CompileDiagnostic[];
};

export type FixSuggestion = {
  diagnostic_index: number;
  source: "compiler";
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
  original_text: string;
  replacement_text: string;
  explanation: string;
};

export type CompilerSuggestionResult = {
  suggestions: FixSuggestion[];
};

type ApiError = { error?: { message?: string } };

export class CompileRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CompileRequestError";
  }
}

function isCompileResult(value: unknown): value is CompileResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<CompileResult>;
  const hasValidDiagnostics =
    Array.isArray(result.diagnostics) &&
    result.diagnostics.every(
      (diagnostic) =>
        diagnostic !== null &&
        typeof diagnostic === "object" &&
        typeof diagnostic.line === "number" &&
        typeof diagnostic.column === "number" &&
        ["error", "warning", "note"].includes(diagnostic.severity) &&
        typeof diagnostic.message === "string" &&
        (diagnostic.explanation === null ||
          typeof diagnostic.explanation === "string"),
    );
  return (
    typeof result.success === "boolean" &&
    typeof result.stdout === "string" &&
    typeof result.stderr === "string" &&
    typeof result.exit_code === "number" &&
    hasValidDiagnostics
  );
}

function isFixSuggestion(value: unknown): value is FixSuggestion {
  if (!value || typeof value !== "object") return false;
  const suggestion = value as Partial<FixSuggestion>;
  return (
    Number.isInteger(suggestion.diagnostic_index) &&
    suggestion.source === "compiler" &&
    Number.isInteger(suggestion.start_line) &&
    Number.isInteger(suggestion.start_column) &&
    Number.isInteger(suggestion.end_line) &&
    Number.isInteger(suggestion.end_column) &&
    typeof suggestion.original_text === "string" &&
    typeof suggestion.replacement_text === "string" &&
    typeof suggestion.explanation === "string"
  );
}

function isCompilerSuggestionResult(
  value: unknown,
): value is CompilerSuggestionResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<CompilerSuggestionResult>;
  return (
    Array.isArray(result.suggestions) &&
    result.suggestions.every(isFixSuggestion)
  );
}

function apiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export async function compileCpp(code: string): Promise<CompileResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/compile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, language: "cpp" }),
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new CompileRequestError(
        apiError?.error?.message ?? "The backend could not compile the code.",
      );
    }
    if (!isCompileResult(body)) {
      throw new CompileRequestError(
        "The backend returned an invalid compilation result.",
      );
    }
    return body;
  } catch (error) {
    if (error instanceof CompileRequestError) throw error;
    throw new CompileRequestError(
      "The compiler backend is unavailable. Check the backend and retry.",
    );
  }
}

export async function requestCompilerSuggestions(
  code: string,
  diagnostics: CompileDiagnostic[],
): Promise<CompilerSuggestionResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/compiler-suggestions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, language: "cpp", diagnostics }),
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new CompileRequestError(
        apiError?.error?.message ??
          "The backend could not provide fix suggestions.",
      );
    }
    if (!isCompilerSuggestionResult(body)) {
      throw new CompileRequestError(
        "The backend returned invalid fix suggestions.",
      );
    }
    return body;
  } catch (error) {
    if (error instanceof CompileRequestError) throw error;
    throw new CompileRequestError(
      "Fix suggestions are unavailable. Compiler issues remain available.",
    );
  }
}
