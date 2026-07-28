from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class FunctionTypeResponse(BaseModel):
    kind: Literal["scalar", "vector", "array", "void"]
    display_type: str
    scalar_type: str | None = None
    element_type: str | None = None
    passing: Literal[
        "value",
        "const_reference",
        "mutable_reference",
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


class SourceModeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]


class SourceModeResponse(BaseModel):
    mode: Literal["program", "function", "unsupported"]
    functions: list[FunctionResponse] = Field(default_factory=list)
    message: str | None = None


class ProgramTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    stdin: str = Field(default="", max_length=64 * 1024)
    expected_stdout: str = Field(max_length=64 * 1024)


class FunctionTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    arguments: list[str] = Field(max_length=20)
    expected_return: str | None = Field(default=None, max_length=1_000)
    expected_stdout: str | None = Field(default=None, max_length=64 * 1024)
    expected_final_arguments: dict[str, str] | None = Field(
        default=None,
        max_length=1,
    )

    @model_validator(mode="after")
    def validate_expected_value(self) -> "FunctionTestCase":
        supplied = sum(
            value is not None
            for value in (
                self.expected_return,
                self.expected_stdout,
                self.expected_final_arguments,
            )
        )
        if supplied != 1:
            raise ValueError(
                "Provide exactly one expected result channel."
            )
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
    tests: list[ProgramTestCase] = Field(min_length=1, max_length=10)


class FunctionRunTestsRequest(BaseModel):
    mode: Literal["function"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    target_function: str = Field(min_length=1, max_length=300)
    comparison_mode: Literal["whitespace_tolerant", "exact"] = (
        "whitespace_tolerant"
    )
    tests: list[FunctionTestCase] = Field(min_length=1, max_length=10)


RunTestsRequest = Annotated[
    ProgramRunTestsRequest | FunctionRunTestsRequest,
    Field(discriminator="mode"),
]


class ProgramTestResult(BaseModel):
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


class FunctionTestResult(BaseModel):
    name: str
    passed: bool
    arguments: list[str]
    expected_return: str
    actual_return: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "whitespace_normalized", "mismatch"]


class FunctionOutputTestResult(BaseModel):
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


class FunctionMutationTestResult(BaseModel):
    name: str
    passed: bool
    initial_arguments: dict[str, str]
    expected_final_arguments: dict[str, str]
    actual_final_arguments: dict[str, str]
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "mismatch"]


class RunTestsResponse(BaseModel):
    mode: Literal["program", "function", "unsupported"]
    success: bool
    compile_error: str | None = None
    input_error: str | None = None
    unsupported_error: str | None = None
    function: FunctionResponse | None = None
    tests: list[
        FunctionTestResult
        | FunctionOutputTestResult
        | FunctionMutationTestResult
        | ProgramTestResult
    ]
