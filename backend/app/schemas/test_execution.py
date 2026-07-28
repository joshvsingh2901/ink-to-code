from typing import Annotated, Literal

from pydantic import BaseModel, Field


class FunctionParameterResponse(BaseModel):
    name: str
    type: str


class FunctionResponse(BaseModel):
    id: str
    name: str
    return_type: str
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
    expected_return: str = Field(max_length=1_000)


class ProgramRunTestsRequest(BaseModel):
    mode: Literal["program"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    tests: list[ProgramTestCase] = Field(min_length=1, max_length=10)


class FunctionRunTestsRequest(BaseModel):
    mode: Literal["function"]
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    target_function: str = Field(min_length=1, max_length=300)
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
    match_type: Literal["exact", "whitespace_normalized", "mismatch"]


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


class RunTestsResponse(BaseModel):
    mode: Literal["program", "function", "unsupported"]
    success: bool
    compile_error: str | None = None
    input_error: str | None = None
    unsupported_error: str | None = None
    function: FunctionResponse | None = None
    tests: list[ProgramTestResult | FunctionTestResult]
