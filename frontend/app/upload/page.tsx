"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import ImageUploadCard from "@/components/ImageUploadCard";
import { useUploads } from "@/components/UploadProvider";
import {
  buildTranscriptionFormData,
  createMockTranscription,
  requestTranscription,
} from "@/lib/transcription";
import { EMPTY_UPLOAD_STATE } from "@/lib/questionUpload";
import { mockTranscriptionEnabled } from "@/lib/webSecurity";

/**
 * Visual source of truth: the Claude Design project "InkToCode landing
 * page", file "InkToCode Upload.dc.html". Restyled to the same dark
 * visual identity as the landing page (app/page.tsx) — scoped under the
 * itc-landing class in globals.css, same as there.
 *
 * All upload behavior (validation, drag/drop, browse, page limits,
 * transcription submission, error handling) is unchanged from before —
 * this file only changes presentation. See ImageUploadCard.tsx for the
 * same restyle-only treatment of the upload surface itself.
 */

type SubmissionStatus = "idle" | "preparing" | "transcribing" | "failed";

export default function UploadPage() {
  const router = useRouter();
  const { codeUpload, setCodeUpload, setReviewedCode, setTranscriptionResult } =
    useUploads();
  const [submissionStatus, setSubmissionStatus] =
    useState<SubmissionStatus>("idle");
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const isSubmitting =
    submissionStatus === "preparing" || submissionStatus === "transcribing";
  const canContinue = codeUpload.pages.length > 0 && !isSubmitting;

  function invalidateTranscription() {
    setTranscriptionResult(null);
    setReviewedCode(null);
    setSubmissionError(null);
    setSubmissionStatus("idle");
  }

  async function handleContinue() {
    if (codeUpload.pages.length === 0 || isSubmitting) return;

    setSubmissionError(null);
    try {
      let result;
      if (
        mockTranscriptionEnabled(
          process.env.NODE_ENV,
          process.env.NEXT_PUBLIC_USE_MOCK_TRANSCRIPTION,
        )
      ) {
        setSubmissionStatus("transcribing");
        result = createMockTranscription(codeUpload.pages.length);
      } else {
        setSubmissionStatus("preparing");
        // Code transcription receives handwritten-code pages only — the
        // assignment question (attached separately, in the AI Tests tab)
        // must never influence how the handwriting is read. See
        // AI_WORKFLOW_REFINEMENT_PLAN.md §12.1.
        const formData = await buildTranscriptionFormData(
          codeUpload,
          EMPTY_UPLOAD_STATE,
        );
        setSubmissionStatus("transcribing");
        result = await requestTranscription(formData);
      }
      setTranscriptionResult(result);
      setReviewedCode(result.code);
      setSubmissionStatus("idle");
      router.push("/review");
    } catch (error) {
      setSubmissionError(
        error instanceof Error
          ? error.message
          : "Transcription failed. Please retry.",
      );
      setSubmissionStatus("failed");
    }
  }

  const continueLabel =
    submissionStatus === "preparing"
      ? "Preparing pages…"
      : submissionStatus === "transcribing"
        ? "Transcribing handwriting…"
        : submissionStatus === "failed"
          ? "Retry"
          : "Continue to review";

  const hint = isSubmitting
    ? continueLabel.toLowerCase()
    : canContinue
      ? "you can edit the transcription before anything compiles"
      : "nothing is uploaded until you continue";

  return (
    <div
      className="itc-landing"
      style={{
        background: "#08090b",
        color: "#e6e8ec",
        fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
        fontSize: 16,
        lineHeight: 1.5,
        WebkitFontSmoothing: "antialiased",
        minWidth: 1280,
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top bar */}
      <div style={{ borderBottom: "1px solid #14171d", background: "#08090b" }}>
        <div style={{ maxWidth: 1160, margin: "0 auto", padding: "0 32px", height: 56, display: "flex", alignItems: "center", gap: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <div style={{ width: 16, height: 16, border: "1px solid #5b7cfa", borderRadius: 3, position: "relative", flex: "none" }}>
              <div style={{ position: "absolute", left: 3, top: 3, width: 8, height: 8, background: "#5b7cfa", borderRadius: 1 }} />
            </div>
            <span style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-0.01em" }}>InkToCode</span>
          </div>
          <span style={{ width: 1, height: 18, background: "#1b1f26" }} />
          <Link
            href="/"
            className="itc-back-link"
            style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13.5, color: "#8b929d" }}
          >
            <span style={{ fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace", fontSize: 12 }}>←</span>
            <span>Back</span>
          </Link>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace", fontSize: 11.5, color: "#6f7784" }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#7fbf67", flex: "none" }} />
            <span>compiler online</span>
            <span style={{ color: "#2b3038" }}>·</span>
            <span>g++ 13 · c++17</span>
          </div>
        </div>
      </div>

      {/* Main */}
      <div style={{ position: "relative", flex: 1, overflow: "hidden" }}>
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            backgroundImage:
              "linear-gradient(to right,#ffffff 1px,transparent 1px),linear-gradient(to bottom,#ffffff 1px,transparent 1px)",
            backgroundSize: "72px 72px",
            backgroundPosition: "center top",
            opacity: 0.03,
            WebkitMaskImage:
              "radial-gradient(ellipse 70% 60% at 50% 32%,#000 0%,rgba(0,0,0,0.5) 58%,transparent 100%)",
            maskImage:
              "radial-gradient(ellipse 70% 60% at 50% 32%,#000 0%,rgba(0,0,0,0.5) 58%,transparent 100%)",
          }}
        />
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background: "radial-gradient(ellipse 52% 40% at 50% 26%,rgba(91,124,250,0.07),transparent 72%)",
          }}
        />

        <div style={{ position: "relative", maxWidth: 840, margin: "0 auto", padding: "64px 32px 88px" }}>
          {/* Heading */}
          <div style={{ display: "flex", alignItems: "center", gap: 9, fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace", fontSize: 11, letterSpacing: "0.16em", textTransform: "uppercase", color: "#6f7784" }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#5b7cfa", flex: "none" }} />
            <span>
              Step 01 <span style={{ color: "#3f4650" }}>·</span> Upload
            </span>
          </div>
          <h1
            style={{
              margin: "18px 0 0",
              fontFamily: "var(--font-ui), 'Inter Tight', 'Inter', sans-serif",
              fontSize: 40,
              lineHeight: 1.08,
              letterSpacing: "-0.032em",
              fontWeight: 600,
              color: "#f4f6fa",
            }}
          >
            Upload your handwritten C++
          </h1>
          <p style={{ margin: "14px 0 0", fontSize: 16, lineHeight: 1.6, color: "#8f97a3", maxWidth: 520 }}>
            Add photos or a PDF of the code you wrote on paper. You can attach the
            assignment question later, from the AI Tests tab, once your code is
            transcribed.
          </p>

          {/* Upload surface */}
          <div style={{ marginTop: 34 }}>
            <ImageUploadCard
              id="code-images"
              sectionLabel="code"
              upload={codeUpload}
              onUploadChange={(upload) => {
                setCodeUpload(upload);
                invalidateTranscription();
              }}
            />

            {submissionError && (
              <div
                role="alert"
                style={{
                  marginTop: 12,
                  border: "1px solid #35242a",
                  borderRadius: 7,
                  background: "#120f11",
                  padding: "13px 14px",
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-start",
                }}
              >
                <span style={{ fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace", fontSize: 12, color: "#e0776b", lineHeight: 1.5 }}>
                  ✗
                </span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: "#f0d6d2" }}>
                    Transcription couldn&apos;t be started
                  </div>
                  <div style={{ fontSize: 13.5, color: "#a9909a", marginTop: 4, lineHeight: 1.55 }}>
                    {submissionError} Your uploaded pages and their order are unchanged.
                  </div>
                </div>
                <div style={{ flex: 1 }} />
                <button
                  type="button"
                  onClick={() => setSubmissionError(null)}
                  className="itc-dismiss-btn"
                  style={{ fontSize: 13.5, color: "#c9a9a2", border: "1px solid #35242a", borderRadius: 5, padding: "4px 10px", cursor: "pointer", background: "transparent" }}
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* Action row */}
            <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace", fontSize: 11.5, color: "#5f6672" }}>
                {hint}
              </div>
              <div style={{ flex: 1 }} />
              <button
                type="button"
                disabled={!canContinue}
                onClick={handleContinue}
                className="itc-continue-btn"
                style={
                  canContinue
                    ? { fontSize: 14.5, fontWeight: 500, color: "#fff", background: "#5b7cfa", borderRadius: 6, padding: "11px 20px", border: "none", cursor: "pointer" }
                    : { fontSize: 14.5, fontWeight: 500, color: "#5a6070", background: "#0f1218", border: "1px solid #1b1f26", borderRadius: 6, padding: "10px 19px", cursor: "not-allowed" }
                }
              >
                {continueLabel}
              </button>
            </div>
          </div>

          {/* Step trail */}
          <div
            style={{
              marginTop: 44,
              paddingTop: 18,
              borderTop: "1px solid #14171d",
              display: "flex",
              alignItems: "center",
              gap: 12,
              fontFamily: "var(--font-mono-code), 'JetBrains Mono', monospace",
              fontSize: 11.5,
              color: "#4b525d",
            }}
          >
            <span style={{ color: "#c9cfd8" }}>01 Upload</span>
            <span style={{ color: "#2b3038" }}>→</span>
            <span>02 Review transcription</span>
            <span style={{ color: "#2b3038" }}>→</span>
            <span>03 Compile</span>
            <span style={{ color: "#2b3038" }}>→</span>
            <span>04 Test</span>
          </div>
        </div>
      </div>
    </div>
  );
}
