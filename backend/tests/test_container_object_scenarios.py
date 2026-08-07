"""
Object scenario execution tests for STL container support.
Requires g++ to be installed; each execution test is guarded accordingly.
"""

import shutil

import pytest

from app.schemas.test_execution import (
    ObjectScenarioRunTestsRequest,
    ObjectScenarioStep,
    ObjectScenarioTestCase,
)
from app.services.object_analysis import analyze_object_scenarios
from app.services.test_execution import run_test_request

NEEDS_GPP = pytest.mark.skipif(
    shutil.which("g++") is None, reason="g++ is not installed"
)


def object_request(
    code: str,
    *,
    constructor_index: int = 0,
    constructor_arguments: list[str] | None = None,
    steps: list[dict[str, object]],
    class_index: int = 0,
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
        comparison_mode="whitespace_tolerant",
        tests=[
            ObjectScenarioTestCase(
                name="Scenario 1",
                class_id=object_class.id,
                constructor_id=object_class.constructors[constructor_index].id,
                constructor_arguments=constructor_arguments or [],
                steps=scenario_steps,
            )
        ],
    )


# ---------------------------------------------------------------------------
# 1. Bag class: ctor std::vector<int>, add(int), get() -> std::vector<int>
# ---------------------------------------------------------------------------

BAG_SOURCE = """
#include <vector>
class Bag {
    std::vector<int> items;
public:
    Bag(std::vector<int> initial) : items(initial) {}
    void add(int v) { items.push_back(v); }
    std::vector<int> get() const { return items; }
};
"""


@NEEDS_GPP
def test_bag_vector_constructor_and_observer():
    result = run_test_request(
        object_request(
            BAG_SOURCE,
            constructor_arguments=["[1, 2]"],
            steps=[
                {"method_index": 0, "arguments": ["3"]},           # add(3)
                {"method_index": 1, "expected_return": "[1, 2, 3]"},  # get()
            ],
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 2. Constructor taking std::map<std::string,int>, observer returning map
# ---------------------------------------------------------------------------

DICT_SOURCE = """
#include <map>
#include <string>
class Dict {
    std::map<std::string, int> data;
public:
    Dict(std::map<std::string, int> d) : data(d) {}
    std::map<std::string, int> get() const { return data; }
};
"""


@NEEDS_GPP
def test_dict_map_constructor_and_observer():
    result = run_test_request(
        object_request(
            DICT_SOURCE,
            constructor_arguments=['{"a": 1, "b": 2}'],
            steps=[
                {"method_index": 0, "expected_return": '{"a": 1, "b": 2}'},
            ],
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 3. Method taking std::deque<int> argument
# ---------------------------------------------------------------------------

DEQUE_SOURCE = """
#include <deque>
class Accumulator {
    std::deque<int> data;
public:
    Accumulator() {}
    void load(std::deque<int> vals) { data = vals; }
    int sum() const { int s = 0; for (int v : data) s += v; return s; }
};
"""


@NEEDS_GPP
def test_deque_method_argument():
    result = run_test_request(
        object_request(
            DEQUE_SOURCE,
            constructor_arguments=[],
            steps=[
                {"method_index": 0, "arguments": ["[10, 20, 30]"]},  # load
                {"method_index": 1, "expected_return": "60"},          # sum
            ],
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 4. Observer returning std::set<int> — order-independent pass
# ---------------------------------------------------------------------------

SET_SOURCE = """
#include <set>
class UniqueStore {
    std::set<int> data;
public:
    UniqueStore() {}
    void insert(int v) { data.insert(v); }
    std::set<int> all() const { return data; }
};
"""


@NEEDS_GPP
def test_set_observer_order_independent():
    result = run_test_request(
        object_request(
            SET_SOURCE,
            constructor_arguments=[],
            steps=[
                {"method_index": 0, "arguments": ["3"]},    # insert(3)
                {"method_index": 0, "arguments": ["1"]},    # insert(1)
                {"method_index": 0, "arguments": ["2"]},    # insert(2)
                # Expected unsorted; comparison must be order-insensitive
                {"method_index": 1, "expected_return": "[3, 1, 2]"},
            ],
        )
    )
    assert result.success is True


# ---------------------------------------------------------------------------
# 5. Container observation before later step — non-destructive serialization
# ---------------------------------------------------------------------------


@NEEDS_GPP
def test_non_destructive_observation_before_later_step():
    result = run_test_request(
        object_request(
            BAG_SOURCE,
            constructor_arguments=["[10, 20]"],
            steps=[
                # Observe first — proves serializer does not destroy state
                {"method_index": 1, "expected_return": "[10, 20]"},   # get()
                {"method_index": 0, "arguments": ["30"]},              # add(30)
                {"method_index": 1, "expected_return": "[10, 20, 30]"}, # get()
            ],
        )
    )
    assert result.success is True
