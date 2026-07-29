import shutil

import pytest

from app.schemas.test_execution import ObjectScenarioRunTestsRequest
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request


TEXT_SOURCE = """
#include <string>
#include <utility>
class Text {
    std::string value;
public:
    Text(std::string value): value{value} {}
    Text(const Text& other): value{other.value} {}
    Text& operator=(const Text& other) {
        if (this != &other) value = other.value;
        return *this;
    }
    Text(Text&& other) noexcept: value{std::move(other.value)} {}
    Text& operator=(Text&& other) noexcept {
        if (this != &other) value = std::move(other.value);
        return *this;
    }
    void append(std::string suffix) { value += suffix; }
    std::string get() const { return value; }
};
"""


def metadata(source=TEXT_SOURCE):
    object_class = analyze_object_scenarios(source).classes[0]
    members = {item.kind: item for item in object_class.special_members}
    methods = {item.name: item for item in object_class.methods}
    return object_class, members, methods


def request(steps, objects=None, source=TEXT_SOURCE):
    object_class, _, _ = metadata(source)
    constructor = object_class.constructors[0]
    return ObjectScenarioRunTestsRequest(
        mode="object",
        code=source,
        language="cpp",
        tests=[
            {
                "name": "Big Five",
                "objects": objects
                or [
                    {
                        "object_id": "original",
                        "name": "original",
                        "class_id": object_class.id,
                        "constructor_id": constructor.id,
                        "arguments": ["hello"],
                    }
                ],
                "steps": steps,
            }
        ],
    )


def test_discovers_explicit_and_defaulted_special_members():
    source = """
    class Value {
    public:
        Value(int value) {}
        Value(const Value& other) = default;
        Value(Value&& other) = default;
        Value& operator=(const Value& other) = default;
        Value& operator=(Value&& other) = default;
        ~Value() = default;
        int get() const { return 1; }
    };
    """
    object_class = analyze_object_scenarios(source).classes[0]

    assert {item.kind for item in object_class.special_members} == {
        "copy_constructor",
        "copy_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
    }
    assert all(item.is_defaulted for item in object_class.special_members)


def test_private_protected_and_deleted_special_members_are_excluded():
    source = """
    class Value {
        Value(const Value& other) {}
    protected:
        Value(Value&& other) {}
    public:
        Value() {}
        Value& operator=(const Value& other) = delete;
        int get() const { return 1; }
    };
    """
    assert analyze_object_scenarios(source).classes[0].special_members == ()


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_copy_construction_independence_and_self_assignment():
    _, members, methods = metadata()
    result = run_test_request(
        request(
            [
                {
                    "step_type": "copy_construct",
                    "special_member_id": members["copy_constructor"].id,
                    "target_object_id": "original",
                    "source_object_id": "original",
                    "result_object_id": "copied",
                    "result_name": "copied",
                },
                {
                    "step_type": "method",
                    "target_object_id": "copied",
                    "method_id": methods["append"].id,
                    "arguments": ["-copy"],
                },
                {
                    "step_type": "self_assign",
                    "target_object_id": "original",
                    "source_object_id": "original",
                    "special_member_id": members["copy_assignment"].id,
                },
                {
                    "step_type": "observer",
                    "target_object_id": "original",
                    "method_id": methods["get"].id,
                    "expected_return": "hello",
                },
                {
                    "step_type": "observer",
                    "target_object_id": "copied",
                    "method_id": methods["get"].id,
                    "expected_return": "hello-copy",
                },
            ]
        )
    )
    assert result.success is True


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_copy_and_move_assignment_preserve_targets():
    object_class, members, methods = metadata()
    constructor = object_class.constructors[0]
    objects = [
        {
            "object_id": "source",
            "name": "source",
            "class_id": object_class.id,
            "constructor_id": constructor.id,
            "arguments": ["source"],
        },
        {
            "object_id": "target",
            "name": "target",
            "class_id": object_class.id,
            "constructor_id": constructor.id,
            "arguments": ["target"],
        },
    ]
    copy_result = run_test_request(
        request(
            [
                {
                    "step_type": "copy_assign",
                    "target_object_id": "target",
                    "source_object_id": "source",
                    "special_member_id": members["copy_assignment"].id,
                },
                {
                    "step_type": "observer",
                    "target_object_id": "target",
                    "method_id": methods["get"].id,
                    "expected_return": "source",
                },
            ],
            objects,
        )
    )
    move_result = run_test_request(
        request(
            [
                {
                    "step_type": "move_assign",
                    "target_object_id": "target",
                    "source_object_id": "source",
                    "special_member_id": members["move_assignment"].id,
                },
                {
                    "step_type": "observer",
                    "target_object_id": "target",
                    "method_id": methods["get"].id,
                    "expected_return": "source",
                },
            ],
            objects,
        )
    )
    assert copy_result.success is True
    assert move_result.success is True
    assert move_result.tests[0].moved_from_objects == ["source"]


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_move_construction_creates_usable_destination():
    _, members, methods = metadata()
    result = run_test_request(
        request(
            [
                {
                    "step_type": "move_construct",
                    "target_object_id": "original",
                    "source_object_id": "original",
                    "special_member_id": members["move_constructor"].id,
                    "result_object_id": "moved",
                    "result_name": "moved",
                },
                {
                    "step_type": "observer",
                    "target_object_id": "moved",
                    "method_id": methods["get"].id,
                    "expected_return": "hello",
                },
            ]
        )
    )
    assert result.success is True
    assert result.tests[0].moved_from_objects == ["original"]


def test_moved_from_stale_and_duplicate_validation():
    _, members, methods = metadata()
    moved_then_observed = request(
        [
            {
                "step_type": "move_construct",
                "target_object_id": "original",
                "source_object_id": "original",
                "special_member_id": members["move_constructor"].id,
                "result_object_id": "moved",
                "result_name": "moved",
            },
            {
                "step_type": "observer",
                "target_object_id": "original",
                "method_id": methods["get"].id,
                "expected_return": "",
            },
        ]
    )
    stale = request(
        [
            {
                "step_type": "copy_construct",
                "target_object_id": "original",
                "source_object_id": "original",
                "special_member_id": "stale",
                "result_object_id": "copy",
                "result_name": "copy",
            }
        ]
    )
    duplicate = request(
        [
            {
                "step_type": "copy_construct",
                "target_object_id": "original",
                "source_object_id": "original",
                "special_member_id": members["copy_constructor"].id,
                "result_object_id": "copy",
                "result_name": "original",
            }
        ]
    )
    assert "moved-from" in run_test_request(moved_then_observed).input_error
    assert run_test_request(stale).input_error
    assert run_test_request(duplicate).input_error


@pytest.mark.skipif(shutil.which("g++") is None, reason="g++ is not installed")
def test_destruction_failure_is_classified_after_completed_steps():
    source = """
    class Crash {
    public:
        Crash() {}
        Crash(const Crash&) {}
        ~Crash() { int* value = nullptr; *value = 1; }
        int get() const { return 1; }
    };
    """
    object_class, members, methods = metadata(source)
    constructor = object_class.constructors[0]
    result = run_test_request(
        request(
            [
                {
                    "step_type": "observer",
                    "target_object_id": "original",
                    "method_id": methods["get"].id,
                    "expected_return": "1",
                }
            ],
            [
                {
                    "object_id": "original",
                    "name": "original",
                    "class_id": object_class.id,
                    "constructor_id": constructor.id,
                    "arguments": [],
                }
            ],
            source,
        )
    )
    assert members["copy_constructor"]
    assert result.success is False
    assert result.tests[0].steps[0].passed is True
    assert result.tests[0].destruction_failed is True
