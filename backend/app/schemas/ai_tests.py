"""Schemas for AI test generation, validation, and results."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.test_execution import (
    ExceptionType,
    FunctionCombinedTestResult,
    FunctionTestCase,
    ObjectScenarioTestCase,
    ObjectScenarioTestResult,
    TemplateArgumentInput,
)


# ---------------------------------------------------------------------------
# Error class
# ---------------------------------------------------------------------------


class AiTestServiceError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Coverage categories
# ---------------------------------------------------------------------------

AiCoverageCategory = Literal[
    "normal",
    "zero",
    "negative",
    "boundary",
    "below_boundary",
    "above_boundary",
    "empty",
    "single_element",
    "duplicate",
    "ordering",
    "already_sorted",
    "reverse_sorted",
    "not_found",
    "first_element",
    "last_element",
    "mutation",
    "exception",
    "iterator_begin",
    "iterator_end",
    "empty_range",
    "full_range",
    "partial_range",
    "object_state",
    "template_case",
]

# ---------------------------------------------------------------------------
# Gemini response schemas — strict, extra="forbid" on every model
# ---------------------------------------------------------------------------

_STRICT = ConfigDict(extra="forbid")

_CPP_KEYWORDS = frozenset(
    {
        "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
        "bool", "break", "case", "catch", "char", "char8_t", "char16_t", "char32_t",
        "class", "compl", "concept", "const", "consteval", "constexpr", "constinit",
        "const_cast", "continue", "co_await", "co_return", "co_yield", "decltype",
        "default", "delete", "do", "double", "dynamic_cast", "else", "enum",
        "explicit", "export", "extern", "false", "float", "for", "friend", "goto",
        "if", "inline", "int", "long", "mutable", "namespace", "new", "noexcept",
        "not", "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
        "public", "register", "reinterpret_cast", "requires", "return", "short",
        "signed", "sizeof", "static", "static_assert", "static_cast", "struct",
        "switch", "template", "this", "thread_local", "throw", "true", "try",
        "typedef", "typeid", "typename", "union", "unsigned", "using", "virtual",
        "void", "volatile", "wchar_t", "while", "xor", "xor_eq",
    }
)


class AiModelMutation(BaseModel):
    model_config = _STRICT
    parameter_name: str = Field(min_length=1, max_length=100)
    expected_final_value: str = Field(max_length=1000)


class AiModelFunctionTest(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=80)
    category: AiCoverageCategory
    reason: str = Field(min_length=1, max_length=200)
    arguments: list[str] = Field(max_length=20)
    expected_outcome: Literal["return_value", "return_void", "throws"]
    expected_return: str | None = Field(default=None, max_length=1000)
    expected_stdout: str | None = Field(default=None, max_length=2000)
    expected_mutations: list[AiModelMutation] = Field(
        default_factory=list, max_length=20
    )
    expected_exception_type: ExceptionType | None = None
    exception_message_rule: Literal["ignore", "contains"] = "ignore"
    expected_exception_message: str | None = Field(default=None, max_length=200)


class AiModelTestPlan(BaseModel):
    model_config = _STRICT
    target_id: str = Field(min_length=1, max_length=300)
    tests: list[AiModelFunctionTest] = Field(min_length=0, max_length=8)
    skipped_topics: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("skipped_topics")
    @classmethod
    def _validate_skipped(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 200:
                raise ValueError("Each skipped_topics entry must be ≤ 200 characters.")
        return v


# --- Object variant ---


class AiModelScenarioObject(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=50)
    constructor_id: str
    arguments: list[str] = Field(max_length=20)
    expected_outcome: Literal["return_void", "throws"] = "return_void"
    expected_exception_type: ExceptionType | None = None

    @field_validator("name")
    @classmethod
    def _no_keywords(cls, v: str) -> str:
        if not v.isidentifier():
            raise ValueError(f"Object name '{v}' is not a valid C++ identifier.")
        if v in _CPP_KEYWORDS:
            raise ValueError(f"Object name '{v}' collides with a C++ keyword.")
        return v


class AiModelScenarioStep(BaseModel):
    model_config = _STRICT
    step_type: Literal["method", "observer"]
    target_object_name: str
    method_id: str
    arguments: list[str] = Field(default_factory=list, max_length=20)
    expected_outcome: Literal["return_value", "return_void", "throws"]
    expected_return: str | None = Field(default=None, max_length=1000)
    check_stdout: bool = False
    expected_stdout: str | None = Field(default=None, max_length=2000)
    expected_exception_type: ExceptionType | None = None
    exception_message_rule: Literal["ignore", "contains"] = "ignore"
    expected_exception_message: str | None = Field(default=None, max_length=200)


class AiModelScenarioTest(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=80)
    category: AiCoverageCategory
    reason: str = Field(min_length=1, max_length=200)
    objects: list[AiModelScenarioObject] = Field(min_length=1, max_length=5)
    steps: list[AiModelScenarioStep] = Field(min_length=1, max_length=10)


class AiModelScenarioPlan(BaseModel):
    model_config = _STRICT
    target_id: str = Field(min_length=1, max_length=300)
    tests: list[AiModelScenarioTest] = Field(min_length=0, max_length=8)
    skipped_topics: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("skipped_topics")
    @classmethod
    def _validate_skipped(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 200:
                raise ValueError("Each skipped_topics entry must be ≤ 200 characters.")
        return v


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class AiScore(BaseModel):
    passed: int
    executed: int
    percentage: int


class AiTestResultRow(BaseModel):
    id: str
    name: str
    category: AiCoverageCategory
    reason: str
    passed: bool
    input_summary: str
    expected_summary: str
    actual_summary: str
    detail: FunctionCombinedTestResult | ObjectScenarioTestResult | None = None


class AiStoredTest(BaseModel):
    id: str
    name: str
    category: AiCoverageCategory
    reason: str
    function_test: FunctionTestCase | None = None
    scenario_test: ObjectScenarioTestCase | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "AiStoredTest":
        has_fn = self.function_test is not None
        has_sc = self.scenario_test is not None
        if has_fn == has_sc:
            raise ValueError(
                "Exactly one of function_test or scenario_test must be present."
            )
        return self


_AI_STATUS = Literal[
    "completed",
    "missing_question",
    "compile_failed",
    "unsupported",
    "source_too_large",
    "generation_timeout",
    "generation_rate_limited",
    "generation_unavailable",
    "generation_failed",
    "no_useful_tests",
    "infrastructure_failed",
    "incompatible",
]

PRACTICE_DISCLAIMER = (
    "This is a practice score based on AI-generated tests, "
    "not an official course grade."
)


class AiTestRunResponse(BaseModel):
    status: _AI_STATUS
    message: str | None = None
    unsupported_reason: str | None = None
    unsupported_parameters: list[list[str]] = []
    supported_targets: list[str] = []
    score: AiScore | None = None
    tests: list[AiTestResultRow] = []
    stored_tests: list[AiStoredTest] = []
    skipped_topics: list[str] = []
    generation_note: str | None = None
    memory_status: Literal["not_run"] = "not_run"
    disclaimer: str = PRACTICE_DISCLAIMER


class AiTestRunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    question_text: str = Field(min_length=1, max_length=8000)
    target_kind: Literal["function", "object"]
    target_id: str = Field(min_length=1, max_length=300)
    template_argument_mode: Literal["deduced", "explicit"] | None = None
    template_arguments: list[TemplateArgumentInput] = Field(
        default_factory=list, max_length=10
    )


class AiTestRerunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=1_000_000)
    language: Literal["cpp"]
    target_kind: Literal["function", "object"]
    target_id: str = Field(min_length=1, max_length=300)
    template_argument_mode: Literal["deduced", "explicit"] | None = None
    template_arguments: list[TemplateArgumentInput] = Field(
        default_factory=list, max_length=10
    )
    tests: list[AiStoredTest] = Field(min_length=1, max_length=8)
