# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

InkToCode converts handwritten programming code (photos/PDFs) into editable, testable C++17 source. Workflow: upload handwritten pages → Gemini two-pass transcription → user reviews/edits in a browser → confirmed code opens in a Monaco editor → user compiles and runs explicit tests against the code (full-program stdin/stdout, or function-only via a generated harness) with optional memory-sanitizer diagnostics.

Stack: Next.js/TypeScript/Tailwind/App Router frontend (`frontend/`), FastAPI/Pydantic backend (`backend/`), isolated C++ execution runner (`runner/`) reachable through a pluggable execution provider — Docker locally (the default) or Modal cloud sandboxes for deployment.

**`AGENTS.md` is the authoritative, extremely detailed spec for this project** — scope rules, per-stage behavioral contracts (transcription, compilation, test execution, object scenarios, memory diagnostics, templates, STL containers, etc.), and the definition of done. Read it before making non-trivial changes; this file only summarizes architecture and commands.

## Commands

### Backend (`backend/`)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + pytest/httpx
cp .env.example .env                  # set GEMINI_API_KEY

uvicorn app.main:app --reload --port 8000 --env-file .env   # run the API

pytest                                          # full suite
pytest tests/test_function_execution.py         # single file
pytest tests/test_function_execution.py -k name # single test
pytest tests/test_execution_providers.py        # provider tests (capability-gated Docker coverage)

python -m compileall app                        # compile check after backend changes
```

Tests mock the Gemini client and never consume API quota; do not add tests that make real Gemini calls.

### Frontend (`frontend/`)

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev      # http://localhost:3000
npm run lint      # required after frontend changes
npm run build     # required after frontend changes
npm test          # runs tests/*.test.mts via node --test
```

### Isolated C++ runner (`runner/`)

```bash
docker build -t inktocode-cpp-runner ./runner
# after editing runner/Dockerfile or runner/runner.py:
docker build --no-cache -t inktocode-cpp-runner ./runner
```

Set `CPP_EXECUTION_PROVIDER=docker` in `backend/.env` (the local default; `modal` selects the cloud sandbox provider instead — see `docs/internal/MODAL_DEPLOYMENT.md`). This runner is mandatory, not optional: normal Compile, manual tests, AI-generated tests, Rerun Same Tests, object scenarios, and memory diagnostics all compile and execute user-submitted C++ only inside this isolated container/sandbox. The API host never compiles or executes user code directly, and there is no host fallback on either provider — if the configured provider's runtime or runner image is unavailable, requests report an infrastructure error instead of silently degrading. Do not reintroduce direct host `g++`/`clang++`/binary execution.

## Architecture

### Backend layering

Routes (`app/api/*.py`) → Pydantic schemas (`app/schemas/*.py`) → services (`app/services/*.py`). Each API module is thin; validation and business logic live in schemas/services, kept deliberately separated per `AGENTS.md`.

- **`app/api/transcription.py`** — `POST /api/transcribe`. Accepts ordered handwritten-code pages (+ optional question pages) as multipart form data, delegates to `services/transcription.py`.
- **`app/services/transcription.py`** — runs exactly two Gemini requests per job: Pass 1 (literal transcription of all pages in one request) and Pass 2 (visual-faithfulness verification against the Pass 1 candidate). Never repairs C++ syntax; apparent handwriting mistakes are preserved.
- **`app/api/compilation.py`** — `POST /api/compile`. Compiles current Monaco contents with `g++ -std=c++17`; never executes the program, never repairs code.
- **`app/services/compiler.py`** / **`compiler_diagnostics.py`** / **`compiler_explanations.py`** — invoke the compiler, parse raw diagnostics into structured issues, and generate conservative beginner explanations. The compiler is the sole authority for errors; explanations never invent fixes.
- **`app/api/test_execution.py`** — `POST /api/test-mode` (classifies source as full-program / function-only / unsupported) and `POST /api/run-tests` (executes 1–10 explicit cases). This is the largest and most active surface.
- **`app/services/function_analysis.py`** (~1.5k lines) — parses C++ source to detect testable top-level functions, classifies parameter types (scalars, strings, vectors incl. nested, C-style arrays, scalar pointers, mutable references), and determines which signatures are supported vs. rejected. Never guesses ambiguous signatures.
- **`app/services/object_analysis.py`** (~1.3k lines) — discovers public constructors/methods/operators on classes/structs for object-scenario testing, including single-inheritance relationships (base pointers/references, slicing, virtual dispatch) and Big Five special members (copy/move ctor/assignment).
- **`app/services/test_execution.py`** (~5.4k lines) — the core harness generator and runner. Builds temporary deterministic C++ harness code (never modifies the user's Monaco source), compiles it, executes with strict timeouts/output limits in a unique temp directory, and serializes results (return values, mutated arguments, captured stdout, exceptions) for comparison. This is where most test-mode features (vectors, arrays, pointers, exceptions, object scenarios, templates, STL containers) converge.
- **`app/services/execution_providers.py`** — the sole execution boundary and the shared `ExecutionProvider` interface/helpers (manifest builders, payload parsers, capability helpers) that both providers use. `DockerExecutionProvider` here and `ModalExecutionProvider` in `app/services/modal_provider.py` (imported lazily, only when `CPP_EXECUTION_PROVIDER=modal`) are the only two implementations. Every compile/run of user-submitted C++ across the app goes through the configured provider (no network, non-root, fixed resource limits) launched here or in `modal_provider.py`; no other module in `app/` may invoke a compiler or a compiled binary directly — a static test enforces this. Fails closed with an infrastructure-unavailable error when the configured provider's runtime or runner image isn't available — never falls back to host execution, on either provider. See `docs/internal/MODAL_DEPLOYMENT.md` for the honest Docker-vs-Modal control matrix.
- **`app/services/memory_*.py`** (`memory_classifier`, `memory_runtime_parser`, `memory_source_analysis`, `memory_source_mapping`, `memory_explanations`, `memory_diagnosis_models`) — normalize AddressSanitizer/UndefinedBehaviorSanitizer/Valgrind output into bounded, tool-independent findings, then combine it with conservative static analysis to produce confirmed/likely/possible diagnoses. Runtime tool output is always the authority for confirmed failures; static analysis only ever adds a "possible" cause.
- **`app/services/big_five_diagnosis.py`** — educational diagnoses for copy/move behavior, layered on top of (never replacing) behavioral + sanitizer results.
- **`app/schemas/ai_tests.py`** + **`app/services/ai_test_capability.py`** / **`ai_test_generation.py`** / **`ai_test_validation.py`** / **`ai_test_orchestration.py`** / **`app/api/ai_tests.py`** — AI test generation pipeline. `ai_test_capability.py` is a pure deterministic gate (no I/O). `ai_test_generation.py` builds prompts and calls Gemini for structured JSON only (never C++ source). `ai_test_validation.py` normalizes Gemini output into `FunctionTestCase` / `ObjectScenarioTestCase`, using three pure private helpers from `test_execution.py` for value-level validation. `ai_test_orchestration.py` orchestrates run/rerun, calls `run_test_request` directly (in-process), and computes the deterministic equal-weight practice score. `POST /api/ai-tests/run` and `POST /api/ai-tests/rerun` are the two new endpoints; `POST /api/transcribe-question` extracts question text from uploaded pages.
- **`app/services/uploads.py`** — validates upload metadata (ordering, size limits, category separation) independently of frontend validation.
- **`app/config.py`** — loads `backend/.env` via a path derived from the file's own location (so it works regardless of CWD) and exposes a single `Settings` dataclass consumed everywhere; add new env vars here rather than reading `os.getenv` elsewhere.

`app/schemas/test_execution.py` (~1k lines) is the single structured contract for every test-execution request/response shape (function tests, object scenarios, exceptions, mutations, templates, containers) — check here first when tracing how a field flows from frontend to harness.

### Frontend structure

- **`app/page.tsx`** → upload screen, **`app/review/page.tsx`** → OCR review/edit screen, **`app/editor/page.tsx`** → Monaco editor + compile/test screen. State (uploaded pages, order, reviewed transcription) is passed client-side between screens via `UploadProvider`.
- **`lib/*.ts`** hold the non-UI logic: `compiler.ts` and `testExecution.ts` call the backend endpoints; `transcription.ts` calls `/api/transcribe` (a mock mode exists only behind an explicit dev env flag — never silently falls back to mock after a real failure); `objectScenarioState.ts` / `objectScenarioSummary.ts` / `exceptionTestState.ts` / `templateTesting.ts` manage the structured test-builder state that mirrors the backend schemas; `memoryDiagnostics.ts` formats memory-diagnosis payloads for display; `pdf.ts` renders uploaded PDFs page-by-page in-browser (original PDFs are never sent to the backend, only rendered page images).
- **`lib/aiTests.ts`** / **`lib/aiTestState.ts`** — AI test API helpers and pure state utilities (hashing, staleness classification, fingerprinting, run-gate, result shaping). `aiTestState.ts` is importable in node tests with no React dependency.
- **`components/QuestionContextPanel.tsx`** — automatic question extraction (fires once per page-set fingerprint, no button needed for the first extraction) plus the editable text area, Retry/Replace actions.
- **`components/AITestPanel.tsx`** — owns AI test state (result set, phase, prior score); renders the Run AI Tests button, progress, score-first result rows, Rerun Same Tests / Generate Fresh AI Tests buttons, disclaimer, and skipped-topics disclosure.
- **`components/`** — `ImageUploadCard` (upload UI), `ObjectScenarioTests` / `ExceptionExpectationFields` (structured test-builder UI), `BackendStatus` (health-check indicator).
- Frontend `tests/*.test.mts` unit-test the `lib/` state/logic modules directly (run via `npm test`, node's built-in test runner — not Jest/Vitest).

### Cross-cutting invariants (see `AGENTS.md` for full detail)

- The user's Monaco source is never silently modified, formatted, or repaired — anywhere in the pipeline.
- Gemini is used for handwriting transcription and structured AI test generation only — never for compiling, executing, or fixing code. All Gemini output is structured JSON validated against strict schemas; no field can carry C++ source or executable expressions.
- All generated C++ (harness code, template instantiations, container literals) is built server-side from validated structured metadata — raw expressions/syntax from the frontend are never interpolated into generated source.
- Test/compile execution never uses `shell=True`, always uses temp directories cleaned up afterward, and always enforces timeouts and output-size limits.
- Memory/sanitizer results and behavioral pass/fail are independent channels; a behavioral pass with a memory failure is reported as a memory issue, not a plain pass.
