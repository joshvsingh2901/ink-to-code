# InkToCode Development Instructions

## Project

InkToCode converts handwritten programming code into editable C++ source files.

Current frontend stack:

- Next.js
- TypeScript
- Tailwind CSS
- App Router
- ESLint
- Monaco Editor

Current backend stack:

- Python
- FastAPI
- Google Gen AI Python SDK
- Pydantic

Current MVP language:

- C++17 only

## Scope rules

- Work only on the feature requested in the current prompt.
- Do not implement future stages unless explicitly requested.
- Preserve existing working behaviour.
- Do not add unnecessary dependencies.
- Do not commit changes. The user will test and commit manually.
- Do not expose secrets, API keys, uploaded files, source code, or private document contents in logs.
- Do not silently change architecture outside the requested feature.
- Prefer small, testable stages over large combined implementations.

## Before editing

1. Inspect the existing implementation.
2. Inspect all files relevant to the requested stage.
3. Explain which files will be created or modified.
4. Reuse existing components, schemas, services, and utilities where appropriate.
5. Identify important assumptions before implementation.
6. Do not begin editing until the relevant files have been inspected.

## After editing

1. Run `npm run lint` from the frontend directory when frontend code changes.
2. Run `npm run build` from the frontend directory when frontend code changes.
3. Run the backend test suite when backend code changes.
4. Run `python -m compileall app` when backend Python code changes.
5. Fix errors and warnings caused by the changes.
6. Summarize every file created or modified.
7. Explain important implementation decisions.
8. Provide exact manual testing steps.
9. Do not commit changes.

## Frontend standards

- Use TypeScript types rather than `any`.
- Keep components reasonably small and reusable.
- Use accessible HTML and keyboard-accessible controls.
- Maintain responsive desktop and mobile layouts.
- Avoid browser console errors.
- Clean up object URLs and event listeners when required.
- Match the existing visual design unless a redesign is requested.
- Do not place private API keys or server secrets in frontend code.
- Preserve uploaded pages and current workflow state after recoverable failures.
- Preserve the exact user-reviewed source code when moving between screens.
- Do not silently modify, format, repair, or normalize code.

## Backend standards

- Use Python type hints.
- Use Pydantic models for API request and response validation where appropriate.
- Keep API routes, validation, configuration, external-service logic, and compiler logic separated.
- Return structured JSON responses.
- Use environment variables for environment-specific values and secrets.
- Load the backend `.env` file reliably using a path derived from the backend project location.
- Do not log API keys, authorization headers, image contents, full documents, or complete student source code.
- Uploaded files must be processed temporarily and not stored permanently unless storage is explicitly requested.
- Temporary compiler files must also be deleted after use.
- Automated tests must mock external AI requests and must not consume Gemini API quota.
- Backend failures should produce clear, structured errors rather than raw tracebacks to the frontend.

## Current exclusions

Do not add these unless explicitly requested:

- Gemini-generated test cases;
- automatic code repair;
- AI-generated code fixes;
- Docker-based sandboxing;
- production-grade remote code execution infrastructure;
- authentication;
- database integration;
- permanent file storage;
- Python language support;
- additional programming languages;
- cloud deployment.

Real local C++ compilation is implemented.

Real local C++ test execution with explicit/manual test cases is now part of the current development plan.

For the current local MVP:
- test execution may run student C++ code only after an explicit `Run Tests` action;
- auto-compile must never execute student code;
- test execution must use strict timeouts, output limits, temporary files, and safe subprocess invocation;
- supported function-only code may execute through a deterministic temporary harness;
- stronger sandboxing is required before arbitrary code execution is exposed to real users.

## Definition of done

A feature is complete only when:

- its stated acceptance criteria pass;
- existing working behaviour remains functional;
- frontend lint passes for frontend changes;
- frontend build passes for frontend changes;
- backend tests pass for backend changes;
- Python compile checks pass for backend changes;
- no unrelated regressions are introduced;
- manual testing instructions are provided.

## Application workflow

The current intended MVP workflow is:

1. User uploads handwritten-code pages.
2. User may optionally upload programming-question pages.
3. Gemini Pass 1 performs literal transcription.
4. Gemini Pass 2 verifies the transcription against the original handwriting.
5. User reviews and edits the verified transcription.
6. User confirms the transcription.
7. The confirmed code opens in Monaco Editor.
8. The user may copy or download the code.
9. The user may compile the current Monaco Editor contents using the backend C++ compiler endpoint.
10. Compiler output is displayed without automatically repairing the code.

Future stages such as generated tests and automatic syntax repair must not be implemented unless explicitly requested.

## Upload rules

- Each upload section supports either:
  - up to 5 image files; or
  - 1 PDF containing up to 5 pages.
- Do not allow images and a PDF to be mixed within the same upload section.
- Preserve the page order selected by the user.
- PDFs must be previewed page by page before continuing.
- Images may be reordered by the user.
- The application must process pages in exactly the order shown.
- Handwritten-code pages are required.
- Programming-question pages are optional.
- Frontend validation must be repeated independently by the backend.
- Uploaded pages are temporary and are not permanently stored.

## OCR review stage

- The upload screen passes ordered handwritten-code pages and optional question pages to the review screen.
- The review screen uses real Gemini transcription during normal operation.
- A mock transcription mode may exist only behind an explicit development environment flag.
- Do not silently fall back to mock data after a real transcription failure.
- Extracted code must always be editable before compilation or download.
- Preserve apparent mistakes in the transcription.
- Never automatically format, correct, compile, or improve the extracted code during transcription.
- Users must be able to inspect every uploaded handwritten-code page.
- Uncertain regions are review aids, not guaranteed probabilities.
- Review-screen state may remain client-side until persistence is explicitly requested.
- A failed transcription must preserve uploaded pages, their order, and the ability to retry.

## Browser editor stage

- Confirming the transcription opens the code in a Monaco Editor screen.
- The reviewed transcription must be preserved exactly.
- Do not automatically format or correct the student's code.
- The editor supports copying and downloading the current code.
- C++17 is the only supported language for the current MVP.
- Downloaded source files use the `.cpp` extension.
- Downloaded contents must exactly match the current Monaco Editor contents.
- Compilation must always use the current Monaco Editor contents, not the original OCR result.
- Compilation must not automatically modify the editor contents.
- Compiler errors must be shown separately from the source code.

## Backend foundation

- The backend uses Python and FastAPI.
- Backend code lives in the `backend` directory.
- The frontend and backend run as separate local services.
- API responses use structured JSON.
- Environment-specific values come from environment variables.
- Do not place secrets or API keys in frontend code.
- CORS must allow only documented frontend origins.
- The backend health endpoint remains available for connection testing.

## Gemini transcription API

- Use the official Google Gen AI Python SDK.
- Gemini API calls occur only in the FastAPI backend.
- Read the API key from `GEMINI_API_KEY`.
- Read the selected model from `GEMINI_TRANSCRIPTION_MODEL`.
- Never expose or log the Gemini API key.
- Do not retain an unused OpenAI provider implementation unless multi-provider support is explicitly requested.
- The FastAPI backend receives ordered handwritten-code pages using multipart form data.
- Validate all pages and metadata before sending anything to Gemini.
- Send handwritten-code pages to Gemini in the exact user-selected order.
- Keep programming-question pages separate from handwritten-code pages.
- Question pages may provide limited context but must never be used to silently correct the student's handwriting.
- The handwritten code remains the source of truth for transcription.
- The transcription must preserve line breaks, indentation, variable names, spelling, punctuation, operators, braces, semicolons, and apparent mistakes.
- The model must not correct, format, compile, explain, or improve the student's code.
- Do not return Markdown code fences or page headings as part of the transcription.
- When handwriting is unclear, provide the closest visible transcription and flag the region as uncertain rather than inventing content.
- Validate Gemini's structured response using Pydantic before returning it to the frontend.
- Confidence values are model-estimated review aids, not calibrated probabilities.
- Uploaded files are processed temporarily and are not stored permanently.
- A failed request must preserve uploaded pages and allow retrying.
- Distinguish missing key, invalid key, quota limits, rate limits, service failures, timeouts, empty responses, and malformed responses.
- Automated tests must mock the Gemini client and must not make real Gemini API calls.

## Gemini transcription pipeline

- Real transcription uses exactly two Gemini generation requests per transcription job.
- Pass 1 performs strict literal visual transcription.
- Pass 2 verifies the candidate transcription against the original handwritten-code images.
- All 1–5 ordered handwritten-code pages are bundled together in each Gemini request.
- Do not send one Gemini request per page.
- Pass 2 receives the original handwritten-code pages plus the Pass 1 candidate transcription.
- The verification pass audits visual faithfulness rather than programming correctness.
- The verification pass must not repair C++ syntax or make code more correct.
- Missing semicolons, braces, parentheses, operators, keywords, or other syntax must remain missing when they are not visibly handwritten.
- Apparent mistakes such as misspelled identifiers must remain unchanged when visually supported.
- Programming-question pages must never be used to repair the student's handwritten code.
- The final API response uses the verified Pass 2 transcription.
- Do not concatenate Pass 1 and Pass 2 results.
- If Pass 2 fails, do not silently fall back to Pass 1.
- Both passes use the configured `GEMINI_TRANSCRIPTION_MODEL`.
- One transcription job uses exactly two Gemini generation requests whether it contains 1 or 5 handwritten-code pages.

## C++ compilation stage

Real C++ compilation is the current next stage.

### Compilation scope

- C++17 is the only supported language.
- Compilation must use the exact current Monaco Editor contents.
- Compilation must occur only in the backend.
- The frontend must never execute compiler commands directly.
- Use the locally installed C++ compiler available to the backend environment.
- Prefer `g++` with `-std=c++17` unless the inspected environment requires a documented equivalent.
- Do not involve Gemini in compilation.
- Do not automatically repair compiler errors.
- Do not automatically change source code.
- Do not generate tests during this stage.
- Do not run arbitrary shell commands provided by the user.

### Compiler API

The compilation feature should use a dedicated backend endpoint.

The expected request should contain the current source code in structured JSON, for example:

```json
{
  "code": "#include <iostream>\nint main() { return 0; }",
  "language": "cpp"
}
```

## Compiler fix suggestions

- The C++ compiler remains the sole authority for error detection.
- Users manually fix most compiler errors.
- Automatic suggestions are limited to explicit, high-confidence compiler-provided token replacements.
- A compiler suggestion must identify both the original token and replacement exactly, and the reported source range must match.
- Do not use Gemini for compiler fixes; Gemini remains limited to handwriting transcription.
- Do not automatically suggest structural token insertions such as braces, semicolons, parentheses, or brackets.
- Never apply a fix without an explicit individual Apply action from the user.
- Apply changes only the exact validated token and then recompiles the updated Monaco contents.
- Do not add Dismiss or Resolve All.
- Compilation issue counts always derive from the latest compiler result.
- Manual source edits invalidate stale suggestions.

## Compiler explanations

- The C++ compiler remains the sole authority for error detection.
- Beginner-friendly compiler explanations must be deterministic and conservative.
- Explanations must preserve the original compiler message and must not invent errors, intended structure, or exact fixes.
- A directly related compiler note may enrich an error explanation when the relationship is explicit.
- NOTE diagnostics remain hidden from the main issue list.
- Raw compiler output, including notes, remains available unchanged.
- Do not use Gemini for compiler explanations.
- Missing downstream errors are expected to appear naturally after the user edits and recompiles.

## Editor compilation feedback

- Manual Compile remains available at all times when no request is actively running.
- After the first completed compile, source edits trigger debounced automatic compilation.
- Compiler requests must be debounced rather than sent on every keystroke.
- Previous diagnostic cards and their issue count remain visible while a new result is being checked.
- Potentially stale Monaco compiler markers are cleared immediately after source edits.
- Stale or out-of-order compile responses must never replace newer results.
- Issue counts derive only from completed compiler results.
- Automatic compilation compiles only and never executes the resulting program.
- Gemini is not involved in compilation or automatic compilation.
- Clicking a diagnostic temporarily highlights its source line without modifying source text.

## Test execution stage

- Compile and Run Tests are separate operations.
- Compile performs C++17 syntax/type checking and does not require `main()`.
- Run Tests executes student code only after an explicit user action.
- Full-program tests execute code containing `main()` with stdin/stdout cases.
- Supported function-only tests execute through a deterministic temporary harness.
- Tests are explicit/manual in this stage.
- Gemini must not generate tests, expected outputs, or runtime fixes.
- Test execution must use strict timeouts and output-size limits.
- Student programs must run only inside unique temporary working directories.
- Temporary source files and binaries must be deleted after execution.
- Never use `shell=True`.
- Never allow user-controlled compiler flags, executable paths, or shell commands.
- Auto-compile must never execute student binaries.
- Run Tests must never modify Monaco source code.
- Preserve raw expected and actual output for display.
- Compare output using whitespace-separated token sequences.
- Ignore leading, trailing, and repeated whitespace only during comparison.
- Token text, punctuation, capitalization, and order must match exactly.
- Runtime stderr, exit codes, and timeouts must be reported explicitly.
- A compile failure during Run Tests must prevent execution.
- Local subprocess execution is for development only and is not production-grade sandboxing.
- Stronger sandboxing/container isolation is required before exposing arbitrary code execution to real users.

## Function test harness stage

- InkToCode may generate deterministic temporary C++ harness code for testing function-only submissions.
- Generated harness code must never modify the Monaco source shown to the user.
- Harness generation is infrastructure only and must not use Gemini.
- The user's submitted function must remain unchanged.
- Function tests use explicit argument values and explicit expected results.
- The initial version should support simple function signatures only.
- Unsupported signatures must return a clear unsupported message rather than guessing.
- Full programs with `main()` continue to use stdin/stdout tests.
- Function-only tests and full-program tests are separate execution modes.

- Function-only submissions may contain multiple supported top-level functions.
- When multiple supported functions are detected, the frontend must let the user choose which function to test.
- The backend must never guess which function is intended.
- The selected target function is the only function directly invoked by the generated harness.
- All other user-defined functions must remain available so the selected function can call them normally.


## Vector function testing

- Function-mode tests may support selected `std::vector` parameter and return types.
- Vector test values must be entered as data, never as arbitrary C++ expressions.
- The backend must validate and safely convert vector elements into generated C++ literals.
- Vector testing supports one-dimensional vectors and explicitly supported
  two-dimensional nested vectors only.
- Supported element types are `int`, `long`, `long long`, `double`, and `bool`.
- Vector parameters may be passed by value, const reference, or supported
  non-const reference mutation.
- Vector results must use deterministic serialization for comparison.
- Generated harness code must never modify the Monaco source.
- Full-program stdin/stdout testing and scalar function testing must remain unchanged.

## String function testing

- Function-mode tests may support `std::string`, `std::vector<std::string>`,
  and `std::vector<std::vector<std::string>>`.
- String arguments are data, never arbitrary C++ expressions.
- Strings must support spaces and escaped quotes safely.
- Vector-of-string inputs must use a clear quoted format such as `["hello", "world"]`.
- String and vector-of-string returns must use deterministic serialization.
- Generated harness code must escape string literals safely.
- Full-program, scalar, and existing vector testing must remain unchanged.
- Character arrays and raw C strings are not supported in this stage.

## Void function output testing

- Function-mode tests may support `void` functions that produce output through `stdout`.
- For supported `void` functions, tests compare captured standard output instead of a return value.
- The generated harness calls the selected function with validated arguments.
- The user's source code must remain unchanged.
- Existing output-comparison modes apply to captured function output.
- `void` functions may be checked through supported scalar, vector, or array
  mutation models.
- Arbitrary pointer mutation remains a separate future stage.

## C-style array testing

- Function-mode tests may support one-dimensional numeric C-style arrays.
- Supported declarations include `T arr[]` and `T* arr` when explicitly treated as array input.
- Array tests require an explicit size parameter.
- Supported element types are `int`, `long`, `long long`, `double`, and `bool`.
- Array values are data, never arbitrary C++ expressions.
- Generated harness code must create temporary local arrays safely.
- Array-return pointers, pointer ownership, dynamic allocation, pointer-to-pointer types, and multidimensional arrays are not supported yet.
- Array mutation checking uses the explicit size parameter as its comparison
  boundary.
- Existing program, scalar, string, vector, and void-output testing must remain unchanged.

## Scalar reference mutation testing

- Function-mode tests may support non-const scalar reference parameters.
- Supported mutable reference types are `int&`, `long&`, `long long&`, `double&`, `bool&`, and `std::string&`.
- Tests provide an initial argument value and an expected final argument value.
- The generated harness must inspect mutable arguments after the function call.
- The user’s Monaco source must never be modified.
- Const references remain read-only inputs.
- Pointer mutation and returned references are not part of this stage.

## Vector and array mutation testing

- Function-mode tests may inspect mutations to supported non-const vector references and C-style array parameters.
- Supported mutable vectors include one-dimensional vectors and supported
  two-dimensional nested vectors of existing element types.
- Supported mutable arrays are one-dimensional numeric C-style arrays with an explicit size parameter.
- Tests provide initial values and expected final values.
- The generated harness must serialize mutated arguments after the function call.
- The Monaco source must never be modified.
- Pointer ownership, returned pointers, and multidimensional arrays remain
  unsupported.

## Multiple mutable output testing

- Function-mode tests may support multiple mutable arguments.
- Each mutable argument must have an initial value and expected final value.
- Supported mutable arguments may include existing scalar references, vector references, and mutable C-style arrays.
- All function inputs must appear first in parameter order.
- Expected mutations must appear afterward in a separate section.
- The generated harness must capture every mutable argument after the function call.
- A test passes only when every expected mutation matches.
- Combined return values, stdout, and multiple mutations must not be silently ignored.
- The Monaco source must never be modified.

## Combined result-channel testing

- Function-mode tests may validate more than one result channel from the same call.
- Supported result channels are return value, captured stdout, and mutated arguments.
- A test passes only when every active expected result channel matches.
- The generated harness must capture all active result channels deterministically.
- No return value, stdout, or mutation may be silently ignored.
- Test inputs appear first, followed by expected return/output and expected mutations in separate sections.
- Existing timeout, output-limit, cleanup, and source-preservation rules remain unchanged.

## Scalar pointer testing

- Function-mode tests may treat supported scalar pointer parameters as one mutable scalar value rather than as arrays.
- Scalar-pointer mode must only be used when the pointer is not paired with an array-size parameter.
- Numeric pointer spelling paired with exactly one recognized later integral size parameter remains array-backed; bracket spelling is always array-backed.
- A supported one-level pointer without such a size pairing is scalar-pointer mode.
- Supported scalar pointee types match the existing scalar reference types.
- Each mutable scalar pointer has an initial value and expected final value.
- The harness must allocate safe local storage and pass its address to the function.
- Null-pointer testing, pointer ownership, returned pointers, pointer arithmetic, and pointer-to-pointer parameters remain unsupported.
- Ambiguous pointers must be rejected rather than guessed.

## Nested vector testing

- Function-mode tests may support two-dimensional nested vectors.
- Supported forms are `std::vector<std::vector<T>>` and mutable references to them.
- Supported inner element types match the existing scalar/vector types.
- Inputs may be rectangular or jagged.
- Empty outer vectors and empty inner rows are valid.
- Mutable nested vectors require an initial value and expected final value.
- Nested vectors must be parsed and compared structurally.
- Deeper nesting, vectors of custom types, raw 2D arrays, and pointer-to-pointer matrices remain unsupported.

## Object scenario testing

- Function-mode testing may also test public class and struct behavior through object scenarios.
- A scenario creates one or more named objects using selected public constructors, then performs ordered public method or supported operator calls.
- Object state must be observed only through public methods, return values, or stdout.
- Private fields must never be accessed or exposed by the generated harness.
- Constructors and methods must be identified by full signatures, not names alone.
- The original Monaco source must remain unchanged.
- Automatic Big Five generation and arbitrary multi-object interactions remain separate future stages.
- Supported single-public-inheritance scenarios follow the inheritance and
  polymorphism rules below.

## Operator-overload scenario testing

- Object scenarios may test supported overloaded operators on user-defined classes and structs.
- Operators must be identified by full signature and declaring type.
- Scenarios may construct multiple named objects and store object-valued operator results.
- Object state and operator results must be observed only through public methods, supported scalar returns, comparisons, or captured stdout.
- Private and protected fields must never be accessed.
- The original Monaco source must remain unchanged.
- Automatic Big Five generation, inheritance, implicit conversions, memory diagnostics, and arbitrary expression evaluation remain separate stages.

## Big Five behavioural testing

- Object scenarios may test explicitly declared copy constructors, copy assignment operators, move constructors, and move assignment operators.
- Big Five behavior must be tested through observable public methods, operator results, stdout, runtime stability, and object independence.
- Private fields and raw memory addresses must never be exposed.
- Copy scenarios must verify that copied objects can be modified independently when deep-copy behavior is expected.
- Self-assignment must leave the object valid and observable.
- Moved-to objects may be observed normally; moved-from objects may only be checked through explicitly safe public operations.
- Destruction must occur naturally through scope.
- Automatic leak detection and sanitizer reporting remain a separate memory-diagnostics stage.

## Memory diagnostics

- Memory checks are optional and disabled by default.
- Sanitizer compilation and execution occur only in the backend.
- Normal and sanitizer execution paths must remain separate.
- AddressSanitizer and UndefinedBehaviorSanitizer are used where supported.
- A behavioural PASS with a sanitizer error is still a failed test.
- Sanitizer-unavailable is distinct from clean and from user-code failure.
- Temporary paths and internal backend details must be removed from returned diagnostics.
- Sanitizer output must remain size-limited.
- Do not silently fall back to an unsanitized run when checks were explicitly requested.

## Big Five educational diagnoses

- Big Five diagnoses supplement, but never replace, behavioural and sanitizer results.
- Diagnoses use confirmed, likely, or possible confidence levels.
- Confirmed claims require direct runtime or behavioural evidence.
- Static ownership inference must remain conservative.
- Raw pointers are not automatically treated as owning.
- Recognize common safe RAII, swap, reset, and helper-based patterns.
- Prefer no diagnosis over a misleading diagnosis.
- Diagnoses must not change test pass/fail status.
- Source highlights must use the user's original line numbers and minimal ranges.

## Test-result presentation

- Default result cards must prioritize behavioural outcome, memory outcome, the
  diagnosed issue, its source location, and the next action.
- Keep successful scenario steps collapsed by default; failed steps remain
  visible.
- Memory diagnostics use one compact summary in the default view. Sanitizer
  capability, provider, tool, exit status, raw diagnostics, and stderr belong
  in one collapsed technical-details section.
- Big Five diagnoses show one concise educational summary. Evidence and
  diagnostic internals remain secondary.
- Source excerpts are hidden by default and must use the smallest available
  suspicious source range.
- A behavioural pass with a memory failure is presented as a memory issue, not
  as an ordinary pass or ordinary behavioural failure.
- Unavailable memory infrastructure is presented as an incomplete check, never
  as a clean result.

## Isolated C++ execution

- Normal tests use the host execution provider unless configured otherwise.
- Memory diagnostics prefer an isolated Linux Docker runner.
- Docker-specific behaviour is isolated behind an execution-provider abstraction.
- Submitted code must run as a non-root user with no network and strict CPU, memory, process, filesystem, and timeout limits.
- Never mount the repository, secrets, home directory, or Docker socket.
- Never use privileged containers.
- Frontend requests cannot control Docker commands, images, compiler flags, mounts, environment variables, or resource limits.
- LeakSanitizer and Valgrind capability must be proven with deliberate-leak probes.
- Infrastructure failures are distinct from student-code failures.
- All containers and temporary files must be removed after execution.
- Diagnostics must redact host/container paths and remain size-limited.

## Exception-test behaviour

- Exception expectations are structured and validated.
- Never inject raw client exception-type strings into generated C++.
- Named exception types use exact matching.
- “Any std::exception” matches any standard exception.
- Non-standard exceptions are reported separately.
- Expected exceptions are normal test outcomes, not crashes.
- Memory diagnostics remain independent from exception matching.
- Failed constructors do not create usable scenario objects.
- Result cards stay concise and technical details remain collapsed.

## Memory-diagnostics architecture

- Runtime tools are the source of truth for confirmed memory failures.
- Source analysis only identifies likely locations and possible causes.
- Memory categories and operation contexts are modeled separately.
- Diagnostics use confirmed, likely, or possible confidence wording.
- Do not add one-off explanations for individual test programs.
- Tool-specific output must be normalized before classification.
- Prefer one primary diagnosis over repeated symptoms.
- Student-facing results show issue, location, cause, and direction.
- Raw sanitizer and Valgrind evidence remains under Technical details.
- Never expose temporary paths, raw addresses, or generated harness internals.
- Infrastructure failures must not be reported as student-code failures.
- Memory and exception outcomes remain independent.
- Keep source excerpts minimal and escaped.
- Do not attempt to replace a full C++ static analyzer.

## Inheritance and polymorphism testing

- Support single public inheritance first.
- Static type and runtime type must be tracked separately.
- Virtual dispatch, non-virtual dispatch, and slicing are distinct outcomes.
- Do not construct abstract classes directly.
- Base pointers and references must come from validated parsed relationships.
- Deleting through a base pointer requires ownership tracking.
- A non-virtual base destructor is a structural warning unless runtime evidence confirms memory failure.
- Runtime tools remain the source of truth for confirmed cleanup failures.
- Do not inject raw frontend class or method names into generated C++.
- Keep polymorphism results concise and show technical lifecycle details only when expanded.
- Do not add multiple inheritance or virtual inheritance without a separate design stage.

## Template testing

- Support function templates and class templates through validated structured metadata.
- Never accept arbitrary raw template argument syntax from the frontend.
- Build template identifiers server-side from validated arguments.
- Let the compiler remain the final authority for deduction and substitution.
- Template compilation failures remain compile errors.
- Preserve template argument declaration order.
- Defaults must be represented explicitly.
- Runtime exceptions and memory diagnostics remain independent from template compilation.
- Do not add partial specialization, variadic templates, concepts, or metaprogramming without a separate design stage.
- Keep student-facing results concise and place full template metadata under Technical details.
