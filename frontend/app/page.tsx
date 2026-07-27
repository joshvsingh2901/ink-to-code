"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import ImageUploadCard from "@/components/ImageUploadCard";
import { useUploads } from "@/components/UploadProvider";
import {
  buildTranscriptionFormData,
  createMockTranscription,
  requestTranscription,
} from "@/lib/transcription";

type SubmissionStatus = "idle" | "preparing" | "transcribing" | "failed";

export default function Home() {
  const router = useRouter();
  const {
    codeUpload,
    setCodeUpload,
    questionUpload,
    setQuestionUpload,
    setReviewedCode,
    setTranscriptionResult,
  } = useUploads();
  const [submissionStatus, setSubmissionStatus] =
    useState<SubmissionStatus>("idle");
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const isSubmitting =
    submissionStatus === "preparing" || submissionStatus === "transcribing";

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
      if (process.env.NEXT_PUBLIC_USE_MOCK_TRANSCRIPTION === "true") {
        setSubmissionStatus("transcribing");
        result = createMockTranscription(codeUpload.pages.length);
      } else {
        setSubmissionStatus("preparing");
        const formData = await buildTranscriptionFormData(
          codeUpload,
          questionUpload,
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

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
      <div className="mx-auto max-w-6xl">
        <header>
          <p className="text-lg font-bold tracking-tight text-slate-950">
            InkToCode
          </p>
          <div className="mt-10 max-w-3xl sm:mt-14">
            <h1 className="text-3xl font-bold tracking-tight text-slate-950 sm:text-5xl">
              Upload Your Handwritten Code
            </h1>
            <p className="mt-5 text-base leading-7 text-slate-600 sm:text-lg">
              Upload images or a PDF of your handwritten code. You may also
              upload the programming question if you want test generation and
              question-aware feedback later.
            </p>
          </div>
        </header>

        <div className="mt-10 grid items-start gap-6 lg:grid-cols-2">
          <ImageUploadCard
            id="code-images"
            sectionLabel="code"
            title="Handwritten Code"
            description="Upload up to 5 images or one PDF."
            required
            upload={codeUpload}
            onUploadChange={(upload) => {
              setCodeUpload(upload);
              invalidateTranscription();
            }}
          />
          <ImageUploadCard
            id="question-images"
            sectionLabel="question"
            title="Programming Question"
            description="Add up to 5 images or one PDF."
            upload={questionUpload}
            onUploadChange={(upload) => {
              setQuestionUpload(upload);
              invalidateTranscription();
            }}
          />
        </div>

        <div className="mt-8 flex flex-col items-start gap-3 sm:flex-row sm:items-center">
          <button
            type="button"
            disabled={codeUpload.pages.length === 0 || isSubmitting}
            onClick={handleContinue}
            className="rounded-lg bg-slate-900 px-6 py-3 font-semibold text-white transition-colors hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-slate-900"
          >
            {submissionStatus === "preparing"
              ? "Preparing pages..."
              : submissionStatus === "transcribing"
                ? "Transcribing handwriting..."
                : submissionStatus === "failed"
                  ? "Retry"
                  : "Continue"}
          </button>
          {submissionError && (
            <p role="alert" className="max-w-xl text-sm text-rose-700">
              {submissionError} Your uploaded pages and their order are unchanged.
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
