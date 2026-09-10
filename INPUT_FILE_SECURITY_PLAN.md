# Input File Security Plan

This document describes the implemented Phase 3 upload, filesystem, parser,
privacy, and process controls. It is an implementation record, not a list of
future work.

## Upload entry points and data flow

| Endpoint | Multipart fields | Validation and parsing | Storage and destination |
| --- | --- | --- | --- |
| `POST /api/transcribe` | 1–5 `handwritten_code_pages`; optional 0–5 `question_pages`; JSON metadata for each category | FastAPI/Starlette multipart parsing, Pydantic metadata validation, shared PNG/JPEG signature and Pillow decode validation | Framework-owned spooled upload object → immutable in-memory bytes → two Gemini transcription requests; no application file persistence |
| `POST /api/transcribe-question` | 1–5 `question_pages`; JSON metadata | The same shared validation path | Framework-owned spooled upload object → immutable in-memory bytes → one Gemini question-extraction request; no application file persistence |

The browser accepts either up to five PNG/JPEG images or one PDF of up to five
pages per upload section. PDF.js validates and renders an original PDF in the
browser. Only the resulting ordered PNG page blobs and PDF-origin metadata are
sent to the backend; original PDF bytes do not cross the backend upload
boundary.

## Supported formats and content validation

The backend supports single-frame PNG and JPEG pages only. It does not infer
type from a filename extension. For every page it:

1. permits only the documented PNG/JPEG multipart MIME values;
2. detects the PNG or JPEG signature from the bytes;
3. requires the declared MIME and byte signature to agree;
4. opens and fully decodes the image once with Pillow;
5. requires the parser format to agree with the detected signature; and
6. rejects empty, unreadable, truncated, malformed, multi-frame, or unsupported
   content before Gemini is called.

This intentionally uses a strict consistency policy: a correct image with a
misleading browser MIME is rejected with `upload_content_mismatch` rather than
silently reclassified. This keeps multipart declarations auditable while the
actual parser result remains authoritative.

The browser requires an exact leading `%PDF-` signature and then parses the
document with PDF.js. A signature alone is not enough: corrupt/truncated PDFs,
encrypted PDFs, zero-page PDFs, and PDFs over five pages are rejected. PDF.js
strict parse errors and its decoded-image pixel ceiling are enabled with
`stopAtErrors: true` and `maxImageSize`; parser verbosity is disabled so
malformed input details are not written to the browser console.

The parser dependencies are deliberately narrow: `Pillow>=12.3,<13` in the
backend and the existing `pdfjs-dist` 6.x dependency in the frontend. FastAPI,
Starlette, and `python-multipart` own multipart decoding. No general dependency
upgrade was performed.

## Filename and path policy

`UploadFile.filename` is an opaque multipart page identifier. It must match a
validated metadata `file_id`, but neither value is joined to, opened as, or
used to name a filesystem path. `file_id`, `original_filename`, and the
multipart filename reject forward slashes, backslashes, dot/dot-dot path
segments, and ASCII control characters. The original filename is retained only
as display/provider diagnostic metadata; its bytes never select a local path.

Path traversal and absolute-path inputs are therefore rejected before content
processing. The upload layer creates no server-side filename, reopens no upload
by path, and has no upload-path symlink surface.

## Temporary-file lifecycle and symlinks

The application reads each validated upload once into immutable bytes and does
not create a temporary upload directory or permanent artifact. Starlette may
spill multipart bodies into a secure `SpooledTemporaryFile`; that object is
owned by the request parser and closed after the response. Integration tests
force disk spooling and verify closure/removal after success, parser failure,
and mocked Gemini failure. Request cancellation cleanup remains delegated to
the ASGI framework's request/form lifecycle.

Phase 1 compiler/test workspaces remain unique `TemporaryDirectory` instances
and are outside the upload path. Docker result files are accepted only when
they are ordinary files and not symlinks. Phase 3 does not alter that execution
boundary. Because uploaded pages are never reopened from attacker-selected
paths, there is no applicable upload symlink to follow.

## Parser safeguards

Pillow fully decodes each image once. A page is rejected before Gemini when a
dimension exceeds 16,384 pixels, total decoded pixels exceed 50,000,000, or
Pillow reports a decompression bomb. These ceilings preserve ordinary
handwritten-page resolution while bounding decoded memory. Byte and page-count
limits from Phase 2 remain independent admission controls.

PDF rendering uses a fixed 1.25 scale. The frontend validates the calculated
width, height, and pixel count before canvas allocation and rejects PNG output
over the backend's 10 MiB page limit. Each PDF page object is cleaned in a
`finally` block, canvas backing stores are released, created object URLs are
revoked on failure, and the PDF loading task is destroyed on every exit path.
The backend does not parse or rasterize PDFs and does not decode images a
second time before handing the already validated bytes to the provider.

## Error contract

Upload failures return a structured JSON envelope with specific safe codes:

- `unsupported_file_type`
- `upload_content_mismatch`
- `malformed_image`
- `image_dimensions_too_large`
- `corrupt_upload`
- `unsafe_filename`
- `invalid_upload_metadata`
- `invalid_page_count`
- `upload_too_large`

Browser PDF errors distinguish invalid signature, malformed, unreadable,
encrypted, empty, excessive page count, excessive render dimensions, and an
unsupported browser environment. UI messages do not include parser errors,
local paths, tracebacks, temporary directory names, or provider internals.

## Privacy and persistence

No application code writes uploaded pages, extracted source, or question text
to persistent local storage or a cache. Upload contents and full documents are
not logged. Development diagnostics are limited to category/order, byte count,
validated media type, and a safe filename extension; production error logging
uses structured error type/status information rather than input content.

Gemini is the necessary external trust boundary for transcription and question
extraction: validated image bytes are sent to the configured Google Gen AI
service. This phase does not change that provider behavior or claim local-only
processing.

## Backend process audit

All production Python under `backend/app` and `runner` was audited for
`subprocess.run`, `subprocess.Popen`, `asyncio.create_subprocess*`, `os.system`,
`os.popen`, `shell=True`, `eval`, and `exec`.

The only process launches are the existing Phase 1 Docker provider calls in
`backend/app/services/execution_providers.py` and the isolated container runner
calls in `runner/runner.py`. They use argument lists and explicit
`shell=False`. Frontend upload names/content cannot choose the executable,
flags, environment, mount, or working directory. No upload processing launches
a process. A static regression test enforces these properties without changing
the Phase 1 design.

## Residual risks

- This phase does not add antivirus, content-disarm, or malware classification.
- Complex but valid images/PDFs still consume bounded client/server CPU and
  memory; byte, page, pixel, rate, request, and concurrency limits mitigate but
  cannot eliminate denial-of-service risk.
- PDF parsing occurs in the user's browser, so its isolation also depends on
  browser and PDF.js security updates.
- Multipart spooling and cancellation cleanup rely on supported
  FastAPI/Starlette behavior; integration tests cover ordinary success and
  exception paths, not forced process termination.
- Validated student images necessarily leave the local trust boundary when
  sent to Gemini. Provider retention and processing are governed by the
  configured Google service terms and account settings.
- Dependency vulnerability monitoring and future security updates remain an
  operational responsibility; Phase 3 made only the concrete Pillow addition.
