from __future__ import annotations

import base64
import binascii
from pathlib import Path

from config import Settings
from .models import (
    ALLOWED_IMAGE_COUNTS,
    ALLOWED_IMAGE_QUALITIES,
    ALLOWED_IMAGE_RESPONSE_FORMATS,
    ALLOWED_IMAGE_SIZES,
    ALLOWED_REFERENCE_MIME_TYPES,
    IMAGE_MAX_ASPECT_RATIO,
    IMAGE_MAX_SIDE_PX,
    IMAGE_MAX_TOTAL_PIXELS,
    IMAGE_MIN_TOTAL_PIXELS,
    IMAGE_SIZE_MULTIPLE_PX,
    MAX_REFERENCE_IMAGE_BYTES,
    MAX_REFERENCE_IMAGES,
    ImageGenerationRequest,
    ImageReferenceInput,
    _image_error,
)

def _base64_from_data_url(value: str) -> str | None:
    prefix, separator, data = value.partition(",")
    if separator and prefix.startswith("data:image/") and ";base64" in prefix:
        return data
    return None


def _normalized_base64(value: str) -> str:
    return _base64_from_data_url(value) or value


def _detect_reference_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _extension_from_mime(mime_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get(mime_type, "png")


def _safe_original_file_name(value: str) -> str:
    name = Path(value).name.strip()
    return name or "reference-image"


def _decode_reference_image(reference: ImageReferenceInput) -> tuple[str, bytes]:
    if reference.mime_type not in ALLOWED_REFERENCE_MIME_TYPES:
        raise _image_error(400, "IMAGE_REFERENCE_UNSUPPORTED_TYPE", "Reference image type is not supported")
    try:
        data = base64.b64decode(_normalized_base64(reference.b64_json), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _image_error(400, "IMAGE_REFERENCE_INVALID", "Reference image data is invalid") from exc
    if len(data) > MAX_REFERENCE_IMAGE_BYTES:
        raise _image_error(400, "IMAGE_REFERENCE_TOO_LARGE", "Reference image is too large")
    detected_mime = _detect_reference_mime(data)
    if detected_mime is None or detected_mime != reference.mime_type:
        raise _image_error(400, "IMAGE_REFERENCE_UNSUPPORTED_TYPE", "Reference image type is not supported")
    return detected_mime, data


def _validated_reference_images(payload: ImageGenerationRequest) -> list[tuple[ImageReferenceInput, str, bytes]]:
    if len(payload.reference_images) > MAX_REFERENCE_IMAGES:
        raise _image_error(400, "IMAGE_REFERENCE_TOO_MANY", "Too many reference images")
    return [
        (reference, mime_type, data)
        for reference in payload.reference_images
        for mime_type, data in [_decode_reference_image(reference)]
    ]


def _parse_image_size(value: str) -> tuple[int, int] | None:
    width_text, separator, height_text = value.partition("x")
    if not separator:
        return None
    try:
        width = int(width_text)
        height = int(height_text)
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _image_size_satisfies_constraints(value: str) -> bool:
    dimensions = _parse_image_size(value)
    if dimensions is None:
        return False
    width, height = dimensions
    long_side = max(width, height)
    short_side = min(width, height)
    total_pixels = width * height
    return (
        long_side <= IMAGE_MAX_SIDE_PX
        and width % IMAGE_SIZE_MULTIPLE_PX == 0
        and height % IMAGE_SIZE_MULTIPLE_PX == 0
        and long_side <= short_side * IMAGE_MAX_ASPECT_RATIO
        and IMAGE_MIN_TOTAL_PIXELS <= total_pixels <= IMAGE_MAX_TOTAL_PIXELS
    )


def _validate_payload(settings: Settings, payload: ImageGenerationRequest) -> None:
    prompt = payload.prompt.strip()
    if not prompt:
        raise _image_error(400, "IMAGE_PROMPT_REQUIRED", "Prompt is required")
    if len(prompt) > settings.image_max_prompt_chars:
        raise _image_error(400, "IMAGE_PROMPT_TOO_LONG", "Prompt is too long")
    if not _image_size_satisfies_constraints(payload.size) or payload.size not in ALLOWED_IMAGE_SIZES:
        raise _image_error(400, "IMAGE_INVALID_SIZE", "Invalid image size")
    if payload.quality not in ALLOWED_IMAGE_QUALITIES:
        raise _image_error(400, "IMAGE_INVALID_QUALITY", "Invalid image quality")
    if payload.n not in ALLOWED_IMAGE_COUNTS:
        raise _image_error(400, "IMAGE_INVALID_COUNT", "Invalid image count")
    if payload.response_format not in ALLOWED_IMAGE_RESPONSE_FORMATS:
        raise _image_error(400, "IMAGE_INVALID_RESPONSE_FORMAT", "Invalid image response format")
    _validated_reference_images(payload)
