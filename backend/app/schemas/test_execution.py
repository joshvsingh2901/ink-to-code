from typing import Literal

from pydantic import BaseModel, Field


class ExecutionTestCase(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    stdin: str = Field(default="", max_length=64 * 1024)
    expected_stdout: str = Field(max_length=64 * 1024)


class RunTestsRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    tests: list[ExecutionTestCase] = Field(min_length=1, max_length=10)


class ExecutionTestResult(BaseModel):
    name: str
    passed: bool
    expected_stdout: str
    actual_stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    output_limited: bool
    match_type: Literal["exact", "whitespace_normalized", "mismatch"]


class RunTestsResponse(BaseModel):
    success: bool
    compile_error: str | None
    tests: list[ExecutionTestResult]
