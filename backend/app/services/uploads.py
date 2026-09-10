from dataclasses import dataclass
from io import BytesIO
import warnings

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import TypeAdapter, ValidationError

from app.schemas.transcription import PageCategory, PageMetadata

MAX_PAGE_SIZE = 10 * 1024 * 1024
MAX_CATEGORY_SIZE = 50 * 1024 * 1024
ACCEPTED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
MAX_IMAGE_DIMENSION = 16_384
MAX_IMAGE_PIXELS = 50_000_000


class UploadValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def validate_image_content(content: bytes, page_order: int) -> str:
    """Fully parse one image in memory and return its canonical MIME type."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                image_format = (image.format or "").upper()
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise UploadValidationError(
                        "image_dimensions_too_large",
                        f"Page {page_order} has image dimensions that are too large.",
                    )
                if image_format not in {"PNG", "JPEG"}:
                    raise UploadValidationError(
                        "unsupported_file_type",
                        f"Page {page_order} is not a supported PNG or JPEG image.",
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise UploadValidationError(
                        "unsupported_file_type",
                        f"Page {page_order} must be a single-frame image.",
                    )
                image.load()
    except UploadValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise UploadValidationError(
            "image_dimensions_too_large",
            f"Page {page_order} has image dimensions that are too large.",
        ) from error
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise UploadValidationError(
            "malformed_image",
            f"Page {page_order} is damaged or is not a complete image.",
        ) from error

    return "image/png" if image_format == "PNG" else "image/jpeg"


def parse_metadata(raw_metadata: str, category: PageCategory) -> list[PageMetadata]:
    try:
        metadata = TypeAdapter(list[PageMetadata]).validate_json(raw_metadata)
    except ValidationError as error:
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Page metadata is malformed.",
        ) from error

    if any(item.category != category for item in metadata):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Page metadata contains the wrong category.",
        )
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
            "invalid_page_count",
            f"{category.replace('_', ' ').title()} requires between "
            f"{minimum} and {maximum} pages."
        )

    metadata = parse_metadata(raw_metadata, category)
    if len(metadata) != len(files):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Every file must have exactly one metadata entry.",
        )

    file_ids = [item.file_id for item in metadata]
    if len(set(file_ids)) != len(file_ids):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Metadata contains duplicate file identifiers.",
        )

    orders = [item.order for item in metadata]
    if len(set(orders)) != len(orders):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Page order values must not contain duplicates.",
        )
    if sorted(orders) != list(range(1, len(metadata) + 1)):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Page order must begin at 1 and be contiguous.",
        )

    uploaded_by_id: dict[str, UploadFile] = {}
    for upload in files:
        if not upload.filename:
            raise UploadValidationError(
                "unsafe_filename",
                "Every uploaded page requires a safe file identifier.",
            )
        if (
            upload.filename in {".", ".."}
            or "/" in upload.filename
            or "\\" in upload.filename
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in upload.filename
            )
        ):
            raise UploadValidationError(
                "unsafe_filename",
                "Uploaded file identifiers must not contain paths.",
            )
        if upload.filename in uploaded_by_id:
            raise UploadValidationError(
                "invalid_upload_metadata",
                "Uploaded files contain duplicate identifiers.",
            )
        uploaded_by_id[upload.filename] = upload

    if set(uploaded_by_id) != set(file_ids):
        raise UploadValidationError(
            "invalid_upload_metadata",
            "Uploaded files and metadata do not match.",
        )

    normalized: list[NormalizedPage] = []
    total_size = 0
    for item in sorted(metadata, key=lambda page: page.order):
        upload = uploaded_by_id[item.file_id]
        declared_content_type = (upload.content_type or "").strip().lower()
        if declared_content_type not in ACCEPTED_CONTENT_TYPES:
            raise UploadValidationError(
                "unsupported_file_type",
                f"Page {item.order} has an unsupported content type."
            )
        content_type = normalize_content_type(declared_content_type)

        try:
            content = await upload.read(MAX_PAGE_SIZE + 1)
        except (OSError, ValueError) as error:
            raise UploadValidationError(
                "corrupt_upload",
                f"Page {item.order} could not be read.",
            ) from error
        if not content:
            raise UploadValidationError(
                "corrupt_upload",
                f"Page {item.order} is empty.",
            )
        if len(content) > MAX_PAGE_SIZE:
            raise UploadValidationError(
                "upload_too_large",
                f"Page {item.order} exceeds 10 MB.",
            )

        signature_type = detect_image_signature(content)
        if signature_type is None:
            raise UploadValidationError(
                "upload_content_mismatch",
                f"Page {item.order} does not contain PNG or JPEG image data.",
            )
        if signature_type != content_type:
            raise UploadValidationError(
                "upload_content_mismatch",
                f"Page {item.order} image bytes do not match its declared content type."
            )
        parsed_content_type = validate_image_content(content, item.order)
        if parsed_content_type != signature_type:
            raise UploadValidationError(
                "upload_content_mismatch",
                f"Page {item.order} image content is inconsistent.",
            )

        total_size += len(content)
        if total_size > MAX_CATEGORY_SIZE:
            raise UploadValidationError(
                "upload_too_large",
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
