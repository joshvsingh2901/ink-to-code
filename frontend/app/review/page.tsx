"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import { createMockTranscription, type UncertainRegion } from "@/lib/transcription";
import { mockTranscriptionEnabled } from "@/lib/webSecurity";

/**
 * Visual source of truth: the Claude Design project "InkToCode landing
 * page", file "InkToCode Review.dc.html". Restyled to the same dark
 * visual identity as / and /upload — scoped under itc-landing in
 * globals.css.
 *
 * All review data/logic (transcription source, uncertain regions,
 * focusLine/applySuggestion, page navigation, edited-state detection,
 * review -> editor handoff) is unchanged from before — this file only
 * changes presentation. Two mockup states have no real equivalent and are
 * NOT implemented: the mockup's per-page "loading"/"error" states model a
 * streaming per-page transcription flow this product doesn't have —
 * transcription is a single batched request that fully succeeds or fails
 * on /upload, before /review is ever reached. The mockup's read-only
 * syntax-highlighted code panel is also not implemented as a static
 * view — the real transcription is a directly editable <textarea>
 * (dropping that would remove real editing capability); its container is
 * restyled to the same dark chrome instead.
 */

const MONO = "var(--font-mono-code), 'JetBrains Mono', monospace";

export default function ReviewPage() {
  const router = useRouter();
  const {
    codeUpload,
    transcriptionResult,
    reviewedCode,
    setReviewedCode,
  } = useUploads();
  const [selectedPageIndex, setSelectedPageIndex] = useState(0);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const pages = codeUpload.pages;
  const allowMock = mockTranscriptionEnabled(
    process.env.NODE_ENV,
    process.env.NEXT_PUBLIC_USE_MOCK_TRANSCRIPTION,
  );
  const result =
    transcriptionResult ??
    (allowMock && pages.length > 0 ? createMockTranscription(pages.length) : null);
  const transcription = reviewedCode ?? result?.code ?? "";
  const isEdited = result !== null && transcription !== result.code;

  useEffect(() => {
    if (pages.length === 0 || !result) router.replace("/upload");
  }, [pages.length, result, router]);

  function focusLine(lineNumber: number) {
    const lines = transcription.split("\n");
    const start = lines
      .slice(0, lineNumber - 1)
      .reduce((length, line) => length + line.length + 1, 0);
    const end = start + (lines[lineNumber - 1]?.length ?? 0);
    editorRef.current?.focus();
    editorRef.current?.setSelectionRange(start, end);
  }

  function applySuggestion(region: UncertainRegion, alternative: string) {
    if (region.line === null) return;
    const lines = transcription.split("\n");
    const lineIndex = region.line - 1;
    if (lines[lineIndex]?.includes(region.detected)) {
      lines[lineIndex] = lines[lineIndex].replace(region.detected, alternative);
      setReviewedCode(lines.join("\n"));
      requestAnimationFrame(() => focusLine(region.line!));
    } else {
      focusLine(region.line);
    }
  }

  if (pages.length === 0 || !result) {
    return (
      <div
        className="itc-landing"
        style={{
          background: "#08090b",
          color: "#e6e8ec",
          fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, textAlign: "center" }}>
          <div
            style={{
              width: 38,
              height: 38,
              border: "1px solid #35242a",
              borderRadius: 5,
              background: "#120f11",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: MONO,
              fontSize: 14,
              color: "#e0776b",
            }}
          >
            ✗
          </div>
          <div style={{ fontSize: 16, fontWeight: 500, color: "#f0d6d2" }}>
            No completed transcription was found
          </div>
          <div style={{ fontSize: 14, color: "#a9909a", maxWidth: 360, lineHeight: 1.6 }}>
            Upload your handwritten pages first — you&apos;ll come back here to review
            the transcription before anything compiles.
          </div>
          <button
            type="button"
            onClick={() => router.push("/upload")}
            className="itc-continue-btn"
            style={{
              marginTop: 6,
              fontSize: 14.5,
              fontWeight: 500,
              color: "#fff",
              background: "#5b7cfa",
              borderRadius: 6,
              padding: "11px 20px",
              border: "none",
              cursor: "pointer",
            }}
          >
            Return to upload
          </button>
        </div>
      </div>
    );
  }

  const selectedPage = pages[selectedPageIndex] ?? pages[0];
  const confidencePct = Math.round(result.overall_confidence * 100);
  const regionCount = result.uncertain_regions.length;
  const confRegionsText = isEdited
    ? "edited locally"
    : regionCount === 0
      ? "no regions flagged"
      : `${regionCount} region${regionCount === 1 ? "" : "s"} to review`;
  const confColor = isEdited ? "#8aa8ff" : regionCount === 0 ? "#8fc470" : "#d8a76a";

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
        <div style={{ maxWidth: 1240, margin: "0 auto", padding: "0 32px", height: 56, display: "flex", alignItems: "center", gap: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <div style={{ width: 16, height: 16, border: "1px solid #5b7cfa", borderRadius: 3, position: "relative", flex: "none" }}>
              <div style={{ position: "absolute", left: 3, top: 3, width: 8, height: 8, background: "#5b7cfa", borderRadius: 1 }} />
            </div>
            <span style={{ fontSize: 14.5, fontWeight: 600, letterSpacing: "-0.01em" }}>InkToCode</span>
          </div>
          <span style={{ width: 1, height: 18, background: "#1b1f26" }} />
          <button
            type="button"
            onClick={() => router.push("/upload")}
            className="itc-back-link"
            style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 13.5, color: "#8b929d", background: "none", border: "none", padding: 0, cursor: "pointer" }}
          >
            <span style={{ fontFamily: MONO, fontSize: 12 }}>←</span>
            <span>Back to upload</span>
          </button>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 7, fontFamily: MONO, fontSize: 11.5, color: "#6f7784" }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#7fbf67", flex: "none" }} />
            <span>compiler online</span>
            <span style={{ color: "#2b3038" }}>·</span>
            <span>g++ 13 · c++17</span>
          </div>
        </div>
      </div>

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
              "radial-gradient(ellipse 70% 58% at 50% 24%,#000 0%,rgba(0,0,0,0.5) 58%,transparent 100%)",
            maskImage:
              "radial-gradient(ellipse 70% 58% at 50% 24%,#000 0%,rgba(0,0,0,0.5) 58%,transparent 100%)",
          }}
        />
        <div
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background: "radial-gradient(ellipse 50% 34% at 50% 16%,rgba(91,124,250,0.06),transparent 72%)",
          }}
        />

        <div style={{ position: "relative", maxWidth: 1240, margin: "0 auto", padding: "40px 32px 72px" }}>
          {/* Heading */}
          <div style={{ fontFamily: MONO, fontSize: 11, letterSpacing: "0.16em", textTransform: "uppercase", color: "#6f7784", display: "flex", alignItems: "center", gap: 9 }}>
            <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#5b7cfa", flex: "none" }} />
            <span>
              02 <span style={{ color: "#3f4650" }}>·</span> Review
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 32, marginTop: 14, flexWrap: "wrap" }}>
            <h1
              style={{
                margin: 0,
                fontFamily: "var(--font-ui), 'Inter Tight', 'Inter', sans-serif",
                fontSize: 29,
                lineHeight: 1.14,
                letterSpacing: "-0.028em",
                fontWeight: 600,
                color: "#f4f6fa",
                flex: "none",
              }}
            >
              Review transcription
            </h1>
            <div style={{ flex: 1 }} />
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontFamily: MONO, fontSize: 12.5, flex: "none" }}>
              <span style={{ color: confColor }}>{confidencePct}%</span>
              <span style={{ color: "#2b3038" }}>·</span>
              <span style={{ color: "#8f97a3" }}>{confRegionsText}</span>
            </div>
          </div>
          <p style={{ margin: "9px 0 0", fontSize: 14.5, lineHeight: 1.55, color: "#8f97a3" }}>
            Compare the source with the extracted C++.
          </p>

          {/* Workspace */}
          <div style={{ marginTop: 22, display: "grid", gridTemplateColumns: "minmax(0,42fr) minmax(0,58fr)", gap: 16, alignItems: "stretch" }}>
            {/* Left: source */}
            <section aria-labelledby="original-pages-heading" style={{ border: "1px solid #1b1f26", borderRadius: 8, background: "#0a0c0f", display: "flex", flexDirection: "column", minHeight: 560 }}>
              <div style={{ height: 38, borderBottom: "1px solid #16191f", display: "flex", alignItems: "center", padding: "0 13px", gap: 10, fontFamily: MONO, fontSize: 11.5, color: "#8b929d" }}>
                <span id="original-pages-heading" style={{ color: "#dfe3e9" }}>
                  Handwritten source
                </span>
                <span style={{ color: "#2b3038" }}>·</span>
                <span>
                  page {selectedPageIndex + 1} of {pages.length}
                </span>
                <div style={{ flex: 1 }} />
                <span style={{ color: "#5f6672" }}>source of truth</span>
              </div>

              <div style={{ flex: 1, padding: 13, minHeight: 0 }}>
                <div style={{ position: "relative", width: "100%", height: "100%", minHeight: 380, borderRadius: 4, overflow: "hidden", background: "#0d1014" }}>
                  <Image
                    src={selectedPage.previewUrl}
                    alt={`Handwritten code page ${selectedPageIndex + 1}`}
                    fill
                    unoptimized
                    className="object-contain"
                  />
                </div>
              </div>

              <div style={{ padding: "0 13px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <button
                  type="button"
                  disabled={selectedPageIndex === 0}
                  onClick={() => setSelectedPageIndex((index) => index - 1)}
                  aria-label="Show previous handwritten-code page"
                  className="itc-add-more-pill"
                  style={{
                    fontSize: 13,
                    color: selectedPageIndex === 0 ? "#4b525d" : "#c3c9d2",
                    border: "1px solid #22262e",
                    borderRadius: 5,
                    padding: "6px 12px",
                    background: "transparent",
                    cursor: selectedPageIndex === 0 ? "not-allowed" : "pointer",
                  }}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={selectedPageIndex === pages.length - 1}
                  onClick={() => setSelectedPageIndex((index) => index + 1)}
                  aria-label="Show next handwritten-code page"
                  className="itc-add-more-pill"
                  style={{
                    fontSize: 13,
                    color: selectedPageIndex === pages.length - 1 ? "#4b525d" : "#c3c9d2",
                    border: "1px solid #22262e",
                    borderRadius: 5,
                    padding: "6px 12px",
                    background: "transparent",
                    cursor: selectedPageIndex === pages.length - 1 ? "not-allowed" : "pointer",
                  }}
                >
                  Next
                </button>
              </div>

              {pages.length > 1 && (
                <div style={{ borderTop: "1px solid #16191f", padding: "10px 13px", display: "flex", alignItems: "center", gap: 8 }}>
                  <div aria-label="Choose a page" style={{ display: "flex", gap: 8, overflowX: "auto" }}>
                    {pages.map((page, index) => (
                      <button
                        key={page.id}
                        type="button"
                        onClick={() => setSelectedPageIndex(index)}
                        aria-label={`Show handwritten-code page ${index + 1}`}
                        aria-current={selectedPageIndex === index ? "page" : undefined}
                        className="itc-page-thumb"
                        style={{
                          position: "relative",
                          width: 34,
                          height: 44,
                          flex: "none",
                          borderRadius: 3,
                          border: `1px solid ${selectedPageIndex === index ? "#5b7cfa" : "#22262e"}`,
                          background: "#0d1014",
                          overflow: "hidden",
                          cursor: "pointer",
                          padding: 0,
                        }}
                      >
                        <Image src={page.previewUrl} alt="" fill unoptimized className="object-cover" />
                      </button>
                    ))}
                  </div>
                  <div style={{ flex: 1 }} />
                  <span style={{ fontFamily: MONO, fontSize: 11.5, color: "#5f6672" }}>
                    page {selectedPageIndex + 1} of {pages.length}
                  </span>
                </div>
              )}
            </section>

            {/* Right: transcription */}
            <section aria-labelledby="transcription-heading" style={{ border: "1px solid #1b1f26", borderRadius: 8, background: "#0b0d10", display: "flex", flexDirection: "column", minHeight: 560, overflow: "hidden" }}>
              <div style={{ height: 38, borderBottom: "1px solid #16191f", display: "flex", alignItems: "center", padding: "0 13px", gap: 10, fontFamily: MONO, fontSize: 11.5, color: "#8b929d" }}>
                <span id="transcription-heading" style={{ color: "#dfe3e9" }}>
                  Extracted C++
                </span>
                <span style={{ color: "#2b3038" }}>·</span>
                <span>solution.cpp</span>
                <div style={{ flex: 1 }} />
                <span style={{ color: isEdited ? "#8aa8ff" : "#5f6672" }}>{isEdited ? "edited · unsaved" : "editable"}</span>
              </div>

              <div style={{ flex: 1, minHeight: 0, padding: 13, display: "flex" }}>
                <label htmlFor="transcription-editor" className="sr-only">
                  Editable code transcription
                </label>
                <textarea
                  ref={editorRef}
                  id="transcription-editor"
                  value={transcription}
                  onChange={(event) => setReviewedCode(event.target.value)}
                  spellCheck={false}
                  style={{
                    flex: 1,
                    minHeight: 0,
                    width: "100%",
                    resize: "vertical",
                    borderRadius: 4,
                    border: "1px solid #1b1f26",
                    background: "#0a0c0f",
                    padding: 14,
                    fontFamily: MONO,
                    fontSize: 13,
                    lineHeight: 1.7,
                    color: "#dfe3e9",
                    outline: "none",
                  }}
                  className="itc-review-editor"
                />
              </div>

              {/* Uncertain regions */}
              {result.uncertain_regions.length === 0 ? (
                <div style={{ borderTop: "1px solid #16191f", padding: "10px 13px", display: "flex", alignItems: "center", gap: 9, fontFamily: MONO, fontSize: 11.5, color: "#6f7784" }}>
                  <span style={{ color: "#7fbf67" }}>✓</span>
                  <span>No uncertain regions reported.</span>
                </div>
              ) : (
                <div style={{ borderTop: "1px solid #16191f", background: "#0a0c0f", fontFamily: MONO, fontSize: 12 }}>
                  <div style={{ padding: "8px 13px 7px", fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "#8a7245" }}>
                    Needs review
                  </div>
                  {result.uncertain_regions.map((region) => {
                    const alternative = region.alternatives[0];
                    return (
                      <div
                        key={region.id}
                        style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, padding: "8px 13px", borderTop: "1px solid #13161b" }}
                      >
                        <button
                          type="button"
                          disabled={region.line === null}
                          onClick={() => region.line !== null && focusLine(region.line)}
                          aria-label={region.line === null ? `Review uncertainty on page ${region.page}` : `Focus uncertain transcription on line ${region.line}`}
                          className="itc-jump-btn"
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 10,
                            background: "none",
                            border: "none",
                            padding: 0,
                            cursor: region.line === null ? "default" : "pointer",
                            textAlign: "left",
                            color: "inherit",
                            font: "inherit",
                          }}
                        >
                          <span style={{ color: "#d8a76a", flex: "none" }}>
                            {region.line === null ? `Page ${region.page}` : `Line ${region.line}`}
                          </span>
                          <span style={{ color: "#c9cfd8", flex: "none" }}>{region.detected}</span>
                          {alternative && (
                            <>
                              <span style={{ color: "#3f4650", flex: "none" }}>→</span>
                              <span style={{ color: "#8f97a3", minWidth: 0, maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {region.alternatives.join(" / ")}
                              </span>
                            </>
                          )}
                          <span style={{ color: "#6f7784", flex: "none" }}>{Math.round(region.confidence * 100)}%</span>
                          {region.line !== null && <span className="itc-jump-label">Jump</span>}
                        </button>
                        <div style={{ flex: 1 }} />
                        {alternative && region.line !== null && (
                          <button
                            type="button"
                            onClick={() => applySuggestion(region, alternative)}
                            className="itc-add-more-pill"
                            style={{ fontSize: 12, color: "#c3c9d2", border: "1px solid #22262e", borderRadius: 5, padding: "4px 10px", background: "transparent", cursor: "pointer", flex: "none" }}
                          >
                            Apply {alternative}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          </div>

          {/* Actions */}
          <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 12, justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={() => router.push("/upload")}
              className="itc-btn-secondary"
              style={{ fontSize: 14.5, color: "#c3c9d2", border: "1px solid #22262e", borderRadius: 6, padding: "11px 18px", background: "transparent", cursor: "pointer" }}
            >
              Back to upload
            </button>
            <button
              type="button"
              onClick={() => {
                setReviewedCode(transcription);
                router.push("/editor");
              }}
              className="itc-continue-btn"
              style={{ fontSize: 14.5, fontWeight: 500, color: "#fff", background: "#5b7cfa", borderRadius: 6, padding: "11px 20px", border: "none", cursor: "pointer" }}
            >
              Confirm and continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
