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

- Docker-based sandboxing;
- real generated test cases;
- automatic code repair;
- AI-generated code fixes;
- authentication;
- database integration;
- permanent file storage;
- Python language support;
- additional programming languages;
- cloud deployment;
- production-grade remote code execution infrastructure.

Real local C++ compilation is now part of the current development plan.

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
