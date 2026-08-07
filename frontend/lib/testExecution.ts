export type FunctionParameter = {
  name: string;
  type: string;
  type_metadata: FunctionTypeMetadata;
};

export type FunctionTypeMetadata = {
  kind: "scalar" | "vector" | "array" | "void" | "container" | "iterator";
  display_type: string;
  scalar_type: string | null;
  element_type: string | null;
  vector_depth: number | null;
  passing:
    | "value"
    | "const_reference"
    | "mutable_reference"
    | "scalar_pointer"
    | "array_pointer";
  size_parameter_name: string | null;
  // Container-specific fields (null/undefined for non-container kinds)
  container_family?: "sequence" | "associative" | "unordered" | "adapter" | null;
  container_name?: string | null;
  key_type?: string | null;
  mapped_type?: string | null;
  fixed_size?: number | null;
  nested_depth?: number | null;
  ordered?: boolean | null;
  associative?: boolean | null;
  unordered?: boolean | null;
  adapter?: boolean | null;
  supported?: boolean;
  unsupported_reason?: string | null;
  // Iterator-specific fields (null/undefined for non-iterator kinds)
  iterator_container?: string | null;
  iterator_const?: boolean | null;
  iterator_role?: "single" | "range_begin" | "range_end" | null;
  iterator_group_index?: number | null;
};

export type FunctionDescriptor = {
  id: string;
  name: string;
  return_type: string;
  return_type_metadata: FunctionTypeMetadata;
  parameters: FunctionParameter[];
  display: string;
  template_kind: "none" | "function_template" | "explicit_specialization";
  template_parameters: TemplateParameter[];
  template_argument_mode: "deduced" | "explicit" | null;
  effective_template_arguments: TemplateArgument[];
  concrete_instantiation: string | null;
  specialization_selected: boolean;
  explicit_specializations: Array<{
    primary_template_name: string;
    effective_template_arguments: string[];
    return_type: string;
    parameter_types: string[];
    source_line: number;
  }>;
  source_line: number | null;
};

export type TemplateParameter = {
  name: string;
  kind: "type" | "non_type";
  non_type_type: string | null;
  default_argument: string | null;
  deducible: boolean;
};

export type TemplateArgument = {
  parameter_name: string;
  kind: "type" | "non_type";
  value: string;
  used_default: boolean;
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
  is_virtual: boolean;
  is_pure_virtual: boolean;
  is_override: boolean;
  is_final: boolean;
  overrides_method_id: string | null;
  override_mismatch_reason: string | null;
};

export type ObjectClass = {
  id: string;
  name: string;
  kind: "class" | "struct";
  constructors: ObjectConstructor[];
  methods: ObjectMethod[];
  operators: ObjectOperator[];
  special_members: ObjectSpecialMember[];
  base_class_id: string | null;
  inheritance_access: string | null;
  inheritance_supported: boolean;
  is_abstract: boolean;
  has_virtual_destructor: boolean;
  derived_class_ids: string[];
  inheritance_depth: number;
  template_kind: "none" | "class_template";
  template_parameters: TemplateParameter[];
  effective_template_arguments: TemplateArgument[];
  concrete_type: string | null;
};

export type ObjectSpecialMember = {
  id: string;
  kind:
    | "copy_constructor"
    | "copy_assignment"
    | "move_constructor"
    | "move_assignment"
    | "destructor";
  display: string;
  is_defaulted: boolean;
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

export type ExpectedOutcomeKind = "return_value" | "return_void" | "throws";
export type ExceptionMessageRule = "ignore" | "exact" | "contains";
export type SupportedExceptionType =
  | "any_std_exception"
  | "std::exception"
  | "std::runtime_error"
  | "std::logic_error"
  | "std::invalid_argument"
  | "std::domain_error"
  | "std::length_error"
  | "std::out_of_range"
  | "std::overflow_error"
  | "std::underflow_error"
  | "std::range_error"
  | "std::bad_alloc"
  | "std::bad_cast"
  | "std::bad_typeid"
  | "std::bad_function_call";

export type ExceptionExpectationInput = {
  expected_outcome: ExpectedOutcomeKind;
  expected_exception_type?: SupportedExceptionType;
  exception_message_rule?: ExceptionMessageRule;
  expected_exception_message?: string;
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

export type FunctionCombinedTestInput = ExceptionExpectationInput & {
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
    template_arguments?: Array<{
      parameter_name: string;
      kind: "type" | "non_type";
      value: string;
      use_default: boolean;
    }>;
    arguments: string[];
  } & ExceptionExpectationInput>;
  steps: Array<{
    step_type:
      | "create_object"
      | "create_base_reference"
      | "create_base_pointer"
      | "create_owned_base_pointer"
      | "polymorphic_method"
      | "delete_base_pointer"
      | "slice_object"
      | "dynamic_cast"
      | "method"
      | "observer"
      | "operator"
      | "copy_construct"
      | "copy_assign"
      | "self_assign"
      | "move_construct"
      | "move_assign";
    method_id?: string;
    class_id?: string;
    constructor_id?: string;
    template_arguments?: Array<{
      parameter_name: string;
      kind: "type" | "non_type";
      value: string;
      use_default: boolean;
    }>;
    operator_id?: string;
    target_object_id?: string;
    arguments?: string[];
    operands?: string[];
    result_object_id?: string;
    result_name?: string;
    special_member_id?: string;
    source_object_id?: string;
    base_class_id?: string;
    derived_class_id?: string;
    cast_target_class_id?: string;
    cast_mode?: "pointer" | "reference";
    expected_cast_result?:
      | "succeeds"
      | "returns_null"
      | "throws_bad_cast";
    expected_return?: string;
    check_stdout?: boolean;
    expected_stdout?: string;
  } & ExceptionExpectationInput>;
};

export type ExceptionOutcomeResult = {
  expected_outcome: ExpectedOutcomeKind;
  actual_outcome:
    | "returned"
    | "threw_standard"
    | "threw_non_standard"
    | "crashed"
    | "timed_out";
  expected_exception_type: SupportedExceptionType | null;
  actual_exception_type: string | null;
  expected_message_rule: ExceptionMessageRule;
  expected_message: string | null;
  actual_message: string | null;
  type_matched: boolean | null;
  message_matched: boolean | null;
  expectation_passed: boolean;
  execution_continued: boolean;
};

type ResultBase = {
  name: string;
  passed: boolean;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  output_limited: boolean;
  memory_check_enabled: boolean;
  memory_status: MemoryStatus;
  memory_summary: string | null;
  memory_diagnostics: string | null;
  address_sanitizer_available: boolean | null;
  undefined_behavior_sanitizer_available: boolean | null;
  leak_sanitizer_available: boolean | null;
  memory_access_status: SanitizerCheckStatus;
  undefined_behavior_status: SanitizerCheckStatus;
  leak_status: SanitizerCheckStatus;
  execution_provider: "host" | "docker";
  memory_tool:
    | "none"
    | "sanitizer"
    | "valgrind"
    | "sanitizer_and_valgrind";
  container_runtime_available: boolean | null;
  leaked_bytes: number | null;
  leaked_allocations: number | null;
  leak_kind: string | null;
  memory_diagnoses?: MemoryDiagnosis[];
  match_type:
    | "exact"
    | "whitespace_normalized"
    | "formatting_mismatch"
    | "mismatch";
  exception_result?: ExceptionOutcomeResult | null;
  template_kind:
    | "function_template"
    | "class_template"
    | "explicit_specialization"
    | null;
  template_name: string | null;
  template_argument_mode: "deduced" | "explicit" | null;
  effective_template_arguments: TemplateArgument[];
  concrete_instantiation: string | null;
  specialization_selected: boolean;
  specialization_kind: "primary" | "explicit_specialization" | null;
};

export type MemoryDiagnosis = {
  category: string;
  title: string;
  confidence: "confirmed" | "likely" | "possible";
  summary: string;
  likely_cause: string | null;
  source_range: {
    start_line: number;
    end_line: number;
    excerpt: string;
    label: string;
    confidence: "confirmed" | "likely" | "possible";
  } | null;
  suggested_direction: string;
  related_operation: string | null;
  confirmed_by: string[];
  technical_details: string[];
  supporting_findings: string[];
};

export type MemoryStatus =
  | "not_run"
  | "clean"
  | "partial"
  | "leak"
  | "use_after_free"
  | "double_free"
  | "invalid_free"
  | "buffer_overflow"
  | "undefined_behavior"
  | "runtime_error"
  | "unavailable"
  | "unknown_memory_error";

export type SanitizerCheckStatus =
  | "not_run"
  | "clean"
  | "failed"
  | "unavailable"
  | "possible";

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
  moved_from_objects: string[];
  destruction_failed: boolean;
  failed_step_index: number | null;
  steps: Array<{
    index: number;
    method_id: string | null;
    step_type:
      | "create_object"
      | "create_base_reference"
      | "create_base_pointer"
      | "create_owned_base_pointer"
      | "polymorphic_method"
      | "delete_base_pointer"
      | "slice_object"
      | "dynamic_cast"
      | "method"
      | "observer"
      | "operator"
      | "copy_construct"
      | "copy_assign"
      | "self_assign"
      | "move_construct"
      | "move_assign";
    operator_id: string | null;
    method: string;
    expression: string | null;
    result_object_name: string | null;
    status: "completed" | "failed" | "not_executed";
    passed: boolean;
    return_result: FunctionChannelResult | null;
    stdout_result: FunctionChannelResult | null;
    exception_result: ExceptionOutcomeResult | null;
    static_type: string | null;
    runtime_type: string | null;
    ownership_mode:
      | "value"
      | "reference"
      | "non_owning_pointer"
      | "owned_pointer"
      | null;
    dispatch_kind: "virtual" | "non_virtual" | null;
    selected_implementation: string | null;
    slicing_occurred: boolean;
    cast_result: "succeeded" | "null" | "threw_bad_cast" | null;
    virtual_destructor: boolean | null;
  }>;
  big_five_diagnosis: BigFiveDiagnosis | null;
  constructor_exception_result: ExceptionOutcomeResult | null;
};

export type BigFiveDiagnosis = {
  title: string;
  confidence: "confirmed" | "likely" | "possible";
  summary: string;
  evidence: string[];
  suspicious_ranges: Array<{
    start_line: number;
    end_line: number;
    snippet: string;
    reason: string;
  }>;
  suggested_direction: string;
  related_operation:
    | "copy_constructor"
    | "copy_assignment"
    | "self_assignment"
    | "move_constructor"
    | "move_assignment"
    | "destructor"
    | null;
};

export type RunTestsResult = {
  mode: "program" | "function" | "object" | "unsupported";
  success: boolean;
  compile_error: string | null;
  input_error: string | null;
  unsupported_error: string | null;
  memory_check_enabled: boolean;
  memory_status: MemoryStatus;
  memory_summary: string | null;
  memory_diagnostics: string | null;
  address_sanitizer_available: boolean | null;
  undefined_behavior_sanitizer_available: boolean | null;
  leak_sanitizer_available: boolean | null;
  execution_provider: "host" | "docker";
  memory_tool:
    | "none"
    | "sanitizer"
    | "valgrind"
    | "sanitizer_and_valgrind";
  container_runtime_available: boolean | null;
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
      run_memory_checks?: boolean;
      tests: ProgramTestInput[];
    }
  | {
      mode: "function";
      code: string;
      language: "cpp";
      target_function: string;
      template_argument_mode?: "deduced" | "explicit";
      template_arguments?: Array<{
        parameter_name: string;
        kind: "type" | "non_type";
        value: string;
        use_default: boolean;
      }>;
      comparison_mode: "whitespace_tolerant" | "exact";
      run_memory_checks?: boolean;
      tests: FunctionCombinedTestInput[];
    }
  | {
      mode: "object";
      code: string;
      language: "cpp";
      comparison_mode: "whitespace_tolerant" | "exact";
      run_memory_checks?: boolean;
      tests: ObjectScenarioTestInput[];
    };

type ApiError = { error?: { code?: string; message?: string } };

export class RunTestsRequestError extends Error {
  constructor(
    message: string,
    readonly code: string | null = null,
  ) {
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
    (descriptor.template_kind === undefined ||
      ["none", "function_template", "explicit_specialization"].includes(
        descriptor.template_kind,
      )) &&
    (descriptor.template_parameters === undefined ||
    (Array.isArray(descriptor.template_parameters) &&
    descriptor.template_parameters.every(
      (parameter) =>
        parameter !== null &&
        typeof parameter === "object" &&
        typeof parameter.name === "string" &&
        ["type", "non_type"].includes(parameter.kind) &&
        (parameter.non_type_type === null ||
          typeof parameter.non_type_type === "string") &&
        (parameter.default_argument === null ||
          typeof parameter.default_argument === "string") &&
        typeof parameter.deducible === "boolean",
    ))) &&
    (descriptor.template_argument_mode === undefined ||
      descriptor.template_argument_mode === null ||
      ["deduced", "explicit"].includes(descriptor.template_argument_mode)) &&
    (descriptor.effective_template_arguments === undefined ||
      Array.isArray(descriptor.effective_template_arguments)) &&
    (descriptor.concrete_instantiation === undefined ||
      descriptor.concrete_instantiation === null ||
      typeof descriptor.concrete_instantiation === "string") &&
    (descriptor.specialization_selected === undefined ||
      typeof descriptor.specialization_selected === "boolean") &&
    (descriptor.explicit_specializations === undefined ||
      (Array.isArray(descriptor.explicit_specializations) &&
        descriptor.explicit_specializations.every(
          (specialization) =>
            specialization !== null &&
            typeof specialization === "object" &&
            typeof specialization.primary_template_name === "string" &&
            Array.isArray(
              specialization.effective_template_arguments,
            ) &&
            specialization.effective_template_arguments.every(
              (argument) => typeof argument === "string",
            ) &&
            typeof specialization.return_type === "string" &&
            Array.isArray(specialization.parameter_types) &&
            specialization.parameter_types.every(
              (parameter) => typeof parameter === "string",
            ) &&
            typeof specialization.source_line === "number",
        ))) &&
    (descriptor.source_line === undefined ||
      descriptor.source_line === null ||
      typeof descriptor.source_line === "number") &&
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
        typeof method.is_virtual === "boolean" &&
        typeof method.is_pure_virtual === "boolean" &&
        typeof method.is_override === "boolean" &&
        typeof method.is_final === "boolean" &&
        (method.overrides_method_id === null ||
          typeof method.overrides_method_id === "string") &&
        (method.override_mismatch_reason === null ||
          typeof method.override_mismatch_reason === "string") &&
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
    ) &&
    Array.isArray(objectClass.special_members) &&
    objectClass.special_members.every(
      (member) =>
        member !== null &&
        typeof member === "object" &&
        typeof member.id === "string" &&
        [
          "copy_constructor",
          "copy_assignment",
          "move_constructor",
          "move_assignment",
          "destructor",
        ].includes(member.kind) &&
        typeof member.display === "string" &&
        typeof member.is_defaulted === "boolean",
    ) &&
    (objectClass.base_class_id === null ||
      typeof objectClass.base_class_id === "string") &&
    (objectClass.inheritance_access === null ||
      typeof objectClass.inheritance_access === "string") &&
    typeof objectClass.inheritance_supported === "boolean" &&
    typeof objectClass.is_abstract === "boolean" &&
    typeof objectClass.has_virtual_destructor === "boolean" &&
    Array.isArray(objectClass.derived_class_ids) &&
    objectClass.derived_class_ids.every(
      (item) => typeof item === "string",
    ) &&
    typeof objectClass.inheritance_depth === "number"
    &&
    (objectClass.template_kind === undefined ||
      ["none", "class_template"].includes(objectClass.template_kind)) &&
    (objectClass.template_parameters === undefined ||
    (Array.isArray(objectClass.template_parameters) &&
    objectClass.template_parameters.every(
      (parameter) =>
        parameter !== null &&
        typeof parameter === "object" &&
        typeof parameter.name === "string" &&
        ["type", "non_type"].includes(parameter.kind),
    ))) &&
    (objectClass.effective_template_arguments === undefined ||
      Array.isArray(objectClass.effective_template_arguments)) &&
    (objectClass.concrete_type === undefined ||
      objectClass.concrete_type === null ||
      typeof objectClass.concrete_type === "string")
  );
}

function isFunctionTypeMetadata(
  value: unknown,
): value is FunctionTypeMetadata {
  if (!value || typeof value !== "object") return false;
  const metadata = value as Partial<FunctionTypeMetadata>;
  return (
    ["scalar", "vector", "array", "void", "container", "iterator"].includes(
      metadata.kind ?? "",
    ) &&
    typeof metadata.display_type === "string" &&
    (metadata.scalar_type === null ||
      typeof metadata.scalar_type === "string") &&
    (metadata.element_type === null ||
      typeof metadata.element_type === "string") &&
    (metadata.vector_depth === null ||
      typeof metadata.vector_depth === "number") &&
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
    typeof result.memory_check_enabled === "boolean" &&
    isMemoryStatus(result.memory_status) &&
    (result.memory_summary === null ||
      typeof result.memory_summary === "string") &&
    (result.memory_diagnostics === null ||
      typeof result.memory_diagnostics === "string") &&
    (result.address_sanitizer_available === null ||
      typeof result.address_sanitizer_available === "boolean") &&
    (result.undefined_behavior_sanitizer_available === null ||
      typeof result.undefined_behavior_sanitizer_available === "boolean") &&
    (result.leak_sanitizer_available === null ||
      typeof result.leak_sanitizer_available === "boolean") &&
    isSanitizerCheckStatus(result.memory_access_status) &&
    isSanitizerCheckStatus(result.undefined_behavior_status) &&
    isSanitizerCheckStatus(result.leak_status) &&
    ["host", "docker"].includes(result.execution_provider ?? "") &&
    ["none", "sanitizer", "valgrind", "sanitizer_and_valgrind"].includes(
      result.memory_tool ?? "",
    ) &&
    (result.container_runtime_available === null ||
      typeof result.container_runtime_available === "boolean") &&
    (result.leaked_bytes === null ||
      typeof result.leaked_bytes === "number") &&
    (result.leaked_allocations === null ||
      typeof result.leaked_allocations === "number") &&
    (result.leak_kind === null || typeof result.leak_kind === "string") &&
    (result.memory_diagnoses === undefined ||
      (Array.isArray(result.memory_diagnoses) &&
        result.memory_diagnoses.every(isMemoryDiagnosis))) &&
    isMatchType(result.match_type) &&
    (result.exception_result === undefined ||
      result.exception_result === null ||
      isExceptionOutcomeResult(result.exception_result)) &&
    (result.template_kind === undefined ||
      result.template_kind === null ||
      [
        "function_template",
        "class_template",
        "explicit_specialization",
      ].includes(result.template_kind)) &&
    (result.template_name === undefined ||
      result.template_name === null ||
      typeof result.template_name === "string") &&
    (result.template_argument_mode === undefined ||
      result.template_argument_mode === null ||
      ["deduced", "explicit"].includes(result.template_argument_mode)) &&
    (result.effective_template_arguments === undefined ||
    (Array.isArray(result.effective_template_arguments) &&
    result.effective_template_arguments.every(
      (argument) =>
        argument !== null &&
        typeof argument === "object" &&
        typeof argument.parameter_name === "string" &&
        ["type", "non_type"].includes(argument.kind) &&
        typeof argument.value === "string" &&
        typeof argument.used_default === "boolean",
    ))) &&
    (result.concrete_instantiation === undefined ||
      result.concrete_instantiation === null ||
      typeof result.concrete_instantiation === "string") &&
    (result.specialization_selected === undefined ||
      typeof result.specialization_selected === "boolean") &&
    (result.specialization_kind === undefined ||
      result.specialization_kind === null ||
      ["primary", "explicit_specialization"].includes(
        result.specialization_kind,
      ))
  );
}

function isMemoryDiagnosis(value: unknown): value is MemoryDiagnosis {
  if (!value || typeof value !== "object") return false;
  const diagnosis = value as Partial<MemoryDiagnosis>;
  const sourceRange = diagnosis.source_range;
  return (
    typeof diagnosis.category === "string" &&
    typeof diagnosis.title === "string" &&
    ["confirmed", "likely", "possible"].includes(
      diagnosis.confidence ?? "",
    ) &&
    typeof diagnosis.summary === "string" &&
    (diagnosis.likely_cause === null ||
      typeof diagnosis.likely_cause === "string") &&
    (sourceRange === null ||
      (typeof sourceRange === "object" &&
        typeof sourceRange.start_line === "number" &&
        typeof sourceRange.end_line === "number" &&
        typeof sourceRange.excerpt === "string" &&
        typeof sourceRange.label === "string" &&
        ["confirmed", "likely", "possible"].includes(
          sourceRange.confidence,
        ))) &&
    typeof diagnosis.suggested_direction === "string" &&
    (diagnosis.related_operation === null ||
      typeof diagnosis.related_operation === "string") &&
    Array.isArray(diagnosis.confirmed_by) &&
    diagnosis.confirmed_by.every((item) => typeof item === "string") &&
    Array.isArray(diagnosis.technical_details) &&
    diagnosis.technical_details.every(
      (item) => typeof item === "string",
    ) &&
    Array.isArray(diagnosis.supporting_findings) &&
    diagnosis.supporting_findings.every(
      (item) => typeof item === "string",
    )
  );
}

function isMemoryStatus(value: unknown): value is MemoryStatus {
  return [
    "not_run",
    "clean",
    "partial",
    "leak",
    "use_after_free",
    "double_free",
    "invalid_free",
    "buffer_overflow",
    "undefined_behavior",
    "runtime_error",
    "unavailable",
    "unknown_memory_error",
  ].includes(typeof value === "string" ? value : "");
}

function isSanitizerCheckStatus(
  value: unknown,
): value is SanitizerCheckStatus {
  return ["not_run", "clean", "failed", "unavailable", "possible"].includes(
    typeof value === "string" ? value : "",
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
    Array.isArray(objectResult.moved_from_objects) &&
    objectResult.moved_from_objects.every(
      (item) => typeof item === "string",
    ) &&
    typeof objectResult.destruction_failed === "boolean" &&
    (objectResult.constructor_exception_result === null ||
      isExceptionOutcomeResult(objectResult.constructor_exception_result)) &&
    (objectResult.big_five_diagnosis === null ||
      isBigFiveDiagnosis(objectResult.big_five_diagnosis)) &&
    (objectResult.failed_step_index === null ||
      typeof objectResult.failed_step_index === "number") &&
    Array.isArray(objectResult.steps) &&
    objectResult.steps.every(
      (step) =>
        step !== null &&
        typeof step === "object" &&
        typeof step.index === "number" &&
        [
          "create_object",
          "create_base_reference",
          "create_base_pointer",
          "create_owned_base_pointer",
          "polymorphic_method",
          "delete_base_pointer",
          "slice_object",
          "dynamic_cast",
          "method",
          "observer",
          "operator",
          "copy_construct",
          "copy_assign",
          "self_assign",
          "move_construct",
          "move_assign",
        ].includes(step.step_type) &&
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
          isFunctionChannelResult(step.stdout_result)) &&
        (step.exception_result === null ||
          isExceptionOutcomeResult(step.exception_result)) &&
        (step.static_type === null ||
          typeof step.static_type === "string") &&
        (step.runtime_type === null ||
          typeof step.runtime_type === "string") &&
        (step.ownership_mode === null ||
          [
            "value",
            "reference",
            "non_owning_pointer",
            "owned_pointer",
          ].includes(step.ownership_mode)) &&
        (step.dispatch_kind === null ||
          ["virtual", "non_virtual"].includes(step.dispatch_kind)) &&
        (step.selected_implementation === null ||
          typeof step.selected_implementation === "string") &&
        typeof step.slicing_occurred === "boolean" &&
        (step.cast_result === null ||
          ["succeeded", "null", "threw_bad_cast"].includes(
            step.cast_result,
          )) &&
        (step.virtual_destructor === null ||
          typeof step.virtual_destructor === "boolean"),
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

function isExceptionOutcomeResult(
  value: unknown,
): value is ExceptionOutcomeResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<ExceptionOutcomeResult>;
  return (
    ["return_value", "return_void", "throws"].includes(
      result.expected_outcome ?? "",
    ) &&
    [
      "returned",
      "threw_standard",
      "threw_non_standard",
      "crashed",
      "timed_out",
    ].includes(result.actual_outcome ?? "") &&
    (result.expected_exception_type === null ||
      typeof result.expected_exception_type === "string") &&
    (result.actual_exception_type === null ||
      typeof result.actual_exception_type === "string") &&
    ["ignore", "exact", "contains"].includes(
      result.expected_message_rule ?? "",
    ) &&
    (result.expected_message === null ||
      typeof result.expected_message === "string") &&
    (result.actual_message === null ||
      typeof result.actual_message === "string") &&
    (result.type_matched === null ||
      typeof result.type_matched === "boolean") &&
    (result.message_matched === null ||
      typeof result.message_matched === "boolean") &&
    typeof result.expectation_passed === "boolean" &&
    typeof result.execution_continued === "boolean"
  );
}

function isBigFiveDiagnosis(value: unknown): value is BigFiveDiagnosis {
  if (!value || typeof value !== "object") return false;
  const diagnosis = value as Partial<BigFiveDiagnosis>;
  return (
    typeof diagnosis.title === "string" &&
    ["confirmed", "likely", "possible"].includes(
      diagnosis.confidence ?? "",
    ) &&
    typeof diagnosis.summary === "string" &&
    Array.isArray(diagnosis.evidence) &&
    diagnosis.evidence.every((item) => typeof item === "string") &&
    Array.isArray(diagnosis.suspicious_ranges) &&
    diagnosis.suspicious_ranges.every(
      (range) =>
        range !== null &&
        typeof range === "object" &&
        typeof range.start_line === "number" &&
        typeof range.end_line === "number" &&
        typeof range.snippet === "string" &&
        typeof range.reason === "string",
    ) &&
    typeof diagnosis.suggested_direction === "string" &&
    (diagnosis.related_operation === null ||
      [
        "copy_constructor",
        "copy_assignment",
        "self_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
      ].includes(diagnosis.related_operation ?? ""))
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
    typeof result.memory_check_enabled === "boolean" &&
    isMemoryStatus(result.memory_status) &&
    (result.memory_summary === null ||
      typeof result.memory_summary === "string") &&
    (result.memory_diagnostics === null ||
      typeof result.memory_diagnostics === "string") &&
    (result.address_sanitizer_available === null ||
      typeof result.address_sanitizer_available === "boolean") &&
    (result.undefined_behavior_sanitizer_available === null ||
      typeof result.undefined_behavior_sanitizer_available === "boolean") &&
    (result.leak_sanitizer_available === null ||
      typeof result.leak_sanitizer_available === "boolean") &&
    ["host", "docker"].includes(result.execution_provider ?? "") &&
    ["none", "sanitizer", "valgrind", "sanitizer_and_valgrind"].includes(
      result.memory_tool ?? "",
    ) &&
    (result.container_runtime_available === null ||
      typeof result.container_runtime_available === "boolean") &&
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
      apiError?.error?.code ?? null,
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
