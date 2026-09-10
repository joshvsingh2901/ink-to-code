"use client";

import Image from "next/image";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import { renderPdfPages, type RenderedPdfPage } from "@/lib/pdf";
import {
  MAX_PAGE_COUNT,
  MAX_IMAGE_SIZE,
  MAX_SECTION_SIZE,
  MAX_PDF_SIZE,
  ACCEPTED_IMAGE_TYPES,
  ACCEPTED_FILE_TYPES,
  isSameFile,
  isPdfFile,
  getPdfErrorMessage,
} from "@/lib/questionUpload";

export type ImagePage = {
  id: string;
  kind: "image";
  file: File;
  previewUrl: string;
};

export type PdfPage = RenderedPdfPage & {
  kind: "pdf";
};

export type UploadState =
  | { mode: "empty"; pages: [] }
  | { mode: "images"; pages: ImagePage[] }
  | { mode: "pdf"; file: File; pages: PdfPage[] };

type ImageUploadCardProps = {
  id: string;
  sectionLabel: "code" | "question";
  upload: UploadState;
  onUploadChange: (upload: UploadState) => void;
};

const MONO = "var(--font-mono-code), 'JetBrains Mono', monospace";

function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb >= 10 ? mb.toFixed(0) : mb.toFixed(1)} MB`;
}

function ReplaceIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-4 w-4">
      <path
        d="M20 7v5h-5M4 17v-5h5m9.5-2A7 7 0 0 0 6.7 6.7L4 9m16 6-2.7 2.3A7 7 0 0 1 5.5 14"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-4 w-4">
      <path
        d="M9 4h6m-9 3h12m-10 0 .7 12h6.6L16 7M10 10.5v5m4-5v5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The small "scanned document" glyph shown in the empty dropzone. */
function DocumentIcon({ dragging }: { dragging: boolean }) {
  const border = dragging ? "#3d4a7a" : "#22262e";
  const glyph = dragging ? "#8aa8ff" : "#5f6672";
  return (
    <div
      style={{
        position: "relative",
        width: 44,
        height: 54,
        border: `1px solid ${border}`,
        borderRadius: 3,
        background: "#0c0f13",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        gap: 5,
        padding: "0 8px",
      }}
    >
      <div style={{ height: 1, background: "#2a303a" }} />
      <div style={{ height: 1, background: "#2a303a", width: "78%" }} />
      <div style={{ height: 1, background: "#2a303a", width: "88%" }} />
      <div style={{ height: 1, background: "#2a303a", width: "60%" }} />
      <div
        style={{
          position: "absolute",
          right: -9,
          bottom: -8,
          width: 22,
          height: 22,
          border: `1px solid ${border}`,
          borderRadius: 3,
          background: "#0a0c0f",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: MONO,
          fontSize: 10,
          color: glyph,
        }}
      >
        {"{}"}
      </div>
    </div>
  );
}

function IconButton({
  onClick,
  disabled,
  label,
  tone = "default",
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  label: string;
  tone?: "default" | "danger";
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={tone === "danger" ? "itc-icon-btn itc-icon-btn-danger" : "itc-icon-btn"}
      style={{
        display: "inline-flex",
        height: 30,
        width: 30,
        alignItems: "center",
        justifyContent: "center",
        borderRadius: 5,
        border: "1px solid #22262e",
        background: "transparent",
        color: "#8b929d",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.4 : 1,
      }}
    >
      {children}
    </button>
  );
}

export default function ImageUploadCard({
  id,
  sectionLabel,
  upload,
  onUploadChange,
}: ImageUploadCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [isAddingFiles, setIsAddingFiles] = useState(false);
  const [isProcessingPdf, setIsProcessingPdf] = useState(false);
  const [draggedPageId, setDraggedPageId] = useState<string | null>(null);
  const addInputRef = useRef<HTMLInputElement>(null);
  const pdfReplaceInputRef = useRef<HTMLInputElement>(null);
  const imageReplaceInputRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const isMountedRef = useRef(true);
  const { registerPreviewUrls, revokePreviewUrls } = useUploads();
  const pages = upload.pages;
  const accessibleSection =
    sectionLabel === "code" ? "handwritten code" : "programming question";

  useEffect(() => {
    isMountedRef.current = true;

    return () => {
      isMountedRef.current = false;
    };
  }, []);

  function resetAddInput() {
    if (addInputRef.current) addInputRef.current.value = "";
  }

  function trackPreviewUrls(nextPages: { previewUrl: string }[]) {
    registerPreviewUrls(nextPages);
  }

  async function processPdf(file: File, isReplacement = false) {
    if (file.size > MAX_PDF_SIZE) {
      setError(`${file.name}: PDFs must be 50 MB or smaller.`);
      return;
    }

    setError(null);
    setIsProcessingPdf(true);

    try {
      const renderedPages = await renderPdfPages(file);

      if (!isMountedRef.current) {
        renderedPages.forEach((page) => URL.revokeObjectURL(page.previewUrl));
        return;
      }

      const pdfPages: PdfPage[] = renderedPages.map((page) => ({
        ...page,
        kind: "pdf",
      }));
      trackPreviewUrls(pdfPages);

      if (isReplacement && upload.mode === "pdf") {
        revokePreviewUrls(upload.pages);
      }

      onUploadChange({ mode: "pdf", file, pages: pdfPages });
      setError(null);
    } catch (pdfError) {
      if (isMountedRef.current) setError(getPdfErrorMessage(pdfError));
    } finally {
      if (isMountedRef.current) setIsProcessingPdf(false);
    }
  }

  function appendImages(selectedFiles: File[]) {
    const currentImages = upload.mode === "images" ? upload.pages : [];
    const nextImages = [...currentImages];
    const rejectedMessages: string[] = [];
    let nextTotalSize = nextImages.reduce(
      (total, page) => total + page.file.size,
      0,
    );

    selectedFiles.forEach((file) => {
      if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
        rejectedMessages.push(
          `${file.name}: unsupported file type. Choose PNG, JPG, JPEG, or PDF.`,
        );
        return;
      }
      if (file.size > MAX_IMAGE_SIZE) {
        rejectedMessages.push(`${file.name}: each image must be 10 MB or smaller.`);
        return;
      }
      if (nextImages.some((page) => isSameFile(page.file, file))) {
        rejectedMessages.push(`${file.name}: this image has already been added.`);
        return;
      }
      if (nextImages.length >= MAX_PAGE_COUNT) {
        rejectedMessages.push(`${file.name}: this section accepts a maximum of 5 images.`);
        return;
      }
      if (nextTotalSize + file.size > MAX_SECTION_SIZE) {
        rejectedMessages.push(
          `${file.name}: adding this image would exceed the 50 MB section limit.`,
        );
        return;
      }

      const previewUrl = URL.createObjectURL(file);
      registerPreviewUrls([{ previewUrl }]);
      nextImages.push({ id: crypto.randomUUID(), kind: "image", file, previewUrl });
      nextTotalSize += file.size;
    });

    if (nextImages.length !== currentImages.length) {
      onUploadChange({ mode: "images", pages: nextImages });
    }
    setError(rejectedMessages.length > 0 ? rejectedMessages.join(" ") : null);
  }

  function acceptFiles(selectedFiles: File[]) {
    if (selectedFiles.length === 0) return;

    const pdfFiles = selectedFiles.filter(isPdfFile);
    const nonPdfFiles = selectedFiles.filter((file) => !isPdfFile(file));

    if (upload.mode === "pdf") {
      setError(
        pdfFiles.length > 0
          ? "This section already contains a PDF. Use Replace PDF to choose another file."
          : "Remove the PDF before uploading separate images.",
      );
    } else if (upload.mode === "images" && pdfFiles.length > 0) {
      setError("This section already contains images. Remove them before uploading a PDF.");
    } else if (pdfFiles.length > 0 && nonPdfFiles.length > 0) {
      setError("Images and a PDF cannot be uploaded together in the same section.");
    } else if (pdfFiles.length > 1) {
      setError("Only one PDF can be uploaded per section.");
    } else if (pdfFiles.length === 1) {
      void processPdf(pdfFiles[0]);
    } else {
      appendImages(nonPdfFiles);
    }

    resetAddInput();
  }

  function handleAddInputChange(event: ChangeEvent<HTMLInputElement>) {
    acceptFiles(Array.from(event.target.files ?? []));
  }

  function handleAddDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsAddingFiles(true);
  }

  function handleAddDragLeave(event: DragEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsAddingFiles(false);
    }
  }

  function handleAddDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsAddingFiles(false);
    acceptFiles(Array.from(event.dataTransfer.files));
  }

  function removeImage(pageId: string) {
    if (upload.mode !== "images") return;
    const pageToRemove = upload.pages.find((page) => page.id === pageId);
    if (!pageToRemove) return;

    revokePreviewUrls([pageToRemove]);
    const nextPages = upload.pages.filter((page) => page.id !== pageId);
    setError(null);
    onUploadChange(
      nextPages.length > 0
        ? { mode: "images", pages: nextPages }
        : { mode: "empty", pages: [] },
    );
  }

  function replaceImage(pageId: string, replacement: File) {
    if (upload.mode !== "images") return;
    const pageIndex = upload.pages.findIndex((page) => page.id === pageId);
    if (pageIndex === -1) return;

    if (!ACCEPTED_IMAGE_TYPES.includes(replacement.type)) {
      setError(`${replacement.name}: choose a PNG, JPG, or JPEG replacement image.`);
      return;
    }
    if (replacement.size > MAX_IMAGE_SIZE) {
      setError(`${replacement.name}: each image must be 10 MB or smaller.`);
      return;
    }
    if (
      upload.pages.some(
        (page, index) => index !== pageIndex && isSameFile(page.file, replacement),
      )
    ) {
      setError(`${replacement.name}: this image has already been added.`);
      return;
    }

    const totalSize = upload.pages.reduce((total, page) => total + page.file.size, 0);
    if (totalSize - upload.pages[pageIndex].file.size + replacement.size > MAX_SECTION_SIZE) {
      setError(
        `${replacement.name}: replacing this image would exceed the 50 MB section limit.`,
      );
      return;
    }

    const oldPage = upload.pages[pageIndex];
    const previewUrl = URL.createObjectURL(replacement);
    registerPreviewUrls([{ previewUrl }]);
    const nextPages = [...upload.pages];
    nextPages[pageIndex] = {
      id: oldPage.id,
      kind: "image",
      file: replacement,
      previewUrl,
    };
    revokePreviewUrls([oldPage]);
    setError(null);
    onUploadChange({ mode: "images", pages: nextPages });
  }

  function handleImageReplace(
    event: ChangeEvent<HTMLInputElement>,
    pageId: string,
  ) {
    const replacement = event.target.files?.[0];
    if (replacement) replaceImage(pageId, replacement);
    event.target.value = "";
  }

  function handlePdfReplace(event: ChangeEvent<HTMLInputElement>) {
    const replacement = event.target.files?.[0];
    if (replacement) {
      if (!isPdfFile(replacement)) {
        setError("Remove the PDF before uploading separate images.");
      } else {
        void processPdf(replacement, true);
      }
    }
    event.target.value = "";
  }

  function removePdf() {
    if (upload.mode !== "pdf") return;
    revokePreviewUrls(upload.pages);
    setError(null);
    onUploadChange({ mode: "empty", pages: [] });
  }

  function movePage(fromIndex: number, toIndex: number) {
    if (toIndex < 0 || toIndex >= pages.length || fromIndex === toIndex) return;
    const nextPages = [...pages];
    const [movedPage] = nextPages.splice(fromIndex, 1);
    nextPages.splice(toIndex, 0, movedPage);
    setError(null);

    if (upload.mode === "images") {
      onUploadChange({ mode: "images", pages: nextPages as ImagePage[] });
    } else if (upload.mode === "pdf") {
      onUploadChange({ ...upload, pages: nextPages as PdfPage[] });
    }
  }

  function handlePageDrop(event: DragEvent<HTMLElement>, targetIndex: number) {
    event.preventDefault();
    const sourceIndex = pages.findIndex((page) => page.id === draggedPageId);
    setDraggedPageId(null);
    if (sourceIndex !== -1) movePage(sourceIndex, targetIndex);
  }

  const errorId = `${id}-error`;
  const showAddArea = upload.mode !== "pdf" && pages.length < MAX_PAGE_COUNT;
  const fileCount = upload.mode === "pdf" ? 1 : pages.length;

  return (
    <div className="min-w-0">
      {pages.length > 0 && (
        <div style={{ border: "1px solid #1b1f26", borderRadius: 8, background: "#0a0c0f", overflow: "hidden" }}>
          {/* Header */}
          <div
            style={{
              height: 40,
              borderBottom: "1px solid #16191f",
              display: "flex",
              alignItems: "center",
              padding: "0 14px",
              gap: 10,
              fontFamily: MONO,
              fontSize: 11.5,
              color: "#8b929d",
            }}
          >
            <span style={{ color: "#dfe3e9" }}>{pages.length > 1 ? "Pages queued" : "File queued"}</span>
            <span style={{ color: "#2b3038" }}>·</span>
            <span>
              {fileCount} {fileCount === 1 ? "file" : "files"} · {pages.length}{" "}
              {pages.length === 1 ? "page" : "pages"}
            </span>
            <div style={{ flex: 1 }} />
            {pages.length > 1 && <span style={{ color: "#5f6672" }}>drag rows to reorder</span>}
          </div>

          {/* PDF source summary + Replace/Remove-whole-PDF */}
          {upload.mode === "pdf" && (
            <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 14px", borderBottom: "1px solid #13161b" }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontFamily: MONO, fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase", color: "#5f6672" }}>
                  Source · one PDF
                </div>
                <div className="truncate" style={{ marginTop: 3, fontSize: 13.5, fontWeight: 500, color: "#e6e8ec" }} title={upload.file.name}>
                  {upload.file.name}
                </div>
              </div>
              {isProcessingPdf && (
                <span
                  aria-hidden="true"
                  className="animate-spin"
                  style={{ width: 13, height: 13, flex: "none", border: "1.5px solid #262c35", borderTopColor: "#5b7cfa", borderRadius: "50%" }}
                />
              )}
              <IconButton onClick={() => pdfReplaceInputRef.current?.click()} disabled={isProcessingPdf} label={`Replace ${accessibleSection} PDF`}>
                <ReplaceIcon />
              </IconButton>
              <input
                ref={pdfReplaceInputRef}
                type="file"
                accept=".pdf,application/pdf"
                onChange={handlePdfReplace}
                aria-describedby={error ? errorId : undefined}
                className="sr-only"
                tabIndex={-1}
              />
              <IconButton onClick={removePdf} disabled={isProcessingPdf} label={`Remove ${accessibleSection} PDF`} tone="danger">
                <TrashIcon />
              </IconButton>
            </div>
          )}

          {/* Per-page rows */}
          <div>
            {pages.map((page, index) => (
              <div
                key={page.id}
                draggable
                onDragStart={() => setDraggedPageId(page.id)}
                onDragEnd={() => setDraggedPageId(null)}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => handlePageDrop(event, index)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 14,
                  padding: "10px 14px",
                  borderBottom: "1px solid #13161b",
                  opacity: draggedPageId === page.id ? 0.5 : 1,
                  cursor: "grab",
                }}
              >
                <span aria-hidden="true" style={{ fontFamily: MONO, fontSize: 12, color: "#4b525d", width: 14, flex: "none" }}>
                  ⠿
                </span>
                <div style={{ position: "relative", width: 38, height: 48, flex: "none", overflow: "hidden", borderRadius: 3, border: "1px solid #22262e", background: "#0d1014" }}>
                  <Image
                    src={page.previewUrl}
                    alt={`${accessibleSection} page ${index + 1} preview`}
                    fill
                    unoptimized
                    className="object-cover"
                  />
                </div>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="truncate" style={{ fontSize: 14, color: "#e6e8ec", fontWeight: 500 }} title={page.kind === "image" ? page.file.name : upload.mode === "pdf" ? upload.file.name : "PDF page"}>
                    {page.kind === "image"
                      ? page.file.name
                      : `PDF page ${index + 1} of ${pages.length}`}
                  </div>
                  <div style={{ fontFamily: MONO, fontSize: 11.5, color: "#6f7784", marginTop: 3 }}>
                    {page.kind === "image" ? formatBytes(page.file.size) : "from " + (upload.mode === "pdf" ? upload.file.name : "PDF")}
                  </div>
                </div>
                {page.kind === "image" && (
                  <div style={{ display: "flex", flex: "none", gap: 6 }}>
                    <IconButton onClick={() => imageReplaceInputRefs.current[page.id]?.click()} label={`Replace ${sectionLabel} page ${index + 1}`}>
                      <ReplaceIcon />
                    </IconButton>
                    <input
                      ref={(element) => {
                        imageReplaceInputRefs.current[page.id] = element;
                      }}
                      type="file"
                      accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                      onChange={(event) => handleImageReplace(event, page.id)}
                      aria-describedby={error ? errorId : undefined}
                      className="sr-only"
                      tabIndex={-1}
                    />
                    <IconButton onClick={() => removeImage(page.id)} label={`Remove ${sectionLabel} page ${index + 1}`} tone="danger">
                      <TrashIcon />
                    </IconButton>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Footer: add-more / max-reached, also a drop target so drag/drop
              still works once pages already exist (design shows this as a
              plain pill; the whole row still accepts a drop to preserve
              full drag-and-drop behavior). */}
          {showAddArea ? (
            <div
              onDragOver={handleAddDragOver}
              onDragLeave={handleAddDragLeave}
              onDrop={handleAddDrop}
              style={{
                padding: "11px 14px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                background: isAddingFiles ? "#0d1119" : "transparent",
              }}
            >
              <label
                htmlFor={id}
                className="itc-add-more-pill"
                style={{
                  fontSize: 13.5,
                  color: "#c3c9d2",
                  border: "1px solid #22262e",
                  borderRadius: 5,
                  padding: "6px 12px",
                  cursor: isProcessingPdf ? "not-allowed" : "pointer",
                  opacity: isProcessingPdf ? 0.5 : 1,
                }}
              >
                <span className="sr-only">Add more pages for {accessibleSection}</span>
                + Add more
                <input
                  ref={addInputRef}
                  id={id}
                  type="file"
                  multiple
                  accept={ACCEPTED_FILE_TYPES}
                  onChange={handleAddInputChange}
                  aria-describedby={error ? errorId : undefined}
                  disabled={isProcessingPdf}
                  className="sr-only"
                />
              </label>
              <span style={{ fontFamily: MONO, fontSize: 11.5, color: "#5f6672" }}>
                {Math.max(0, MAX_PAGE_COUNT - pages.length)} of {MAX_PAGE_COUNT} pages remaining
              </span>
            </div>
          ) : upload.mode === "images" ? (
            <div style={{ padding: "11px 14px", fontFamily: MONO, fontSize: 11.5, color: "#5f6672" }}>
              Maximum of {MAX_PAGE_COUNT} images reached
            </div>
          ) : null}
        </div>
      )}

      {/* Empty / dragging dropzone */}
      {pages.length === 0 && (
        <div
          tabIndex={0}
          onDragOver={handleAddDragOver}
          onDragLeave={handleAddDragLeave}
          onDrop={handleAddDrop}
          className="itc-dropzone"
          style={{
            position: "relative",
            border: `1px ${isAddingFiles ? "solid" : "dashed"} ${isAddingFiles ? "#5b7cfa" : "#1e222a"}`,
            borderRadius: 8,
            background: isAddingFiles ? "#0d1119" : "#0a0c0f",
            padding: "52px 32px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
            cursor: isProcessingPdf ? "default" : "pointer",
            outline: "none",
            opacity: isProcessingPdf ? 0.6 : 1,
            pointerEvents: isProcessingPdf ? "none" : "auto",
          }}
        >
          {isProcessingPdf ? (
            <span
              aria-hidden="true"
              className="animate-spin"
              style={{ width: 22, height: 22, border: "2px solid #262c35", borderTopColor: "#5b7cfa", borderRadius: "50%" }}
            />
          ) : (
            <DocumentIcon dragging={isAddingFiles} />
          )}
          <div style={{ marginTop: 22, fontSize: 16, fontWeight: 500, color: "#e6e8ec" }}>
            {isProcessingPdf
              ? "Preparing PDF previews…"
              : isAddingFiles
                ? "Drop to add your files"
                : "Drop your handwritten pages here"}
          </div>
          <div style={{ marginTop: 7, fontSize: 14, color: "#8f97a3" }}>
            {isAddingFiles ? "Release anywhere in this area" : "or click to browse your files"}
          </div>
          <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 14, fontFamily: MONO, fontSize: 11.5, color: "#5f6672" }}>
            <span>PNG · JPG · JPEG · PDF</span>
            <span style={{ color: "#22262e" }}>|</span>
            <span>up to {MAX_PAGE_COUNT} pages</span>
            <span style={{ color: "#22262e" }}>|</span>
            <span>10 MB per image</span>
          </div>
          <label htmlFor={id} style={{ position: "absolute", inset: 0, cursor: isProcessingPdf ? "default" : "pointer" }}>
            <span className="sr-only">Choose images or one PDF for {accessibleSection}</span>
            <input
              ref={addInputRef}
              id={id}
              type="file"
              multiple
              accept={ACCEPTED_FILE_TYPES}
              onChange={handleAddInputChange}
              aria-describedby={error ? errorId : undefined}
              disabled={isProcessingPdf}
              className="h-full w-full cursor-pointer opacity-0"
            />
          </label>
        </div>
      )}

      {error && (
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
          <span style={{ fontFamily: MONO, fontSize: 12, color: "#e0776b", lineHeight: 1.5 }}>✗</span>
          <div>
            <div id={errorId} style={{ fontSize: 13.5, color: "#f0d6d2", lineHeight: 1.55 }}>
              {error}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button
            type="button"
            onClick={() => setError(null)}
            className="itc-dismiss-btn"
            style={{ fontSize: 13.5, color: "#c9a9a2", border: "1px solid #35242a", borderRadius: 5, padding: "4px 10px", cursor: "pointer", background: "transparent" }}
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
