# AI Test Generation — Gemini Structured-Output Schema Repair Plan

Diagnosis completed against the live `gemini-3.5-flash-lite` endpoint using isolated,
harmless-prompt reproductions. No application source was modified during diagnosis.

---

## 1. Confirmed current request path

`POST /api/ai-tests/run`
→ `app/api/ai_tests.py`
→ `app/services/ai_test_orchestration.py`
  - function targets: line 260 `generate_function_tests(...)`
  - object targets: line 386 `generate_object_tests(...)`
  - repair (function): line 287 — **same function**, `rejected_tests=` supplied
  - repair (object): line 408 — **same function**, `rejected_tests=` supplied
→ `app/services/ai_test_generation.py`
  - `generate_function_tests` line 453 → `_call_gemini(prompt, AiModelTestPlan.model_json_schema(), ...)`
  - `generate_object_tests` line 532 → `_call_gemini(prompt, AiModelScenarioPlan.model_json_schema(), ...)`
  - `_call_gemini` line 331 → `types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=json_schema)`
  - `_parse_response` line 355 → `_response_is_blocked` → `response.text` → `schema.model_validate_json(text)`

**Initial generation and repair generation use the identical config path and the identical
schema.** There is no separate repair schema. Confirmed by code inspection: the repair call
differs only by the `rejected_tests` argument, which affects prompt text only.

Schema transport currently in use: **`response_json_schema` only**. `response_schema` is
not used anywhere in `ai_test_generation.py`. (`app/services/transcription.py` lines 306 and
489 still use `response_schema`, and those calls work — see §6.)

Response handling: **`response.text` is consumed; `response.parsed` is not used.** The
implementation manually validates the returned JSON through the original strict Pydantic
model via `model_validate_json`.

---

## 2. Installed SDK and model configuration

| Item | Value |
|---|---|
| `google-genai` | **1.75.0** |
| `pydantic` | 2.13.4 |
| Python | 3.13.5 |
| `settings.test_generation_model` | **`gemini-3.5-flash-lite`** |
| `settings.transcription_model` | `gemini-3.5-flash-lite` |
| `GEMINI_TEST_GENERATION_MODEL` in `.env` | **not set** — falls back to `GEMINI_TRANSCRIPTION_MODEL` (`app/config.py` lines 38–42) |

`GenerateContentConfig` in 1.75.0 exposes **both** `response_schema`
(`Union[dict, type, Schema, ...]`) and `response_json_schema` (`Optional[Any]`). Both fields
are available; neither is missing.

Captured request configuration immediately before the SDK call (contents and key excluded):

```
generationConfig keys : ['responseJsonSchema', 'responseMimeType']
responseMimeType      : application/json
schema transport field: responseJsonSchema
serialized schema     : 2968 bytes (AiModelTestPlan) / 4226 bytes (AiModelScenarioPlan)
model                 : gemini-3.5-flash-lite
```

---

## 3. Exact schemas inspected

### `AiModelTestPlan.model_json_schema()`
- 2968 bytes; top-level keys `['$defs','additionalProperties','properties','required','title','type']`
- 2 definitions: `AiModelFunctionTest`, `AiModelMutation`
- Keyword census: `additionalProperties`×3, `anyOf`×4, `default`×5, `enum`×4, `title`×19,
  `minLength`×4, `maxLength`×8, `minItems`×1, `maxItems`×4, `$ref`×2
- `maxItems` locations:
  - `$.properties.tests` → `maxItems: 8`, `minItems: 0`, `items: {"$ref": "#/$defs/AiModelFunctionTest"}`
  - `$.properties.skipped_topics` → `maxItems: 5`, `items: {"type":"string"}`
  - `$.$defs.AiModelFunctionTest.properties.arguments` → `maxItems: 20`, `items: {"type":"string"}`
  - `$.$defs.AiModelFunctionTest.properties.expected_mutations` → `maxItems: 20`, `items: {"$ref": "#/$defs/AiModelMutation"}`

### `AiModelScenarioPlan.model_json_schema()`
- 4226 bytes; 3 definitions: `AiModelScenarioObject`, `AiModelScenarioStep`, `AiModelScenarioTest`
- Keyword census: `additionalProperties`×4, `anyOf`×5, `default`×8, `enum`×7, `title`×28,
  `minLength`×4, `maxLength`×7, `minItems`×3, `maxItems`×6
- `maxItems` on `$ref`-item arrays: `$.properties.tests` (8),
  `$.$defs.AiModelScenarioTest.properties.objects` (5),
  `$.$defs.AiModelScenarioTest.properties.steps` (10)

### Structural findings (both schemas)
- **No `$ref` nodes with sibling keys.**
- **No recursive references.**
- **No dictionary/map-shaped fields** (every `additionalProperties` is the boolean `false`,
  never a subschema).
- Unions appear only as `anyOf`; nullability is Pydantic's `anyOf: [{...}, {"type": "null"}]`.
- No `oneOf`, `allOf`, `prefixItems`, `pattern`, `const`, `discriminator`, or `nullable`.

### Repair-response schema
**None exists.** Repair reuses `AiModelTestPlan` / `AiModelScenarioPlan` verbatim.

---

## 4. Controlled reproduction results

Model `gemini-3.5-flash-lite`, transport `response_json_schema`, prompt
`"Return a valid object matching the supplied schema."` HTTP 429 responses were retried,
so every result below is a genuine schema verdict.

### Isolated feature probes — **all accepted**

| Probe | Result |
|---|---|
| A simple object | OK |
| B `additionalProperties: false` | OK |
| C nested array of objects | OK |
| D nullable via `anyOf` + `{"type":"null"}` + `default: null` (exact Pydantic form) | OK |
| E `enum` | OK |
| F `$defs` + `$ref` | OK |
| G `minLength` / `maxLength` | OK |
| H `minItems` / `maxItems` on a string array | OK |
| I `default` | OK |
| J `title` | OK |

**No individual JSON Schema keyword used by either model is rejected.**

### Full application schemas

| Schema | Result |
|---|---|
| `AiModelTestPlan` (full) | **FAIL 400 INVALID_ARGUMENT** ×3 |
| `AiModelScenarioPlan` (full) | **FAIL 400 INVALID_ARGUMENT** ×3 |

### Single-keyword removal from full `AiModelTestPlan`

| Removed | Result |
|---|---|
| `title` | FAIL 400 |
| `default` | FAIL 400 |
| `minLength` | FAIL 400 |
| `maxLength` | FAIL 400 |
| `minItems` | FAIL 400 |
| `additionalProperties` | FAIL 400 |
| `enum` | FAIL 400 |
| `anyOf` | FAIL 400 |
| **`maxItems`** | **OK** |

### `maxItems` localisation (3 trials each)

| Variant | Result |
|---|---|
| drop `maxItems` at **`$.properties.tests` only** | **OK, OK, OK** |
| drop `maxItems` at `expected_mutations` only | FAIL, FAIL, FAIL |
| drop `maxItems` on both `$ref`-item arrays | OK, OK, OK |
| drop `maxItems` on both primitive-item arrays | FAIL, FAIL, FAIL |

### Decisive threshold experiment — vary `$.properties.tests.maxItems`, full schema otherwise

| `tests.maxItems` | `AiModelTestPlan` | `AiModelScenarioPlan` |
|---|---|---|
| 1 | **OK** | FAIL 400 |
| 2 | **OK** | FAIL 400 |
| 3 | FAIL 400 | — |
| 4 | FAIL 400 | FAIL 400 |
| 6 | FAIL 400 | — |
| 8 | FAIL 400 | FAIL 400 |

A bound of 2 is accepted and a bound of 3 is rejected **with the schema otherwise byte-identical**.
The larger `AiModelScenarioPlan` item type is rejected even at a bound of 1.

### Proposed-fix verification (3 trials each)

| Schema | Transform | Result |
|---|---|---|
| `AiModelTestPlan` | strip **`maxItems`** only | **OK, OK, OK** |
| `AiModelScenarioPlan` | strip **`maxItems`** only | **OK, OK, OK** |

### Minimal reconstructions that were **accepted** (proving keyword support)
- `$ref`-item array + `maxItems: 8` — OK
- `$ref`-item array + `minItems: 0` + `maxItems: 8` + `title` — OK
- Two-level nested `$ref` arrays with `maxItems: 8` / `maxItems: 20` + `default: []` +
  `additionalProperties: false` — OK

---

## 5. Exact root cause

**Gemini rejects the request because `maxItems` is applied to arrays whose item type is a
`$ref` to a large object, and the resulting bounded-array expansion exceeds the endpoint's
internal structured-output complexity budget. The rejection is a function of the bound value
multiplied by item complexity, not of any unsupported keyword.**

Proven by:

1. Every JSON Schema keyword in both schemas is accepted in isolation, including `maxItems`,
   `$ref`, `additionalProperties: false`, `anyOf`+null, `enum`, `default`, and `title`.
2. Removing `maxItems` — and only `maxItems` — from the full schema converts a reproducible
   400 into a reproducible success, 3/3, on **both** schemas. Every other single-keyword
   removal leaves the 400 intact.
3. The threshold experiment isolates the mechanism: with the schema otherwise byte-identical,
   `tests.maxItems: 2` is accepted and `tests.maxItems: 3` is rejected. A pure keyword-support
   failure cannot depend on the numeric bound.
4. The effect scales with item complexity, not with schema byte size: the 2968-byte
   `AiModelTestPlan` tolerates a bound of 2, while the 4226-byte `AiModelScenarioPlan`
   (whose item type itself contains two further bounded `$ref` arrays, `objects: 5` and
   `steps: 10`) is rejected at a bound of 1.
5. `maxItems` on primitive-item arrays (`skipped_topics`, `arguments`) is harmless: removing
   those two while leaving the `$ref`-array bounds in place still returns 400, 3/3.

Not the cause, each excluded by evidence: unsupported schema keywords (§4 probes A–J);
model incompatibility (the same model accepts 10/10 probes and both stripped schemas);
`response_json_schema` itself (accepted in every passing case); request size (the smaller
schema fails while a larger stripped schema succeeds); prompt content (identical harmless
prompt throughout); SDK version (SDK serialisation verified correct, §7); repair-call
behaviour (repair shares one code path and one schema with initial generation).

---

## 6. Why the previous `response_schema` fix failed

The original error was:

```
Unknown name "additional_properties" at 'generation_config.response_schema'
```

Captured wire payload for `response_schema=AiModelTestPlan` under google-genai 1.75.0:

```
generationConfig keys : ['responseMimeType', 'responseSchema']
responseSchema inner keys include: additional_properties, max_items, max_length,
                                   min_items, min_length, nullable, property_ordering
```

The `response_schema` path converts the schema into the proto `Schema` type, which
snake_cases every field name. `extra="forbid"` on the AI models emits
`additionalProperties: false`, which becomes the literal key `additional_properties` — a name
the endpoint does not accept. This was a **real and correctly diagnosed defect**, and moving
off `response_schema` genuinely fixed it.

Why transcription is unaffected: `ModelTranscription` and `QuestionExtraction` do **not** set
`extra="forbid"` (`model_config.extra` is `None`). Their serialised `responseSchema` is 1133
bytes and contains **no** `additional_properties` key. Verified directly.

---

## 7. Why the `response_json_schema` attempt still failed

It fixed the reported problem and introduced no new one. Captured wire payload:

```
generationConfig keys : ['responseJsonSchema', 'responseMimeType']
responseJsonSchema inner keys: $defs, $ref, additionalProperties, anyOf, default, enum,
                               items, maxItems, maxLength, minItems, minLength,
                               properties, required, title, type
```

The SDK passes the dict through verbatim: correct camelCase `responseJsonSchema` envelope,
and **no snake_case corruption inside the schema** — `additionalProperties` survives intact.
`additional_properties` is produced **only** by the legacy `response_schema` path and never by
`response_json_schema`.

The `response_json_schema` change was therefore correct and must be kept. It simply exposed a
**second, independent defect** that the first error had been masking: the bounded-`$ref`-array
complexity rejection described in §5. Two distinct causes produced two distinct 400s, and only
the first had a field path in its message.

---

## 8. Exact files to modify

| File | Change |
|---|---|
| `backend/app/services/ai_test_generation.py` | Add one private helper; use it at the two existing `_call_gemini` call sites. |
| `backend/tests/test_ai_test_generation.py` | Add focused tests (§17). |

**No other file may change.** Do **not** modify `backend/app/schemas/ai_tests.py`,
`ai_test_orchestration.py`, `transcription.py`, `config.py`, `.env`, or any frontend file.

---

## 9. Exact code path to change

`backend/app/services/ai_test_generation.py`

**Add** a module-level private helper next to `_call_gemini`:

```python
def _wire_schema(model: type) -> dict:
    """JSON Schema for Gemini transport, with array upper bounds removed.

    Gemini rejects `maxItems` on arrays whose items are `$ref`s to large objects
    (400 INVALID_ARGUMENT, no field path). Bounds remain enforced locally by the
    Pydantic model in `_parse_response`, which is the sole validation authority.
    """
```

Behaviour: deep-copy `model.model_json_schema()` and recursively delete **every** `maxItems`
key at every depth, including inside `$defs`, `items`, and `anyOf` branches. Return the copy.
Nothing else is altered — `minItems`, `additionalProperties`, `anyOf`, `enum`, `default`,
`title`, `minLength`, `maxLength`, `$defs`, `$ref`, and `required` are all preserved.

**Change** exactly two call sites:

- `generate_function_tests` line 453:
  `AiModelTestPlan.model_json_schema()` → `_wire_schema(AiModelTestPlan)`
- `generate_object_tests` line 532:
  `AiModelScenarioPlan.model_json_schema()` → `_wire_schema(AiModelScenarioPlan)`

**Must not change:** `_call_gemini`'s signature or body, `_parse_response`, `_map_service_error`,
`_AI_GENERATION_MESSAGES`, `_TRANSCRIPTION_TO_GEN`, both prompt builders, `select_source_context`,
or either public function's signature.

Strip `maxItems` only. Do **not** strip `minItems` — it is proven harmless
(`AiModelTestPlan` minus `maxItems` alone succeeds 3/3), and removing it would widen the
change without evidence.

---

## 10. Exact schema-transport strategy

Keep `response_json_schema`. Keep `response_mime_type="application/json"`.
Do **not** reintroduce `response_schema` on the AI path — §6 proves it corrupts
`additionalProperties` whenever `extra="forbid"` is set.

Do **not** switch models. The current model accepts every probe and both stripped schemas;
§5 proves the model is not the cause. `transcription_model` and `test_generation_model` are
already the same model.

Do **not** apply general schema sanitisation. Only `maxItems` is proven to require removal;
every other keyword is proven accepted.

---

## 11. Strict local Pydantic validation to preserve

`extra="forbid"` **stays** on every model in `app/schemas/ai_tests.py`. It is not the cause of
the current failure, and it is what makes local validation strict.

`_parse_response` must keep calling `schema.model_validate_json(text)` against the **unmodified**
Pydantic model. Because `_wire_schema` returns a throwaway dict and never touches the class,
all constraints — `extra="forbid"`, `max_length=8` on `tests`, `max_length` on `arguments`,
`expected_mutations`, `objects`, `steps`, `skipped_topics`, every string bound, every `Literal`,
and both `field_validator`s — remain fully enforced after the response arrives.

The wire schema is a **hint** to the model; the Pydantic model remains the **authority**.
Relaxing the upper bound on the wire cannot relax it locally.

Consequence to accept as-is: if the model ever returns more than 8 tests, `model_validate_json`
raises and `_parse_response` maps it to `invalid_model_response`. Both prompts already state
`"hard maximum: 8"`. Do **not** add truncation, do **not** relax `max_length`, and do **not**
loosen `extra="forbid"` to work around this unless it is actually observed.

---

## 12. Initial-generation handling

Both initial paths route through the two changed call sites and require no further edits:
`generate_function_tests` (orchestration line 260) and `generate_object_tests` (line 386).
Error handling, `target_id` cross-check, and blocked-response handling stay exactly as they are.

---

## 13. Repair-generation handling

Repair requires **no separate change**. Orchestration lines 287 and 408 call the same two
functions with `rejected_tests=`, so they pick up `_wire_schema` automatically. `rejected_tests`
affects prompt text only and must continue to do so. Do not introduce a repair-specific schema.

---

## 14. Function schema handling

`AiModelTestPlan` — four `maxItems` removed for transport: `tests` (8),
`skipped_topics` (5), `arguments` (20), `expected_mutations` (20).
Verified accepted 3/3. `minItems: 0` on `tests` is retained.

---

## 15. Object schema handling

`AiModelScenarioPlan` — six `maxItems` removed for transport, including the nested
`objects` (5) and `steps` (10) inside `AiModelScenarioTest`.
Verified accepted 3/3. The `minItems: 1` bounds on `objects` and `steps` are retained.

---

## 16. Error mapping and safe diagnostics

Current behaviour, confirmed correct — **do not change the mapping**:

`errors.ClientError` (code `400`, status `INVALID_ARGUMENT`) → `_classify_api_error`
(`transcription.py`) matches no branch and falls to the catch-all → `gemini_service_error`
→ `_map_service_error` → `generation_failed` / HTTP 502, message
`"AI tests could not be generated right now."` → orchestration line 271
`AiTestRunResponse(status=exc.code, message=exc.message)` → frontend banner.

The generic user-facing message is correct and must stay. Gemini returns no field path for
this class of rejection, so no useful detail is available to surface, and raw Gemini errors
must never reach users.

Existing safe logging in both generation functions already records
`type`, `code`, `status`, `model`, and a 300-char key-redacted message. That is sufficient —
it emits `code=400 status=INVALID_ARGUMENT`. **Keep it unchanged.** One permitted addition:
a single `logger.debug` recording the serialised wire-schema **byte size and top-level key
names only**. Never log schema contents, prompts, source code, question text, or the API key.

---

## 17. Focused backend tests

Add to `backend/tests/test_ai_test_generation.py`. All must use the existing `_FakeClient` /
`_FakeModels` fakes — **no test may contact Gemini.**

1. `test_wire_schema_removes_all_max_items_function` — `_wire_schema(AiModelTestPlan)`
   serialised contains no `"maxItems"` at any depth.
2. `test_wire_schema_removes_all_max_items_object` — same for `AiModelScenarioPlan`,
   including the nested `objects` / `steps` bounds inside `$defs.AiModelScenarioTest`.
3. `test_wire_schema_preserves_additional_properties_false` — top level and every `$defs`
   entry still carry `additionalProperties: False`.
4. `test_wire_schema_preserves_min_items_and_other_keywords` — `minItems`, `minLength`,
   `maxLength`, `enum`, `anyOf`, `default`, `$ref`, `$defs`, `required` all still present.
5. `test_wire_schema_does_not_mutate_the_pydantic_model` — call `_wire_schema` twice, then
   assert `AiModelTestPlan.model_json_schema()` still contains `maxItems` and that
   `AiModelTestPlan.model_fields["tests"]` still carries its length constraint.
6. `test_function_call_sends_schema_without_max_items` — assert the captured
   `config.response_json_schema` has no `maxItems` and `config.response_schema is None`.
7. `test_object_call_sends_schema_without_max_items` — same for `generate_object_tests`.
8. `test_repair_call_sends_schema_without_max_items` — same with `rejected_tests=[...]`.
9. `test_more_than_eight_tests_still_rejected_locally` — a 9-test payload still raises
   `invalid_model_response`, proving the bound survives on the local side.
10. `test_unknown_field_still_rejected_locally` — `extra="forbid"` still rejects an unknown
    nested field.
11. `test_valid_plan_still_parses_after_wire_schema_change` — happy path for both function
    and object generation.

Existing tests must not be edited. The full file must still pass.

---

## 18. One live manual verification

1. Restart the backend: `uvicorn app.main:app --reload --port 8000 --env-file .env` from `backend/`.
2. In the editor screen, load a single simple function (for example `int absoluteValue(int n)`),
   enter a one-line question, compile, then press **Run AI Tests**.
3. Expected: generated tests execute and a practice score appears.
   The banner `"AI tests could not be generated right now."` must not appear.
4. Confirm the backend log shows **no** `AI test generation API error: ... code=400`.
5. Repeat once for a small class target to exercise `AiModelScenarioPlan`.

---

## 19. Commands

```bash
cd backend
source .venv/bin/activate

python -m compileall app                              # after the source edit
python -m pytest tests/test_ai_test_generation.py -q  # focused suite — must be all green
python -m pytest -q                                   # full suite, once, at the end
```

Known pre-existing unrelated failure in the full suite:
`tests/test_memory_diagnostics.py::test_destruction_time_sanitizer_error_fails_object_scenario`
(host sanitizer-environment assertion). It is not caused by this change and must not be "fixed"
here.

---

## 20. Hard-stop conditions

Stop and report instead of improvising if any of the following occur:

1. Stripping `maxItems` does not clear the 400 in the live check — the endpoint's budget may
   have shifted; re-run the §4 threshold experiment before changing anything else.
2. A fix requires editing `app/schemas/ai_tests.py`. Removing or weakening `extra="forbid"`,
   `max_length`, or any `Literal` is **out of scope**.
3. A fix appears to require switching models or changing `.env`. §5 disproves a model cause.
4. A fix appears to require reverting to `response_schema`. §6 disproves that path.
5. The model begins returning more than 8 tests and `invalid_model_response` becomes frequent.
   Report the observed rate; do not silently add truncation.
6. Any change is needed in `ai_test_orchestration.py`, `transcription.py`, or the frontend.
7. Focused tests pass but the full suite gains a **new** failure beyond the known
   memory-diagnostics one.

Do not commit. Do not broaden scope. Prefer the smallest proven fix.
