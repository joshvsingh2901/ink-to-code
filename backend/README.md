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
```

`GEMINI_TRANSCRIPTION_MODEL` is optional. When blank or absent, the service uses `gemini-3.5-flash-lite`. Start the API with:

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

Function tests also support one-dimensional `std::vector<T>` parameters and
returns where `T` is `int`, `long`, `long long`, `double`, or `bool`. Parameters
may be passed by value or by const reference; vector returns must be by value.
Unqualified `vector<T>` is accepted only when the source contains
`using namespace std;`. Inputs may use `[1, 2, 3]`, `1, 2, 3`, or `1 2 3`;
`[]` represents an empty vector. Elements are validated as data and converted
to safe literals before harness generation. Results use canonical
`[1, 2, 3]` serialization and exact typed sequence comparison with no fuzzy
numeric tolerance. Nested vectors, unsupported element types, vector pointers,
non-const references, and mutation-through-void signatures are not supported.

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
multidimensional arrays, character arrays, arbitrary expressions, and
mutation-result checking are not supported.

Function mode supports `std::string` and one-dimensional
`std::vector<std::string>` parameters by value or const reference, with returns
by value. A scalar string field is the complete string value and does not
require C++ quotation marks. String vectors require JSON-style quoted-list
syntax such as `["hello", "hello world"]`; `[]` is empty. Quotes, backslashes,
newlines, tabs, carriage returns, and control bytes are escaped before safe C++
literals are generated. Scalar strings compare exact contents.
`vector<string>` results serialize canonically as `["hello", "world"]` and
compare exact element contents, order, and length. Character pointers, character
arrays, string pointers, mutable vector references, and nested vectors remain
unsupported.

Function mode supports exactly one mutable scalar reference parameter of type
`int&`, `long&`, `long long&`, `double&`, `bool&`, or `std::string&` on a
`void` target. Each test supplies the parameter's initial value in the ordinary
argument list and its expected final value in `expected_final_arguments`, keyed
by parameter name. The harness creates validated local storage, calls the
unchanged target, and serializes the final local value. Integer, boolean, and
string values compare exactly; doubles retain the existing exact, non-fuzzy
output policy. String values use the existing safe literal escaping and quoted
serialization internally.

Scalar and string const references remain read-only inputs. Non-void functions
with mutable references are conservatively rejected so neither a return value
nor a mutation is ignored. Multiple mutable references, returned references,
rvalue references, pointer/array/vector mutation, and custom reference types
are unsupported. Mutation tests do not have a second stdout expectation
channel; if the target writes to `std::cout`, the test fails with a clear
runtime message rather than silently discarding that output.

Supported `void` functions are tested through their captured standard output.
Their test cases use `expected_stdout` instead of `expected_return` and may use
the same whitespace-tolerant or exact comparison modes as full-program output.
The harness calls the function without storing or printing a return value.
Standard error remains separate. Supported scalar-reference mutation uses the
dedicated final-value model above; pointer, array, and vector mutation remain
outside the current test model.

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
