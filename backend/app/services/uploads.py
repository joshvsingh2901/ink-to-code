from dataclasses import dataclass

from fastapi import UploadFile
from pydantic import TypeAdapter, ValidationError

from app.schemas.transcription import PageCategory, PageMetadata

MAX_PAGE_SIZE = 10 * 1024 * 1024
MAX_CATEGORY_SIZE = 50 * 1024 * 1024
ACCEPTED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedPage:
    metadata: PageMetadata
    content: bytes
    content_type: str
    declared_content_type: str | None = None
    signature_type: str | None = None


def normalize_content_type(content_type: str) -> str:
    normalized = content_type.strip().lower()
    return "image/jpeg" if normalized == "image/jpg" else normalized


def detect_image_signature(content: bytes) -> str | None:
    if content.startswith(PNG_SIGNATURE):
        return "image/png"
    if content.startswith(JPEG_SIGNATURE):
        return "image/jpeg"
    return None


def parse_metadata(raw_metadata: str, category: PageCategory) -> list[PageMetadata]:
    try:
        metadata = TypeAdapter(list[PageMetadata]).validate_json(raw_metadata)
    except ValidationError as error:
        raise UploadValidationError("Page metadata is malformed.") from error

    if any(item.category != category for item in metadata):
        raise UploadValidationError("Page metadata contains the wrong category.")
    return metadata


async def validate_and_normalize_pages(
    files: list[UploadFile],
    raw_metadata: str,
    *,
    category: PageCategory,
    minimum: int,
    maximum: int,
) -> list[NormalizedPage]:
    if not minimum <= len(files) <= maximum:
        raise UploadValidationError(
            f"{category.replace('_', ' ').title()} requires between "
            f"{minimum} and {maximum} pages."
        )

    metadata = parse_metadata(raw_metadata, category)
    if len(metadata) != len(files):
        raise UploadValidationError("Every file must have exactly one metadata entry.")

    file_ids = [item.file_id for item in metadata]
    if len(set(file_ids)) != len(file_ids):
        raise UploadValidationError("Metadata contains duplicate file identifiers.")

    orders = [item.order for item in metadata]
    if len(set(orders)) != len(orders):
        raise UploadValidationError("Page order values must not contain duplicates.")
    if sorted(orders) != list(range(1, len(metadata) + 1)):
        raise UploadValidationError("Page order must begin at 1 and be contiguous.")

    uploaded_by_id: dict[str, UploadFile] = {}
    for upload in files:
        if not upload.filename:
            raise UploadValidationError("Every uploaded page requires a file identifier.")
        if upload.filename in uploaded_by_id:
            raise UploadValidationError("Uploaded files contain duplicate identifiers.")
        uploaded_by_id[upload.filename] = upload

    if set(uploaded_by_id) != set(file_ids):
        raise UploadValidationError("Uploaded files and metadata do not match.")

    normalized: list[NormalizedPage] = []
    total_size = 0
    for item in sorted(metadata, key=lambda page: page.order):
        upload = uploaded_by_id[item.file_id]
        declared_content_type = (upload.content_type or "").strip().lower()
        if declared_content_type not in ACCEPTED_CONTENT_TYPES:
            raise UploadValidationError(
                f"Page {item.order} has an unsupported content type."
            )
        content_type = normalize_content_type(declared_content_type)

        content = await upload.read(MAX_PAGE_SIZE + 1)
        if not content:
            raise UploadValidationError(f"Page {item.order} is empty.")
        if len(content) > MAX_PAGE_SIZE:
            raise UploadValidationError(f"Page {item.order} exceeds 10 MB.")

        signature_type = detect_image_signature(content)
        if signature_type is None:
            raise UploadValidationError(
                f"Page {item.order} is not a valid PNG or JPEG image."
            )
        if signature_type != content_type:
            raise UploadValidationError(
                f"Page {item.order} image bytes do not match its declared content type."
            )

        total_size += len(content)
        if total_size > MAX_CATEGORY_SIZE:
            raise UploadValidationError(
                f"{category.replace('_', ' ').title()} pages exceed 50 MB total."
            )

        normalized.append(
            NormalizedPage(
                metadata=item,
                content=content,
                content_type=content_type,
                declared_content_type=declared_content_type,
                signature_type=signature_type,
            )
        )

    return normalized
