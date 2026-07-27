export type ExplicitTestCase = {
  name: string;
  stdin: string;
  expected_stdout: string;
};

export type TestCaseResult = {
  name: string;
  passed: boolean;
  expected_stdout: string;
  actual_stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  output_limited: boolean;
  match_type: "exact" | "whitespace_normalized" | "mismatch";
};

export type RunTestsResult = {
  success: boolean;
  compile_error: string | null;
  tests: TestCaseResult[];
};

type ApiError = { error?: { message?: string } };

export class RunTestsRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunTestsRequestError";
  }
}

function isTestCaseResult(value: unknown): value is TestCaseResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<TestCaseResult>;
  return (
    typeof result.name === "string" &&
    typeof result.passed === "boolean" &&
    typeof result.expected_stdout === "string" &&
    typeof result.actual_stdout === "string" &&
    typeof result.stderr === "string" &&
    (result.exit_code === null || typeof result.exit_code === "number") &&
    typeof result.timed_out === "boolean" &&
    typeof result.output_limited === "boolean" &&
    ["exact", "whitespace_normalized", "mismatch"].includes(
      result.match_type ?? "",
    )
  );
}

function isRunTestsResult(value: unknown): value is RunTestsResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<RunTestsResult>;
  return (
    typeof result.success === "boolean" &&
    (result.compile_error === null ||
      typeof result.compile_error === "string") &&
    Array.isArray(result.tests) &&
    result.tests.every(isTestCaseResult)
  );
}

function apiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export async function runCppTests(
  code: string,
  tests: ExplicitTestCase[],
): Promise<RunTestsResult> {
  try {
    const response = await fetch(`${apiBaseUrl()}/api/run-tests`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, language: "cpp", tests }),
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new RunTestsRequestError(
        apiError?.error?.message ?? "The backend could not run the tests.",
      );
    }
    if (!isRunTestsResult(body)) {
      throw new RunTestsRequestError(
        "The backend returned an invalid test result.",
      );
    }
    return body;
  } catch (error) {
    if (error instanceof RunTestsRequestError) throw error;
    throw new RunTestsRequestError(
      "The test runner is unavailable. Check the backend and retry.",
    );
  }
}
