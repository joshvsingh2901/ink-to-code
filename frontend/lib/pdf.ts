const MAX_PDF_PAGES = 5;
const MAX_RENDERED_PAGE_DIMENSION = 16_384;
const MAX_RENDERED_PAGE_PIXELS = 50_000_000;
const MAX_RENDERED_PAGE_BYTES = 10 * 1024 * 1024;
const PDF_SIGNATURE = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]);

export type RenderedPdfPage = {
  id: string;
  originalPageNumber: number;
  previewUrl: string;
};

export type PdfErrorCode =
  | "encrypted"
  | "empty"
  | "invalid-signature"
  | "malformed"
  | "page-too-large"
  | "too-many-pages"
  | "unsupported-environment"
  | "unreadable";

export class PdfPreviewError extends Error {
  readonly code: PdfErrorCode;

  constructor(code: PdfErrorCode) {
    super(code);
    this.code = code;
    this.name = "PdfPreviewError";
  }
}

type OpenPdfDocument = {
  document: Awaited<
    ReturnType<
      (typeof import("pdfjs-dist/legacy/build/pdf.mjs"))["getDocument"]
    >["promise"]
  >;
  destroy: () => Promise<void>;
};

function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new PdfPreviewError("unreadable"));
      }
    }, "image/png");
  });
}

function isBrowserCompatibilityError(error: unknown) {
  return (
    error instanceof Error &&
    /(?:getOrInsertComputed|Promise\.withResolvers).*not a function/i.test(
      error.message,
    )
  );
}

function normalizePdfError(error: unknown): PdfPreviewError {
  if (error instanceof PdfPreviewError) {
    return error;
  }
  if (isBrowserCompatibilityError(error)) {
    return new PdfPreviewError("unsupported-environment");
  }
  if (error instanceof Error && error.name === "PasswordException") {
    return new PdfPreviewError("encrypted");
  }
  if (
    error instanceof Error &&
    ["InvalidPDFException", "FormatError"].includes(error.name)
  ) {
    return new PdfPreviewError("malformed");
  }
  return new PdfPreviewError("unreadable");
}

async function safelyDestroy(destroy: () => Promise<void>): Promise<void> {
  try {
    await destroy();
  } catch {
    // Cleanup errors must not replace the validation/rendering result.
  }
}

export function hasPdfSignature(data: Uint8Array): boolean {
  return PDF_SIGNATURE.every((byte, index) => data[index] === byte);
}

export function validatePdfPageDimensions(width: number, height: number): void {
  const renderedWidth = Math.ceil(width);
  const renderedHeight = Math.ceil(height);
  if (
    !Number.isFinite(renderedWidth) ||
    !Number.isFinite(renderedHeight) ||
    renderedWidth <= 0 ||
    renderedHeight <= 0 ||
    renderedWidth > MAX_RENDERED_PAGE_DIMENSION ||
    renderedHeight > MAX_RENDERED_PAGE_DIMENSION ||
    renderedWidth * renderedHeight > MAX_RENDERED_PAGE_PIXELS
  ) {
    throw new PdfPreviewError("page-too-large");
  }
}

export async function openValidatedPdf(file: File): Promise<OpenPdfDocument> {
  const data = new Uint8Array(await file.arrayBuffer());
  if (!hasPdfSignature(data)) {
    throw new PdfPreviewError("invalid-signature");
  }

  let pdfjs: typeof import("pdfjs-dist/legacy/build/pdf.mjs");
  try {
    pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  } catch (error) {
    throw normalizePdfError(error);
  }

  if (typeof window !== "undefined") {
    pdfjs.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
  }

  const loadingTask = pdfjs.getDocument({
    data,
    stopAtErrors: true,
    maxImageSize: MAX_RENDERED_PAGE_PIXELS,
    verbosity: 0,
  });

  try {
    const document = await loadingTask.promise;
    if (document.numPages === 0) {
      throw new PdfPreviewError("empty");
    }
    if (document.numPages > MAX_PDF_PAGES) {
      throw new PdfPreviewError("too-many-pages");
    }
    return {
      document,
      destroy: () => loadingTask.destroy(),
    };
  } catch (error) {
    await safelyDestroy(() => loadingTask.destroy());
    throw normalizePdfError(error);
  }
}

export async function renderPdfPages(file: File): Promise<RenderedPdfPage[]> {
  const previewUrls: string[] = [];
  let openedPdf: OpenPdfDocument | undefined;

  try {
    openedPdf = await openValidatedPdf(file);
    const { document } = openedPdf;
    const pages: RenderedPdfPage[] = [];

    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      let canvas: HTMLCanvasElement | undefined;
      try {
        const viewport = page.getViewport({ scale: 1.25 });
        validatePdfPageDimensions(viewport.width, viewport.height);
        canvas = window.document.createElement("canvas");
        const context = canvas.getContext("2d");

        if (!context) {
          throw new PdfPreviewError("unreadable");
        }

        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        await page.render({ canvas, canvasContext: context, viewport }).promise;

        const blob = await canvasToBlob(canvas);
        if (blob.size > MAX_RENDERED_PAGE_BYTES) {
          throw new PdfPreviewError("page-too-large");
        }
        const previewUrl = URL.createObjectURL(blob);
        previewUrls.push(previewUrl);
        pages.push({
          id: crypto.randomUUID(),
          originalPageNumber: pageNumber,
          previewUrl,
        });
      } finally {
        page.cleanup();
        if (canvas) {
          canvas.width = 0;
          canvas.height = 0;
        }
      }
    }

    return pages;
  } catch (error) {
    previewUrls.forEach((previewUrl) => URL.revokeObjectURL(previewUrl));
    throw normalizePdfError(error);
  } finally {
    if (openedPdf) {
      await safelyDestroy(openedPdf.destroy);
    }
  }
}
