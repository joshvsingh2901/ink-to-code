# Web and API Security Plan

This document records the implemented Phase 4 state. It complements the
execution, resource-protection, and input-file plans; it does not claim the
application is fully secure.

## Secret boundaries

`GEMINI_API_KEY` is read only by the FastAPI backend from `backend/.env` or the
server environment. The frontend exposes only `NEXT_PUBLIC_API_BASE_URL` and a
development mock-mode switch; no backend key or model credential uses a
`NEXT_PUBLIC_*` name. Mock transcription is now gated by both the public flag
and `NODE_ENV=development`, so the flag cannot enable mock results in a
production build.

Real local environment files are ignored by Git. The tracked examples contain
an empty Gemini key and non-secret configuration only. Next.js production
browser source maps are explicitly disabled. Static tests scan product
frontend sources for backend secret identifiers and common key shapes; the
post-build validation also scans generated frontend artifacts.

Docker runner commands pass no host environment or `--env` arguments. The
runner can inherit only the fixed container image environment and its
internally constructed sanitizer settings; application secrets, `.env`, the
repository, home directory, and Docker socket remain outside the container.

## CORS policy

`FRONTEND_ORIGINS` configures a comma-separated set of exact HTTP(S) origins.
The legacy single `FRONTEND_ORIGIN` remains supported. Production refuses to
start without an explicitly configured origin. Empty values, `*`, URL paths,
queries, fragments, or embedded credentials are rejected at startup.

CORS permits only `GET` and `POST`, request headers `Accept` and
`Content-Type`, and exposes `X-Request-ID`. Credentials are disabled because
the current anonymous application uses neither cookies nor browser
authentication. Development defaults to `http://localhost:3000`; arbitrary
origins receive no allow-origin header.

## Security headers and CSP

The Next.js server applies the following to every frontend route:

- `Content-Security-Policy`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- a restrictive camera, microphone, geolocation, payment, and USB
  `Permissions-Policy`
- `X-Frame-Options: DENY` as defense in depth

The production CSP defaults to same-origin content, disallows plugins and
frames, blocks embedding with `frame-ancestors 'none'`, restricts form/base
targets, permits only the configured API origin for connections, and permits
`blob:` workers/images required by PDF.js, object previews, and Monaco.
Self-hosted Next.js fonts and scripts remain allowed. `unsafe-inline` remains
for Next.js bootstrap scripts and application styles because no per-request
nonce architecture exists. `unsafe-eval` is absent in production and allowed
only for the development toolchain/HMR.

FastAPI API/health responses receive a non-document CSP (`default-src 'none'`
and `frame-ancestors 'none'`) plus nosniff, no-referrer, permissions, and frame
headers. The API CSP is not applied to `/docs`, preserving the public Swagger
UI. HSTS is emitted by both services only when explicitly enabled in their
production environment. It should also be configured at the HTTPS termination
edge; it is deliberately off for local HTTP development.

## XSS and HTML rendering

The application frontend contains no `dangerouslySetInnerHTML`, direct
`innerHTML`/`outerHTML`, `insertAdjacentHTML`, `document.write`, raw-HTML
Markdown renderer, or dynamic script injection. Student C++, filenames,
compiler/runtime diagnostics, Gemini transcriptions/reasons, questions, and
backend messages are inserted through React text children, form values, or
Monaco models, which do not interpret them as HTML. Focused tests render a
hostile compiler/model-style string and verify escaping, and statically guard
against introducing direct HTML sinks.

## Error exposure policy

Expected product diagnostics remain specific: input validation, upload
validation, supported-signature analysis, compiler diagnostics, test output,
rate limits, capacity limits, and timeouts. Execution-provider failures and
Gemini transport failures continue to map to neutral domain messages.

Unexpected backend exceptions are caught at the outer request boundary and
return only:

```json
{
  "error": {
    "code": "internal_server_error",
    "message": "An unexpected server error occurred."
  },
  "request_id": "server-generated UUID"
}
```

Tracebacks, exception messages, paths, environment values, and provider
details are never copied into this response. AI generation catch-all errors
were similarly changed from raw exception interpolation to a neutral product
message. The frontend ignores message bodies on HTTP 500 and optionally shows
only a strictly validated server request ID as a support reference.

## Request IDs and logging

Every HTTP request receives a fresh server-generated UUIDv4. Incoming
`X-Request-ID` values are ignored, preventing oversized/control-character
header values from becoming trusted log or response data. The ID is stored in
request state/context, returned as `X-Request-ID`, exposed through CORS, and
included in structured product errors created inside the request context.

The request logger records `request_id`, method, repr-escaped path, status, and
duration in milliseconds. Unexpected-error logs add only the exception class.
It never logs query strings or bodies. Existing provider diagnostics now omit
raw provider messages; they retain error type, provider status/code, and model.
Tests prove that source/question body sentinels, synthetic secrets, paths, and
exception text do not appear in request logs or 500 responses.

## Production and API exposure

FastAPI is explicitly created with `debug=False`, so production tracebacks are
not API responses. `/docs` and `/openapi.json` remain enabled: this is an
anonymous portfolio API with no administrative routes or hidden credential
contract, and public schema documentation is useful. If private/authenticated
routes are introduced, that decision must be reviewed.

Next.js browser source maps are disabled in production. Development HMR gets a
deliberately looser CSP, while mock transcription remains development-only.
Environment validation fails closed for unsafe CORS origins.

## Residual risks and deferred work

- The production CSP still needs `unsafe-inline` until a nonce-based Next.js
  deployment design is introduced. This reduces, but does not eliminate, XSS
  impact if a future injection sink appears.
- HSTS correctness ultimately depends on the deployment proxy/CDN serving
  HTTPS and forwarding headers correctly. `ENABLE_HSTS` must not be enabled on
  a domain that is not permanently HTTPS.
- CORS is not authentication or CSRF protection. The current app is anonymous
  and non-credentialed; authentication would require a separate design.
- Logs are process-local standard Python/Uvicorn logs. Central retention,
  access control, alerting, sampling, and deletion policies are deployment
  responsibilities.
- Dependency/security advisory monitoring, WAF/CDN choices, deployment header
  verification, and Strix remain deferred to deployment/operations phases.
- Developer-only untracked tooling is not part of the shipped Next.js,
  FastAPI, or runner runtime and must be reviewed separately before inclusion
  in a production artifact.
