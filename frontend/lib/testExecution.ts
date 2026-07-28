export type FunctionParameter = {
  name: string;
  type: string;
  type_metadata: FunctionTypeMetadata;
};

export type FunctionTypeMetadata = {
  kind: "scalar" | "vector" | "array" | "void";
  display_type: string;
  scalar_type: string | null;
  element_type: string | null;
  passing:
    | "value"
    | "const_reference"
    | "mutable_reference"
    | "array_pointer";
  size_parameter_name: string | null;
};

export type FunctionDescriptor = {
  id: string;
  name: string;
  return_type: string;
  return_type_metadata: FunctionTypeMetadata;
  parameters: FunctionParameter[];
  display: string;
};

export type TestModeAnalysis = {
  mode: "program" | "function" | "unsupported";
  functions: FunctionDescriptor[];
  message: string | null;
};

export type ProgramTestInput = {
  name: string;
  stdin: string;
  expected_stdout: string;
};

export type FunctionTestInput = {
  name: string;
  arguments: string[];
  expected_return: string;
};

export type FunctionOutputTestInput = {
  name: string;
  arguments: string[];
  expected_stdout: string;
};

export type FunctionMutationTestInput = {
  name: string;
  arguments: string[];
  expected_final_arguments: Record<string, string>;
};

type ResultBase = {
  name: string;
  passed: boolean;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  output_limited: boolean;
  match_type:
    | "exact"
    | "whitespace_normalized"
    | "formatting_mismatch"
    | "mismatch";
};

export type ProgramTestResult = ResultBase & {
  expected_stdout: string;
  actual_stdout: string;
};

export type FunctionTestResult = ResultBase & {
  arguments: string[];
  expected_return: string;
  actual_return: string;
};

export type FunctionOutputTestResult = ResultBase & {
  arguments: string[];
  expected_stdout: string;
  actual_stdout: string;
};

export type FunctionMutationTestResult = ResultBase & {
  initial_arguments: Record<string, string>;
  expected_final_arguments: Record<string, string>;
  actual_final_arguments: Record<string, string>;
};

export type RunTestsResult = {
  mode: "program" | "function" | "unsupported";
  success: boolean;
  compile_error: string | null;
  input_error: string | null;
  unsupported_error: string | null;
  function: FunctionDescriptor | null;
  tests: Array<
    ProgramTestResult | FunctionTestResult | FunctionOutputTestResult
    | FunctionMutationTestResult
  >;
};

export type RunTestsRequest =
  | {
      mode: "program";
      code: string;
      language: "cpp";
      comparison_mode: "whitespace_tolerant" | "exact";
      tests: ProgramTestInput[];
    }
  | {
      mode: "function";
      code: string;
      language: "cpp";
      target_function: string;
      comparison_mode: "whitespace_tolerant" | "exact";
      tests: Array<
        FunctionTestInput
        | FunctionOutputTestInput
        | FunctionMutationTestInput
      >;
    };

type ApiError = { error?: { message?: string } };

export class RunTestsRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunTestsRequestError";
  }
}

function isFunctionDescriptor(value: unknown): value is FunctionDescriptor {
  if (!value || typeof value !== "object") return false;
  const descriptor = value as Partial<FunctionDescriptor>;
  return (
    typeof descriptor.id === "string" &&
    typeof descriptor.name === "string" &&
    typeof descriptor.return_type === "string" &&
    isFunctionTypeMetadata(descriptor.return_type_metadata) &&
    typeof descriptor.display === "string" &&
    Array.isArray(descriptor.parameters) &&
    descriptor.parameters.every(
      (parameter) =>
        parameter !== null &&
        typeof parameter === "object" &&
        typeof parameter.name === "string" &&
        typeof parameter.type === "string" &&
        isFunctionTypeMetadata(parameter.type_metadata),
    )
  );
}

function isFunctionTypeMetadata(
  value: unknown,
): value is FunctionTypeMetadata {
  if (!value || typeof value !== "object") return false;
  const metadata = value as Partial<FunctionTypeMetadata>;
  return (
    ["scalar", "vector", "array", "void"].includes(metadata.kind ?? "") &&
    typeof metadata.display_type === "string" &&
    (metadata.scalar_type === null ||
      typeof metadata.scalar_type === "string") &&
    (metadata.element_type === null ||
      typeof metadata.element_type === "string") &&
    [
      "value",
      "const_reference",
      "mutable_reference",
      "array_pointer",
    ].includes(
      metadata.passing ?? "",
    ) &&
    (metadata.size_parameter_name === null ||
      typeof metadata.size_parameter_name === "string")
  );
}

function isMatchType(value: unknown) {
  return [
    "exact",
    "whitespace_normalized",
    "formatting_mismatch",
    "mismatch",
  ].includes(typeof value === "string" ? value : "");
}

function isResultBase(value: unknown): value is ResultBase {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<ResultBase>;
  return (
    typeof result.name === "string" &&
    typeof result.passed === "boolean" &&
    typeof result.stderr === "string" &&
    (result.exit_code === null || typeof result.exit_code === "number") &&
    typeof result.timed_out === "boolean" &&
    typeof result.output_limited === "boolean" &&
    isMatchType(result.match_type)
  );
}

function isTestResult(
  value: unknown,
): value is
  | ProgramTestResult
  | FunctionTestResult
  | FunctionOutputTestResult
  | FunctionMutationTestResult {
  if (!isResultBase(value)) return false;
  const result = value as Partial<ProgramTestResult & FunctionTestResult>;
  const programResult =
    typeof result.expected_stdout === "string" &&
    typeof result.actual_stdout === "string";
  const functionResult =
    Array.isArray(result.arguments) &&
    result.arguments.every((argument) => typeof argument === "string") &&
    typeof result.expected_return === "string" &&
    typeof result.actual_return === "string";
  const functionOutputResult =
    Array.isArray(result.arguments) &&
    result.arguments.every((argument) => typeof argument === "string") &&
    typeof result.expected_stdout === "string" &&
    typeof result.actual_stdout === "string";
  const mutation = value as Partial<FunctionMutationTestResult>;
  const mutationResult =
    isStringRecord(mutation.initial_arguments) &&
    isStringRecord(mutation.expected_final_arguments) &&
    isStringRecord(mutation.actual_final_arguments);
  return (
    programResult ||
    functionResult ||
    functionOutputResult ||
    mutationResult
  );
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.values(value).every((item) => typeof item === "string")
  );
}

function isRunTestsResult(value: unknown): value is RunTestsResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<RunTestsResult>;
  return (
    ["program", "function", "unsupported"].includes(result.mode ?? "") &&
    typeof result.success === "boolean" &&
    (result.compile_error === null ||
      typeof result.compile_error === "string") &&
    (result.input_error === null || typeof result.input_error === "string") &&
    (result.unsupported_error === null ||
      typeof result.unsupported_error === "string") &&
    (result.function === null || isFunctionDescriptor(result.function)) &&
    Array.isArray(result.tests) &&
    result.tests.every(isTestResult)
  );
}

function isTestModeAnalysis(value: unknown): value is TestModeAnalysis {
  if (!value || typeof value !== "object") return false;
  const analysis = value as Partial<TestModeAnalysis>;
  return (
    ["program", "function", "unsupported"].includes(analysis.mode ?? "") &&
    Array.isArray(analysis.functions) &&
    analysis.functions.every(isFunctionDescriptor) &&
    (analysis.message === null || typeof analysis.message === "string")
  );
}

function apiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function postJson(path: string, payload: object, signal?: AbortSignal) {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const apiError = body as ApiError | null;
    throw new RunTestsRequestError(
      apiError?.error?.message ?? "The test runner request failed.",
    );
  }
  return body;
}

export async function analyzeTestMode(
  code: string,
  signal?: AbortSignal,
): Promise<TestModeAnalysis> {
  try {
    const body = await postJson(
      "/api/test-mode",
      { code, language: "cpp" },
      signal,
    );
    if (!isTestModeAnalysis(body)) {
      throw new RunTestsRequestError(
        "The backend returned an invalid test-mode analysis.",
      );
    }
    return body;
  } catch (error) {
    if (error instanceof RunTestsRequestError || error instanceof DOMException) {
      throw error;
    }
    throw new RunTestsRequestError(
      "The test analyzer is unavailable. Check the backend and retry.",
    );
  }
}

export async function runCppTests(
  request: RunTestsRequest,
): Promise<RunTestsResult> {
  try {
    const body = await postJson("/api/run-tests", request);
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
