from __future__ import annotations

import base64
import binascii
import logging
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from config import Settings
from .models import (
    IMAGE_DERIVED_DIR,
    IMAGE_FILE_URL_PREFIX,
    IMAGE_OUTPUTS_DIR,
    IMAGE_REFERENCES_DIR,
    IMAGE_THUMBNAIL_MAX_SIDE_PX,
    IMAGE_THUMBNAIL_SUFFIX,
    ImageData,
    ImageGenerationResponse,
    ImageReferenceData,
    ImageReferenceInput,
    _image_error,
)
from .validation import _base64_from_data_url, _extension_from_mime, _safe_original_file_name

logger = logging.getLogger(__name__)


@dataclass
class ImageStorageContext:
    task_dir: str | None = None
    output_index: int = 0
    reference_index: int = 0
    direct_uuid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def resolve_task_dir(self, created: int) -> str:
        if self.task_dir is None:
            self.task_dir = f"{_image_date_dir(created)}/direct-{created}-{self.direct_uuid}"
        return self.task_dir



def _image_output_dir(settings: Settings) -> Path:
    output_dir = settings.image_output_dir or settings.db_path.parent / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    return output_dir


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def is_image_thumbnail_filename(filename: str) -> bool:
    return Path(filename).name.endswith(IMAGE_THUMBNAIL_SUFFIX)


def image_thumbnail_filename(filename: str) -> str:
    path = Path(filename)
    return f"{path.stem}{IMAGE_THUMBNAIL_SUFFIX}"


def _image_file_url(file_name: str) -> str:
    return f"{IMAGE_FILE_URL_PREFIX}/{file_name}"


def _image_date_dir(created: int) -> str:
    return time.strftime("%Y/%m/%d", time.gmtime(created))


def _image_job_task_dir(job_id: str, created: int) -> str:
    return f"{_image_date_dir(created)}/{job_id}"


def _image_path_parts(file_path: str) -> list[str]:
    if not file_path or file_path.startswith("/") or "\\" in file_path:
        raise ValueError("Invalid image filename")
    parts = file_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid image filename")
    if len(parts) not in {5, 6}:
        raise ValueError("Invalid image filename")
    year, month = parts[:2]
    if len(year) != 4 or not year.isdigit() or len(month) != 2 or not month.isdigit():
        raise ValueError("Invalid image filename")
    if len(parts) == 6:
        day = parts[2]
        if len(day) != 2 or not day.isdigit():
            raise ValueError("Invalid image filename")
    task_dir = parts[-3]
    role = parts[-2]
    filename = parts[-1]
    if not task_dir or not filename:
        raise ValueError("Invalid image filename")
    if role in {IMAGE_REFERENCES_DIR, IMAGE_OUTPUTS_DIR, IMAGE_DERIVED_DIR}:
        return parts
    raise ValueError("Invalid image filename")


def _image_file_role(file_name: str) -> str | None:
    parts = _image_path_parts(file_name)
    role = parts[-2]
    if role in {IMAGE_REFERENCES_DIR, IMAGE_OUTPUTS_DIR}:
        return role
    return None


def image_thumbnail_relative_path(file_name: str) -> str:
    thumbnail_name = image_thumbnail_filename(file_name)
    parts = _image_path_parts(file_name)
    return "/".join([*parts[:-2], IMAGE_DERIVED_DIR, thumbnail_name])


def _image_thumbnail_path(settings: Settings, file_name: str) -> Path:
    return image_file_path(settings, image_thumbnail_relative_path(file_name))


def _thumbnail_url_for_filename(settings: Settings, filename: str | None) -> str | None:
    if not filename or is_image_thumbnail_filename(filename):
        return None
    try:
        thumbnail_relative_path = image_thumbnail_relative_path(filename)
        thumbnail = image_file_path(settings, thumbnail_relative_path)
    except ValueError:
        return None
    if not thumbnail.exists() or not thumbnail.is_file():
        return None
    return _image_file_url(thumbnail_relative_path)


def _thumbnail_url_for_data(settings: Settings, data: ImageData) -> str | None:
    thumbnail_url = _thumbnail_url_for_filename(settings, data.file_name)
    return thumbnail_url or (data.thumbnail_url if not data.file_name else None)


def create_image_thumbnail(source_path: Path, thumbnail_path: Path | None = None) -> Path | None:
    if is_image_thumbnail_filename(source_path.name) or not source_path.exists() or not source_path.is_file():
        return None
    thumbnail_path = thumbnail_path or source_path.with_name(image_thumbnail_filename(source_path.name))
    _ensure_private_dir(thumbnail_path.parent)
    try:
        with Image.open(source_path) as image:
            image.thumbnail((IMAGE_THUMBNAIL_MAX_SIDE_PX, IMAGE_THUMBNAIL_MAX_SIDE_PX), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            image.save(thumbnail_path, format="WEBP", quality=82, method=6)
    except (OSError, UnidentifiedImageError) as exc:
        with suppress(OSError):
            thumbnail_path.unlink()
        logger.warning("Image thumbnail generation failed for %s: %s", source_path.name, type(exc).__name__)
        return None
    os.chmod(thumbnail_path, 0o600)
    return thumbnail_path


def image_file_metadata(path: Path) -> tuple[int | None, int | None, int | None]:
    if not path.exists() or not path.is_file():
        return None, None, None
    size_bytes = path.stat().st_size
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        width = None
        height = None
    return width, height, size_bytes


def _image_data_with_file_metadata(data: ImageData, path: Path) -> ImageData:
    width, height, size_bytes = image_file_metadata(path)
    return data.model_copy(update={"width": width, "height": height, "size_bytes": size_bytes})


def _decode_image_base64(data: ImageData) -> bytes:
    value = data.b64_json or _base64_from_data_url(data.url or "")
    if not value:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned no image bytes")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned invalid image data") from exc


def _save_image_file(
    settings: Settings,
    data: ImageData,
    created: int,
    storage_context: ImageStorageContext,
    generation_started_at: int | None = None,
    generation_completed_at: int | None = None,
) -> ImageData:
    extension = Path(data.file_name or "image.png").suffix.lstrip(".") or "png"
    storage_context.output_index += 1
    task_dir = storage_context.resolve_task_dir(created)
    filename = f"{task_dir}/{IMAGE_OUTPUTS_DIR}/o{storage_context.output_index}.{extension}"
    path = image_file_path(settings, filename)
    _ensure_private_dir(path.parent)
    path.write_bytes(_decode_image_base64(data))
    os.chmod(path, 0o600)
    thumbnail_relative_path = image_thumbnail_relative_path(filename)
    thumbnail_path = create_image_thumbnail(path, image_file_path(settings, thumbnail_relative_path))
    data = _image_data_with_file_metadata(data, path)
    if generation_started_at is not None and generation_completed_at is not None:
        data.duration_seconds = max(0, generation_completed_at - generation_started_at)
    data.file_name = filename
    data.file_url = _image_file_url(filename)
    data.thumbnail_url = _image_file_url(thumbnail_relative_path) if thumbnail_path else None
    data.saved_path = str(path)
    data.url = data.file_url
    return data


def _delete_private_file(path_value: str | None, thumbnail_path: Path | None = None) -> None:
    if not path_value:
        return
    path = Path(path_value)
    if thumbnail_path is not None:
        with suppress(OSError):
            thumbnail_path.unlink()
    with suppress(OSError):
        path.unlink()


def _delete_image_file(settings: Settings, file_name: str | None = None, path_value: str | None = None) -> None:
    path: Path | None = None
    thumbnail_path: Path | None = None
    if file_name:
        with suppress(ValueError):
            path = image_file_path(settings, file_name)
            thumbnail_path = _image_thumbnail_path(settings, file_name)
    if path is None and path_value:
        path = Path(path_value)
        thumbnail_path = path.with_name(image_thumbnail_filename(path.name))
    if path is not None:
        _delete_private_file(str(path), thumbnail_path=thumbnail_path)


def _delete_image_task_dir(settings: Settings, job_id: str, created_at: int) -> None:
    task_dir = image_file_path(settings, f"{_image_job_task_dir(job_id, created_at)}/{IMAGE_OUTPUTS_DIR}/placeholder").parents[1]
    if not task_dir.exists() or not task_dir.is_dir():
        return
    for path in sorted(task_dir.rglob("*"), reverse=True):
        if path.is_file():
            with suppress(OSError):
                path.unlink()
        elif path.is_dir():
            with suppress(OSError):
                path.rmdir()
    with suppress(OSError):
        task_dir.rmdir()


def _response_for_storage(result: ImageGenerationResponse) -> ImageGenerationResponse:
    return result.model_copy(
        update={
            "data": [
                item.model_copy(update={"b64_json": None}) if item.file_url or item.saved_path else item
                for item in result.data
            ],
            "upstream_metadata": [],
        }
    )


def image_file_path(settings: Settings, filename: str) -> Path:
    parts = _image_path_parts(filename)
    path = _image_output_dir(settings).joinpath(*parts)
    if path.parent.resolve() != _image_output_dir(settings).resolve():
        root = _image_output_dir(settings).resolve()
        if not path.parent.resolve().is_relative_to(root):
            raise ValueError("Invalid image filename")
    return path


def _reference_from_row(settings: Settings, row) -> ImageReferenceData:
    file_name = str(row["file_name"])
    return ImageReferenceData(
        id=str(row["id"]),
        file_name=file_name,
        file_url=_image_file_url(file_name),
        thumbnail_url=_thumbnail_url_for_filename(settings, file_name),
        original_file_name=str(row["original_file_name"]),
        mime_type=str(row["mime_type"]),
        size_bytes=int(row["size_bytes"]),
    )


def _save_reference_file(
    settings: Settings,
    storage_context: ImageStorageContext,
    reference: ImageReferenceInput,
    mime_type: str,
    data: bytes,
    created_at: int,
) -> ImageReferenceData:
    reference_id = uuid.uuid4().hex
    extension = _extension_from_mime(mime_type)
    storage_context.reference_index += 1
    task_dir = storage_context.resolve_task_dir(created_at)
    filename = f"{task_dir}/{IMAGE_REFERENCES_DIR}/r{storage_context.reference_index}.{extension}"
    path = image_file_path(settings, filename)
    _ensure_private_dir(path.parent)
    path.write_bytes(data)
    os.chmod(path, 0o600)
    thumbnail_relative_path = image_thumbnail_relative_path(filename)
    thumbnail_path = create_image_thumbnail(path, image_file_path(settings, thumbnail_relative_path))
    return ImageReferenceData(
        id=reference_id,
        file_name=filename,
        file_url=_image_file_url(filename),
        thumbnail_url=_image_file_url(thumbnail_relative_path) if thumbnail_path else None,
        original_file_name=_safe_original_file_name(reference.file_name),
        mime_type=mime_type,
        size_bytes=len(data),
    )
