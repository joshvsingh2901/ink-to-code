import type { UploadState } from "@/components/ImageUploadCard";

export type UncertainRegion = {
  id: string;
  page: number;
  line: number | null;
  detected: string;
  alternatives: string[];
  confidence: number;
  reason: string;
};

export type TranscriptionResult = {
  code: string;
  overall_confidence: number;
  uncertain_regions: UncertainRegion[];
  page_count: number;
  model: string;
};

type PageCategory = "handwritten_code" | "question";

type PageMetadata = {
  file_id: string;
  order: number;
  category: PageCategory;
  source_type: "image" | "pdf";
  original_filename: string;
  original_pdf_page_number: number | null;
};

type ApiError = { error?: { message?: string } };

export class TranscriptionRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TranscriptionRequestError";
  }
}

async function appendUpload(
  formData: FormData,
  upload: UploadState,
  category: PageCategory,
) {
  const fieldName =
    category === "handwritten_code" ? "handwritten_code_pages" : "question_pages";
  const metadataName =
    category === "handwritten_code"
      ? "handwritten_code_metadata"
      : "question_metadata";
  const metadata: PageMetadata[] = [];

  for (const [index, page] of upload.pages.entries()) {
    const order = index + 1;
    const fileId = `${category}-${page.id}.png`;
    let file: File;
    let originalFilename: string;
    let originalPdfPageNumber: number | null = null;

    if (page.kind === "image") {
      const normalizedType =
        page.file.type === "image/jpg" ? "image/jpeg" : page.file.type;
      const extension = normalizedType === "image/jpeg" ? "jpg" : "png";
      const imageFileId = `${category}-${page.id}.${extension}`;
      file = new File([page.file], imageFileId, { type: normalizedType });
      originalFilename = page.file.name;
      formData.append(fieldName, file, imageFileId);
      metadata.push({
        file_id: imageFileId,
        order,
        category,
        source_type: "image",
        original_filename: originalFilename,
        original_pdf_page_number: null,
      });
      continue;
    }

    const response = await fetch(page.previewUrl);
    if (!response.ok) {
      throw new TranscriptionRequestError(
        `Could not prepare PDF page ${order}. Please replace the PDF and retry.`,
      );
    }
    const blob = await response.blob();
    file = new File([blob], fileId, { type: "image/png" });
    originalFilename = upload.mode === "pdf" ? upload.file.name : "document.pdf";
    originalPdfPageNumber = page.originalPageNumber;
    formData.append(fieldName, file, fileId);
    metadata.push({
      file_id: fileId,
      order,
      category,
      source_type: "pdf",
      original_filename: originalFilename,
      original_pdf_page_number: originalPdfPageNumber,
    });
  }

  formData.append(metadataName, JSON.stringify(metadata));
}

export async function buildTranscriptionFormData(
  codeUpload: UploadState,
  questionUpload: UploadState,
) {
  if (codeUpload.pages.length === 0) {
    throw new TranscriptionRequestError("Add at least one handwritten-code page.");
  }

  const formData = new FormData();
  await appendUpload(formData, codeUpload, "handwritten_code");
  if (questionUpload.pages.length > 0) {
    await appendUpload(formData, questionUpload, "question");
  }
  return formData;
}

function isTranscriptionResult(value: unknown): value is TranscriptionResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Partial<TranscriptionResult>;
  return (
    typeof result.code === "string" &&
    result.code.length > 0 &&
    typeof result.overall_confidence === "number" &&
    Array.isArray(result.uncertain_regions) &&
    typeof result.page_count === "number" &&
    typeof result.model === "string"
  );
}

export async function requestTranscription(formData: FormData) {
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${apiBaseUrl}/api/transcribe`, {
      method: "POST",
      body: formData,
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      const apiError = body as ApiError | null;
      throw new TranscriptionRequestError(
        apiError?.error?.message ?? "Transcription failed. Please retry.",
      );
    }
    if (!isTranscriptionResult(body)) {
      throw new TranscriptionRequestError(
        "The transcription service returned an invalid response.",
      );
    }
    return body;
  } catch (error) {
    if (error instanceof TranscriptionRequestError) throw error;
    throw new TranscriptionRequestError(
      "The transcription service is unavailable. Check the backend and retry.",
    );
  }
}

/**
 * Build a FormData payload containing only question pages (for question extraction).
 * Mirrors `buildTranscriptionFormData` but sends only the "question" category.
 */
export async function buildQuestionFormData(questionUpload: UploadState) {
  if (questionUpload.pages.length === 0) {
    throw new TranscriptionRequestError(
      "Add at least one question page before extracting.",
    );
  }
  const formData = new FormData();
  await appendUpload(formData, questionUpload, "question");
  return formData;
}

export function createMockTranscription(pageCount: number): TranscriptionResult {
  return {
    code: `#include <iostream>\nusing namespace std;\n\nint main()\n{\n    int n\n    cin >> n;\n    count << n * 2;\n}`,
    overall_confidence: 0.84,
    uncertain_regions: [
      {
        id: "mock-count",
        page: 1,
        line: 8,
        detected: "count",
        alternatives: ["cout"],
        confidence: 0.61,
        reason: "The handwritten identifier is unclear.",
      },
    ],
    page_count: pageCount,
    model: "mock",
  };
}
