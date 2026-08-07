# InkToCode backend

FastAPI service for health checks and temporary, ordered handwriting transcription. Uploaded pages are validated in memory and are not stored.

## Configure and run

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your server-side Gemini key in `backend/.env`:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_TRANSCRIPTION_MODEL=gemini-3.5-flash-lite
GEMINI_TEST_GENERATION_MODEL=gemini-3.5-flash-lite
```

`GEMINI_TRANSCRIPTION_MODEL` and `GEMINI_TEST_GENERATION_MODEL` are both optional. When blank or absent each defaults to `gemini-3.5-flash-lite`. `GEMINI_TEST_GENERATION_MODEL` controls only AI test generation; the transcription model is used as a fallback when it is absent. Start the API with:

```bash
uvicorn app.main:app --reload --port 8000 --env-file .env
```

- Health: [http://localhost:8000/health](http://localhost:8000/health)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

`FRONTEND_ORIGIN` defaults to `http://localhost:3000` and is the only browser origin allowed by CORS unless explicitly changed.

## Transcription request

`POST /api/transcribe` accepts `multipart/form-data` with:

- `handwritten_code_pages`: repeated PNG/JPEG fields, 1–5 pages.
- `handwritten_code_metadata`: JSON array describing those pages.
- `question_pages`: optional repeated PNG/JPEG fields, 0–5 pages.
- `question_metadata`: optional JSON array describing question pages.

Each metadata object contains `file_id`, contiguous 1-based `order`, `category`, `source_type`, `original_filename`, and optional `original_pdf_page_number`. The uploaded multipart filename must equal `file_id`. PDF uploads are rendered in the browser and sent as ordered page images; original PDFs are never sent to this endpoint.

Images are limited to 10 MB each and 50 MB per category. The API validates and explicitly sorts metadata order before calling Gemini. Each validated page is sent as an in-memory PNG or JPEG byte part in the exact selected order. Programming-question pages are appended as a clearly separated context section. Confidence values are model-estimated review aids, not calibrated probabilities.

## Local C++ test execution

`POST /api/test-mode` deterministically classifies current C++17 source as a
full program, a supported function-only submission, or unsupported. `POST
/api/run-tests` accepts 1–10 explicit cases in the corresponding mode. Program
tests provide standard input and expected standard output. Function tests
provide one scalar value per parameter and an expected return value.

Function mode conservatively supports top-level functions returning `void`,
`int`, `long`, `long long`, `double`, or `bool`, with zero or more named
parameters using the supported scalar, string, or vector types. One detected function is selected
automatically. When several supported functions are present, the frontend
requires an explicit target selection and the backend validates that target
against the submitted source. The harness calls only the selected target while
keeping the complete original translation unit available for helper calls.
Overloaded function names and other ambiguous source are rejected without
guessing. Arguments accept signed decimal integers,
finite decimal doubles, and lowercase `true` or `false`; arbitrary C++
expressions are never accepted. A temporary harness calls the unchanged user
target. Bool returns print as `true` or `false`, and doubles use 17 significant
digits without fuzzy comparison.

Function tests and object scenarios support 15 standard-library STL containers:
`std::vector`, `std::array`, `std::deque`, `std::list`, `std::set`, `std::multiset`,
`std::map`, `std::multimap`, `std::unordered_set`, `std::unordered_multiset`,
`std::unordered_map`, `std::unordered_multimap`, `std::stack`, `std::queue`, and
`std::priority_queue`. Supported element, key, and value types are limited to scalar
types (`int`, `long`, `long long`, `float`, `double`, `bool`, `char`) and `std::string`.
Container metadata and values are validated as structured data and compiled safely
server-side. Adapters (`stack`, `queue`, `priority_queue`) use default comparators and
are compared in their logical pop/peek order. Nested containers inside non-vector
containers are not supported; `std::vector<std::vector<T>>` (depth 2) remains the only
supported nested form. Custom comparators, custom allocators, and C++20 ranges are not
supported.


Nested vectors use strict JSON-style outer and row lists such as
`[[1, 2], [3, 4]]`. Rectangular, jagged, empty outer, and empty-row shapes are
preserved. Every row and innermost value is validated before safe C++ literals
are generated. Results serialize canonically without flattening and compare
outer length, each row length, row order, element order, and exact typed values.
Structural mismatches report the first useful row or element location when
available. Nesting deeper than two levels, unsupported/custom elements, vector
pointers, and unsupported reference types remain unsupported.

Function tests support one-dimensional numeric C-style array parameters written
as `T values[]` or `T* values`, where `T` is `int`, `long`, `long long`,
`double`, or `bool`. Each array must have exactly one later integral size
parameter named `size`, `count`, `length`, `len`, or `n`; missing or ambiguous
relationships are rejected instead of guessed. Array inputs use the same
numeric list syntax as vectors. The supplied size must be non-negative and may
not exceed the number of provided elements, though it may be smaller.

The temporary harness creates validated local array storage and passes it to the
unchanged target function. Empty input (`[]`) uses a one-element
value-initialized backing array while the explicit size remains zero, avoiding
non-standard zero-length arrays. Pointer-to-pointer and returned-pointer types,
multidimensional arrays, character arrays, and arbitrary expressions are not
supported.

Function mode also supports mutable scalar pointers to `int`, `long`,
`long long`, `double`, `bool`, and `std::string`. A one-level numeric `T*`
parameter is classified as the existing array-backed form when exactly one
recognized later integral size parameter is paired before the next pointer or
array parameter. Without such a size, it is classified as one scalar pointer.
Bracket declarations remain array-backed and always require a size.
`std::string*` is scalar-only.

Each scalar pointer receives one validated initial value and one expected final
value. The harness creates typed local storage, passes its address to the
unchanged target, and serializes the storage after the single function call.
Scalar pointers participate in the existing multiple-mutation and combined
return/stdout result models. Null inputs, const pointers, pointer references,
pointer-to-pointer parameters, custom pointees, and pointer returns are
rejected. This deterministic signature classification does not attempt
general pointer ownership or memory-safety analysis.

Function mode supports `std::string`, `std::vector<std::string>`, and
`std::vector<std::vector<std::string>>`. A scalar string field is the complete
string value and does not require C++ quotation marks. String vectors require
JSON-style quoted-list syntax such as `["hello", "hello world"]`; nested
strings use row lists such as `[["one", "two"], ["three"]]`. Quotes,
backslashes, newlines, tabs, carriage returns, and control bytes are escaped
before safe C++ literals are generated. Scalar strings compare exact contents.
`vector<string>` results serialize canonically as `["hello", "world"]` and
compare exact element contents, order, and length. Character pointers,
character arrays, string pointers, and deeper vector nesting remain
unsupported.

Function mode supports one or more mutable outputs on supported targets. These
may combine scalar references (`int&`, `long&`, `long long&`, `double&`,
`bool&`, or `std::string&`), non-const `std::vector<T>&` parameters using
supported element types, and supported C-style array parameters. Each test
supplies initial values in the ordinary argument list and an explicit
`expected_mutations` entry for every mutable parameter identifier. The backend
rejects missing, duplicate, stale, or immutable identifiers. The harness
creates validated local storage, calls the unchanged target once, and
serializes every final mutable value in parameter order.

Mutated vectors serialize all elements canonically. Mutated arrays serialize
only the first explicit-size elements; supplied backing elements beyond that
size are not part of mutation comparison. Element order and count matter.
Integer, boolean, and string values compare exactly; doubles retain the existing
exact, non-fuzzy policy. Strings use the existing safe literal escaping and
quoted serialization internally.

Scalar and string const references remain read-only inputs. Returned
references, rvalue references, arbitrary pointer mutation, and custom reference
types are unsupported.

Function mode supports iterator parameters for `std::vector<T>::iterator`,
`std::deque<T>::iterator`, `std::list<T>::iterator`, `std::array<T,N>::iterator`,
and their `const_iterator` variants. Two adjacent same-type iterators are paired
as a half-open range `[begin, end)` sharing a single backing container. A lone
iterator of the same type is a single-iterator parameter. Three or more adjacent
same-type iterators are rejected as ambiguous; adjacent iterators of different
types become independent single-iterator parameters. `reverse_iterator`,
set/map/unordered iterators, and nested-element iterators are rejected.

Each iterator parameter is passed as a JSON object. Range-begin (and single)
parameters carry `{"container": [...], "position": N}`. Range-end (tail) parameters
carry only `{"position": N}` — no container key. The position must satisfy
`0 ≤ position ≤ container.size()`; negative positions and positions exceeding
the size are rejected with a clear error message. `std::next(storage.begin(), pos)`
is used for all containers, so `std::list` iterators work correctly without
random-access arithmetic.

Non-const iterator heads are mutation-capable. Mutation comparisons use the final
container contents as a JSON array, not an iterator value. An iterator return type
is supported only when the function has exactly one parameter whose container type
unambiguously matches the return iterator's container type; the return serializes
as an index or `"end"`.

Only `<iterator>` is added to the harness preamble. `<algorithm>` and `<numeric>`
are never injected — the student must include them explicitly. Functions that use
STL algorithms compile and run correctly when the student includes the right headers;
ordinary iterator, mutation, and exception/memory paths work unchanged alongside
algorithmic code. Callable parameters (function pointers, `std::function`, lambdas)
are not supported as function parameters and are deferred entirely.

Function tests may combine return values, captured standard output, and mutable
arguments in one deterministic call. Non-void targets always require an
expected return value. Every mutable parameter requires one expected final
value. A per-test `check_stdout` option enables expected-output comparison for
either void or non-void targets; when it is disabled, output is captured for
runtime isolation but does not affect the result. Existing void output-only
tests remain enabled by default, while mutation-only and return-only tests do
not enable output checking automatically.

The harness redirects the selected function's `std::cout` to a dedicated
temporary output file during the call. It writes return and mutation data as
JSON to a separate temporary metadata file and atomically completes that file
after serialization. User output therefore cannot be confused with harness
metadata. A combined test passes only when its return value, enabled output
expectation, and every expected mutation all match. Return and mutation values
use existing type-aware comparisons; output uses the request's exact or
whitespace-tolerant comparison mode.

Supported `void` functions are tested through their captured standard output.
Their test cases use `expected_stdout` instead of `expected_return` and may use
the same whitespace-tolerant or exact comparison modes as full-program output.
The harness calls the function without storing or printing a return value.
Standard error remains separate. Supported mutation uses the dedicated
final-value model above; arbitrary pointer mutation remains outside the current
test model.

The test runner compiles with a fixed argument list, runs only after an explicit
request, and uses a unique temporary directory that is deleted afterward.
Generated harness code exists only in that directory and never changes the
editor source. Each test has a two-second timeout. Standard output and standard
error are each limited to 64 KiB; a process exceeding either limit is stopped
and its output is reported as limited. Output comparison preserves the raw
expected and actual text for display, but compares their whitespace-separated
token sequences. Leading and trailing whitespace, repeated spaces, tabs, and
line-break differences are ignored; token text, punctuation, capitalization,
and order must still match exactly.

This local subprocess isolation is for development only. It is not a
production-grade sandbox; container or equivalent isolation is required before
running arbitrary code for real users.

### Isolated Linux memory runner

Memory diagnostics prefer the dedicated Linux runner when
`CPP_EXECUTION_PROVIDER=auto` and Docker is available. Install Docker Desktop,
then build the fixed local image from the repository root:

Runtime output is normalized into bounded, tool-independent findings before it
is classified. The API retains the existing memory status fields and adds up
to three `memory_diagnoses` per test result. Each diagnosis contains a stable
category, confidence, concise explanation, optional minimal source range,
suggested direction, and collapsed technical evidence. AddressSanitizer,
UndefinedBehaviorSanitizer, LeakSanitizer, and Valgrind remain the authority
for confirmed failures; conservative source analysis can only add a possible
cause when runtime checking is incomplete.

The frontend shows one primary diagnosis and at most two compact secondary
summaries. Raw runtime output, provider/tool data, and classification evidence
remain under Technical details. Temporary paths and generated harness frames
are not used as the main student source location.

```bash
docker build -t inktocode-cpp-runner ./runner
```

Configure `backend/.env`:

```dotenv
CPP_EXECUTION_PROVIDER=auto
CPP_RUNNER_IMAGE=inktocode-cpp-runner
CPP_RUNNER_MEMORY=256m
CPP_RUNNER_CPUS=1.0
CPP_RUNNER_PIDS=32
CPP_RUNNER_USER=runner
CPP_DOCKER_COMPILE_TIMEOUT_SECONDS=30
CPP_DOCKER_RUN_TIMEOUT_SECONDS=8
CPP_DOCKER_VALGRIND_TIMEOUT_SECONDS=20
```

Docker sanitizer compilation, student-program execution, and Valgrind use
separate backend-only time limits. The compile limit includes container and
compiler startup. The shorter run limit applies only to student execution;
these values are never accepted from frontend requests.

Start the backend normally:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Check Docker and image readiness with:

```bash
docker version
docker image inspect inktocode-cpp-runner
```

Run the provider tests, including capability-gated integration coverage:

```bash
cd backend
source .venv/bin/activate
pytest tests/test_execution_providers.py
```

After changing `runner/Dockerfile` or `runner/runner.py`, rebuild explicitly:

```bash
docker build --no-cache -t inktocode-cpp-runner ./runner
```

In `auto` mode, unavailable Docker falls back to the honest host capability
result. In `docker` mode, an unavailable daemon or missing image produces an
infrastructure-unavailable response and never falls back. Runner containers
have no network, run as a non-root user, mount only one generated temporary
directory, and use fixed CPU, memory, process, filesystem, and timeout limits.

This local Docker runner is a development-stage isolation improvement, not a
complete production arbitrary-code execution platform. Public deployment
requires a dedicated security review, hardened orchestration, monitoring, and
additional isolation controls. Never use privileged containers for submitted
code.

### Object scenario testing

Exception expectations are available for function tests, constructors, object
methods, operators, and supported copy/move steps. Each expectation is a
structured choice between a return value, normal void completion, or a thrown
exception. The backend maps validated exception enums to a fixed C++ allowlist;
raw client type text is never inserted into generated harness source.

Named exception types use exact matching. `any_std_exception` accepts any value
catchable as `const std::exception&`; integers, string literals, and other
non-standard values are reported separately. Messages may be ignored, matched
exactly, or matched as case-sensitive substrings. Exact and substring rules
require a non-empty expected message.

Harnesses write exception outcomes to structured sidecar metadata instead of
parsing student output or stderr. Expected exceptions remain independent from
memory diagnostics, and a matching exception cannot hide a sanitizer or
Valgrind failure. Objects whose constructors are expected to throw are not
available to later scenario steps.

Constructor exceptions use the ordered `create_object` scenario step. Setup
objects remain pre-step fixtures that are expected to construct normally.
Successful create steps register their object for later steps; expected or
failed construction does not create a usable object.

Object scenario mode discovers usable inline public constructors and public
instance methods on classes and structs. Each scenario selects one or more
named objects with full-signature constructors, then provides at least one
ordered method, operator, or special-member step. The harness constructs each
initial object once, invokes each selected operation once in the displayed
order, and lets every object be destroyed naturally.

Non-void steps use the existing type-aware return comparison. Any step may
optionally compare stdout using the selected exact or whitespace-tolerant mode.
Each method's stdout and serialized return metadata use separate temporary
channels. A runtime failure or timeout marks the current step failed and all
later steps not executed. Object state is observed only through public method
calls; the harness never accesses fields or rewrites the student's class.

Object analysis also supports one validated public base class. Scenario steps
can create derived values, non-owning base reference or pointer views, owning
base pointers, sliced base values, and validated dynamic casts. Static and
runtime types remain separate in result metadata. Virtual calls use ordinary
C++ dispatch; non-virtual calls correctly use the static type.

Pure virtual methods mark a class abstract, so it cannot be constructed
directly but remains available as a base pointer/reference type. Deleting an
owned derived object through a base pointer tracks whether the parsed base
destructor is virtual. A non-virtual destructor produces a structural warning;
only sanitizer or Valgrind evidence can confirm a cleanup failure.

Multiple inheritance, virtual inheritance, static methods, arbitrary object
expressions, and separate header/source definitions remain unsupported.

### Operator-overload scenarios

Object scenarios may construct up to five named objects and execute structured
member or standalone operator calls. Supported operators are `+`, `-`, `*`,
`/`, `+=`, `-=`, `*=`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `[]`, `()`, and
stream output with `<<`. Operator identifiers include member/standalone kind,
participating class, symbol, ordered parameter types, const qualification, and
return type.

Custom objects returned by value can be stored under a unique scenario-local
identifier and used only by later steps. Their private state is never
serialized; later public observer calls verify the result. Mutation operators
continue using their target object. Scalar results use the existing type-aware
comparison, and `operator<<` uses isolated per-step stdout comparison.

The runner constructs initial objects once in listed order and stops the whole
scenario after the first runtime failure, marking later steps not executed.
Assignment, increment/decrement, conversion, pointer-return, custom-object
reference-result storage, short-circuit, comma, allocation, and spaceship
operators remain unsupported. `<=>` is intentionally deferred because it
requires a dedicated comparison-category result model.

### Big Five behavioral scenarios

The analyzer reports explicitly defined or explicitly defaulted public copy
constructors, copy assignments, move constructors, and move assignments using
full-signature special-member IDs. Deleted, private, protected, ambiguous, and
unimplemented declaration-only special members are excluded. Destructors are
reported for informational metadata only.

Structured steps perform copy construction, copy assignment, self-assignment,
move construction, or move assignment directly against validated scenario
objects. Copy/move construction creates a uniquely named object available only
to later steps. Assignments retain their existing target. The generated
harness uses ordinary C++ object operations and `std::move`; it never copies
fields, bytes, or addresses.

After a move, the source remains alive for natural destruction but is excluded
from later method, observer, operator, copy, and move-source selection. The
moved-to object remains available normally. If all step metadata completes but
scope destruction terminates abnormally, the response classifies that as a
destruction/runtime failure while preserving completed step results.

This stage does not generate assertions automatically, inspect private state,
compare addresses, count destructor calls, run sanitizers, or report leaks.
Copy independence is verified only through user-selected mutations and public
observer expectations.

### Template testing

The source-analysis endpoint exposes supported function and class templates as
structured metadata. Template parameters retain declaration order, kind
(`type` or `non_type`), declared non-type type, and a safely parsed default.
The frontend sends parameter names plus validated selections; it never sends a
raw template-id expression.

Function templates support straightforward compiler-authoritative deduction
or explicit arguments. Explicit type arguments come from the supported value
type allowlist. Integral, boolean, and character non-type arguments accept
bounded literal data only. The backend builds calls such as
`maximum<int>(3, 5)` after revalidating every selection. Result metadata reports
the concrete instantiation and reliably matched explicit specializations.

Class-template object steps use the same structured arguments and instantiate
their constructors, public methods, and existing operators through the object
scenario harness. Exceptions and optional memory diagnostics use the existing
independent result channels. Template substitution and instantiation failures
remain compiler failures with the raw diagnostic retained.

Partial specialization, variadic templates, parameter packs, concepts,
template-template parameters, user-defined deduction guides, dependent-base
analysis, metaprogramming-heavy APIs, and multi-file templates are not
supported. These forms return a limitation rather than accepting raw C++ from
the test form.

### AI-generated test cases

`POST /api/transcribe-question` accepts `multipart/form-data` with the same
page and metadata fields as the main transcription endpoint (`question_pages`,
`question_metadata`) and returns `{ "question_text": "..." }`. It uses the
Gemini API to extract the assignment question from uploaded question-category
pages and is called automatically by the frontend when question pages are
present; it makes a real Gemini call and consumes API quota.

`POST /api/ai-tests/run` accepts a JSON body with the current C++ source,
question text, and a structured target descriptor (function or object class
with full signature metadata). It makes one Gemini call to generate structured
test cases and immediately executes them against the unchanged student source
using the same `run_test_request` harness as manual tests. Source files above
20 000 characters return `source_too_large` without calling Gemini. At most
one repair attempt is made if the initial generation produces invalid structured
data. The response includes a stable `run_id`, all test results, a
deterministic equal-weight practice score, and a `PRACTICE_DISCLAIMER` constant
matching `"This is a practice score based on AI-generated tests, not an
official course grade."`.

`POST /api/ai-tests/rerun` accepts a `run_id` and the same test cases that
were executed in the original run. It makes **zero** Gemini calls and re-runs
exactly the previously generated tests against the current source. The response
uses the same schema as `/run` and includes the original and new practice
scores for comparison.

The `max_question_chars` setting (default 10 000) limits how many characters
of question text are sent to Gemini. Longer text is truncated before the
request is made. AI test results are kept separate from manual test results;
they never overwrite or replace the user's manually written cases.

## Tests

Tests mock the Gemini client and never make quota-consuming API calls:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Frontend

In a second terminal:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).
