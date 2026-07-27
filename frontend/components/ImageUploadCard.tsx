"use client";

import Image from "next/image";
import { ChangeEvent, DragEvent, useEffect, useRef, useState } from "react";
import { useUploads } from "@/components/UploadProvider";
import {
  PdfPreviewError,
  renderPdfPages,
  type RenderedPdfPage,
} from "@/lib/pdf";

const MAX_PAGE_COUNT = 5;
const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
const MAX_SECTION_SIZE = 50 * 1024 * 1024;
const MAX_PDF_SIZE = 50 * 1024 * 1024;
const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/jpg"];
const ACCEPTED_FILE_TYPES =
  ".png,.jpg,.jpeg,.pdf,image/png,image/jpeg,image/jpg,application/pdf";

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
  title: string;
  description: string;
  required?: boolean;
  upload: UploadState;
  onUploadChange: (upload: UploadState) => void;
};

function isSameFile(first: File, second: File) {
  return (
    first.name === second.name &&
    first.size === second.size &&
    first.lastModified === second.lastModified
  );
}

function isPdfFile(file: File) {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  );
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

function getPdfErrorMessage(error: unknown) {
  if (!(error instanceof PdfPreviewError)) {
    return "The PDF cannot be read. Try a different file.";
  }

  switch (error.code) {
    case "encrypted":
      return "This PDF is password-protected or encrypted and cannot be opened safely.";
    case "empty":
      return "This PDF contains no pages. Choose a PDF with 1 to 5 pages.";
    case "too-many-pages":
      return "This PDF contains more than 5 pages. Choose a PDF with 1 to 5 pages.";
    case "unsupported-environment":
      return "PDF preview is not supported in this browser environment.";
    default:
      return "The PDF cannot be read. It may be damaged or unsupported.";
  }
}

export default function ImageUploadCard({
  id,
  sectionLabel,
  title,
  description,
  required = false,
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

  return (
    <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${
            required ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"
          }`}
        >
          {required ? "Required" : "Optional"}
        </span>
      </div>

      {pages.length > 0 && (
        <p className="mt-4 text-sm font-semibold text-slate-800">
          {pages.length} of {MAX_PAGE_COUNT} pages
        </p>
      )}

      {upload.mode === "pdf" && (
        <div className="mt-5 flex min-w-0 items-center justify-between gap-3 rounded-xl bg-slate-50 p-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Source: one PDF
            </p>
            <p className="mt-1 truncate text-sm font-medium text-slate-800" title={upload.file.name}>
              {upload.file.name}
            </p>
          </div>
          <div className="flex shrink-0 gap-1.5">
            <button
              type="button"
              onClick={() => pdfReplaceInputRef.current?.click()}
              disabled={isProcessingPdf}
              aria-label={`Replace ${accessibleSection} PDF`}
              title={`Replace ${accessibleSection} PDF`}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:opacity-40"
            >
              <ReplaceIcon />
            </button>
            <input
              ref={pdfReplaceInputRef}
              type="file"
              accept=".pdf,application/pdf"
              onChange={handlePdfReplace}
              aria-describedby={error ? errorId : undefined}
              className="sr-only"
              tabIndex={-1}
            />
            <button
              type="button"
              onClick={removePdf}
              disabled={isProcessingPdf}
              aria-label={`Remove ${accessibleSection} PDF`}
              title={`Remove ${accessibleSection} PDF`}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 disabled:opacity-40"
            >
              <TrashIcon />
            </button>
          </div>
        </div>
      )}

      {pages.length > 0 && (
        <div className="mt-5">
          <p className="text-sm leading-6 text-slate-600">
            Pages will be processed in the order shown. Arrange the pages correctly
            before continuing.
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {pages.map((page, index) => (
              <article
                key={page.id}
                draggable
                onDragStart={() => setDraggedPageId(page.id)}
                onDragEnd={() => setDraggedPageId(null)}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "move";
                }}
                onDrop={(event) => handlePageDrop(event, index)}
                className={`min-w-0 rounded-xl border bg-white p-3 transition ${
                  draggedPageId === page.id
                    ? "border-slate-400 opacity-50"
                    : "border-slate-200"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-sm font-bold text-slate-900">Page {index + 1}</p>
                  {page.kind === "image" && (
                    <div className="flex shrink-0 gap-1.5">
                      <button
                        type="button"
                        onClick={() => imageReplaceInputRefs.current[page.id]?.click()}
                        aria-label={`Replace ${sectionLabel} page ${index + 1}`}
                        title={`Replace ${sectionLabel} page ${index + 1}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 hover:text-slate-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                      >
                        <ReplaceIcon />
                      </button>
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
                      <button
                        type="button"
                        onClick={() => removeImage(page.id)}
                        aria-label={`Remove ${sectionLabel} page ${index + 1}`}
                        title={`Remove ${sectionLabel} page ${index + 1}`}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  )}
                </div>
                <span className="mt-1 block cursor-grab text-xs font-medium text-slate-400" aria-hidden="true">
                  Drag to reorder
                </span>
                <div className="relative mt-3 aspect-[4/3] overflow-hidden rounded-lg bg-slate-100">
                  <Image
                    src={page.previewUrl}
                    alt={`${accessibleSection} page ${index + 1} preview`}
                    fill
                    unoptimized
                    className="object-contain"
                  />
                </div>
                <p className="mt-3 truncate text-sm font-medium text-slate-700" title={page.kind === "image" ? page.file.name : upload.mode === "pdf" ? upload.file.name : "PDF page"}>
                  {page.kind === "image"
                    ? page.file.name
                    : upload.mode === "pdf"
                      ? upload.file.name
                      : "PDF page"}
                </p>
              </article>
            ))}
          </div>
        </div>
      )}

      {showAddArea ? (
        <div
          onDragOver={handleAddDragOver}
          onDragLeave={handleAddDragLeave}
          onDrop={handleAddDrop}
          className={`relative mt-5 flex min-h-36 flex-col items-center justify-center rounded-xl border-2 border-dashed px-5 py-7 text-center transition-colors ${
            isAddingFiles ? "border-slate-900 bg-slate-100" : "border-slate-300 bg-slate-50"
          } ${isProcessingPdf ? "pointer-events-none opacity-60" : "hover:border-slate-400"}`}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="h-8 w-8 text-slate-400">
            <path
              d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <p className="mt-3 font-semibold text-slate-900">
            {isProcessingPdf
              ? "Preparing PDF previews…"
              : pages.length > 0
                ? "Add More Images"
                : "Drop files here, or click to browse"}
          </p>
          <p className="mt-1 text-sm text-slate-500">PNG, JPG, JPEG or PDF</p>
          <label htmlFor={id} className="absolute inset-0 cursor-pointer">
            <span className="sr-only">Choose images or one PDF for {title.toLowerCase()}</span>
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
      ) : upload.mode === "images" ? (
        <p className="mt-5 rounded-xl bg-slate-100 px-4 py-3 text-center text-sm font-semibold text-slate-700">
          Maximum of 5 images reached
        </p>
      ) : null}

      {error && (
        <p id={errorId} role="alert" className="mt-3 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
    </section>
  );
}
