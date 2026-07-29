import asyncio
import shutil

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.test_execution import (
    ObjectScenarioRunTestsRequest,
    ObjectScenarioStep,
    ObjectScenarioTestCase,
)
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request


async def api_request(path: str, payload: object):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.post(path, json=payload)


def object_request(
    code: str,
    *,
    constructor_index: int = 0,
    constructor_arguments: list[str] | None = None,
    steps: list[dict[str, object]],
    class_index: int = 0,
    comparison_mode: str = "whitespace_tolerant",
) -> ObjectScenarioRunTestsRequest:
    analysis = analyze_object_scenarios(code)
    object_class = analysis.classes[class_index]
    scenario_steps = []
    for step in steps:
        method = object_class.methods[int(step["method_index"])]
        scenario_steps.append(
            ObjectScenarioStep(
                method_id=method.id,
                arguments=list(step.get("arguments", [])),
                expected_return=step.get("expected_return"),
                check_stdout=bool(step.get("check_stdout", False)),
                expected_stdout=step.get("expected_stdout"),
            )
        )
    return ObjectScenarioRunTestsRequest(
        mode="object",
        code=code,
        language="cpp",
        comparison_mode=comparison_mode,
        tests=[
            ObjectScenarioTestCase(
                name="Scenario 1",
                class_id=object_class.id,
                constructor_id=object_class.constructors[
                    constructor_index
                ].id,
                constructor_arguments=constructor_arguments or [],
                steps=scenario_steps,
            )
        ],
    )


COUNTER_SOURCE = """
class Counter
{
    int value;
public:
    Counter(int value): value{value} {}
    void increment() { value++; }
    int getValue() const { return value; }
};
"""


def test_discovers_public_constructor_and_methods_only():
    analysis = analyze_object_scenarios(
        """
        class Sample {
            Sample(double) {}
            void hidden() {}
        protected:
            void protectedMethod() {}
        public:
            Sample() {}
            Sample(int value) {}
            void update(int value) {}
            int value() const { return 1; }
            static int staticValue() { return 1; }
            Sample(const Sample&) = delete;
        };
        """
    )

    assert len(analysis.classes) == 1
    object_class = analysis.classes[0]
    assert [item.id for item in object_class.constructors] == [
        "Sample::Sample()",
        "Sample::Sample(int)",
    ]
    assert [item.id for item in object_class.methods] == [
        "Sample::update(int)->void",
        "Sample::value() const->int",
    ]


def test_struct_members_default_to_public():
    analysis = analyze_object_scenarios(
        "struct Value { Value() {} int get() const { return 1; } };"
    )

    assert len(analysis.classes) == 1
    assert analysis.classes[0].kind == "struct"


def test_overloaded_methods_use_full_signature_ids():
    analysis = analyze_object_scenarios(
        """
        class Converter {
        public:
            Converter() {}
            int convert(int value) const { return value * 2; }
            double convert(double value) const { return value / 2.0; }
        };
        """
    )

    assert [method.id for method in analysis.classes[0].methods] == [
        "Converter::convert(int) const->int",
        "Converter::convert(double) const->double",
    ]


def test_test_mode_endpoint_exposes_object_target():
    response = asyncio.run(
        api_request(
            "/api/test-mode",
            {"code": COUNTER_SOURCE, "language": "cpp"},
        )
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "object"
    assert payload["available_modes"] == ["object"]
    assert payload["classes"][0]["name"] == "Counter"
    assert payload["classes"][0]["constructors"][0]["display"] == (
        "Counter(int)"
    )


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_ordered_stateful_scenario_passes():
    result = run_test_request(
        object_request(
            COUNTER_SOURCE,
            constructor_arguments=["5"],
            steps=[
                {"method_index": 0},
                {"method_index": 0},
                {"method_index": 1, "expected_return": "7"},
            ],
        )
    )

    assert result.success is True
    assert [step.status for step in result.tests[0].steps] == [
        "completed",
        "completed",
        "completed",
    ]
    assert result.tests[0].steps[2].return_result.actual == "7"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_overloaded_constructor_and_string_observer():
    source = """
    #include <string>
    class User {
        std::string name;
        int score;
    public:
        User(): name{"unknown"}, score{0} {}
        User(std::string name, int score): name{name}, score{score} {}
        void addScore(int amount) { score += amount; }
        int getScore() const { return score; }
        std::string getName() const { return name; }
    };
    """
    result = run_test_request(
        object_request(
            source,
            constructor_index=1,
            constructor_arguments=["Josh", "10"],
            steps=[
                {"method_index": 0, "arguments": ["5"]},
                {"method_index": 1, "expected_return": "15"},
                {"method_index": 2, "expected_return": "Josh"},
            ],
        )
    )

    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_method_return_mismatch_fails_only_that_step():
    result = run_test_request(
        object_request(
            COUNTER_SOURCE,
            constructor_arguments=["5"],
            steps=[
                {"method_index": 0},
                {"method_index": 1, "expected_return": "8"},
            ],
        )
    )

    assert result.success is False
    assert result.tests[0].steps[0].passed is True
    assert result.tests[0].steps[1].return_result.passed is False
    assert result.tests[0].steps[1].return_result.actual == "6"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize(
    ("expected_stdout", "passed"),
    [("9", True), ("8", False)],
)
def test_checked_method_stdout_is_per_step(
    expected_stdout: str,
    passed: bool,
):
    source = """
    #include <iostream>
    class Printer {
        int value;
    public:
        Printer(int value): value{value} {}
        void print() const { std::cout << value; }
    };
    """
    result = run_test_request(
        object_request(
            source,
            constructor_arguments=["9"],
            steps=[
                {
                    "method_index": 0,
                    "check_stdout": True,
                    "expected_stdout": expected_stdout,
                }
            ],
        )
    )

    assert result.success is passed
    assert result.tests[0].steps[0].stdout_result.actual == "9"


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_method_return_and_stdout_both_must_match():
    source = """
    #include <iostream>
    class Value {
    public:
        Value() {}
        int show() const { std::cout << "value"; return 3; }
    };
    """
    result = run_test_request(
        object_request(
            source,
            steps=[
                {
                    "method_index": 0,
                    "expected_return": "3",
                    "check_stdout": True,
                    "expected_stdout": "value",
                }
            ],
        )
    )

    assert result.success is True


def test_stale_and_wrong_class_member_ids_are_rejected():
    request = object_request(
        COUNTER_SOURCE,
        constructor_arguments=["5"],
        steps=[{"method_index": 0}],
    )
    request.tests[0].constructor_id = "Other::Other()"
    constructor_result = run_test_request(request)
    request = object_request(
        COUNTER_SOURCE,
        constructor_arguments=["5"],
        steps=[{"method_index": 0}],
    )
    request.tests[0].steps[0].method_id = "Other::increment()->void"
    method_result = run_test_request(request)

    assert "constructor" in (constructor_result.input_error or "")
    assert "method" in (method_result.input_error or "")


def test_constructor_and_method_argument_validation_precedes_compile(
    monkeypatch,
):
    invoked = False

    def unexpected_compile(*_args, **_kwargs):
        nonlocal invoked
        invoked = True

    from app.services import test_execution

    monkeypatch.setattr(test_execution, "_compile_executable", unexpected_compile)
    constructor_result = run_test_request(
        object_request(
            COUNTER_SOURCE,
            constructor_arguments=["invalid"],
            steps=[{"method_index": 0}],
        )
    )
    method_result = run_test_request(
        object_request(
            """
            class Value {
            public:
                Value() {}
                int add(int amount) { return amount; }
            };
            """,
            steps=[
                {
                    "method_index": 0,
                    "arguments": ["invalid"],
                    "expected_return": "1",
                }
            ],
        )
    )

    assert constructor_result.input_error
    assert method_result.input_error
    assert invoked is False


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
@pytest.mark.parametrize("failure", ["timeout", "crash"])
def test_runtime_failure_marks_later_steps_not_executed(failure: str):
    method = (
        "void fail() { while (true) {} }"
        if failure == "timeout"
        else "void fail() { int* value = nullptr; *value = 1; }"
    )
    source = f"""
    class Failure {{
    public:
        Failure() {{}}
        {method}
        int later() const {{ return 1; }}
    }};
    """
    result = run_test_request(
        object_request(
            source,
            steps=[
                {"method_index": 0},
                {"method_index": 1, "expected_return": "1"},
            ],
        ),
        test_timeout_seconds=0.5,
    )

    scenario = result.tests[0]
    assert result.success is False
    assert scenario.steps[0].status == "failed"
    assert scenario.steps[1].status == "not_executed"


def test_private_fields_never_appear_in_metadata():
    analysis = analyze_object_scenarios(COUNTER_SOURCE)
    serialized = repr(analysis.classes[0])

    assert "value_type" in serialized
    assert "hidden" not in serialized
    assert all(
        parameter.name != "value"
        for method in analysis.classes[0].methods
        for parameter in method.parameters
    )


def test_unsupported_object_features_are_excluded():
    cases = [
        "class Child : public Base { public: Child() {} void run() {} };",
        (
            "class Static { public: Static() {} "
            "static void run() {} };"
        ),
    ]

    for source in cases:
        assert not analyze_object_scenarios(source).classes


def test_existing_safe_reference_and_array_arguments_are_discovered():
    source = """
    class Values {
    public:
        Values(int &seed): seed_{seed} {}
        int sum(int values[], int size) {
            int result = seed_;
            for (int i = 0; i < size; ++i) result += values[i];
            return result;
        }
    private:
        int seed_;
    };
    """

    object_class = analyze_object_scenarios(source).classes[0]

    assert (
        object_class.constructors[0].parameters[0].value_type.passing
        == "mutable_reference"
    )
    assert (
        object_class.methods[0].parameters[0].value_type.passing
        == "array_pointer"
    )
