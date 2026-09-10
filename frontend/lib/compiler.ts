import { apiErrorMessage } from "./apiErrors";

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
      throw new CompileRequestError(
        apiErrorMessage(
          response.status,
          body,
          "The backend could not compile the code.",
          "compiler",
          response.headers.get("X-Request-ID"),
        ),
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
