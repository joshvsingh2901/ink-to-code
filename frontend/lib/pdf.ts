const MAX_PDF_PAGES = 5;

export type RenderedPdfPage = {
  id: string;
  originalPageNumber: number;
  previewUrl: string;
};

export type PdfErrorCode =
  | "encrypted"
  | "empty"
  | "too-many-pages"
  | "unsupported-environment"
  | "unreadable";

export class PdfPreviewError extends Error {
  constructor(public readonly code: PdfErrorCode) {
    super(code);
    this.name = "PdfPreviewError";
  }
}

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

export async function renderPdfPages(file: File): Promise<RenderedPdfPage[]> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
    import.meta.url,
  ).toString();

  const loadingTask = pdfjs.getDocument({ data: await file.arrayBuffer() });
  const previewUrls: string[] = [];

  try {
    const document = await loadingTask.promise;

    if (document.numPages === 0) {
      throw new PdfPreviewError("empty");
    }

    if (document.numPages > MAX_PDF_PAGES) {
      throw new PdfPreviewError("too-many-pages");
    }

    const pages: RenderedPdfPage[] = [];

    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const viewport = page.getViewport({ scale: 1.25 });
      const canvas = window.document.createElement("canvas");
      const context = canvas.getContext("2d");

      if (!context) {
        throw new PdfPreviewError("unreadable");
      }

      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await page.render({ canvas, canvasContext: context, viewport }).promise;

      const previewUrl = URL.createObjectURL(await canvasToBlob(canvas));
      previewUrls.push(previewUrl);
      pages.push({
        id: crypto.randomUUID(),
        originalPageNumber: pageNumber,
        previewUrl,
      });
      page.cleanup();
      canvas.width = 0;
      canvas.height = 0;
    }

    await loadingTask.destroy();
    return pages;
  } catch (error) {
    if (process.env.NODE_ENV === "development") {
      console.error("PDF processing failed:", error);
    }

    previewUrls.forEach((previewUrl) => URL.revokeObjectURL(previewUrl));
    await loadingTask.destroy();

    if (error instanceof PdfPreviewError) {
      throw error;
    }

    if (isBrowserCompatibilityError(error)) {
      throw new PdfPreviewError("unsupported-environment");
    }

    if (
      error instanceof pdfjs.PasswordException ||
      (error instanceof Error && error.name === "PasswordException")
    ) {
      throw new PdfPreviewError("encrypted");
    }

    throw new PdfPreviewError("unreadable");
  }
}
