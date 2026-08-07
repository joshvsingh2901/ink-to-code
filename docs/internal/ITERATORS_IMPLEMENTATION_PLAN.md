# Iterators and STL Algorithms — Implementation Plan

Execution plan for Claude Sonnet 4.6.

The architecture in this document is already reviewed and approved.
Do not re-plan it.
Inspect only the functions named below.
Do not commit.

## Scope corrections baked into this plan

Three corrections were applied during review. They change scope and are not optional.

- Generated harness code adds `<iterator>` only, because InkToCode-generated code itself
  calls `std::next` and `std::distance`.
- `<algorithm>` and `<numeric>` are never injected. Student code must supply its own
  algorithm headers so a missing include stays a real compiler error the student sees.
- Iterator returns are supported only in structurally unambiguous cases. The harness cannot
  prove a returned iterator actually points into the resolved container, and no pointer or
  address ownership checks are added.
- External template-callable parameters are deferred entirely. No callable metadata, no
  allowlist, no callable UI, and no callable harness generation are implemented.

---

## 1. Verified current repository state

These facts were confirmed by direct inspection and by probing the live parser.

### Backend structures

- `ValueType` is declared at `backend/app/services/function_analysis.py:104`.
- Its `kind` field is currently:

```python
kind: Literal["scalar", "vector", "array", "void", "container"]
```

- It also carries twelve container fields plus `supported` and `unsupported_reason`.
- `HarnessArgument` is declared at `backend/app/services/test_execution.py:126`:

```python
@dataclass(frozen=True)
class HarnessArgument:
    expression: str
    declarations: tuple[str, ...] = ()
    array_element_count: int | None = None
    mutation_expression: str | None = None
```

- `HarnessArgument.declarations` is the integration hook for iterator support.

### Backend behavior

- `_prepare_argument` at `test_execution.py:1548` branches first on
  `passing in {"mutable_reference", "scalar_pointer"}`, then on array handling, then falls
  through to `_safe_value_literal`.
- `_build_function_harness` at `test_execution.py:2030` concatenates all `declarations` for a
  test, builds the call expression, and assigns the result to `inktocode_return_value`.
- `mutation_capable_parameters` at `test_execution.py:4962` selects parameters whose `passing`
  is in `{"mutable_reference", "scalar_pointer", "array_pointer"}`.
- The validator at `test_execution.py:5005` requires `set(expectations) == mutable_names`
  exactly, so any extra mutation-capable parameter breaks every mutation test.
- `_function_response.type_response` at `test_execution.py:250` copies every `ValueType` field
  explicitly into the API response.
- The result comparison path is `_metadata_value` at `test_execution.py:2781`, then
  `_typed_match` at `test_execution.py:2797`, then `_typed_mismatch_detail` at
  `test_execution.py:2810`.

### Wire format

- Function arguments travel as `FunctionTestCase.arguments: list[str]` at
  `backend/app/schemas/test_execution.py:251`, capped at 20 arguments.
- Because arguments are already plain strings, this feature requires no schema change.

### Frontend

- `isFunctionTypeMetadata` in `frontend/lib/testExecution.ts` currently whitelists exactly
  these kinds:

```ts
["scalar", "vector", "array", "void", "container"]
```

- `frontend/lib/containerValues.ts` provides stable-ID row and entry helpers.
- `frontend/components/ContainerValueEditor.tsx` provides structured container editing.

### Confirmed working today with zero new code

- Functions containing internal lambdas.
- `std::sort`, `std::count_if`, `std::transform`, `std::accumulate`, and `std::remove_if`
  called inside ordinary student functions.
- `template <typename Pred> int countMatching(const std::vector<int>& values, Pred pred)`
  parses as `mode=function`, with `pred` arriving as `kind="scalar"` and
  `scalar_type="Pred"`. It parses, but is not bindable to anything useful without callable
  support, so such functions remain effectively untestable in this stage.

### Confirmed rejected today

- `std::vector<int>::iterator` as a parameter is rejected with the message
  `Unsupported container type: std::vector<int>::iterator.`
- Iterator return types are mis-parsed, because `_FUNCTION_DEFINITION` reads the return type
  as bare `iterator`.
- `int apply(int value, int (*fn)(int))` is rejected at function detection entirely.
- `std::function<bool(int)>` parameters are rejected at function detection entirely.

---

## 2. Final supported scope

- Iterator parameters over `vector`, `deque`, `list`, and `array`.
- Both `::iterator` and `::const_iterator` forms, passed by value.
- Iterator ranges expressed as two adjacent parameters of identical iterator type.
- A single shared backing container object per iterator group, with half-open
  `[start, end)` range semantics.
- Iterator-driven mutation, where expected-after values are stated on the shared backing
  container using the existing mutation infrastructure.
- Iterator return values, only in structurally unambiguous backing-container cases, reported
  as an index or as `end`.
- Common STL algorithms and internal lambdas inside ordinary student functions, covered by
  integration tests only, with no new machinery.

---

## 3. Intentional unsupported scope

Reject cleanly with `unsupported_reason` wherever the parser reaches these. Do not attempt
any of them.

- External template-callable parameters, including
  `template <typename Pred> int f(const std::vector<int>& values, Pred pred)`.
- Raw function pointers such as `int (*fn)(int)`.
- `std::function<...>` parameters.
- Associative container iterators, meaning `set`, `multiset`, `map`, `multimap`, and all
  unordered variants.
- `reverse_iterator`, `move_iterator`, `back_insert_iterator`, `front_insert_iterator`,
  `insert_iterator`, stream iterators, and custom user-written iterator classes.
- C++20 ranges, views, execution policies, and parallel algorithms.
- User-typed lambda source, callable source, or any C++ expression text supplied from the
  browser, anywhere in the UI.
- Iterator parameters inside object scenarios. Methods that use iterators or algorithms
  internally continue to work.
- Static iterator-invalidation analysis.
- Iterator arithmetic beyond a single non-negative position offset.
- Any attempt to detect or diagnose a returned iterator that points into a container other
  than the resolved backing container.

### Why function pointers and `std::function` are blocked

`_FUNCTION_DEFINITION` matches its parameter list with a group of this shape:

```
\((?P<parameters>[^()]*)\)
```

That character class cannot hold nested parentheses. Both `int (*fn)(int)` and
`std::function<bool(int)>` contain nested parentheses inside the parameter list, so the whole
function fails to match and is never detected. Extending that group endangers every existing
function-detection test in the suite. Do not touch it for this feature.

---

## 4. Exact files to modify and create

### Backend, modify

- `backend/app/services/function_analysis.py`
- `backend/app/services/test_execution.py`

### Backend, create

- `backend/tests/test_iterator_analysis.py`
- `backend/tests/test_iterator_execution.py`
- `backend/tests/test_algorithm_integration.py`

### Frontend, modify

- `frontend/lib/testExecution.ts`
- `frontend/app/editor/page.tsx`

### Frontend, create

- `frontend/lib/iteratorValues.ts`
- `frontend/components/IteratorValueEditor.tsx`
- `frontend/tests/iteratorValues.test.mts`

### Documentation, last only, after all checks are green

- `AGENTS.md`
- `backend/README.md`
- `frontend/README.md`

### Do not modify any of these

- `backend/app/services/memory_classifier.py`
- `backend/app/services/memory_runtime_parser.py`
- `backend/app/services/memory_source_analysis.py`
- `backend/app/services/memory_source_mapping.py`
- `backend/app/services/memory_explanations.py`
- `backend/app/services/memory_diagnosis_models.py`
- `backend/app/services/big_five_diagnosis.py`
- `backend/app/services/execution_providers.py`
- `backend/app/services/compiler.py`
- `backend/app/services/compiler_diagnostics.py`
- `backend/app/services/compiler_explanations.py`
- `backend/app/services/object_analysis.py`
- `backend/app/services/transcription.py`
- `backend/app/services/uploads.py`
- `backend/app/schemas/test_execution.py`
- `backend/app/api/test_execution.py`
- `runner/`
- `CLAUDE.md`
- `frontend/lib/exceptionTestState.ts`
- `frontend/lib/templateTesting.ts`
- `frontend/components/ExceptionExpectationFields.tsx`
- `frontend/components/ObjectScenarioTests.tsx`

---

## 5. Existing helpers to reuse

Reuse each of these. Do not create parallel implementations.

- `ValueType` at `function_analysis.py:104`, extended with four new fields only.
- `CONTAINER_PROPERTIES` at `function_analysis.py:80`, read only, used to validate iterator
  container names.
- `_parse_scalar_or_container_type` at `function_analysis.py:666`, used to parse the
  iterator's element type.
- `HarnessArgument` at `test_execution.py:126`, carrying iterator declarations, expression,
  and mutation expression.
- `_container_literal` at `test_execution.py:1359`, used exactly as-is to build the backing
  container literal.
- `_serialized_value_output` at `test_execution.py:2279`, used to serialize the mutated
  backing container.
- `_safe_literal` at `test_execution.py:1232`, retained for element literal validation inside
  container payloads.
- `_function_response.type_response` at `test_execution.py:250`, extended with the new fields.
- `_metadata_value`, `_typed_match`, and `_typed_mismatch_detail`, each gaining exactly one
  `"iterator"` branch.
- `frontend/lib/containerValues.ts` helpers, reused by the iterator editor.
- `frontend/components/ContainerValueEditor.tsx`, embedded by `IteratorValueEditor` rather
  than reimplemented.

---

## 6. Iterator metadata design

Extend the `kind` literal in `ValueType`:

```python
kind: Literal["scalar", "vector", "array", "void", "container", "iterator"]
```

Add exactly four new fields, all defaulting to `None`:

```python
iterator_container: str | None = None
iterator_const: bool | None = None
iterator_role: Literal["single", "range_begin", "range_end"] | None = None
iterator_group_index: int | None = None
```

Field semantics:

- `iterator_container` holds one of `"vector"`, `"deque"`, `"list"`, or `"array"`.
- `iterator_const` is `True` for `const_iterator` and `False` for `iterator`.
- `iterator_role` records the parameter's position within its iterator group.
- `iterator_group_index` is the parameter index of the group head.
- `display_type` keeps the literal source text, for example `std::vector<int>::iterator`.
- `element_type` holds the parsed element type.
- `fixed_size` is populated for `array` only.
- `passing` is always `"value"` for iterators.

Do not add a `"callable"` kind. Do not add a `callable_template_parameter` field.

Add all four fields to `_function_response.type_response` at `test_execution.py:250`, matching
the existing explicit field-copy style used for container fields.

---

## 7. Iterator parsing and return-type parsing

### 7.1 The iterator type regex

Add this regex immediately after `_CONTAINER_TYPE` at `function_analysis.py:320`:

```python
_ITERATOR_TYPE = re.compile(
    r"(?P<qualified>std::)?"
    r"(?P<container>vector|deque|list|array)\s*<\s*(?P<args>.+)\s*>\s*"
    r"::\s*(?P<constness>const_)?iterator"
)
```

### 7.2 The iterator type parser

Add a function with this signature:

```python
def _parse_iterator_type(
    match: re.Match[str],
    normalized: str,
    *,
    allow_reference: bool,
    unqualified_allowed: bool,
) -> tuple[ValueType | None, str | None]:
```

Required behavior, in order:

- If `match.group("qualified")` is `None` and `unqualified_allowed` is false, return
  `(None, f"Unsupported type: {normalized}.")`.
- For `array`, split `match.group("args")` on the last top-level comma to obtain the element
  type and the size. Reuse the same `_split_template_items` plus integer-parse logic already
  present in `_parse_container_type`.
- For every other container, the entire `args` group is the element type.
- Parse the element type with `_parse_scalar_or_container_type`. If it does not parse, or if
  its `kind` is not `"scalar"`, return
  `(None, "Iterators over nested containers are not supported.")`.
- Reject any trailing `&` or `*` modifier with
  `(None, "Iterator references and pointers are not supported.")`.
- On success, build a `ValueType` with `kind="iterator"`, `iterator_const` set from the
  `constness` group, `iterator_container` set from the `container` group, the parsed
  `element_type`, `fixed_size` when applicable, `passing="value"`, and
  `display_type=normalized`.

### 7.3 Wiring into `_parse_value_type`

Insert this block immediately BEFORE the existing line
`container_match = _CONTAINER_TYPE.fullmatch(normalized)` at `function_analysis.py:535`:

```python
iterator_match = _ITERATOR_TYPE.fullmatch(normalized)
if iterator_match is not None:
    return _parse_iterator_type(
        iterator_match,
        normalized,
        allow_reference=allow_reference,
        unqualified_allowed=unqualified_vector_allowed,
    )
if (
    "::iterator" in normalized
    or "::const_iterator" in normalized
    or "reverse_iterator" in normalized
):
    return None, f"Unsupported iterator type: {normalized}."
```

The second check is reached only when `_ITERATOR_TYPE` did not match. It exists so that
unsupported iterator families produce a precise message instead of falling through to the
generic container rejection at `function_analysis.py:547`.

### 7.4 Do not change these

- `CONTAINER_PROPERTIES`
- `_CONTAINER_TYPE`
- `_VECTOR_TYPE`
- Any `_SCALAR_*` pattern
- Any `MAX_*` constant

### 7.5 The `_FUNCTION_DEFINITION` return-type fix

The regex at `function_analysis.py:258` currently causes
`std::vector<int>::iterator findValue(std::vector<int>& values, int target)` to parse with
return type `iterator`.

Append an optional iterator suffix to the FIRST alternative only, so that alternative reads
exactly:

```
(?:const\s+)?(?:std::)?[A-Za-z_]\w*\s*<[^{}();\n]+>(?:\s*::\s*(?:const_)?iterator)?\s*(?:const\s*)?[&*]?
```

This is the only permitted change to `_FUNCTION_DEFINITION`. Nothing else in that regex may be
altered, because it gates every existing function-detection test in the suite.

---

## 8. Iterator grouping and shared backing-container design

### 8.1 Grouping rules

After parameters are parsed in `_parse_parameters` at `function_analysis.py:838`, run a
post-pass named `_assign_iterator_groups(parsed)`.

- Scan parameters left to right.
- Identify each maximal run of ADJACENT parameters where `kind == "iterator"` and where this
  tuple is identical across the run:

```python
(iterator_container, element_type, iterator_const, fixed_size)
```

- Run length 1: set `iterator_role="single"` and set `iterator_group_index` to that
  parameter's own index.
- Run length 2: set the first parameter to `iterator_role="range_begin"` and the second to
  `iterator_role="range_end"`. Set `iterator_group_index` on both to the head's index.
- Run length greater than 2: return
  `(None, "More than two adjacent iterators of the same type are ambiguous.")`.
- Adjacent iterators whose tuples differ form separate groups of size 1 each.

Parameter names are never used for grouping. Names are used only for UI labels and for keying
`expected_final_arguments`.

### 8.2 Shared backing-container identity

The decision is one backing container object per iterator group, declared exactly once, by the
group head.

- The storage variable name is built as:

```
inktocode_iterbase_{test_index}_{group_index}
```

- `group_index` is the parameter index of the group head.
- The group head's `HarnessArgument` carries a single declaration:

```python
declarations=(f"{cpp_type} {storage} = {literal};",)
```

- The group tail's `HarnessArgument` carries `declarations=()` and an expression that
  references the same `storage` name.

Aliasing is therefore structurally impossible to get wrong. There is exactly one declaration
in the generated source, and both iterator expressions name it.

### 8.3 Backing container C++ type

`cpp_type` is derived from iterator metadata and is one of these forms:

```cpp
std::vector<int>
std::deque<int>
std::list<int>
std::array<int, 3>
```

The element type and fixed size come from the parsed metadata. The storage is never declared
`const`, so mutation remains possible. Constness is expressed in the iterator expression
instead, as described in section 11.

---

## 9. Request wire representation

No schema change is required. Iterator arguments travel inside the existing
`arguments: list[str]` as JSON object strings.

### 9.1 Group head payload

A group head has role `single` or `range_begin` and sends:

```json
{"container": [1, 2, 3, 4], "position": 1}
```

The `container` value accepts exactly the forms `_container_literal` already accepts today.

### 9.2 Group tail payload

A group tail has role `range_end` and sends:

```json
{"position": 4}
```

A tail must never carry a `container` key. Enforcing this makes a cross-container range
structurally unrepresentable on the wire.

---

## 10. Server-side validation

Add a validator with this signature to `test_execution.py`:

```python
def _parse_iterator_argument(raw: str, value_type: ValueType, label: str) -> dict:
```

Required behavior:

- The payload must be a JSON object. Otherwise raise:

```python
raise ValueError(f"{label} must be an iterator position object.")
```

- A group head MUST carry `container`. If it is missing, raise a clear error naming the
  parameter.
- A group tail MUST NOT carry `container`. Otherwise raise:

```python
raise ValueError(f"{label} must not carry its own container; the range start owns it.")
```

- `position` must be an integer satisfying `0 <= position <= element_count`.
- Reject negative positions and positions greater than the element count with distinct,
  explicit messages.
- A position equal to `element_count` is VALID and denotes `end()`.
- The element count is taken from the head's parsed container. The tail is therefore validated
  against the head's count, which requires preparing the head before the tail.
- For a two-iterator range, validate `head_position <= tail_position`. Otherwise raise:

```python
raise ValueError("Range start must not be after range end.")
```

Frontend validation is advisory only and is never trusted. All bounds checks above are
enforced server-side.

---

## 11. Harness generation

### 11.1 The iterator argument pre-pass

Add a new function to `test_execution.py`:

```python
def _prepare_iterator_arguments(
    function: FunctionDescriptor,
    raw_arguments: list[str],
    test_index: int,
) -> dict[int, HarnessArgument]:
```

Call it from the per-test argument loop inside `run_test_request`, BEFORE the normal
`_prepare_argument` loop. Parameter indices present in the returned dict skip
`_prepare_argument` entirely.

Do not add an iterator branch inside `_prepare_argument`. Its first branch tests
`passing in {"mutable_reference", "scalar_pointer"}`, and inserting iterator handling there
would require reordering that dispatch, which risks existing behavior. Use the pre-pass.

### 11.2 Per-group steps

Perform these steps in order for each iterator group.

- Parse the head JSON to obtain the container payload and the head position.
- Parse the tail JSON to obtain the tail position, when the group has two members.
- Validate positions as described in section 10.
- Build a synthetic backing `ValueType` with `kind="container"`, or `kind="vector"` when the
  container is `vector` to match existing conventions. Populate `container_name` from
  `iterator_container`, the parsed `element_type`, `fixed_size` when applicable, and
  `passing="value"`.
- Call the existing `_container_literal` to build the literal:

```python
literal = _container_literal(backing_value_type, json.dumps(container_payload), label)
```

- Build the head argument:

```python
HarnessArgument(
    expression=iterator_expression(head_position),
    declarations=(f"{cpp_type} {storage} = {literal};",),
    mutation_expression=storage,
)
```

- Build the tail argument:

```python
HarnessArgument(expression=iterator_expression(tail_position))
```

The tail's `declarations` stays empty. This is the single most important detail in the whole
feature.

### 11.3 The iterator expression

Build the iterator expression exactly as follows.

When `iterator_const` is `True`:

```cpp
std::next(inktocode_iterbase_0_0.cbegin(), 1)
```

When `iterator_const` is `False`:

```cpp
std::next(inktocode_iterbase_0_0.begin(), 1)
```

`std::next` is used for all four containers so that `std::list`, which has no random access,
works identically. Never emit `begin() + n`.

### 11.4 Harness headers

Add exactly one include to the function-harness preamble in `_build_function_harness`, near
`<iomanip>` at approximately `test_execution.py:2225`, in the existing alphabetical position:

```cpp
#include <iterator>
```

This header is added because InkToCode-generated code itself calls `std::next` and
`std::distance`.

Do not add `<algorithm>`. Do not add `<numeric>`. Student code must supply its own algorithm
headers, so a missing include remains a genuine compiler error surfaced through the normal
compile-error path.

Leave the object-scenario harness preamble untouched.

---

## 12. Iterator return handling and limitations

### 12.1 Backing resolution at analysis time

Resolution happens in `analyze_test_mode`, after parameters and the return type are known. For
a returned iterator with a given `iterator_container` and `element_type`, collect candidates:

- Iterator group heads whose `iterator_container` and `element_type` both match.
- Parameters whose `kind` is `"vector"` or `"container"`, whose `container_name` and
  `element_type` both match, and whose `passing` is not `"value"`.

A by-value container parameter is a copy local to the call, so iterators into it are excluded
from candidacy.

Resolution rules:

- Exactly one candidate: supported. Record that parameter's index in the return
  `ValueType.iterator_group_index`.
- Zero candidates, or two or more candidates: set `supported=False` with this reason:

```
The returned iterator's container cannot be identified unambiguously.
```

Reject the function rather than guessing.

### 12.2 Return serialization

Add a branch in the return-serialization chain inside `_build_function_harness`, placed BEFORE
the existing `kind == "container"` branch:

```cpp
auto inktocode_return_value = findValue(inktocode_arg_0, inktocode_arg_1);
if (inktocode_return_value == inktocode_iterbase_0_0.end()) {
    std::cout << "\"end\"";
} else {
    std::cout << std::distance(inktocode_iterbase_0_0.begin(), inktocode_return_value);
}
```

The base object is the iterator group's storage name, or the mutable-reference storage of the
resolved container parameter. Always use `std::distance`, never `operator-`, so that `list` and
`deque` compile.

### 12.3 Honest statement of limitations

- The resolution above is STRUCTURAL only. It identifies which container the returned iterator
  is intended to index against, based on the function signature.
- The harness does not, and cannot, prove that the iterator the student actually returned
  points into that container.
- No pointer comparison, address-range check, or ownership check is added. Such checks are not
  reliable and are explicitly out of scope.
- If a student function returns an iterator into a different container, both the
  `== base.end()` comparison and the `std::distance` call are undefined behavior in C++. The
  result is meaningless and may be any value, or may crash.
- This is documented as undefined student behavior in `AGENTS.md` and `backend/README.md`. It
  is not detected, and no attempt to detect it may be added.

### 12.4 Result-path changes

- `_metadata_value` gains a branch so that for `kind == "iterator"` the value `"end"` maps to
  the string `"end"`, and an integer value maps to its decimal string form.
- `_typed_match` gains a branch so that for `kind == "iterator"` the comparison is
  `expected.strip() == actual.strip()`. The expected value has already been normalized by the
  frontend to either `"end"` or a decimal integer.
- `_typed_mismatch_detail` gains an `"iterator"` branch producing text of this form:

```
Expected position 2, actual position 4.
```

When either value is `"end"`, use the literal word `end()` in place of a number.

---

## 13. Iterator mutation handling

Reuse the existing mutation pipeline exactly. Do not build a second mutation subsystem, and do
not touch `expected_mutations` handling.

### 13.1 Extending mutation capability

Extend `mutation_capable_parameters` at `test_execution.py:4962` to additionally include
parameters satisfying all three of these conditions:

- `value_type.kind == "iterator"`
- `value_type.iterator_const is False`
- `value_type.iterator_role in {"single", "range_begin"}`

Only the group head may be included. If the tail is also included, the validator at
`test_execution.py:5005` requiring `set(expectations) == mutable_names` will reject every
mutation test.

### 13.2 Mutation serialization

In the mutation-serialization chain inside `_build_function_harness`, add a branch BEFORE the
existing `kind == "container"` branch. For `kind == "iterator"`, construct the same synthetic
backing `ValueType` described in section 11.2, then call the existing helper:

```python
_serialized_value_output(mutable_expression, backing_value_type)
```

The `mutable_expression` resolves to the storage name through the head's
`mutation_expression`.

### 13.3 Mutation comparison

Comparison of the expected-after value must use the BACKING `ValueType`, not the iterator
`ValueType`, so that `_classify_container_match` applies unchanged.

Apply the same synthetic-backing substitution where `_function_results` compares mutations, at
approximately `test_execution.py:2929` and `test_execution.py:3041`.

`expected_final_arguments` is keyed by the HEAD parameter's name. The frontend must key it
identically.

---

## 14. Frontend metadata changes

In `frontend/lib/testExecution.ts`, extend `FunctionTypeMetadata` with these optional fields,
using the backend names exactly:

```ts
iterator_container?: string | null;
iterator_const?: boolean | null;
iterator_role?: "single" | "range_begin" | "range_end" | null;
iterator_group_index?: number | null;
```

Update `isFunctionTypeMetadata` to add `"iterator"` to its kind whitelist, producing:

```ts
["scalar", "vector", "array", "void", "container", "iterator"]
```

Do not add `"callable"`.

This guard update is a critical blocker. It is the same class of failure encountered during
the STL container rollout. Without it, every iterator descriptor is silently discarded, the
parameter never renders, and there is no console error pointing at the cause. Check this
first when debugging missing UI.

Keep all new fields optional-tolerant, so responses from an older backend continue to parse.

---

## 15. Frontend iterator state helpers

Create `frontend/lib/iteratorValues.ts` exporting exactly these names. The tests reference
them by name.

```ts
export type IteratorState = {
  container: string;
  position: string;
  endPosition: string;
};

export function isIteratorHead(metadata: FunctionTypeMetadata): boolean;
export function isIteratorTail(metadata: FunctionTypeMetadata): boolean;
export function elementCountOf(containerArgument: string): number;
export function headArgumentPayload(state: IteratorState): string;
export function tailArgumentPayload(state: IteratorState): string;
export function parseHeadArgument(raw: string): IteratorState;
export function parseTailArgument(raw: string): { position: string };
export function validatePosition(position: string, count: number): string | null;
export function rangeElementsPreview(
  container: string,
  start: string,
  end: string,
): string;
export function positionHelperText(position: string, count: number): string;
export function iteratorStateSignature(metadata: FunctionTypeMetadata): string;
export function formatIteratorResult(value: string): string;
```

Behavioral rules:

- `isIteratorHead` returns true for roles `"single"` and `"range_begin"`.
- `isIteratorTail` returns true for role `"range_end"`.
- `elementCountOf` parses the container argument as JSON and returns its length, returning `0`
  for empty or unparseable input.
- `headArgumentPayload` produces a JSON string containing both `container` and `position`.
- `tailArgumentPayload` produces a JSON string containing only `position`, and must never
  include a `container` key.
- `validatePosition` returns `null` when valid, and otherwise returns a human-readable message.
- `validatePosition` rejects non-integers, negative values, and values greater than `count`.
- A position equal to `count` is VALID and denotes `end()`.
- An empty container yields count `0`, so position `0` is valid and the range `[0, 0)` is
  valid.
- `rangeElementsPreview` uses half-open semantics, so start `1` and end `4` over
  `[5, -2, 8, 1, 9]` yields the elements at indices `1`, `2`, and `3`.
- `positionHelperText` produces text such as `Position 2 points to the third element.` or
  `Position 4 is end().`
- `iteratorStateSignature` differs between `vector<int>` and `list<int>`, so switching the
  selected function resets editor state correctly.
- `formatIteratorResult` maps `"end"` to `end()` and the integer `2` to `Index 2`.

---

## 16. IteratorValueEditor behavior

Create `frontend/components/IteratorValueEditor.tsx` with these props:

```ts
type IteratorValueEditorProps = {
  id: string;
  label: string;
  metadata: FunctionTypeMetadata;
  value: string;
  tailValue?: string;
  onChange: (next: string) => void;
  onTailChange?: (next: string) => void;
  usage?: "input" | "expected";
  disabled?: boolean;
};
```

Required behavior:

- Render only for the group head. The tail parameter renders nothing of its own.
- Edit the backing container by embedding the existing `ContainerValueEditor`, passing a
  synthetic container metadata object built from `kind: "container"`, `container_name` taken
  from `metadata.iterator_container`, the element type, and the fixed size. Do not reimplement
  container editing.
- Role `single` renders one numeric Position input.
- Role `range_begin` renders a Start index input and an End index input.
- Role `range_begin` also renders this fixed caption as ordinary visible text, never as a
  tooltip:

```
Uses the half-open range [start, end)
```

- Role `range_begin` also renders the output of `rangeElementsPreview`, for example:

```
Elements in range: [-2, 8, 1]
```

- An invalid position renders an inline text error with `role="alert"` and `aria-invalid` on
  the input.
- Never signal errors by color alone.
- Never block typing while a value is transiently invalid.
- Every input has a real `<label htmlFor>`.
- Every button is `<button type="button">` with a descriptive `aria-label`.
- Reuse the Tailwind class conventions already established in `ContainerValueEditor`.
- The editor never renders, accepts, or echoes C++ iterator syntax.

---

## 17. editor/page.tsx integration

- Wire the new editor in the same argument-input branch that currently dispatches on
  `kind === "container"`, adding a `kind === "iterator"` case.
- Skip any parameter whose `iterator_role` is `"range_end"` in the argument list. Its wire
  value is written by the head's editor through `onTailChange`.
- Keep `test.arguments[parameterIndex]` a string.
- Keep `updateTestArgument` as the single update path.
- Do not restructure function-test state.
- Key `expected_final_arguments` by the head parameter's name, matching the backend.

---

## 18. Template and callable limitations

### 18.1 Template handling is unchanged

- Do not modify template parsing.
- Do not modify `SUPPORTED_TEMPLATE_TYPE_ARGUMENTS`.
- Do not modify `TEMPLATE_TYPE_OPTIONS`.
- Do not modify `frontend/lib/templateTesting.ts`.
- Template functions with generic parameters continue to behave exactly as they do today.

### 18.2 Template iterator parameters are unsupported

`template <typename It, typename Pred> int f(It first, It last, Pred pred)` is not supported,
because `It` cannot be resolved to a concrete backing container. If it reaches iterator
handling at all, reject it with this reason:

```
Template iterator parameters are not supported; use a concrete container iterator type.
```

### 18.3 External callable parameters are fully deferred

No callable metadata is added. No `"callable"` kind is added to `ValueType`. No
`callable_template_parameter` field is added. No allowlist constant is added. No callable
lambda source is generated. No callable UI files are created.

The rationale must not be re-litigated during implementation:

- The only cheap candidate signal was "a template type parameter appearing exactly once as a
  bare value parameter and not used by other parameters or the return type."
- That signal matches `template <typename T> int f(T value)` exactly as well as it matches
  `template <typename Pred> int f(const std::vector<int>& values, Pred pred)`. Both arrive as
  `kind="scalar"` with `scalar_type` equal to the template parameter name. There is no
  structural difference between them.
- Classifying on that signal would silently convert every ordinary generic scalar parameter
  into a callable slot, breaking existing template tests and producing nonsensical UI.
- Distinguishing them reliably requires either parsing the function body to observe call
  syntax such as `pred(x)`, or general declarator parsing for `std::function` and
  function-pointer forms. Both are out of scope.
- Name-based heuristics such as matching `Pred`, `Compare`, or `Func` are rejected, because
  this plan already establishes that parameter names never drive semantics.

Functions with such parameters continue to behave exactly as they do today.

---

## 19. Object-scenario limitations

- Object-scenario iterator parameters are deliberately deferred.
- Do not modify `backend/app/services/object_analysis.py`.
- Do not modify `frontend/components/ObjectScenarioTests.tsx`.
- Methods that use iterators or algorithms INTERNALLY already work. Cover that with one
  integration test in section 24.3.
- If an object method exposes an iterator parameter, `object_analysis` should surface it as
  unsupported through its existing mechanism. Do not add new rejection code there unless a
  test demonstrates an actual crash.

---

## 20. STL algorithm integration

- No algorithm engine, no algorithm registry, and no algorithm-specific backend code.
- Algorithms are covered purely by integration tests proving that ordinary student functions
  using them compile and run correctly.
- Because `<algorithm>` and `<numeric>` are deliberately not injected into the harness
  preamble, every algorithm integration test fixture must include its own headers, exactly as
  a student would.
- Add one dedicated test asserting that a missing `<algorithm>` include produces a compile
  error rather than a silent pass. That test locks in this decision.

---

## 21. Exception and memory compatibility

- Do not modify any `memory_*.py` module.
- Do not modify `big_five_diagnosis.py`.
- Do not modify `execution_providers.py`.
- Do not modify any exception infrastructure.
- Runtime sanitizer and Valgrind output remains the sole authority for iterator misuse,
  including dereferencing `end()`, using invalidated iterators, and using erased iterators.
- Add no static iterator-correctness analysis.
- Cover with one test for an iterator function that throws.
- Cover with one test confirming that an iterator function with a real memory fault is still
  reported by the existing diagnostics, unchanged.

---

## 22. Result formatting

- Reuse the existing generic result panel.
- The only change is in `frontend/app/editor/page.tsx`. When
  `return_type_metadata.kind === "iterator"`, pass expected and actual values through
  `formatIteratorResult` at RENDER TIME ONLY.
- `"end"` therefore displays as `end()`, and `2` displays as `Index 2`.
- Never mutate the value sent to the backend.
- Never display raw pointer values or addresses.

---

## 23. Validation and security

These invariants are unchanged and non-negotiable.

- No `shell=True` anywhere.
- No arbitrary or user-supplied compiler flags.
- No raw C++ expressions, declarations, or lambda text accepted from the browser.
- All generated C++ is built server-side from validated structured metadata.
- Bounded element counts, capped at the existing container limit of 50.
- Bounded output size.
- Enforced timeouts.
- Docker restrictions preserved.
- Temp-directory cleanup preserved.

New rules introduced by this feature:

- Iterator positions are integers, bounds-checked server-side.
- Frontend validation is advisory only and is never trusted.
- A group tail carrying its own `container` key is rejected server-side, because accepting it
  would silently reintroduce cross-container ranges.
- Container payloads inside iterator arguments flow through the existing `_container_literal`
  and `_safe_literal` validation, with no new literal path.

---

## 24. Exact backend tests

### 24.1 backend/tests/test_iterator_analysis.py

Approximately 14 tests. No compilation required.

- Parse `std::vector<int>::iterator` successfully.
- Parse `std::deque<int>::iterator` successfully.
- Parse `std::list<int>::iterator` successfully.
- Parse `std::array<int, 3>::iterator` successfully and assert `fixed_size == 3`.
- Parse `std::vector<int>::const_iterator` and assert `iterator_const is True`.
- Two adjacent identical iterator parameters produce roles `range_begin` and `range_end`
  sharing one `iterator_group_index`.
- Two adjacent iterators of different types produce two groups, each with role `single`.
- Three adjacent identical iterators are rejected with the ambiguity reason.
- `std::vector<int>::reverse_iterator` is rejected with the unsupported-iterator message.
- `std::set<int>::iterator` is rejected with the unsupported-iterator message.
- `std::vector<std::vector<int>>::iterator` is rejected as a nested-container iterator.
- An iterator return type with exactly one matching backing candidate is supported and
  records `iterator_group_index`.
- An iterator return type with zero matching candidates has `supported is False` with the
  documented reason.
- An iterator return type with two matching candidates has `supported is False` with the
  documented reason.

### 24.2 backend/tests/test_iterator_execution.py

Approximately 14 tests. Guard with the existing `NEEDS_GPP` marker. Reuse the
`container_request` fixture pattern from `backend/tests/test_container_execution.py`.

- A single iterator dereferenced inside the function returns the expected value.
- `int sumRange(std::vector<int>::iterator first, std::vector<int>::iterator last)` over
  `[1, 2, 3, 4, 5]` with range `[1, 4)` returns `9`.
- An empty container with range `[0, 0)` returns `0`.
- A position equal to the element count is accepted and denotes `end()`.
- A negative position is rejected with the documented message.
- A position greater than the element count is rejected with the documented message.
- A `std::list<int>` range works correctly, proving `std::next` is used rather than
  `begin() + n`.
- A `const_iterator` range compiles and passes.
- Mutation: `void doubleRange(...)` over `[1, 2, 3, 4]` with range `[1, 3)` produces
  expected-after `[1, 4, 6, 4]`.
- A returned iterator into the backing container reports `Index 2`.
- A returned `end()` iterator reports `"end"`.
- ALIASING PROOF: for a two-iterator function, assert that the generated harness source
  produced by `_build_function_harness` contains exactly one occurrence of the substring
  `inktocode_iterbase_`. This is the canary for the most dangerous failure mode in this
  feature.
- An iterator function that throws `std::out_of_range` passes as a throws test.
- Existing scalar and vector function tests still pass with the new `<iterator>` preamble
  entry.

### 24.3 backend/tests/test_algorithm_integration.py

Approximately 9 tests.

- A function using `std::find` with its own `#include <algorithm>`.
- A function using `std::count_if` with an internal lambda.
- A function using `std::sort` that mutates a vector parameter.
- A function using `std::transform` that returns a vector.
- A function using `std::accumulate` with its own `#include <numeric>` that returns a scalar.
- A function using `std::remove_if` followed by `erase`.
- A function using `std::for_each` with an internal lambda that captures by reference.
- An object-scenario class whose method calls `std::sort` internally.
- A function that calls `std::sort` WITHOUT including `<algorithm>`, asserting that a compile
  error is reported.

Do not materially exceed approximately 49 new tests in total across backend and frontend.

---

## 25. Exact frontend tests

Create `frontend/tests/iteratorValues.test.mts` with approximately 12 tests, run through
node's built-in test runner.

- Head payload round-trips through `headArgumentPayload` and `parseHeadArgument`.
- Tail payload round-trips through `tailArgumentPayload` and `parseTailArgument`.
- The tail payload contains no `container` key.
- `elementCountOf` returns the correct count for a populated array.
- `elementCountOf` returns `0` for an empty or unparseable argument.
- `validatePosition` accepts position `0`.
- `validatePosition` accepts a position equal to the count, denoting `end()`.
- `validatePosition` rejects `-1`.
- `validatePosition` rejects count plus one, and rejects non-integer input.
- An empty container permits the range `[0, 0)`.
- `rangeElementsPreview` respects half-open semantics.
- `positionHelperText` produces the `end()` wording at the boundary,
  `iteratorStateSignature` differs between `vector<int>` and `list<int>`, and
  `formatIteratorResult` maps `"end"` to `end()` and `2` to `Index 2`.

---

## 26. Implementation groups and order

Follow this order exactly. Do not split these groups further, and do not reorder them.

### Group G1 — iterator metadata

- Add the four `ValueType` fields.
- Add `_ITERATOR_TYPE`.
- Add `_parse_iterator_type`.
- Wire into `_parse_value_type`.
- Apply the `_FUNCTION_DEFINITION` suffix.
- Add `_assign_iterator_groups`.
- Add return-backing resolution.
- Extend `type_response` with the new fields.
- Then run T1.

### Group G2 — iterator execution

- Add `_prepare_iterator_arguments`.
- Add `_parse_iterator_argument`.
- Add the `<iterator>` preamble entry.
- Add return serialization.
- Add the mutation branch.
- Add the `_metadata_value`, `_typed_match`, and `_typed_mismatch_detail` branches.
- Then run T2.

### Group G3 — frontend iterator

- Extend `FunctionTypeMetadata`.
- Fix the `isFunctionTypeMetadata` guard.
- Create `iteratorValues.ts`.
- Create `IteratorValueEditor.tsx`.
- Wire `editor/page.tsx`, including the range-tail skip.
- Then run T3 and T5.

### Group G4 — algorithm and internal-lambda integration

- Add the algorithm integration tests.
- Add iterator result formatting in the result panel.
- Then run T2, T4, and T5.

### Group G5 — regression and documentation

- Run the full regression suite.
- Update documentation.

---

## 27. Focused commands

Run each command from the repository root.

T1, after G1:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_iterator_analysis.py -q
```

T2, after G2:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_iterator_execution.py -q
```

T3, after G3:

```bash
cd frontend && npm test && cd ..
```

T4, after G4:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_algorithm_integration.py -q
```

T5, after G3 and G4:

```bash
cd frontend && npm run lint && npm run build && cd ..
```

Run pytest from the repository root using the absolute venv path shown above. Running
`cd backend` first will break collection, because rootdir then resolves incorrectly.

Do not run the full suite before G5.

---

## 28. Full regression commands

Run these once, at G5.

```bash
backend/.venv/bin/python -m pytest backend/
```

```bash
backend/.venv/bin/python -m compileall backend/app
```

```bash
cd frontend && npm test && npm run lint && npm run build && cd ..
```

```bash
git status
```

Known pre-existing failure:

```
backend/tests/test_memory_diagnostics.py::test_destruction_time_sanitizer_error_fails_object_scenario
```

That test fails on unmodified `main`, verified previously with `git stash`. It is not caused by
this work. Report it as pre-existing, do not attempt to fix it, and do not treat it as a
hard-stop condition.

---

## 29. Manual verification

- `int sumRange(std::vector<int>::iterator first, std::vector<int>::iterator last)` shows one
  container editor plus Start index and End index. The half-open caption is visible, and no C++
  syntax appears anywhere.
- The same function with `std::list<int>` iterators passes, proving `std::next` is used.
- `void doubleRange(std::vector<int>::iterator first, std::vector<int>::iterator last)`
  accepts an expected-after container and compares it correctly.
- `std::vector<int>::iterator findValue(std::vector<int>& values, int target)` reads
  `Index 2` for a found case and `end()` for a not-found case.
- A position equal to the container size is accepted.
- A position of size plus one is rejected with a clear message.
- An empty container with the range `[0, 0)` passes.
- A function calling `std::sort` without `#include <algorithm>` produces a visible compile
  error rather than passing.
- All existing scalar, vector, container, template, object-scenario, exception, and memory
  tests behave identically in the UI.

---

## 30. Documentation changes

Apply these at G5 only, after everything is green.

### AGENTS.md

Add an "Iterator testing" section covering:

- Supported containers, which are `vector`, `deque`, `list`, and `array`.
- Half-open `[start, end)` range semantics.
- The one-backing-container-per-group rule, and why a range tail cannot carry a container.
- That the harness resolves the returned iterator's backing container structurally, and cannot
  prove the returned iterator actually points into it.
- That a returned iterator into a different container is undefined student behavior, is not
  detected, and yields meaningless results.
- That the harness adds `<iterator>` only, and that student code must supply its own algorithm
  headers.
- That runtime sanitizer and Valgrind output remains the sole authority for iterator misuse.
- The full unsupported list from section 3, including the deferral of external
  template-callable parameters and the reason for it.

### backend/README.md

Add:

- The iterator wire format for the head and the tail.
- Position bounds, including that a position equal to the element count denotes `end()`.
- That a tail carrying its own container is rejected.
- An explicit statement that function pointers, `std::function`, and external
  template-callable parameters are unsupported.

### frontend/README.md

Add:

- The iterator editor description, covering the embedded container editor, the position and
  range inputs, and the visible half-open caption.

### CLAUDE.md

Not edited.

---

## 31. Known limitations

- Everything listed in section 3.
- One position per iterator, with no arithmetic beyond a single `std::next` offset.
- Ranges limited to exactly two adjacent iterators of identical type.
- Returned iterators are resolved structurally only, with no verification that the returned
  iterator belongs to the resolved container.
- Cross-container iterator returns are undefined student behavior.
- No callable support of any kind in this stage. Internal lambdas remain fully supported.
- Missing algorithm headers in student code surface as compile errors by design, not as
  harness failures.
- Object-scenario iterator parameters remain unsupported.

---

## 32. Likely failure points

- The `isFunctionTypeMetadata` guard is not updated, so iterator functions vanish from the UI
  with no console error. Check this first.
- Two `inktocode_iterbase_` declarations are emitted, producing an invalid cross-container
  range that may still pass by luck on small inputs. The aliasing-proof test is the canary.
  The tail must emit `declarations=()`.
- `begin() + n` is used instead of `std::next`, so `std::list` fails to compile while
  everything else passes. The `std::list` range test catches this.
- The range tail is added to `mutation_capable_parameters`, so the
  `set(expectations) == mutable_names` validator rejects every mutation test.
- `_FUNCTION_DEFINITION` is edited beyond the documented suffix, producing broad and confusing
  failures across unrelated existing tests.
- The iterator branch is placed inside `_prepare_argument` after the `passing` check, so
  iterators fall into the mutable-reference path and generate invalid C++. Use the pre-pass.
- `operator-` is used for the returned iterator, so `list` and `deque` fail to compile. Always
  use `std::distance`.
- The tail argument sends its own `container` field, silently reintroducing the aliasing bug.
  The backend must reject it.
- `<algorithm>` or `<numeric>` is added to the harness preamble out of convenience, silently
  masking student include errors. The dedicated missing-include test exists to prevent this.
- A template scalar parameter is classified as a callable, breaking existing template tests.
  Section 18.3 forbids this outright.

---

## 33. Hard-stop conditions

- A maximum of two focused repair attempts per underlying failure. After that, stop and report
  with the exact command output.
- Stop immediately if any legacy regression fails, covering scalar, vector at depth 1 and 2,
  array, pointer and reference, string, container, adapter, template, object-scenario,
  exception, or memory tests. The sole exception is the documented pre-existing
  memory-diagnostics failure.
- Stop if a fix appears to require modifying any `memory_*.py` module, exception
  infrastructure, `object_analysis.py`, `backend/app/schemas/test_execution.py`, or
  `backend/app/api/test_execution.py`. This plan asserts none of them are needed, so that
  signal means the approach has drifted.
- Stop if supporting function pointers or `std::function` begins to require rewriting the
  parameter group inside `_FUNCTION_DEFINITION`. They are out of scope by design.
- Stop if callable support appears to require function-body parsing or general declarator
  parsing. It is deferred by design. Do not revive it.
- Do not expand scope to associative iterators, reverse iterators, ranges, views, or callables
  of any form.
- Do not commit.
