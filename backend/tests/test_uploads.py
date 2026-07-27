import asyncio
import json
from io import BytesIO

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.uploads import (
    JPEG_SIGNATURE,
    PNG_SIGNATURE,
    UploadValidationError,
    validate_and_normalize_pages,
)

PNG_BYTES = PNG_SIGNATURE + b"synthetic-png"
JPEG_BYTES = JPEG_SIGNATURE + b"synthetic-jpeg\xff\xd9"


def upload(file_id: str, content: bytes = PNG_BYTES, mime: str = "image/png"):
    return UploadFile(
        BytesIO(content),
        filename=file_id,
        headers=Headers({"content-type": mime}),
    )


def metadata(orders: list[int], category: str = "handwritten_code"):
    return json.dumps(
        [
            {
                "file_id": f"page-{index}.png",
                "order": order,
                "category": category,
                "source_type": "image",
                "original_filename": f"original-{index}.png",
                "original_pdf_page_number": None,
            }
            for index, order in enumerate(orders, start=1)
        ]
    )


def validate(files, raw_metadata, category="handwritten_code", minimum=1):
    return asyncio.run(
        validate_and_normalize_pages(
            files,
            raw_metadata,
            category=category,
            minimum=minimum,
            maximum=5,
        )
    )


def test_accepts_one_and_five_code_pages():
    assert len(validate([upload("page-1.png")], metadata([1]))) == 1
    files = [upload(f"page-{index}.png") for index in range(1, 6)]
    assert len(validate(files, metadata([1, 2, 3, 4, 5]))) == 5


def test_accepts_optional_question_pages():
    files = [
        upload("page-1.png"),
        upload("page-2.png", JPEG_BYTES, mime="image/jpeg"),
    ]
    pages = validate(files, metadata([1, 2], "question"), "question", 0)
    assert [page.metadata.category for page in pages] == ["question", "question"]


def test_sorts_using_validated_order_not_multipart_arrival_order():
    first = PNG_BYTES + b"first"
    second = PNG_BYTES + b"second"
    files = [upload("page-1.png", first), upload("page-2.png", second)]
    pages = validate(files, metadata([2, 1]))
    assert [page.content for page in pages] == [second, first]


def test_normalizes_image_jpg_alias_to_image_jpeg():
    pages = validate(
        [upload("page-1.png", JPEG_BYTES, mime="image/jpg")], metadata([1])
    )
    assert pages[0].declared_content_type == "image/jpg"
    assert pages[0].content_type == "image/jpeg"
    assert pages[0].signature_type == "image/jpeg"


def test_rejects_malformed_and_mismatched_image_bytes():
    with pytest.raises(UploadValidationError, match="not a valid PNG or JPEG"):
        validate([upload("page-1.png", b"not-an-image")], metadata([1]))
    with pytest.raises(UploadValidationError, match="do not match"):
        validate(
            [upload("page-1.png", JPEG_BYTES, mime="image/png")], metadata([1])
        )


def test_reads_upload_once_into_reusable_immutable_bytes():
    uploaded = upload("page-1.png", PNG_BYTES)
    pages = validate([uploaded], metadata([1]))
    assert asyncio.run(uploaded.read()) == b""
    assert pages[0].content == PNG_BYTES
    assert isinstance(pages[0].content, bytes)


def test_accepts_pdf_derived_png_page():
    raw_metadata = json.dumps(
        [
            {
                "file_id": "page-1.png",
                "order": 1,
                "category": "handwritten_code",
                "source_type": "pdf",
                "original_filename": "notes.pdf",
                "original_pdf_page_number": 1,
            }
        ]
    )
    pages = validate([upload("page-1.png", PNG_BYTES)], raw_metadata)
    assert pages[0].metadata.source_type == "pdf"
    assert pages[0].content_type == "image/png"


@pytest.mark.parametrize(
    ("files", "raw_metadata"),
    [
        ([], metadata([])),
        ([upload(f"page-{index}.png") for index in range(1, 7)], metadata([1, 2, 3, 4, 5, 6])),
        ([upload("page-1.png", mime="application/pdf")], metadata([1])),
        ([upload("page-1.png", b"")], metadata([1])),
        ([upload("page-1.png"), upload("page-2.png")], metadata([1, 1])),
        ([upload("page-1.png"), upload("page-2.png")], metadata([1, 3])),
        ([upload("page-1.png")], "not-json"),
        ([upload("unexpected.png")], metadata([1])),
    ],
)
def test_rejects_invalid_uploads(files, raw_metadata):
    with pytest.raises(UploadValidationError):
        validate(files, raw_metadata)


def test_rejects_page_over_ten_mb():
    with pytest.raises(UploadValidationError, match="10 MB"):
        validate([upload("page-1.png", b"x" * (10 * 1024 * 1024 + 1))], metadata([1]))


def test_rejects_category_over_fifty_mb(monkeypatch):
    monkeypatch.setattr("app.services.uploads.MAX_PAGE_SIZE", 100)
    monkeypatch.setattr(
        "app.services.uploads.MAX_CATEGORY_SIZE", len(PNG_BYTES) * 2 - 1
    )
    files = [upload("page-1.png"), upload("page-2.png")]
    with pytest.raises(UploadValidationError, match="50 MB"):
        validate(files, metadata([1, 2]))
