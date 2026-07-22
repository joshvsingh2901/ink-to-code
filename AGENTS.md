# InkToCode Development Instructions

## Project

InkToCode converts handwritten programming code into editable source files.

Current frontend stack:

- Next.js
- TypeScript
- Tailwind CSS
- App Router
- ESLint

## Scope rules

- Work only on the feature requested in the current prompt.
- Do not implement future stages unless explicitly requested.
- Preserve existing working behaviour.
- Do not add unnecessary dependencies.
- Do not commit changes. The user will test and commit manually.

## Before editing

1. Inspect the existing implementation.
2. Explain which files will be created or modified.
3. Reuse existing components where appropriate.
4. Do not begin editing until the relevant files have been inspected.

## After editing

1. Run `npm run lint` from the frontend directory.
2. Run `npm run build` from the frontend directory.
3. Fix errors and warnings caused by the changes.
4. Summarize every file created or modified.
5. Explain important implementation decisions.
6. Provide exact manual testing steps.

## Frontend standards

- Use TypeScript types rather than `any`.
- Keep components reasonably small and reusable.
- Use accessible HTML and keyboard-accessible controls.
- Maintain responsive desktop and mobile layouts.
- Avoid browser console errors.
- Clean up object URLs and event listeners when required.
- Match the existing visual design unless a redesign is requested.

## Current exclusions

Do not add these unless explicitly requested:

- OpenAI integration;
- OCR;
- code compilation;
- test generation;
- authentication;
- database integration;

## Definition of done

A feature is complete only when:

- its stated acceptance criteria pass;
- `npm run lint` passes;
- `npm run build` passes;
- manual testing instructions are provided.

## Upload rules

- Each upload section supports either:
  - up to 5 image files, or
  - 1 PDF containing up to 5 pages.
- Do not allow images and a PDF to be mixed within the same section.
- Preserve the page order selected by the user.
- PDFs must be previewed page by page before continuing.

## OCR review stage

- The upload screen passes ordered handwritten-code pages and optional question pages to the review screen.
- OCR results remain mock data until OpenAI integration is explicitly requested.
- Extracted code must always be editable before compilation.
- Preserve apparent mistakes in the transcription.
- Never automatically format or correct the extracted code.
- Users must be able to inspect every uploaded page.
- Review-screen state may remain client-side for the current frontend prototype.

## Browser editor stage

- Confirming the transcription opens the code in a Monaco Editor screen.
- The current reviewed transcription must be preserved exactly.
- Do not automatically format or correct the student’s code.
- The editor must support copying and downloading the current code.
- C++ is the only supported language for the current MVP.
- Downloaded files use the `.cpp` extension.
- Compilation and testing remain mocked until explicitly implemented.

## Backend foundation

- The backend uses Python and FastAPI.
- Backend code lives in the `backend` directory.
- The frontend and backend run as separate local services.
- API responses must use structured JSON.
- Environment-specific values must come from environment variables.
- Do not place secrets or API keys in frontend code.
- OpenAI integration and file transcription remain excluded until explicitly requested.
