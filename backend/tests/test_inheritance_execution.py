import pytest

from app.schemas.test_execution import ObjectScenarioRunTestsRequest
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request


VIRTUAL_SOURCE = """
class Animal
{
public:
    virtual int sound() const { return 0; }
    virtual ~Animal() = default;
};

class Dog : public Animal
{
public:
    int sound() const override { return 1; }
};

class Cat : public Animal
{
public:
    int sound() const override { return 2; }
};
"""


def _step(step_type: str, **values):
    return {
        "step_type": step_type,
        "expected_outcome": "return_void",
        **values,
    }


def _run(source: str, steps: list[dict], *, memory: bool = False):
    request = ObjectScenarioRunTestsRequest.model_validate(
        {
            "mode": "object",
            "code": source,
            "language": "cpp",
            "run_memory_checks": memory,
            "tests": [
                {
                    "name": "Scenario 1",
                    "objects": [],
                    "steps": steps,
                }
            ],
        }
    )
    return run_test_request(request)


def test_public_inheritance_virtual_metadata_and_override_relationship():
    analysis = analyze_object_scenarios(VIRTUAL_SOURCE)
    animal = next(item for item in analysis.classes if item.id == "Animal")
    dog = next(item for item in analysis.classes if item.id == "Dog")
    sound = next(item for item in dog.methods if item.name == "sound")
    assert dog.base_class_id == "Animal"
    assert dog.inheritance_access == "public"
    assert dog.inheritance_supported is True
    assert dog.inheritance_depth == 1
    assert animal.derived_class_ids == ("Dog", "Cat")
    assert animal.has_virtual_destructor is True
    assert sound.is_virtual is True
    assert sound.is_override is True
    assert sound.overrides_method_id == "Animal::sound() const->int"


def test_abstract_base_and_inherited_pure_virtual_detection():
    source = """
class Shape {
public:
    virtual int area() const = 0;
    virtual ~Shape() = default;
};
class Incomplete : public Shape {};
class Square : public Shape {
public:
    int area() const override { return 16; }
};
"""
    analysis = analyze_object_scenarios(source)
    by_name = {item.name: item for item in analysis.classes}
    assert by_name["Shape"].is_abstract is True
    assert by_name["Shape"].methods[0].is_pure_virtual is True
    assert by_name["Incomplete"].is_abstract is True
    assert by_name["Square"].is_abstract is False


def test_concrete_derived_object_calls_through_abstract_base_reference():
    source = """
class Shape {
public:
    virtual int area() const = 0;
    virtual ~Shape() = default;
};
class Square : public Shape {
    int side;
public:
    Square(int side): side{side} {}
    int area() const override { return side * side; }
};
"""
    result = _run(
        source,
        [
            _step(
                "create_object",
                class_id="Square",
                constructor_id="Square::Square(int)",
                arguments=["4"],
                result_object_id="square",
                result_name="square",
            ),
            _step(
                "create_base_reference",
                source_object_id="square",
                base_class_id="Shape",
                result_object_id="shape-ref",
                result_name="shapeRef",
            ),
            _step(
                "polymorphic_method",
                target_object_id="shape-ref",
                method_id="Shape::area() const->int",
                expected_outcome="return_value",
                expected_return="16",
            ),
        ],
    )
    assert result.success is True
    assert result.tests[0].steps[2].runtime_type == "Square"


def test_const_mismatch_does_not_override():
    source = """
class Base { public: virtual int value() const { return 1; } };
class Derived : public Base {
public:
    int value() { return 2; }
};
"""
    derived = next(
        item
        for item in analyze_object_scenarios(source).classes
        if item.id == "Derived"
    )
    method = derived.methods[0]
    assert method.overrides_method_id is None
    assert method.is_virtual is False
    assert method.override_mismatch_reason == "const qualification"


@pytest.mark.parametrize(
    ("view_step", "ownership"),
    [
        ("create_base_reference", "reference"),
        ("create_base_pointer", "non_owning_pointer"),
    ],
)
def test_virtual_dispatch_through_base_views(
    view_step: str, ownership: str
):
    result = _run(
        VIRTUAL_SOURCE,
        [
            _step(
                "create_object",
                class_id="Dog",
                constructor_id="Dog::Dog()",
                result_object_id="dog",
                result_name="dog",
            ),
            _step(
                view_step,
                source_object_id="dog",
                base_class_id="Animal",
                result_object_id="animal-ref",
                result_name="animalRef",
            ),
            _step(
                "polymorphic_method",
                target_object_id="animal-ref",
                method_id="Animal::sound() const->int",
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
    )
    assert result.success is True
    call = result.tests[0].steps[2]
    assert call.passed is True
    assert call.static_type == "Animal"
    assert call.runtime_type == "Dog"
    assert call.dispatch_kind == "virtual"
    assert result.tests[0].steps[1].ownership_mode == ownership


def test_non_virtual_dispatch_uses_static_base_type():
    source = """
class Base { public: int value() const { return 1; } };
class Derived : public Base { public: int value() const { return 2; } };
"""
    result = _run(
        source,
        [
            _step(
                "create_object",
                class_id="Derived",
                constructor_id="Derived::Derived()",
                result_object_id="derived",
                result_name="derived",
            ),
            _step(
                "create_base_reference",
                source_object_id="derived",
                base_class_id="Base",
                result_object_id="base-ref",
                result_name="baseRef",
            ),
            _step(
                "polymorphic_method",
                target_object_id="base-ref",
                method_id="Base::value() const->int",
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
    )
    assert result.success is True
    assert result.tests[0].steps[2].dispatch_kind == "non_virtual"


def test_object_slicing_uses_base_runtime_type():
    result = _run(
        VIRTUAL_SOURCE,
        [
            _step(
                "create_object",
                class_id="Dog",
                constructor_id="Dog::Dog()",
                result_object_id="dog",
                result_name="dog",
            ),
            _step(
                "slice_object",
                source_object_id="dog",
                base_class_id="Animal",
                result_object_id="sliced",
                result_name="sliced",
            ),
            _step(
                "polymorphic_method",
                target_object_id="sliced",
                method_id="Animal::sound() const->int",
                expected_outcome="return_value",
                expected_return="0",
            ),
        ],
    )
    assert result.success is True
    sliced = result.tests[0].steps[1]
    assert sliced.slicing_occurred is True
    assert sliced.static_type == sliced.runtime_type == "Animal"


@pytest.mark.parametrize(
    ("target", "expected", "actual"),
    [
        ("Dog", "succeeds", "succeeded"),
        ("Cat", "returns_null", "null"),
    ],
)
def test_dynamic_pointer_cast_results(
    target: str, expected: str, actual: str
):
    result = _run(
        VIRTUAL_SOURCE,
        [
            _step(
                "create_owned_base_pointer",
                base_class_id="Animal",
                derived_class_id="Dog",
                constructor_id="Dog::Dog()",
                result_object_id="animal",
                result_name="animal",
            ),
            _step(
                "dynamic_cast",
                source_object_id="animal",
                cast_target_class_id=target,
                cast_mode="pointer",
                expected_cast_result=expected,
            ),
            _step("delete_base_pointer", target_object_id="animal"),
        ],
    )
    assert result.success is True
    assert result.tests[0].steps[1].cast_result == actual


def test_dynamic_reference_cast_bad_cast_matches_exception():
    result = _run(
        VIRTUAL_SOURCE,
        [
            _step(
                "create_object",
                class_id="Dog",
                constructor_id="Dog::Dog()",
                result_object_id="dog",
                result_name="dog",
            ),
            _step(
                "create_base_reference",
                source_object_id="dog",
                base_class_id="Animal",
                result_object_id="animal-ref",
                result_name="animalRef",
            ),
            {
                **_step(
                    "dynamic_cast",
                    source_object_id="animal-ref",
                    cast_target_class_id="Cat",
                    cast_mode="reference",
                    expected_cast_result="throws_bad_cast",
                ),
                "expected_outcome": "throws",
                "expected_exception_type": "std::bad_cast",
            },
        ],
    )
    assert result.success is True
    assert result.tests[0].steps[2].cast_result == "threw_bad_cast"


def test_dynamic_reference_cast_success():
    result = _run(
        VIRTUAL_SOURCE,
        [
            _step(
                "create_object",
                class_id="Dog",
                constructor_id="Dog::Dog()",
                result_object_id="dog",
                result_name="dog",
            ),
            _step(
                "create_base_reference",
                source_object_id="dog",
                base_class_id="Animal",
                result_object_id="animal-ref",
                result_name="animalRef",
            ),
            _step(
                "dynamic_cast",
                source_object_id="animal-ref",
                cast_target_class_id="Dog",
                cast_mode="reference",
                expected_cast_result="succeeds",
            ),
        ],
    )
    assert result.success is True
    assert result.tests[0].steps[2].cast_result == "succeeded"


def test_exception_from_virtual_call_uses_existing_expectation_model():
    source = """
#include <stdexcept>
class Base {
public:
    virtual int run() { throw std::runtime_error("failed"); }
    virtual ~Base() = default;
};
class Derived : public Base {
public:
    int run() override { throw std::runtime_error("failed"); }
};
"""
    result = _run(
        source,
        [
            _step(
                "create_object",
                class_id="Derived",
                constructor_id="Derived::Derived()",
                result_object_id="derived",
                result_name="derived",
            ),
            _step(
                "create_base_reference",
                source_object_id="derived",
                base_class_id="Base",
                result_object_id="base-ref",
                result_name="baseRef",
            ),
            {
                **_step(
                    "polymorphic_method",
                    target_object_id="base-ref",
                    method_id="Base::run()->int",
                ),
                "expected_outcome": "throws",
                "expected_exception_type": "std::runtime_error",
                "exception_message_rule": "exact",
                "expected_exception_message": "failed",
            },
        ],
    )
    assert result.success is True
    exception = result.tests[0].steps[2].exception_result
    assert exception is not None
    assert exception.expectation_passed is True


def test_abstract_construction_and_unknown_relationship_are_rejected():
    source = """
class Shape { public: virtual int area() const = 0; };
class Square : public Shape { public: int area() const { return 1; } };
class Other { public: int value() const { return 1; } };
"""
    abstract = _run(
        source,
        [
            _step(
                "create_object",
                class_id="Shape",
                constructor_id="Shape::Shape()",
                result_object_id="shape",
                result_name="shape",
            )
        ],
    )
    assert abstract.input_error

    unrelated = _run(
        source,
        [
            _step(
                "create_object",
                class_id="Square",
                constructor_id="Square::Square()",
                result_object_id="square",
                result_name="square",
            ),
            _step(
                "create_base_reference",
                source_object_id="square",
                base_class_id="Other",
                result_object_id="other",
                result_name="other",
            ),
        ],
    )
    assert unrelated.input_error


def test_repeated_delete_and_use_after_delete_are_rejected():
    base_steps = [
        _step(
            "create_owned_base_pointer",
            base_class_id="Animal",
            derived_class_id="Dog",
            constructor_id="Dog::Dog()",
            result_object_id="animal",
            result_name="animal",
        ),
        _step("delete_base_pointer", target_object_id="animal"),
    ]
    repeated = _run(
        VIRTUAL_SOURCE,
        [*base_steps, _step("delete_base_pointer", target_object_id="animal")],
    )
    assert repeated.input_error
    used = _run(
        VIRTUAL_SOURCE,
        [
            *base_steps,
            _step(
                "polymorphic_method",
                target_object_id="animal",
                method_id="Animal::sound() const->int",
                expected_outcome="return_value",
                expected_return="1",
            ),
        ],
    )
    assert used.input_error


@pytest.mark.parametrize("virtual_destructor", [True, False])
def test_delete_through_base_pointer_tracks_virtual_destructor(
    virtual_destructor: bool,
):
    destructor = "virtual ~Base() = default;" if virtual_destructor else "~Base() {}"
    source = f"""
class Base {{ public: {destructor} }};
class Derived : public Base {{
public:
    Derived() = default;
}};
"""
    result = _run(
        source,
        [
            _step(
                "create_owned_base_pointer",
                base_class_id="Base",
                derived_class_id="Derived",
                constructor_id="Derived::Derived()",
                result_object_id="base",
                result_name="base",
            ),
            _step("delete_base_pointer", target_object_id="base"),
        ],
    )
    assert result.success is True
    deletion = result.tests[0].steps[1]
    assert deletion.virtual_destructor is virtual_destructor


def test_virtual_destructor_with_owned_resource_is_memory_clean_when_supported():
    source = """
class Base { public: virtual ~Base() = default; };
class Derived : public Base {
    int *value;
public:
    Derived(): value{new int{42}} {}
    ~Derived() { delete value; }
};
"""
    result = _run(
        source,
        [
            _step(
                "create_owned_base_pointer",
                base_class_id="Base",
                derived_class_id="Derived",
                constructor_id="Derived::Derived()",
                result_object_id="base",
                result_name="base",
            ),
            _step("delete_base_pointer", target_object_id="base"),
        ],
        memory=True,
    )
    if result.memory_status == "unavailable":
        pytest.skip("Memory diagnostics unavailable")
    assert result.success is True
    assert result.tests[0].memory_status in {"clean", "partial"}
    assert result.tests[0].steps[1].virtual_destructor is True


def test_non_virtual_destructor_is_structurally_marked():
    source = """
class Base { public: ~Base() {} };
class Derived : public Base {
    int *value;
public:
    Derived(): value{new int{42}} {}
    ~Derived() { delete value; }
};
"""
    result = _run(
        source,
        [
            _step(
                "create_owned_base_pointer",
                base_class_id="Base",
                derived_class_id="Derived",
                constructor_id="Derived::Derived()",
                result_object_id="base",
                result_name="base",
            ),
            _step("delete_base_pointer", target_object_id="base"),
        ],
    )
    assert result.tests[0].steps[1].virtual_destructor is False


def test_multiple_and_private_inheritance_are_reported_unsupported():
    multiple = analyze_object_scenarios(
        "class A { public: int x(){return 1;} };"
        "class B { public: int y(){return 2;} };"
        "class C : public A, public B { public: int z(){return 3;} };"
    )
    assert multiple.message == "Inheritance is unsupported in object scenarios."
    private = analyze_object_scenarios(
        "class A { public: int x(){return 1;} };"
        "class C : private A { public: int z(){return 3;} };"
    )
    assert private.message == "Inheritance is unsupported in object scenarios."
