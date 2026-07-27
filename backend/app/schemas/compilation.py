from pydantic import BaseModel, Field


class CompileRequest(BaseModel):
    code: str = Field(max_length=1_000_000)
    language: str


class CompileResponse(BaseModel):
    success: bool
    stdout: str
    stderr: str
    exit_code: int
