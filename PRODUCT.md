# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Self-directed C++ learners — students and hobbyists who write C++ by hand (notes, textbook exercises, practice problems) and want to digitize, compile, test, and get feedback on it at their own pace. Not built around a specific course or instructor workflow; the "AI-generated practice tests" and "beginner-conservative compiler explanations" are framed for independent study, not grading or submission.

## Product Purpose

Ink to Code converts a photo or PDF of handwritten C++ into reviewed, editable source, then gives the learner a real IDE-style workflow around it: compile with an actual C++17 compiler, run explicit manual tests (full-program or function-only), or request structured AI-generated practice tests derived from the assignment question. Success is a learner going from a page of handwriting to a compiled, tested, and understood program — including understanding *why* it fails, via structured compiler diagnostics and optional memory-sanitizer diagnostics.

## Positioning

Not an OCR wrapper. The multimodal transcription (two-pass Gemini: literal transcription, then visual-faithfulness verification) is the entry point, but the differentiating mechanism is everything downstream and deterministic: a real g++ compiler, a generated C++ test harness built from validated structured metadata (never raw LLM-authored source), and an isolated Docker path for ASan/UBSan/Valgrind memory diagnostics. Gemini is used only for transcription and for proposing structured (schema-validated, data-only) test plans — it never compiles, executes, or repairs code, and it is never the oracle for correctness.

## Operating Context

Single-session workflow, no accounts: upload up to five ordered handwritten-code images (or one PDF up to five pages) → transcribe/verify → review and edit transcription → Monaco editor → compile → manual and/or AI-generated tests → structured results (behavior, stdout, mutations, exceptions, compiler diagnostics, memory findings as a separate channel). Uploaded files and generated compiler/harness artifacts are processed temporarily, not stored permanently.

## Capabilities and Constraints

- C++17 only (MVP language scope).
- Supported test-mode surface: primitives, C-style arrays, scalar pointers, mutable references, 15 STL containers, iterators, classes/structs, operators, single-inheritance polymorphism, Big Five special members, templates, exceptions.
- The user's Monaco source is never silently modified, formatted, or repaired anywhere in the pipeline; apparent handwriting mistakes are preserved through transcription rather than auto-corrected.
- Gemini output is always structured JSON validated against strict schemas — never C++ source, harness code, or executable expressions.
- AI test generation: max 8 tests per run, one generation call plus at most one repair call per user action; expected values derive from question text only, never from the student's own implementation.
- Memory/sanitizer results and behavioral pass/fail are independent, separately reported channels.
- No user accounts, no persistent storage of uploaded content or source across sessions (current MVP scope).

## Brand Commitments

Product name: "Ink to Code" (repo/product identity: InkToCode). No locked visual identity, logo, or asset set yet — no design system currently authored (no DESIGN.md).

Standing visual preference for the in-app workflow (Operate surfaces: upload, review, editor): sits alongside Linear, Cursor, and the Vercel dashboard — calm, technical, restrained developer-tool register. Code editor is visually dominant; compact information density; restrained borders and corner radius; no gradients, glassmorphism, decorative pills, or oversized empty sections; interaction reads as professional, not playful. Dark-first theme. Confirmed by the user 2026-08-22 as the craft bar for this surface family, executed at full fidelity per the standing-exit convention rather than an open concept exploration.

## Evidence on Hand

None yet. No real screenshots, demo video, or usage data exist (README currently has a placeholder comment for a screenshot). Future design/portfolio work must not fabricate screenshots, testimonials, metrics, or usage claims — use real captures only.

## Product Principles

- Deterministic execution is the authority; the LLM proposes, structured/compiled tooling disposes. Never blur this line visually or functionally.
- Preserve the learner's own handwriting and code exactly — transcription and editing surfaces should make fidelity legible, not hide it.
- Make failure legible and separate: compiler errors, behavioral test failures, and memory diagnostics are distinct channels and should read as distinct, not merged into a single pass/fail signal.
- Built for independent, self-paced study — design for a solo learner working through one upload at a time, not a classroom or multi-user context.
- This is a solo-built portfolio piece as well as a working tool; any public-facing surface (e.g. a landing page) should hold up to both a learner evaluating the tool and a technical reviewer evaluating the craft.
