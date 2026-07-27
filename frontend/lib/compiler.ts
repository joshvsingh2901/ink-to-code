export type CompileResult = {
  success: boolean;
  stdout: string;
  stderr: string;
  exit_code: number;
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
  return (
    typeof result.success === "boolean" &&
    typeof result.stdout === "string" &&
    typeof result.stderr === "string" &&
    typeof result.exit_code === "number"
  );
}

export async function compileCpp(code: string): Promise<CompileResult> {
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${apiBaseUrl}/api/compile`, {
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
