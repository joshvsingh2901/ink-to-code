# InkToCode frontend

The frontend foundation for InkToCode, built with Next.js, TypeScript, Tailwind CSS, the App Router, and ESLint.

## Run the frontend locally

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Template test builder

Supported function templates provide a compact deduction/explicit-argument
selector in the Tests sidebar. Type parameters use allowlisted selections,
non-type parameters accept literal data, defaults are explicit, and the
concrete instantiation preview is read-only. Class templates use the same
structured controls inside Create object steps. Raw template syntax is never
accepted from the browser.

## STL container test builder

Supported STL containers (`vector`, `array`, `deque`, `list`, `set`, `multiset`, `map`,
`multimap`, `unordered_set`, `unordered_multiset`, `unordered_map`, `unordered_multimap`,
`stack`, `queue`, `priority_queue`) use structured editors in the test sidebar:

- **Sequence containers** (`deque`, `list`) and set-family containers use numbered element
  rows with Add / Remove / Move up / Move down controls.
- **Map containers** (`map`, `multimap`, `unordered_map`, `unordered_multimap`) use
  numbered key/value entry rows with the same controls. Duplicate keys on `map` and
  `unordered_map` show an inline accessible error; `multimap` and `unordered_multimap`
  permit duplicates.
- **Adapter containers** (`stack`, `queue`, `priority_queue`) use element rows and display
  a visible caption describing the required input and expected-result ordering convention
  (e.g. "Enter values bottom → top" for stack).
- All editors use stable row IDs so removing or reordering one row does not affect others.
- Every input has a real label and ARIA attributes; move buttons disable at boundaries.

## Iterator test builder

Iterator parameters (`std::vector<T>::iterator`, `std::deque<T>::iterator`,
`std::list<T>::iterator`, `std::array<T,N>::iterator`, and `const_iterator` variants)
show structured editors in the test sidebar:

- **Range-begin (head) parameters** show a comma-separated container input and a
  numeric position field (0 = `begin()`, size = `end()`). The helper text updates to
  indicate when the position points past the last element.
- **Range-end (tail) parameters** show only a position field. The container is shared
  with the range-begin parameter and is shown read-only for reference.
- **Single-iterator parameters** show the full head editor (container + position).
- Non-const iterator heads appear in the expected-mutations section; the expected final
  value is entered as a JSON array (e.g., `[1, 4, 6, 4]`) representing the container
  after the call.
- Iterator return values display as `Index N` or `end() — past the last element`.
- Functions that use STL algorithms internally work without any special UI — the student
  includes `#include <algorithm>` or `#include <numeric>` in their source code.

## AI-generated test cases

The Tests tab includes two panels above the manual test builder.

**Question Context Panel** (`components/QuestionContextPanel.tsx`) accepts the
assignment question text used to guide AI test generation. When question-category
pages are uploaded, the panel automatically calls `POST /api/transcribe-question`
via `lib/aiTests.ts` once per unique page set and pre-fills the textarea with the
extracted text. The user can edit the text freely, retry a failed extraction, or
replace it from the image again. The character limit (8 000 chars client-side;
10 000 server-side) is shown as a live counter.

**AI Test Panel** (`components/AITestPanel.tsx`) drives the full AI test
generation and rerun flow:

- The **Run AI Tests** button is the single entry point. It is blocked only in
  three hard cases: missing question text, compile not ready, or program mode.
  Unsupported function signatures do not block the button.
- On first run, the panel calls `POST /api/ai-tests/run` with the current source,
  question, and structured target descriptor. Results (pass/fail rows, practice
  score, disclaimer) appear after execution.
- **Rerun Same Tests** re-executes the stored test cases against the current
  source via `POST /api/ai-tests/rerun` — zero additional Gemini calls. The
  prior score is shown alongside the new score.
- **Generate Fresh AI Tests** discards prior results and calls `/run` again with
  a new Gemini request.
- Switching the test target (function, class, or template arguments) automatically
  clears the displayed results without a React state-in-effect call; the context
  key is stored inside the result set and checked during render.
- AI results are fully separate from manual tests and never replace them.

State helpers live in `lib/aiTestState.ts` (pure TypeScript, no React imports).
Network calls live in `lib/aiTests.ts`. Unit tests for the state helpers are in
`tests/aiTestState.test.mts` (run via `npm test`).
