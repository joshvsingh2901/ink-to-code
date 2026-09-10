import { it, describe } from "node:test";
import assert from "node:assert/strict";

import {
  MAX_PAGE_COUNT,
  MAX_IMAGE_SIZE,
  MAX_SECTION_SIZE,
  ACCEPTED_IMAGE_TYPES,
  getPdfErrorMessage,
  isSameFile,
  isPdfFile,
  validateNewImage,
  validatePdfFile,
  acceptImageFiles,
} from "../lib/questionUpload.ts";

function makeImageFile(
  name: string,
  size: number,
  type = "image/png",
): File {
  return new File([new Uint8Array(size)], name, { type });
}

describe("validateNewImage", () => {
  it("rejects a non-accepted MIME type", () => {
    const file = makeImageFile("scan.gif", 1024, "image/gif");
    const result = validateNewImage(file, []);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /unsupported file type/);
    }
  });

  it("accepts every type in ACCEPTED_IMAGE_TYPES", () => {
    for (const type of ACCEPTED_IMAGE_TYPES) {
      const file = makeImageFile("page.img", 1024, type);
      const result = validateNewImage(file, []);
      assert.equal(result.ok, true, `expected ${type} to be accepted`);
    }
  });

  it("enforces the per-image size cap", () => {
    const file = makeImageFile("big.png", MAX_IMAGE_SIZE + 1);
    const result = validateNewImage(file, []);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /10 MB or smaller/);
    }
  });

  it("enforces the page-count cap at MAX_PAGE_COUNT", () => {
    const existing = Array.from({ length: MAX_PAGE_COUNT }, (_, index) => ({
      file: makeImageFile(`existing-${index}.png`, 1024),
    }));
    const file = makeImageFile("one-too-many.png", 1024);
    const result = validateNewImage(file, existing);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /maximum of 5 images/);
    }
  });

  it("enforces the section size cap", () => {
    const existing = [{ file: makeImageFile("existing.png", MAX_SECTION_SIZE - 100) }];
    const file = makeImageFile("pushes-over.png", 200);
    const result = validateNewImage(file, existing);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /50 MB section limit/);
    }
  });

  it("rejects a duplicate of an already-added file", () => {
    const original = makeImageFile("dup.png", 1024);
    const result = validateNewImage(original, [{ file: original }]);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /already been added/);
    }
  });
});

describe("validatePdfFile", () => {
  it("rejects a PDF over the size cap", () => {
    const file = new File([new Uint8Array(10)], "big.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(file, "size", { value: 50 * 1024 * 1024 + 1 });
    const result = validatePdfFile(file);
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.match(result.reason, /50 MB or smaller/);
    }
  });

  it("accepts a PDF within the size cap", () => {
    const file = new File([new Uint8Array(10)], "small.pdf", {
      type: "application/pdf",
    });
    assert.equal(validatePdfFile(file).ok, true);
  });
});

describe("getPdfErrorMessage", () => {
  it("maps content and dimension failures without parser internals", () => {
    assert.match(
      getPdfErrorMessage({ code: "invalid-signature" }),
      /not a valid PDF/,
    );
    assert.match(getPdfErrorMessage({ code: "malformed" }), /damaged or incomplete/);
    assert.match(getPdfErrorMessage({ code: "page-too-large" }), /too large/);
  });
});

describe("isPdfFile / isSameFile", () => {
  it("identifies PDFs by MIME type or extension", () => {
    assert.equal(
      isPdfFile(new File([], "a.pdf", { type: "application/pdf" })),
      true,
    );
    assert.equal(isPdfFile(new File([], "a.PDF", { type: "" })), true);
    assert.equal(isPdfFile(makeImageFile("a.png", 10)), false);
  });

  it("treats two files with the same name/size/lastModified as the same file", () => {
    const a = makeImageFile("same.png", 100);
    const b = makeImageFile("same.png", 100);
    assert.equal(isSameFile(a, b), true);
  });
});

describe("acceptImageFiles", () => {
  it("a valid multi-image selection produces images-mode pages", () => {
    const files = [
      makeImageFile("page1.png", 1024),
      makeImageFile("page2.jpg", 1024, "image/jpeg"),
    ];
    const { pages, errors } = acceptImageFiles(files, []);
    assert.equal(errors.length, 0);
    assert.equal(pages.length, 2);
    for (const page of pages) {
      assert.equal(page.kind, "image");
      assert.ok(page.id);
      assert.ok(page.previewUrl);
    }
    const uploadState = { mode: "images" as const, pages };
    assert.equal(uploadState.mode, "images");
  });

  it("collects an error per rejected file while still accepting the valid ones", () => {
    const files = [
      makeImageFile("ok.png", 1024),
      makeImageFile("too-big.png", MAX_IMAGE_SIZE + 1),
    ];
    const { pages, errors } = acceptImageFiles(files, []);
    assert.equal(pages.length, 1);
    assert.equal(errors.length, 1);
  });

  it("stops accepting once the page-count cap is reached", () => {
    const files = Array.from({ length: MAX_PAGE_COUNT + 2 }, (_, index) =>
      makeImageFile(`page-${index}.png`, 1024),
    );
    const { pages, errors } = acceptImageFiles(files, []);
    assert.equal(pages.length, MAX_PAGE_COUNT);
    assert.equal(errors.length, 2);
  });
});
