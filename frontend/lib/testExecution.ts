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
  vector_depth: 1 | 2 | null;
  passing:
    | "value"
    | "const_reference"
    | "mutable_reference"
    | "scalar_pointer"
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

export type ObjectConstructor = {
  id: string;
  display: string;
  parameters: FunctionParameter[];
};

export type ObjectMethod = {
  id: string;
  name: string;
  display: string;
  parameters: FunctionParameter[];
  return_type: string;
  return_type_metadata: FunctionTypeMetadata;
  is_const: boolean;
};

export type ObjectClass = {
  id: string;
  name: string;
  kind: "class" | "struct";
  constructors: ObjectConstructor[];
  methods: ObjectMethod[];
  operators: ObjectOperator[];
};

export type ObjectOperatorParameter = {
  name: string;
  type: string;
  operand_kind: "value" | "object" | "stream";
  object_class_id: string | null;
  type_metadata: FunctionTypeMetadata | null;
};

export type ObjectOperator = {
  id: string;
  symbol: string;
  display: string;
  kind: "member" | "standalone";
  declaring_class_id: string | null;
  parameters: ObjectOperatorParameter[];
  return_type: string;
  return_kind:
    | "value"
    | "object_value"
    | "mutation_reference"
    | "stream_reference";
  return_object_class_id: string | null;
  return_type_metadata: FunctionTypeMetadata | null;
  is_const: boolean;
};

export type TestModeAnalysis = {
  mode: "program" | "function" | "object" | "unsupported";
  functions: FunctionDescriptor[];
  classes: ObjectClass[];
  available_modes: Array<"program" | "function" | "object">;
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
  expected_mutations: Array<{
    parameter_id: string;
    expected_final_value: string;
  }>;
};

export type FunctionCombinedTestInput = {
  name: string;
  arguments: string[];
  expected_return?: string;
  check_stdout: boolean;
  expected_stdout?: string;
  expected_mutations?: FunctionMutationTestInput["expected_mutations"];
};

export type ObjectScenarioTestInput = {
  name: string;
  objects: Array<{
    object_id: string;
    name: string;
    class_id: string;
    constructor_id: string;
    arguments: string[];
  }>;
  steps: Array<{
    step_type: "method" | "observer" | "operator";
    method_id?: string;
    operator_id?: string;
    target_object_id: string;
    arguments: string[];
    operands: string[];
    result_object_id?: string;
    result_name?: string;
    expected_return?: string;
    check_stdout: boolean;
    expected_stdout?: string;
  }>;
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
  mismatch_detail: string | null;
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
  mismatch_details: Record<string, string>;
};

export type FunctionChannelResult = {
  expected: string;
  actual: string;
  passed: boolean;
  match_type: ResultBase["match_type"];
  mismatch_detail: string | null;
};

export type FunctionCombinedTestResult = ResultBase & {
  arguments: string[];
  return_result: FunctionChannelResult | null;
  stdout_result: FunctionChannelResult | null;
  mutation_results: Array<{
    parameter: string;
    initial: string;
    expected_final: string;
    actual_final: string;
    passed: boolean;
    mismatch_detail: string | null;
  }>;
};

export type ObjectScenarioTestResult = ResultBase & {
  class_name: string;
  constructor: string;
  constructor_arguments: string[];
  constructor_completed: boolean;
  constructed_objects: string[];
  failed_step_index: number | null;
  steps: Array<{
    index: number;
    method_id: string | null;
    step_type: "method" | "observer" | "operator";
    operator_id: string | null;
    method: string;
    expression: string | null;
    result_object_name: string | null;
    status: "completed" | "failed" | "not_executed";
    passed: boolean;
    return_result: FunctionChannelResult | null;
    stdout_result: FunctionChannelResult | null;
  }>;
};

export type RunTestsResult = {
  mode: "program" | "function" | "object" | "unsupported";
  success: boolean;
  compile_error: string | null;
  input_error: string | null;
  unsupported_error: string | null;
  function: FunctionDescriptor | null;
  tests: Array<
    ProgramTestResult | FunctionTestResult | FunctionOutputTestResult
    | FunctionMutationTestResult
    | FunctionCombinedTestResult
    | ObjectScenarioTestResult
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
      tests: FunctionCombinedTestInput[];
    }
  | {
      mode: "object";
      code: string;
      language: "cpp";
      comparison_mode: "whitespace_tolerant" | "exact";
      tests: ObjectScenarioTestInput[];
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

function isObjectClass(value: unknown): value is ObjectClass {
  if (!value || typeof value !== "object") return false;
  const objectClass = value as Partial<ObjectClass>;
  const validParameters = (parameters: unknown) =>
    Array.isArray(parameters) &&
    parameters.every(
      (parameter) =>
        parameter !== null &&
        typeof parameter === "object" &&
        typeof parameter.name === "string" &&
        typeof parameter.type === "string" &&
        isFunctionTypeMetadata(parameter.type_metadata),
    );
  return (
    typeof objectClass.id === "string" &&
    typeof objectClass.name === "string" &&
    ["class", "struct"].includes(objectClass.kind ?? "") &&
    Array.isArray(objectClass.constructors) &&
    objectClass.constructors.every(
      (constructor) =>
        constructor !== null &&
        typeof constructor === "object" &&
        typeof constructor.id === "string" &&
        typeof constructor.display === "string" &&
        validParameters(constructor.parameters),
    ) &&
    Array.isArray(objectClass.methods) &&
    objectClass.methods.every(
      (method) =>
        method !== null &&
        typeof method === "object" &&
        typeof method.id === "string" &&
        typeof method.name === "string" &&
        typeof method.display === "string" &&
        typeof method.return_type === "string" &&
        typeof method.is_const === "boolean" &&
        isFunctionTypeMetadata(method.return_type_metadata) &&
        validParameters(method.parameters),
    ) &&
    Array.isArray(objectClass.operators) &&
    objectClass.operators.every(
      (operator) =>
        operator !== null &&
        typeof operator === "object" &&
        typeof operator.id === "string" &&
        typeof operator.symbol === "string" &&
        typeof operator.display === "string" &&
        ["member", "standalone"].includes(operator.kind) &&
        (operator.declaring_class_id === null ||
          typeof operator.declaring_class_id === "string") &&
        Array.isArray(operator.parameters) &&
        operator.parameters.every(
          (parameter) =>
            parameter !== null &&
            typeof parameter === "object" &&
            typeof parameter.name === "string" &&
            typeof parameter.type === "string" &&
            ["value", "object", "stream"].includes(parameter.operand_kind) &&
            (parameter.object_class_id === null ||
              typeof parameter.object_class_id === "string") &&
            (parameter.type_metadata === null ||
              isFunctionTypeMetadata(parameter.type_metadata)),
        ) &&
        typeof operator.return_type === "string" &&
        [
          "value",
          "object_value",
          "mutation_reference",
          "stream_reference",
        ].includes(operator.return_kind) &&
        (operator.return_object_class_id === null ||
          typeof operator.return_object_class_id === "string") &&
        (operator.return_type_metadata === null ||
          isFunctionTypeMetadata(operator.return_type_metadata)) &&
        typeof operator.is_const === "boolean",
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
    (metadata.vector_depth === null ||
      metadata.vector_depth === 1 ||
      metadata.vector_depth === 2) &&
    [
      "value",
      "const_reference",
      "mutable_reference",
      "scalar_pointer",
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
  | FunctionMutationTestResult
  | FunctionCombinedTestResult
  | ObjectScenarioTestResult {
  if (!isResultBase(value)) return false;
  const result = value as Partial<ProgramTestResult & FunctionTestResult>;
  const programResult =
    typeof result.expected_stdout === "string" &&
    typeof result.actual_stdout === "string";
  const functionResult =
    Array.isArray(result.arguments) &&
    result.arguments.every((argument) => typeof argument === "string") &&
    typeof result.expected_return === "string" &&
    typeof result.actual_return === "string" &&
    (result.mismatch_detail === null ||
      typeof result.mismatch_detail === "string");
  const functionOutputResult =
    Array.isArray(result.arguments) &&
    result.arguments.every((argument) => typeof argument === "string") &&
    typeof result.expected_stdout === "string" &&
    typeof result.actual_stdout === "string";
  const mutation = value as Partial<FunctionMutationTestResult>;
  const mutationResult =
    isStringRecord(mutation.initial_arguments) &&
    isStringRecord(mutation.expected_final_arguments) &&
    isStringRecord(mutation.actual_final_arguments) &&
    isStringRecord(mutation.mismatch_details);
  const combined = value as Partial<FunctionCombinedTestResult>;
  const combinedResult =
    Array.isArray(combined.arguments) &&
    (combined.return_result === null ||
      isFunctionChannelResult(combined.return_result)) &&
    (combined.stdout_result === null ||
      isFunctionChannelResult(combined.stdout_result)) &&
    Array.isArray(combined.mutation_results) &&
    combined.mutation_results.every(
      (item) =>
        item !== null &&
        typeof item === "object" &&
        typeof item.parameter === "string" &&
        typeof item.initial === "string" &&
        typeof item.expected_final === "string" &&
        typeof item.actual_final === "string" &&
        typeof item.passed === "boolean" &&
        (item.mismatch_detail === null ||
          typeof item.mismatch_detail === "string"),
    );
  const objectResult = value as Partial<ObjectScenarioTestResult>;
  const scenarioResult =
    typeof objectResult.class_name === "string" &&
    typeof objectResult.constructor === "string" &&
    Array.isArray(objectResult.constructor_arguments) &&
    objectResult.constructor_arguments.every(
      (argument) => typeof argument === "string",
    ) &&
    typeof objectResult.constructor_completed === "boolean" &&
    Array.isArray(objectResult.constructed_objects) &&
    objectResult.constructed_objects.every(
      (item) => typeof item === "string",
    ) &&
    (objectResult.failed_step_index === null ||
      typeof objectResult.failed_step_index === "number") &&
    Array.isArray(objectResult.steps) &&
    objectResult.steps.every(
      (step) =>
        step !== null &&
        typeof step === "object" &&
        typeof step.index === "number" &&
        ["method", "observer", "operator"].includes(step.step_type) &&
        (step.method_id === null || typeof step.method_id === "string") &&
        (step.operator_id === null || typeof step.operator_id === "string") &&
        typeof step.method === "string" &&
        (step.expression === null || typeof step.expression === "string") &&
        (step.result_object_name === null ||
          typeof step.result_object_name === "string") &&
        ["completed", "failed", "not_executed"].includes(step.status) &&
        typeof step.passed === "boolean" &&
        (step.return_result === null ||
          isFunctionChannelResult(step.return_result)) &&
        (step.stdout_result === null ||
          isFunctionChannelResult(step.stdout_result)),
    );
  return (
    programResult ||
    functionResult ||
    functionOutputResult ||
    mutationResult ||
    combinedResult ||
    scenarioResult
  );
}

function isFunctionChannelResult(
  value: unknown,
): value is FunctionChannelResult {
  if (!value || typeof value !== "object") return false;
  const channel = value as Partial<FunctionChannelResult>;
  return (
    typeof channel.expected === "string" &&
    typeof channel.actual === "string" &&
    typeof channel.passed === "boolean" &&
    (channel.mismatch_detail === null ||
      typeof channel.mismatch_detail === "string") &&
    isMatchType(channel.match_type)
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
    ["program", "function", "object", "unsupported"].includes(
      result.mode ?? "",
    ) &&
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
    ["program", "function", "object", "unsupported"].includes(
      analysis.mode ?? "",
    ) &&
    Array.isArray(analysis.functions) &&
    analysis.functions.every(isFunctionDescriptor) &&
    Array.isArray(analysis.classes) &&
    analysis.classes.every(isObjectClass) &&
    Array.isArray(analysis.available_modes) &&
    analysis.available_modes.every((mode) =>
      ["program", "function", "object"].includes(mode),
    ) &&
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
