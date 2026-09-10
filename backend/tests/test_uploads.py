import asyncio
import json
from io import BytesIO
import tempfile

import pytest
from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.services.uploads import (
    UploadValidationError,
    validate_and_normalize_pages,
)


def image_bytes(image_format: str, size: tuple[int, int] = (8, 8)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=(18, 52, 86)).save(buffer, format=image_format)
    return buffer.getvalue()


PNG_BYTES = image_bytes("PNG")
JPEG_BYTES = image_bytes("JPEG")


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


@pytest.mark.parametrize(
    ("content", "mime", "expected_type"),
    [
        (PNG_BYTES, "image/png", "image/png"),
        (JPEG_BYTES, "image/jpeg", "image/jpeg"),
    ],
)
def test_accepts_fully_parsed_png_and_jpeg(content, mime, expected_type):
    pages = validate([upload("page-1.png", content, mime)], metadata([1]))
    assert pages[0].content_type == expected_type


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


def test_rejects_fake_jpeg_and_mismatched_image_bytes():
    with pytest.raises(UploadValidationError) as fake_error:
        validate(
            [upload("page-1.png", b"arbitrary text", "image/jpeg")],
            metadata([1]),
        )
    assert fake_error.value.code == "upload_content_mismatch"

    with pytest.raises(UploadValidationError) as mismatch_error:
        validate(
            [upload("page-1.png", JPEG_BYTES, mime="image/png")], metadata([1])
        )
    assert mismatch_error.value.code == "upload_content_mismatch"


@pytest.mark.parametrize("content", [PNG_BYTES[:32], JPEG_BYTES[:24]])
def test_rejects_truncated_images_after_magic_byte_check(content):
    mime = "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"
    with pytest.raises(UploadValidationError) as error:
        validate([upload("page-1.png", content, mime)], metadata([1]))
    assert error.value.code == "malformed_image"


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


def test_rejects_original_pdf_bytes_at_backend_boundary():
    with pytest.raises(UploadValidationError) as error:
        validate(
            [upload("page-1.png", b"%PDF-1.7\n%%EOF", "application/pdf")],
            metadata([1]),
        )
    assert error.value.code == "unsupported_file_type"


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


def test_rejects_excessive_decoded_pixel_count(monkeypatch):
    monkeypatch.setattr("app.services.uploads.MAX_IMAGE_PIXELS", 100)
    content = image_bytes("PNG", (11, 10))
    with pytest.raises(UploadValidationError) as error:
        validate([upload("page-1.png", content)], metadata([1]))
    assert error.value.code == "image_dimensions_too_large"


@pytest.mark.parametrize(
    "unsafe_name",
    ["../../secret.png", "../foo.png", "/absolute/path.png", "..\\foo.png"],
)
def test_rejects_path_like_multipart_filenames(unsafe_name):
    with pytest.raises(UploadValidationError) as error:
        validate([upload(unsafe_name)], metadata([1]))
    assert error.value.code == "unsafe_filename"


def test_rejects_path_like_original_display_filename():
    raw_metadata = json.dumps(
        [
            {
                "file_id": "page-1.png",
                "order": 1,
                "category": "handwritten_code",
                "source_type": "image",
                "original_filename": "foo/../../bar.png",
                "original_pdf_page_number": None,
            }
        ]
    )
    with pytest.raises(UploadValidationError) as error:
        validate([upload("page-1.png")], raw_metadata)
    assert error.value.code == "invalid_upload_metadata"


def test_upload_filename_is_never_used_as_a_temp_path(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    pages = validate(
        [upload("client-page-id.png")],
        metadata([1]).replace("page-1.png", "client-page-id.png"),
    )
    assert len(pages) == 1
    assert list(tmp_path.iterdir()) == []


class FailingReadFile(BytesIO):
    def read(self, *_args, **_kwargs):
        raise OSError("simulated read failure")


def test_read_failure_returns_corrupt_upload_without_parser_details():
    uploaded = UploadFile(
        FailingReadFile(PNG_BYTES),
        filename="page-1.png",
        headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(UploadValidationError) as error:
        validate([uploaded], metadata([1]))
    assert error.value.code == "corrupt_upload"
    assert "simulated" not in error.value.message
