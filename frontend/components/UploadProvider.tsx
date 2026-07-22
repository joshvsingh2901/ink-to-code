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

type UploadContextValue = {
  codeUpload: UploadState;
  setCodeUpload: (upload: UploadState) => void;
  questionUpload: UploadState;
  setQuestionUpload: (upload: UploadState) => void;
  reviewedCode: string | null;
  setReviewedCode: (code: string) => void;
  registerPreviewUrls: (pages: { previewUrl: string }[]) => void;
  revokePreviewUrls: (pages: { previewUrl: string }[]) => void;
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
        registerPreviewUrls,
        revokePreviewUrls,
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
