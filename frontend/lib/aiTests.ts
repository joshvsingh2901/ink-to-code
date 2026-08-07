/**
 * API helpers for the AI test generation endpoints.
 * Wire-type mirrors of the backend schemas (ai_tests.py).
 */

// ---------------------------------------------------------------------------
// Wire types (mirrors of backend schemas)
// ---------------------------------------------------------------------------

export type AiScore = {
  passed: number;
  executed: number;
  percentage: number;
};

export type AiTestResultRow = {
  id: string;
  name: string;
  category: string;
  reason: string;
  passed: boolean;
  input_summary: string;
  expected_summary: string;
  actual_summary: string;
  detail: unknown | null;
};

export type AiStoredTest = {
  id: string;
  name: string;
  category: string;
  reason: string;
  function_test?: unknown;
  scenario_test?: unknown;
};

export type TemplateArgumentInput = {
  parameter_name: string;
  kind: "type" | "non_type";
  value: string;
};

export type AiTestRunRequest = {
  code: string;
  language: "cpp";
  question_text: string;
  target_kind: "function" | "object";
  target_id: string;
  template_argument_mode?: "deduced" | "explicit" | null;
  template_arguments?: TemplateArgumentInput[];
};

export type AiTestRerunRequest = {
  code: string;
  language: "cpp";
  target_kind: "function" | "object";
  target_id: string;
  template_argument_mode?: "deduced" | "explicit" | null;
  template_arguments?: TemplateArgumentInput[];
  tests: AiStoredTest[];
};

export type AiTestRunResponseStatus =
  | "completed"
  | "missing_question"
  | "compile_failed"
  | "unsupported"
  | "source_too_large"
  | "generation_timeout"
  | "generation_rate_limited"
  | "generation_unavailable"
  | "generation_failed"
  | "no_useful_tests"
  | "infrastructure_failed"
  | "incompatible";

export type AiTestRunResponse = {
  status: AiTestRunResponseStatus;
  message: string | null;
  unsupported_reason: string | null;
  unsupported_parameters: [string, string][];
  supported_targets: string[];
  score: AiScore | null;
  tests: AiTestResultRow[];
  stored_tests: AiStoredTest[];
  skipped_topics: string[];
  generation_note: string | null;
  memory_status: "not_run";
  disclaimer: string;
};

export type QuestionTextResponse = {
  question_text: string;
  model: string;
};

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

export class AiTestsRequestError extends Error {
  constructor(
    message: string,
    public readonly status: AiTestRunResponseStatus | null,
  ) {
    super(message);
    this.name = "AiTestsRequestError";
  }
}

// ---------------------------------------------------------------------------
// API base URL
// ---------------------------------------------------------------------------

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

type ApiError = { error?: { message?: string } };

// ---------------------------------------------------------------------------
// Run AI tests
// ---------------------------------------------------------------------------

export async function runAiTests(
  request: AiTestRunRequest,
): Promise<AiTestRunResponse> {
  try {
    const response = await fetch(`${apiBase()}/api/ai-tests/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new AiTestsRequestError(
        apiError?.error?.message ?? "AI test generation failed. Please retry.",
        null,
      );
    }
    return body as AiTestRunResponse;
  } catch (error) {
    if (error instanceof AiTestsRequestError) throw error;
    throw new AiTestsRequestError(
      "The AI test service is unavailable. Check the backend and retry.",
      null,
    );
  }
}

// ---------------------------------------------------------------------------
// Rerun AI tests
// ---------------------------------------------------------------------------

export async function rerunAiTests(
  request: AiTestRerunRequest,
): Promise<AiTestRunResponse> {
  try {
    const response = await fetch(`${apiBase()}/api/ai-tests/rerun`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new AiTestsRequestError(
        apiError?.error?.message ?? "AI test rerun failed. Please retry.",
        null,
      );
    }
    return body as AiTestRunResponse;
  } catch (error) {
    if (error instanceof AiTestsRequestError) throw error;
    throw new AiTestsRequestError(
      "The AI test service is unavailable. Check the backend and retry.",
      null,
    );
  }
}

// ---------------------------------------------------------------------------
// Transcribe question pages
// ---------------------------------------------------------------------------

export async function transcribeQuestion(
  formData: FormData,
): Promise<QuestionTextResponse> {
  try {
    const response = await fetch(`${apiBase()}/api/transcribe-question`, {
      method: "POST",
      body: formData,
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new AiTestsRequestError(
        apiError?.error?.message ?? "Question extraction failed. Please retry.",
        null,
      );
    }
    return body as QuestionTextResponse;
  } catch (error) {
    if (error instanceof AiTestsRequestError) throw error;
    throw new AiTestsRequestError(
      "The question extraction service is unavailable.",
      null,
    );
  }
}
