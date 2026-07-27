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

`POST /api/run-tests` accepts the current C++17 source and 1–10 explicit test
cases. Each test provides a name, standard input, and exact expected standard
output. Runnable tests require a complete program with `main()`; function-only
source remains valid for `/api/compile` but cannot be executed without a future
test harness.

The test runner compiles with a fixed argument list, runs only after an explicit
request, and uses a unique temporary directory that is deleted afterward. Each
test has a two-second timeout. Standard output and standard error are each
limited to 64 KiB; a process exceeding either limit is stopped and its output is
reported as limited. Output comparison preserves the raw expected and actual
text for display, but compares their whitespace-separated token sequences.
Leading and trailing whitespace, repeated spaces, tabs, and line-break
differences are ignored; token text, punctuation, capitalization, and order
must still match exactly.

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
