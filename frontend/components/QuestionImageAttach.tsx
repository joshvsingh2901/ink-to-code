"use client";

import { useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import type { PdfPage, UploadState } from "@/components/ImageUploadCard";
import { renderPdfPages } from "@/lib/pdf";
import {
  ACCEPTED_FILE_TYPES,
  acceptImageFiles,
  getPdfErrorMessage,
  isPdfFile,
  validatePdfFile,
} from "@/lib/questionUpload";

type Props = {
  upload: UploadState;
  onUploadChange: (next: UploadState) => void;
  disabled?: boolean;
};

/**
 * Compact question-image attach affordance for the AI Tests tab: a single
 * trigger button (no dropzone, no drag target, no image preview) plus a
 * page-count line once something is attached. Every selection — the first
 * attach or a later Replace — starts a fresh page set; there is no
 * per-page reorder/replace here, unlike the full ImageUploadCard on the
 * upload screen.
 */
export default function QuestionImageAttach({
  upload,
  onUploadChange,
  disabled = false,
}: Props) {
  const { registerPreviewUrls, revokePreviewUrls } = useUploads();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const pageCount = upload.pages.length;

  function resetInput() {
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleFiles(files: File[]) {
    if (files.length === 0) return;
    setError(null);

    const pdfFiles = files.filter(isPdfFile);
    const imageFiles = files.filter((file) => !isPdfFile(file));

    if (pdfFiles.length > 0 && imageFiles.length > 0) {
      setError("Images and a PDF cannot be attached together.");
      resetInput();
      return;
    }
    if (pdfFiles.length > 1) {
      setError("Only one PDF can be attached.");
      resetInput();
      return;
    }

    const previousPages = upload.pages;

    if (pdfFiles.length === 1) {
      const validation = validatePdfFile(pdfFiles[0]);
      if (!validation.ok) {
        setError(validation.reason);
        resetInput();
        return;
      }
      setIsProcessing(true);
      try {
        const renderedPages = await renderPdfPages(pdfFiles[0]);
        const pdfPages: PdfPage[] = renderedPages.map((page) => ({
          ...page,
          kind: "pdf",
        }));
        registerPreviewUrls(pdfPages);
        revokePreviewUrls(previousPages);
        onUploadChange({ mode: "pdf", file: pdfFiles[0], pages: pdfPages });
      } catch (pdfError) {
        setError(getPdfErrorMessage(pdfError));
      } finally {
        setIsProcessing(false);
      }
      resetInput();
      return;
    }

    const { pages, errors } = acceptImageFiles(imageFiles, []);
    if (pages.length > 0) {
      registerPreviewUrls(pages);
      revokePreviewUrls(previousPages);
      onUploadChange({ mode: "images", pages });
    }
    if (errors.length > 0) setError(errors.join(" "));
    resetInput();
  }

  function handleRemove() {
    revokePreviewUrls(upload.pages);
    setError(null);
    onUploadChange({ mode: "empty", pages: [] });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || isProcessing}
        className="text-xs font-medium text-slate-600 underline decoration-slate-300 underline-offset-4 hover:text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isProcessing
          ? "Attaching…"
          : pageCount > 0
            ? "Replace"
            : "Upload question image"}
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_FILE_TYPES}
        onChange={(event) =>
          void handleFiles(Array.from(event.target.files ?? []))
        }
        className="sr-only"
        tabIndex={-1}
        aria-label="Attach question image or PDF"
      />
      {pageCount > 0 && (
        <>
          <span className="text-xs text-slate-400">
            {pageCount} page{pageCount === 1 ? "" : "s"} attached
          </span>
          <button
            type="button"
            onClick={handleRemove}
            disabled={disabled || isProcessing}
            className="text-xs font-medium text-slate-500 underline decoration-slate-300 underline-offset-4 hover:text-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Remove
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="w-full text-xs text-rose-600">
          {error}
        </p>
      )}
    </div>
  );
}
