type ApiErrorBody = { error?: { message?: string; code?: string } };

export type BusyService = "compiler" | "ai";

/** Preserve a useful backend message, with safe status-specific fallbacks. */
export function apiErrorMessage(
  status: number,
  body: unknown,
  fallback: string,
  busyService: BusyService,
  requestId?: string | null,
): string {
  if (status === 500) {
    const reference = safeRequestId(requestId);
    return reference
      ? `An unexpected server error occurred. Retry, and share reference ${reference} if it continues.`
      : "An unexpected server error occurred. Please retry.";
  }
  const apiError = body as ApiErrorBody | null;
  const backendMessage = apiError?.error?.message;
  if (backendMessage) return backendMessage;
  if (status === 429) return "Too many requests. Try again shortly.";
  if (status === 503) {
    return busyService === "compiler"
      ? "The compiler is busy. Try again in a moment."
      : "AI service is busy. Try again in a moment.";
  }
  if (status === 413) return "This request is too large to process.";
  return fallback;
}

function safeRequestId(value: string | null | undefined): string | null {
  if (!value) return null;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  )
    ? value
    : null;
}

export function apiErrorCode(body: unknown): string | null {
  const apiError = body as ApiErrorBody | null;
  return apiError?.error?.code ?? null;
}
