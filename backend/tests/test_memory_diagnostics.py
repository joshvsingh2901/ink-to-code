import shutil
from pathlib import Path

import pytest

from app.schemas.test_execution import (
    ObjectScenarioRunTestsRequest,
    ProgramRunTestsRequest,
    ProgramTestCase,
)
from app.services.object_analysis import analyze_object_scenarios
from app.services import test_execution
from app.services.execution_providers import DockerExecutionProvider
from app.services.test_execution import (
    OUTPUT_LIMIT_MESSAGE,
    SanitizerCapabilities,
    TEST_OUTPUT_LIMIT_BYTES,
    _classify_memory_diagnostics,
    run_cpp_tests,
)


def test_memory_checks_default_to_false():
    request = ProgramRunTestsRequest(
        mode="program",
        code="int main() {}",
        language="cpp",
        tests=[ProgramTestCase(name="Test", expected_stdout="")],
    )
    assert request.run_memory_checks is False


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("ERROR: AddressSanitizer: heap-use-after-free", "use_after_free"),
        ("ERROR: AddressSanitizer: attempting double-free", "double_free"),
        (
            "ERROR: AddressSanitizer: attempting free on address "
            "which was not malloc()-ed",
            "invalid_free",
        ),
        ("ERROR: AddressSanitizer: heap-buffer-overflow", "buffer_overflow"),
        ("ERROR: LeakSanitizer: detected memory leaks", "leak"),
        ("runtime error: signed integer overflow", "undefined_behavior"),
        ("AddressSanitizer:DEADLYSIGNAL", "runtime_error"),
    ],
)
def test_sanitizer_diagnostics_are_classified(
    tmp_path: Path, diagnostic: str, expected: str
):
    status, _, details = _classify_memory_diagnostics(
        diagnostic, tmp_path
    )
    assert status == expected
    assert details


def test_diagnostic_paths_are_removed_and_output_is_limited(tmp_path: Path):
    diagnostic = (
        f"{tmp_path}/main.cpp:7: runtime error: division by zero\n"
        + ("x" * TEST_OUTPUT_LIMIT_BYTES)
    )
    status, _, details = _classify_memory_diagnostics(
        diagnostic, tmp_path
    )
    assert status == "undefined_behavior"
    assert details is not None
    assert str(tmp_path) not in details
    assert "<temporary>/main.cpp:7" in details
    assert details.endswith(OUTPUT_LIMIT_MESSAGE)


@pytest.mark.skipif(
    shutil.which("g++") is None and shutil.which("clang++") is None,
    reason="No C++ compiler is installed",
)
def test_supported_sanitizer_run_reports_clean():
    result = run_cpp_tests(
        "int main() { return 0; }",
        [ProgramTestCase(name="Clean", expected_stdout="")],
        run_memory_checks=True,
    )
    if result.memory_status == "unavailable":
        pytest.skip("The installed compiler does not support sanitizers")
    if result.leak_sanitizer_available:
        assert result.success is True
        assert result.tests[0].memory_status == "clean"
    else:
        assert result.success is True
        assert result.tests[0].memory_status == "partial"
        assert result.tests[0].memory_access_status == "clean"
        assert result.tests[0].undefined_behavior_status == "clean"
        assert result.tests[0].leak_status == "unavailable"
    assert result.tests[0].memory_check_enabled is True


def test_asan_available_without_leaks_cannot_report_fully_clean(tmp_path: Path):
    output = test_execution.ProcessOutput(
        stdout="",
        stderr="",
        exit_code=0,
        timed_out=False,
        output_limited=False,
    )
    capabilities = SanitizerCapabilities(True, True, False)
    statuses = test_execution._sanitizer_channel_statuses(
        "clean", capabilities, True
    )
    assert statuses == ("clean", "clean", "unavailable")
    assert test_execution._memory_is_clean(
        output.__class__(
            **{
                **output.__dict__,
                "memory_status": "partial",
                "memory_access_status": "clean",
                "undefined_behavior_status": "clean",
                "leak_status": "unavailable",
            }
        ),
        True,
    ) is True


@pytest.mark.skipif(
    shutil.which("g++") is None and shutil.which("clang++") is None,
    reason="No C++ compiler is installed",
)
def test_sanitizer_failure_overrides_correct_output():
    result = run_cpp_tests(
        """
        #include <iostream>
        int main() {
            int* value = new int(7);
            delete value;
            std::cout << 7;
            return *value;
        }
        """,
        [ProgramTestCase(name="Memory failure", expected_stdout="7")],
        run_memory_checks=True,
    )
    if result.memory_status == "unavailable":
        pytest.skip("The installed compiler does not support sanitizers")
    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].memory_status == "use_after_free"


@pytest.mark.skipif(
    shutil.which("g++") is None and shutil.which("clang++") is None,
    reason="No C++ compiler is installed",
)
def test_destruction_time_sanitizer_error_fails_object_scenario(monkeypatch):
    source = """
    class Broken {
        int* value;
    public:
        Broken(int input): value{new int{input}} {}
        Broken(const Broken& other): value{other.value} {}
        ~Broken() { delete value; }
        int get() const { return *value; }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]
    constructor = object_class.constructors[0]
    copy_member = next(
        item
        for item in object_class.special_members
        if item.kind == "copy_constructor"
    )
    observer = next(
        item for item in object_class.methods if item.name == "get"
    )
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        run_memory_checks=True,
        tests=[
            {
                "name": "Broken copy",
                "objects": [
                    {
                        "object_id": "original",
                        "name": "original",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["5"],
                    }
                ],
                "steps": [
                    {
                        "step_type": "copy_construct",
                        "target_object_id": "original",
                        "source_object_id": "original",
                        "result_object_id": "copy",
                        "result_name": "copy",
                        "special_member_id": copy_member.id,
                    },
                    {
                        "step_type": "observer",
                        "target_object_id": "copy",
                        "method_id": observer.id,
                        "expected_return": "5",
                    },
                ],
            }
        ],
    )
    result = test_execution.run_test_request(request)
    if result.memory_status == "unavailable":
        pytest.skip("The installed compiler does not support sanitizers")
    assert result.success is False
    assert result.tests[0].passed is False
    assert result.tests[0].destruction_failed is True
    assert result.tests[0].memory_status in {
        "double_free",
        "invalid_free",
        "use_after_free",
    }
    assert result.execution_provider == "docker"


@pytest.mark.skipif(
    shutil.which("g++") is None and shutil.which("clang++") is None,
    reason="No C++ compiler is installed",
)
def test_supported_leak_detection_classifies_allocation_leak():
    capabilities = DockerExecutionProvider().capabilities()
    if not capabilities.leak_sanitizer_available:
        pytest.skip("LeakSanitizer is unavailable")
    result = run_cpp_tests(
        "int main() { new int(7); return 0; }",
        [ProgramTestCase(name="Leak", expected_stdout="")],
        run_memory_checks=True,
    )
    assert result.success is False
    assert result.tests[0].memory_status == "leak"
    assert result.tests[0].leak_status == "failed"


@pytest.mark.skipif(
    shutil.which("g++") is None and shutil.which("clang++") is None,
    reason="No C++ compiler is installed",
)
def test_broken_move_assignment_never_reports_fully_clean():
    source = """
    class Number {
        int* value;
    public:
        Number(int input): value{new int{input}} {}
        Number(Number&& other) noexcept: value{other.value} {
            other.value = nullptr;
        }
        Number& operator=(Number&& other) noexcept {
            value = other.value;
            other.value = nullptr;
            return *this;
        }
        ~Number() { delete value; }
        int get() const { return *value; }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]
    constructor = object_class.constructors[0]
    move_assignment = next(
        member
        for member in object_class.special_members
        if member.kind == "move_assignment"
    )
    observer = next(
        method for method in object_class.methods if method.name == "get"
    )
    request = ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        run_memory_checks=True,
        tests=[
            {
                "name": "Leaking move assignment",
                "objects": [
                    {
                        "object_id": "source",
                        "name": "source",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["5"],
                    },
                    {
                        "object_id": "target",
                        "name": "target",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["20"],
                    },
                ],
                "steps": [
                    {
                        "step_type": "move_assign",
                        "target_object_id": "target",
                        "source_object_id": "source",
                        "special_member_id": move_assignment.id,
                    },
                    {
                        "step_type": "observer",
                        "target_object_id": "target",
                        "method_id": observer.id,
                        "expected_return": "5",
                    },
                ],
            }
        ],
    )
    result = test_execution.run_test_request(request)
    test_result = result.tests[0]

    assert all(step.passed for step in test_result.steps)
    assert test_result.memory_status != "clean"
    if result.leak_sanitizer_available:
        assert result.success is False
        assert test_result.memory_status == "leak"
        assert test_result.leak_status == "failed"
    else:
        assert result.success is True
        assert test_result.memory_status == "partial"
        assert test_result.memory_access_status == "clean"
        assert test_result.undefined_behavior_status == "clean"
        assert test_result.leak_status == "unavailable"
