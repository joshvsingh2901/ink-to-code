"use client";

import { useEffect, useRef } from "react";
import type { UploadState } from "@/components/ImageUploadCard";
import type { QuestionExtractionState } from "@/components/UploadProvider";
import QuestionImageAttach from "@/components/QuestionImageAttach";
import { buildQuestionFormData } from "@/lib/transcription";
import { transcribeQuestion } from "@/lib/aiTests";
import { questionUploadFingerprint } from "@/lib/aiTestState";

const MAX_QUESTION_CHARS = 8000;

type Props = {
  questionText: string;
  onQuestionTextChange: (value: string) => void;
  questionUpload: UploadState;
  onQuestionUploadChange: (next: UploadState) => void;
  questionExtraction: QuestionExtractionState;
  onQuestionExtractionChange: (next: QuestionExtractionState) => void;
  disabled?: boolean;
};

export default function QuestionContextPanel({
  questionText,
  onQuestionTextChange,
  questionUpload,
  onQuestionUploadChange,
  questionExtraction,
  onQuestionExtractionChange,
  disabled = false,
}: Props) {
  // Use refs to hold stable references to callbacks (avoids stale closure
  // in the effect while keeping exhaustive-deps satisfied).
  const callbacksRef = useRef({
    onQuestionExtractionChange,
    onQuestionTextChange,
  });
  // Update synchronously inside a layout-like effect to keep ref current.
  useEffect(() => {
    callbacksRef.current = { onQuestionExtractionChange, onQuestionTextChange };
  });

  // Track the extraction state's fingerprint to detect when we must trigger.
  const extractionFingerprintRef = useRef<string | null>(null);
  const extractionStatusRef = useRef<QuestionExtractionState["status"]>("idle");
  useEffect(() => {
    extractionFingerprintRef.current = questionExtraction.fingerprint;
    extractionStatusRef.current = questionExtraction.status;
  });

  // Automatic extraction: triggers once per question page set.
  useEffect(() => {
    if (questionUpload.pages.length === 0) return;

    const fingerprint = questionUploadFingerprint(questionUpload);

    if (extractionFingerprintRef.current === fingerprint) return;
    if (extractionStatusRef.current === "loading") return;

    // Mark loading immediately.
    callbacksRef.current.onQuestionExtractionChange({
      status: "loading",
      fingerprint,
      errorMessage: null,
    });

    let cancelled = false;

    async function doExtraction() {
      try {
        const formData = await buildQuestionFormData(questionUpload);
        const result = await transcribeQuestion(formData);
        if (cancelled) return;
        if (extractionFingerprintRef.current !== fingerprint) return;
        callbacksRef.current.onQuestionTextChange(result.question_text);
        callbacksRef.current.onQuestionExtractionChange({
          status: "done",
          fingerprint,
          errorMessage: null,
        });
      } catch (err) {
        if (cancelled) return;
        if (extractionFingerprintRef.current !== fingerprint) return;
        const message =
          err instanceof Error ? err.message : "Could not read the question pages.";
        callbacksRef.current.onQuestionExtractionChange({
          status: "failed",
          fingerprint,
          errorMessage: message,
        });
      }
    }

    void doExtraction();
    return () => {
      cancelled = true;
    };
  }, [questionUpload]);

  const hasQuestionPages = questionUpload.pages.length > 0;
  const isLoading = questionExtraction.status === "loading";
  const isFailed = questionExtraction.status === "failed";
  const isDone = questionExtraction.status === "done";

  function handleRetry() {
    onQuestionExtractionChange({
      status: "idle",
      fingerprint: null,
      errorMessage: null,
    });
  }

  function handleReplaceFromImage() {
    onQuestionExtractionChange({
      status: "idle",
      fingerprint: null,
      errorMessage: null,
    });
  }

  return (
    <section aria-label="Assignment question" className="mt-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-slate-700">Assignment Question</p>
        <QuestionImageAttach
          upload={questionUpload}
          onUploadChange={onQuestionUploadChange}
          disabled={disabled}
        />
      </div>

      {hasQuestionPages && isDone && (
        <p className="mt-1 text-xs text-slate-400">
          Extracted from {questionUpload.pages.length} question page
          {questionUpload.pages.length === 1 ? "" : "s"}
        </p>
      )}

      {isLoading && (
        <p
          role="status"
          aria-live="polite"
          className="mt-1.5 text-xs text-slate-500"
        >
          Reading question pages…
        </p>
      )}

      <textarea
        aria-label="Assignment question text"
        value={questionText}
        onChange={(e) => onQuestionTextChange(e.target.value)}
        disabled={disabled || isLoading}
        maxLength={MAX_QUESTION_CHARS}
        rows={4}
        placeholder={
          hasQuestionPages
            ? "Extracting question from uploaded pages…"
            : "Paste or type the assignment question here."
        }
        className="mt-1.5 w-full resize-y rounded-md border border-slate-300 px-2.5 py-2 text-xs leading-5 text-slate-800 placeholder-slate-400 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
      />

      <div className="mt-1 flex items-center justify-between gap-2">
        <span
          className={`text-xs tabular-nums ${
            questionText.length > MAX_QUESTION_CHARS * 0.9
              ? "text-amber-600"
              : "text-slate-400"
          }`}
        >
          {questionText.length} / {MAX_QUESTION_CHARS}
        </span>

        <div className="flex gap-2">
          {isFailed && (
            <>
              <p className="text-xs text-rose-600">
                Could not read the question pages.
              </p>
              <button
                type="button"
                onClick={handleRetry}
                className="text-xs font-medium text-slate-600 underline decoration-slate-300 underline-offset-4 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
              >
                Retry extraction
              </button>
            </>
          )}

          {isDone && (
            <button
              type="button"
              onClick={handleReplaceFromImage}
              className="text-xs font-medium text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
            >
              Replace from image
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
