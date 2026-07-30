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

    @model_validator(mode="after")
    def validate_expected_value(self) -> "FunctionTestCase":
        mutation_supplied = (
            self.expected_final_arguments is not None
            or self.expected_mutations is not None
        )
        if not any(
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

    @model_validator(mode="after")
    def validate_stdout(self) -> "ObjectScenarioStep":
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


class ObjectScenarioTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    objects: list[ObjectScenarioObject] | None = Field(
        default=None, min_length=1, max_length=5
    )
    class_id: str | None = Field(default=None, max_length=200)
    constructor_id: str | None = Field(default=None, max_length=500)
    constructor_arguments: list[str] | None = Field(
        default=None, max_length=20
    )
    steps: list[ObjectScenarioStep] = Field(min_length=1, max_length=20)

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


class ObjectScenarioStepResult(BaseModel):
    index: int
    step_type: Literal[
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
