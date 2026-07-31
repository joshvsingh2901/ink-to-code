from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class FunctionTypeResponse(BaseModel):
    kind: Literal["scalar", "vector", "array", "void"]
    display_type: str
    scalar_type: str | None = None
    element_type: str | None = None
    vector_depth: Literal[1, 2] | None = None
    passing: Literal[
        "value",
        "const_reference",
        "mutable_reference",
        "scalar_pointer",
        "array_pointer",
    ]
    size_parameter_name: str | None = None


class FunctionParameterResponse(BaseModel):
    name: str
    type: str
    type_metadata: FunctionTypeResponse


class FunctionResponse(BaseModel):
    id: str
    name: str
    return_type: str
    return_type_metadata: FunctionTypeResponse
    parameters: list[FunctionParameterResponse]
    display: str


class ObjectConstructorResponse(BaseModel):
    id: str
    display: str
    parameters: list[FunctionParameterResponse]


class ObjectMethodResponse(BaseModel):
    id: str
    name: str
    display: str
    parameters: list[FunctionParameterResponse]
    return_type: str
    return_type_metadata: FunctionTypeResponse
    is_const: bool


class ObjectOperatorParameterResponse(BaseModel):
    name: str
    type: str
    operand_kind: Literal["value", "object", "stream"]
    object_class_id: str | None = None
    type_metadata: FunctionTypeResponse | None = None


class ObjectOperatorResponse(BaseModel):
    id: str
    symbol: str
    display: str
    kind: Literal["member", "standalone"]
    declaring_class_id: str | None = None
    parameters: list[ObjectOperatorParameterResponse]
    return_type: str
    return_kind: Literal[
        "value", "object_value", "mutation_reference", "stream_reference"
    ]
    return_object_class_id: str | None = None
    return_type_metadata: FunctionTypeResponse | None = None
    is_const: bool


class ObjectSpecialMemberResponse(BaseModel):
    id: str
    kind: Literal[
        "copy_constructor",
        "copy_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
    ]
    display: str
    is_defaulted: bool


class ObjectClassResponse(BaseModel):
    id: str
    name: str
    kind: Literal["class", "struct"]
    constructors: list[ObjectConstructorResponse]
    methods: list[ObjectMethodResponse]
    operators: list[ObjectOperatorResponse] = Field(default_factory=list)
    special_members: list[ObjectSpecialMemberResponse] = Field(
        default_factory=list
    )


class SourceModeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]


class SourceModeResponse(BaseModel):
    mode: Literal["program", "function", "object", "unsupported"]
    functions: list[FunctionResponse] = Field(default_factory=list)
    classes: list[ObjectClassResponse] = Field(default_factory=list)
    available_modes: list[
        Literal["program", "function", "object"]
    ] = Field(default_factory=list)
    message: str | None = None


class ProgramTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    stdin: str = Field(default="", max_length=64 * 1024)
    expected_stdout: str = Field(max_length=64 * 1024)


class FunctionMutationExpectation(BaseModel):
    parameter_id: str = Field(min_length=1, max_length=100)
    expected_final_value: str = Field(max_length=1_000)

ExpectedOutcomeKind = Literal["return_value", "return_void", "throws"]
ExceptionMessageRule = Literal["ignore", "exact", "contains"]
ExceptionType = Literal[
    "any_std_exception",
    "std::exception",
    "std::runtime_error",
    "std::logic_error",
    "std::invalid_argument",
    "std::domain_error",
    "std::length_error",
    "std::out_of_range",
    "std::overflow_error",
    "std::underflow_error",
    "std::range_error",
    "std::bad_alloc",
    "std::bad_cast",
    "std::bad_typeid",
    "std::bad_function_call",
]


class FunctionTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    arguments: list[str] = Field(max_length=20)
    expected_return: str | None = Field(default=None, max_length=1_000)
    expected_stdout: str | None = Field(default=None, max_length=64 * 1024)
    check_stdout: bool | None = None
    expected_final_arguments: dict[str, str] | None = Field(
        default=None,
        max_length=1,
    )
    expected_mutations: list[FunctionMutationExpectation] | None = Field(
        default=None,
        min_length=1,
        max_length=20,
    )
    expected_outcome: ExpectedOutcomeKind | None = None
    expected_exception_type: ExceptionType | None = None
    exception_message_rule: ExceptionMessageRule = "ignore"
    expected_exception_message: str | None = Field(
        default=None, max_length=1_000
    )

    @model_validator(mode="after")
    def validate_expected_value(self) -> "FunctionTestCase":
        if self.expected_outcome is None:
            self.expected_outcome = (
                "return_value"
                if self.expected_return is not None
                else "return_void"
            )
        if self.expected_outcome == "throws":
            if not self.expected_exception_type:
                raise ValueError("Exception tests require an exception type.")
            if self.expected_return is not None:
                raise ValueError(
                    "Expected return and expected exception cannot be combined."
                )
            if (
                self.exception_message_rule in {"exact", "contains"}
                and not self.expected_exception_message
            ):
                raise ValueError(
                    "Exact and contains message matching require a message."
                )
            if self.exception_message_rule == "ignore":
                self.expected_exception_message = None
        else:
            if self.expected_exception_type is not None:
                raise ValueError(
                    "Exception fields require a throws outcome."
                )
            self.exception_message_rule = "ignore"
            self.expected_exception_message = None
            if (
                self.expected_outcome == "return_value"
                and self.expected_return is None
            ):
                raise ValueError("Return-value tests require an expected return.")
            if (
                self.expected_outcome == "return_void"
                and self.expected_return is not None
            ):
                raise ValueError("Void outcomes cannot include an expected return.")
        mutation_supplied = (
            self.expected_final_arguments is not None
            or self.expected_mutations is not None
        )
        if self.expected_outcome != "throws" and not any(
            (
                self.expected_return is not None,
                self.expected_stdout is not None,
                mutation_supplied,
            )
        ):
            raise ValueError("Provide at least one expected result channel.")
        if self.check_stdout is False and self.expected_stdout is not None:
            raise ValueError(
                "Expected stdout requires function-output checking."
            )
        if self.check_stdout is True and self.expected_stdout is None:
            raise ValueError(
                "Function-output checking requires expected stdout."
            )
        if (
            self.expected_final_arguments is not None
            and self.expected_mutations is not None
        ):
            raise ValueError("Provide only one mutation expectation format.")
        if self.expected_final_arguments is not None and any(
            not name or len(name) > 100 or len(value) > 1_000
            for name, value in self.expected_final_arguments.items()
        ):
            raise ValueError("Expected final argument values are invalid.")
        return self


class ProgramRunTestsRequest(BaseModel):
    mode: Literal["program"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    comparison_mode: Literal["whitespace_tolerant", "exact"] = (
        "whitespace_tolerant"
    )
    run_memory_checks: bool = False
    tests: list[ProgramTestCase] = Field(min_length=1, max_length=10)


class FunctionRunTestsRequest(BaseModel):
    mode: Literal["function"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    target_function: str = Field(min_length=1, max_length=300)
    comparison_mode: Literal["whitespace_tolerant", "exact"] = (
        "whitespace_tolerant"
    )
    run_memory_checks: bool = False
    tests: list[FunctionTestCase] = Field(min_length=1, max_length=10)


class ObjectScenarioStep(BaseModel):
    step_type: Literal[
        "create_object",
        "method",
        "observer",
        "operator",
        "copy_construct",
        "copy_assign",
        "self_assign",
        "move_construct",
        "move_assign",
    ] = "method"
    method_id: str | None = Field(default=None, max_length=500)
    class_id: str | None = Field(default=None, max_length=200)
    constructor_id: str | None = Field(default=None, max_length=500)
    operator_id: str | None = Field(default=None, max_length=700)
    target_object_id: str | None = Field(default=None, max_length=100)
    arguments: list[str] = Field(default_factory=list, max_length=20)
    operands: list[str] = Field(default_factory=list, max_length=20)
    result_object_id: str | None = Field(default=None, max_length=100)
    result_name: str | None = Field(default=None, max_length=100)
    special_member_id: str | None = Field(default=None, max_length=700)
    source_object_id: str | None = Field(default=None, max_length=100)
    expected_return: str | None = Field(default=None, max_length=1_000)
    check_stdout: bool = False
    expected_stdout: str | None = Field(default=None, max_length=64 * 1024)
    expected_outcome: ExpectedOutcomeKind | None = None
    expected_exception_type: ExceptionType | None = None
    exception_message_rule: ExceptionMessageRule = "ignore"
    expected_exception_message: str | None = Field(
        default=None, max_length=1_000
    )

    @model_validator(mode="after")
    def validate_stdout(self) -> "ObjectScenarioStep":
        if self.expected_outcome is None:
            self.expected_outcome = (
                "return_value"
                if self.expected_return is not None
                else "return_void"
            )
        if self.expected_outcome == "throws":
            if not self.expected_exception_type:
                raise ValueError("Exception steps require an exception type.")
            if self.expected_return is not None:
                raise ValueError(
                    "Expected return and expected exception cannot be combined."
                )
            if (
                self.exception_message_rule in {"exact", "contains"}
                and not self.expected_exception_message
            ):
                raise ValueError(
                    "Exact and contains message matching require a message."
                )
            if self.exception_message_rule == "ignore":
                self.expected_exception_message = None
        else:
            if self.expected_exception_type is not None:
                raise ValueError("Exception fields require a throws outcome.")
            self.exception_message_rule = "ignore"
            self.expected_exception_message = None
        if self.step_type == "create_object":
            if not self.result_object_id or not self.result_name:
                raise ValueError(
                    "Create-object steps require an object name."
                )
            if not self.class_id:
                raise ValueError("Create-object steps require a class.")
            if not self.constructor_id:
                raise ValueError(
                    "Create-object steps require a constructor."
                )
            if self.expected_outcome == "return_value":
                raise ValueError(
                    "Constructors cannot have an expected return value."
                )
        if self.step_type in {"method", "observer"} and not self.method_id:
            raise ValueError("Method steps require a method identifier.")
        if self.step_type == "operator" and not self.operator_id:
            raise ValueError("Operator steps require an operator identifier.")
        if self.step_type in {
            "copy_construct",
            "copy_assign",
            "self_assign",
            "move_construct",
            "move_assign",
        } and not self.special_member_id:
            raise ValueError(
                "Big Five steps require a special-member identifier."
            )
        if self.check_stdout and self.expected_stdout is None:
            raise ValueError(
                "Method-output checking requires expected stdout."
            )
        if not self.check_stdout and self.expected_stdout is not None:
            raise ValueError(
                "Expected stdout requires method-output checking."
            )
        return self


class ObjectScenarioObject(BaseModel):
    object_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    class_id: str = Field(min_length=1, max_length=200)
    constructor_id: str = Field(min_length=1, max_length=500)
    arguments: list[str] = Field(max_length=20)
    expected_outcome: Literal["return_void", "throws"] = "return_void"
    expected_exception_type: ExceptionType | None = None
    exception_message_rule: ExceptionMessageRule = "ignore"
    expected_exception_message: str | None = Field(
        default=None, max_length=1_000
    )

    @model_validator(mode="after")
    def validate_constructor_outcome(self) -> "ObjectScenarioObject":
        if self.expected_outcome == "throws":
            if not self.expected_exception_type:
                raise ValueError(
                    "Constructor exception tests require an exception type."
                )
            if (
                self.exception_message_rule in {"exact", "contains"}
                and not self.expected_exception_message
            ):
                raise ValueError(
                    "Exact and contains message matching require a message."
                )
            if self.exception_message_rule == "ignore":
                self.expected_exception_message = None
        elif self.expected_exception_type is not None:
            raise ValueError(
                "Constructor exception fields require a throws outcome."
            )
        return self


class ObjectScenarioTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    objects: list[ObjectScenarioObject] | None = Field(
        default=None, max_length=5
    )
    class_id: str | None = Field(default=None, max_length=200)
    constructor_id: str | None = Field(default=None, max_length=500)
    constructor_arguments: list[str] | None = Field(
        default=None, max_length=20
    )
    steps: list[ObjectScenarioStep] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_object_shape(self) -> "ObjectScenarioTestCase":
        if self.objects is None and not (
            self.class_id
            and self.constructor_id
            and self.constructor_arguments is not None
        ):
            raise ValueError("Provide scenario objects.")
        if self.objects is not None and self.class_id is not None:
            raise ValueError("Use either objects or the legacy object fields.")
        if self.objects == [] and not self.steps:
            raise ValueError(
                "Provide a setup object or an executable scenario step."
            )
        return self


class ObjectScenarioRunTestsRequest(BaseModel):
    mode: Literal["object"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    comparison_mode: Literal["whitespace_tolerant", "exact"] = (
        "whitespace_tolerant"
    )
    run_memory_checks: bool = False
    tests: list[ObjectScenarioTestCase] = Field(min_length=1, max_length=10)


RunTestsRequest = Annotated[
    ProgramRunTestsRequest
    | FunctionRunTestsRequest
    | ObjectScenarioRunTestsRequest,
    Field(discriminator="mode"),
]


MemoryStatus = Literal[
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
]
SanitizerCheckStatus = Literal[
    "not_run", "clean", "failed", "unavailable", "possible"
]


MemoryDiagnosisCategory = Literal[
    "memory_leak",
    "use_after_free",
    "double_free",
    "invalid_free",
    "out_of_bounds_read",
    "out_of_bounds_write",
    "stack_buffer_overflow",
    "heap_buffer_overflow",
    "global_buffer_overflow",
    "null_pointer_access",
    "uninitialized_read",
    "uninitialized_value",
    "mismatched_allocation_deallocation",
    "overlapping_memory_operation",
    "invalid_pointer_arithmetic",
    "dangling_reference",
    "lifetime_error",
    "resource_overwrite",
    "ownership_aliasing",
    "destructor_failure",
    "cleanup_failure",
    "undefined_behaviour",
    "memory_limit_exceeded",
    "allocator_failure",
    "leak_check_unavailable",
    "memory_check_incomplete",
    "unknown_memory_failure",
]


class MemorySourceRange(BaseModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    excerpt: str = Field(max_length=500)
    label: str = Field(max_length=100)
    confidence: Literal["confirmed", "likely", "possible"]


class MemoryDiagnosisResponse(BaseModel):
    category: MemoryDiagnosisCategory
    title: str = Field(max_length=120)
    confidence: Literal["confirmed", "likely", "possible"]
    summary: str = Field(max_length=500)
    likely_cause: str | None = Field(default=None, max_length=500)
    source_range: MemorySourceRange | None = None
    suggested_direction: str = Field(max_length=500)
    related_operation: str | None = Field(default=None, max_length=100)
    confirmed_by: list[str] = Field(default_factory=list, max_length=10)
    technical_details: list[str] = Field(default_factory=list, max_length=20)
    supporting_findings: list[str] = Field(default_factory=list, max_length=10)


class MemoryDiagnosticResult(BaseModel):
    memory_check_enabled: bool = False
    memory_status: MemoryStatus = "not_run"
    memory_summary: str | None = None
    memory_diagnostics: str | None = None
    address_sanitizer_available: bool | None = None
    undefined_behavior_sanitizer_available: bool | None = None
    leak_sanitizer_available: bool | None = None
    memory_access_status: SanitizerCheckStatus = "not_run"
    undefined_behavior_status: SanitizerCheckStatus = "not_run"
    leak_status: SanitizerCheckStatus = "not_run"
    execution_provider: Literal["host", "docker"] = "host"
    memory_tool: Literal[
        "none", "sanitizer", "valgrind", "sanitizer_and_valgrind"
    ] = "none"
    container_runtime_available: bool | None = None
    leaked_bytes: int | None = None
    leaked_allocations: int | None = None
    leak_kind: str | None = None
    memory_diagnoses: list[MemoryDiagnosisResponse] = Field(
        default_factory=list, max_length=3
    )


class ProgramTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    expected_stdout: str
    actual_stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal[
        "exact",
        "whitespace_normalized",
        "formatting_mismatch",
        "mismatch",
    ]


class FunctionTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    arguments: list[str]
    expected_return: str
    actual_return: str
    mismatch_detail: str | None = None
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "whitespace_normalized", "mismatch"]
    exception_result: "ExceptionOutcomeResult | None" = None


class FunctionOutputTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    arguments: list[str]
    expected_stdout: str
    actual_stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal[
        "exact",
        "whitespace_normalized",
        "formatting_mismatch",
        "mismatch",
    ]
    exception_result: "ExceptionOutcomeResult | None" = None


class FunctionMutationTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    initial_arguments: dict[str, str]
    expected_final_arguments: dict[str, str]
    actual_final_arguments: dict[str, str]
    mismatch_details: dict[str, str] = Field(default_factory=dict)
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "mismatch"]
    exception_result: "ExceptionOutcomeResult | None" = None


class FunctionChannelResult(BaseModel):
    expected: str
    actual: str
    passed: bool
    mismatch_detail: str | None = None
    match_type: Literal[
        "exact",
        "whitespace_normalized",
        "formatting_mismatch",
        "mismatch",
    ]


class ExceptionOutcomeResult(BaseModel):
    expected_outcome: ExpectedOutcomeKind
    actual_outcome: Literal[
        "returned",
        "threw_standard",
        "threw_non_standard",
        "crashed",
        "timed_out",
    ]
    expected_exception_type: ExceptionType | None = None
    actual_exception_type: str | None = None
    expected_message_rule: ExceptionMessageRule = "ignore"
    expected_message: str | None = None
    actual_message: str | None = None
    type_matched: bool | None = None
    message_matched: bool | None = None
    expectation_passed: bool
    execution_continued: bool


class FunctionMutationChannelResult(BaseModel):
    parameter: str
    initial: str
    expected_final: str
    actual_final: str
    passed: bool
    mismatch_detail: str | None = None


class FunctionCombinedTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    arguments: list[str]
    return_result: FunctionChannelResult | None = None
    stdout_result: FunctionChannelResult | None = None
    mutation_results: list[FunctionMutationChannelResult] = Field(
        default_factory=list
    )
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "mismatch"]
    exception_result: ExceptionOutcomeResult | None = None


class ObjectScenarioStepResult(BaseModel):
    index: int
    step_type: Literal[
        "create_object",
        "method",
        "observer",
        "operator",
        "copy_construct",
        "copy_assign",
        "self_assign",
        "move_construct",
        "move_assign",
    ] = "method"
    method_id: str | None = None
    operator_id: str | None = None
    method: str
    expression: str | None = None
    result_object_name: str | None = None
    status: Literal["completed", "failed", "not_executed"]
    passed: bool
    return_result: FunctionChannelResult | None = None
    stdout_result: FunctionChannelResult | None = None
    exception_result: ExceptionOutcomeResult | None = None


class SuspiciousSourceRange(BaseModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    snippet: str
    reason: str


class BigFiveDiagnosis(BaseModel):
    title: str
    confidence: Literal["confirmed", "likely", "possible"]
    summary: str
    evidence: list[str] = Field(default_factory=list)
    suspicious_ranges: list[SuspiciousSourceRange] = Field(
        default_factory=list
    )
    suggested_direction: str
    related_operation: Literal[
        "copy_constructor",
        "copy_assignment",
        "self_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
    ] | None = None


class ObjectScenarioTestResult(MemoryDiagnosticResult):
    name: str
    passed: bool
    class_name: str
    constructor: str
    constructor_arguments: list[str]
    constructor_completed: bool
    constructed_objects: list[str] = Field(default_factory=list)
    moved_from_objects: list[str] = Field(default_factory=list)
    destruction_failed: bool = False
    failed_step_index: int | None = None
    steps: list[ObjectScenarioStepResult]
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "mismatch"]
    big_five_diagnosis: BigFiveDiagnosis | None = None
    constructor_exception_result: ExceptionOutcomeResult | None = None


class RunTestsResponse(BaseModel):
    mode: Literal["program", "function", "object", "unsupported"]
    success: bool
    compile_error: str | None = None
    input_error: str | None = None
    unsupported_error: str | None = None
    memory_check_enabled: bool = False
    memory_status: MemoryStatus = "not_run"
    memory_summary: str | None = None
    memory_diagnostics: str | None = None
    address_sanitizer_available: bool | None = None
    undefined_behavior_sanitizer_available: bool | None = None
    leak_sanitizer_available: bool | None = None
    execution_provider: Literal["host", "docker"] = "host"
    memory_tool: Literal[
        "none", "sanitizer", "valgrind", "sanitizer_and_valgrind"
    ] = "none"
    container_runtime_available: bool | None = None
    function: FunctionResponse | None = None
    tests: list[
        FunctionTestResult
        | FunctionOutputTestResult
        | FunctionMutationTestResult
        | FunctionCombinedTestResult
        | ObjectScenarioTestResult
        | ProgramTestResult
    ]
