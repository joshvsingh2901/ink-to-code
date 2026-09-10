import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  hasPdfSignature,
  openValidatedPdf,
  PdfPreviewError,
  validatePdfPageDimensions,
} from "../lib/pdf.ts";

function minimalPdf(): Uint8Array {
  const objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> /Contents 4 0 R >>\nendobj\n",
    "4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n",
  ];
  let body = "%PDF-1.4\n";
  const offsets = [0];
  for (const object of objects) {
    offsets.push(Buffer.byteLength(body, "ascii"));
    body += object;
  }
  const xrefOffset = Buffer.byteLength(body, "ascii");
  body += `xref\n0 ${objects.length + 1}\n`;
  body += "0000000000 65535 f\r\n";
  for (const offset of offsets.slice(1)) {
    body += `${offset.toString().padStart(10, "0")} 00000 n\r\n`;
  }
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`;
  body += `startxref\n${xrefOffset}\n%%EOF\n`;
  return new TextEncoder().encode(body);
}

async function expectPdfError(
  promise: Promise<unknown>,
  expectedCode: PdfPreviewError["code"],
): Promise<void> {
  await assert.rejects(promise, (error: unknown) => {
    assert.ok(error instanceof PdfPreviewError);
    assert.equal(error.code, expectedCode);
    return true;
  });
}

describe("PDF content validation", () => {
  it("accepts a valid one-page PDF through the real PDF.js parser", async () => {
    const opened = await openValidatedPdf(
      new File([minimalPdf()], "notes.pdf", { type: "application/pdf" }),
    );
    try {
      assert.equal(opened.document.numPages, 1);
    } finally {
      await opened.destroy();
    }
  });

  it("rejects arbitrary text renamed to .pdf before parser use", async () => {
    await expectPdfError(
      openValidatedPdf(
        new File(["not a pdf"], "fake.pdf", { type: "application/pdf" }),
      ),
      "invalid-signature",
    );
  });

  it("rejects a corrupt PDF that has a PDF signature", async () => {
    await expectPdfError(
      openValidatedPdf(
        new File(["%PDF-1.4\ntruncated"], "broken.pdf", {
          type: "application/pdf",
        }),
      ),
      "malformed",
    );
  });

  it("recognizes only an exact leading PDF signature", () => {
    assert.equal(hasPdfSignature(minimalPdf()), true);
    assert.equal(hasPdfSignature(new TextEncoder().encode("x%PDF-1.4")), false);
  });

  it("rejects pathological rendered dimensions before canvas allocation", () => {
    assert.throws(
      () => validatePdfPageDimensions(20_000, 20_000),
      (error: unknown) =>
        error instanceof PdfPreviewError && error.code === "page-too-large",
    );
  });
});
