/**
 * Shared validation limits and file->UploadState conversion for
 * question-page uploads.
 *
 * Used by both the full ImageUploadCard (the handwritten-code upload
 * screen) and the compact QuestionImageAttach (AI Tests tab), so the two
 * paths cannot drift out of sync with each other or with the backend's
 * independent validation in app/services/uploads.py.
 */
import type { ImagePage, UploadState } from "../components/ImageUploadCard.tsx";
// A structural check keeps this utility independent of the PDF parser module.
type PdfErrorLike = { code: string };

function isPdfErrorLike(error: unknown): error is PdfErrorLike {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code: unknown }).code === "string"
  );
}

export const MAX_PAGE_COUNT = 5;
export const MAX_IMAGE_SIZE = 10 * 1024 * 1024;
export const MAX_SECTION_SIZE = 50 * 1024 * 1024;
export const MAX_PDF_SIZE = 50 * 1024 * 1024;
export const ACCEPTED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/jpg"];
export const ACCEPTED_FILE_TYPES =
  ".png,.jpg,.jpeg,.pdf,image/png,image/jpeg,image/jpg,application/pdf";

export function isSameFile(first: File, second: File): boolean {
  return (
    first.name === second.name &&
    first.size === second.size &&
    first.lastModified === second.lastModified
  );
}

export function isPdfFile(file: File): boolean {
  return (
    file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
  );
}

export function getPdfErrorMessage(error: unknown): string {
  if (!isPdfErrorLike(error)) {
    return "The PDF cannot be read. Try a different file.";
  }

  switch (error.code) {
    case "encrypted":
      return "This PDF is password-protected or encrypted and cannot be opened safely.";
    case "empty":
      return "This PDF contains no pages. Choose a PDF with 1 to 5 pages.";
    case "invalid-signature":
      return "This file is not a valid PDF. Choose a PDF that opens normally.";
    case "malformed":
      return "This PDF is damaged or incomplete. Choose a different PDF.";
    case "page-too-large":
      return "A PDF page is too large to preview safely. Use a smaller page size or resolution.";
    case "too-many-pages":
      return "This PDF contains more than 5 pages. Choose a PDF with 1 to 5 pages.";
    case "unsupported-environment":
      return "PDF preview is not supported in this browser environment.";
    default:
      return "The PDF cannot be read. It may be damaged or unsupported.";
  }
}

export type ImageValidationResult = { ok: true } | { ok: false; reason: string };

export function validateNewImage(
  file: File,
  existingImages: Array<{ file: File }>,
): ImageValidationResult {
  if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) {
    return {
      ok: false,
      reason: `${file.name}: unsupported file type. Choose PNG, JPG, JPEG, or PDF.`,
    };
  }
  if (file.size > MAX_IMAGE_SIZE) {
    return {
      ok: false,
      reason: `${file.name}: each image must be 10 MB or smaller.`,
    };
  }
  if (existingImages.some((page) => isSameFile(page.file, file))) {
    return {
      ok: false,
      reason: `${file.name}: this image has already been added.`,
    };
  }
  if (existingImages.length >= MAX_PAGE_COUNT) {
    return {
      ok: false,
      reason: `${file.name}: this section accepts a maximum of 5 images.`,
    };
  }
  const currentTotal = existingImages.reduce(
    (total, page) => total + page.file.size,
    0,
  );
  if (currentTotal + file.size > MAX_SECTION_SIZE) {
    return {
      ok: false,
      reason: `${file.name}: adding this image would exceed the 50 MB section limit.`,
    };
  }
  return { ok: true };
}

export function validatePdfFile(file: File): ImageValidationResult {
  if (file.size > MAX_PDF_SIZE) {
    return { ok: false, reason: `${file.name}: PDFs must be 50 MB or smaller.` };
  }
  return { ok: true };
}

/**
 * Validates and converts a batch of newly-selected image files into
 * ImagePage entries, appended to `existingPages`. Creates a preview URL
 * (via URL.createObjectURL) for each accepted file — callers own
 * registering/revoking those through UploadProvider.
 */
export function acceptImageFiles(
  files: File[],
  existingPages: ImagePage[],
): { pages: ImagePage[]; errors: string[] } {
  const nextPages = [...existingPages];
  const errors: string[] = [];

  files.forEach((file) => {
    const result = validateNewImage(file, nextPages);
    if (!result.ok) {
      errors.push(result.reason);
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    nextPages.push({ id: crypto.randomUUID(), kind: "image", file, previewUrl });
  });

  return { pages: nextPages, errors };
}

export const EMPTY_UPLOAD_STATE: UploadState = { mode: "empty", pages: [] };
