"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { UploadState } from "@/components/ImageUploadCard";
import type { TranscriptionResult } from "@/lib/transcription";

export type QuestionExtractionState = {
  status: "idle" | "loading" | "done" | "failed";
  fingerprint: string | null;
  errorMessage: string | null;
};

const INITIAL_QUESTION_EXTRACTION: QuestionExtractionState = {
  status: "idle",
  fingerprint: null,
  errorMessage: null,
};

type UploadContextValue = {
  codeUpload: UploadState;
  setCodeUpload: (upload: UploadState) => void;
  questionUpload: UploadState;
  setQuestionUpload: (upload: UploadState) => void;
  reviewedCode: string | null;
  setReviewedCode: (code: string | null) => void;
  transcriptionResult: TranscriptionResult | null;
  setTranscriptionResult: (result: TranscriptionResult | null) => void;
  registerPreviewUrls: (pages: { previewUrl: string }[]) => void;
  revokePreviewUrls: (pages: { previewUrl: string }[]) => void;
  questionText: string;
  setQuestionText: (value: string) => void;
  questionExtraction: QuestionExtractionState;
  setQuestionExtraction: (next: QuestionExtractionState) => void;
};

const UploadContext = createContext<UploadContextValue | null>(null);

export default function UploadProvider({ children }: { children: ReactNode }) {
  const [codeUpload, setCodeUpload] = useState<UploadState>({
    mode: "empty",
    pages: [],
  });
  const [questionUpload, setQuestionUpload] = useState<UploadState>({
    mode: "empty",
    pages: [],
  });
  const [reviewedCode, setReviewedCode] = useState<string | null>(null);
  const [transcriptionResult, setTranscriptionResult] =
    useState<TranscriptionResult | null>(null);
  const [questionText, setQuestionText] = useState<string>("");
  const [questionExtraction, setQuestionExtraction] =
    useState<QuestionExtractionState>(INITIAL_QUESTION_EXTRACTION);
  const objectUrlsRef = useRef(new Set<string>());

  useEffect(() => {
    const objectUrls = objectUrlsRef.current;

    return () => {
      objectUrls.forEach((previewUrl) => URL.revokeObjectURL(previewUrl));
      objectUrls.clear();
    };
  }, []);

  function registerPreviewUrls(pages: { previewUrl: string }[]) {
    pages.forEach((page) => objectUrlsRef.current.add(page.previewUrl));
  }

  function revokePreviewUrls(pages: { previewUrl: string }[]) {
    pages.forEach((page) => {
      URL.revokeObjectURL(page.previewUrl);
      objectUrlsRef.current.delete(page.previewUrl);
    });
  }

  return (
    <UploadContext.Provider
      value={{
        codeUpload,
        setCodeUpload,
        questionUpload,
        setQuestionUpload,
        reviewedCode,
        setReviewedCode,
        transcriptionResult,
        setTranscriptionResult,
        registerPreviewUrls,
        revokePreviewUrls,
        questionText,
        setQuestionText,
        questionExtraction,
        setQuestionExtraction,
      }}
    >
      {children}
    </UploadContext.Provider>
  );
}

export function useUploads() {
  const context = useContext(UploadContext);

  if (!context) {
    throw new Error("useUploads must be used within UploadProvider");
  }

  return context;
}
