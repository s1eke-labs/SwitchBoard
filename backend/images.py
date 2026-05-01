from __future__ import annotations

import asyncio
import json
import base64
import binascii
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from contextlib import suppress
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from codex_files import auth_tokens, current_auth_path, read_json
from config import Settings
from db import connect, init_db
from issues import IssueDetail, issue_detail

logger = logging.getLogger(__name__)
CODEX_USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
CODEX_ORIGINATOR = "codex-tui"

ImageSize = Literal[
    "1024x1024",
    "1536x1536",
    "2880x2880",
    "768x1024",
    "1536x2048",
    "2448x3264",
    "1024x768",
    "2048x1536",
    "3264x2448",
    "720x1280",
    "1152x2048",
    "2160x3840",
    "1280x720",
    "2048x1152",
    "3840x2160",
    "1344x576",
    "2688x1152",
    "3360x1440",
]
ImageQuality = Literal["auto"]
ImageResponseFormat = Literal["b64_json", "url"]
ImageJobStatus = Literal["queued", "running", "succeeded", "failed"]

ALLOWED_IMAGE_SIZES = {
    "1024x1024",
    "1536x1536",
    "2880x2880",
    "768x1024",
    "1536x2048",
    "2448x3264",
    "1024x768",
    "2048x1536",
    "3264x2448",
    "720x1280",
    "1152x2048",
    "2160x3840",
    "1280x720",
    "2048x1152",
    "3840x2160",
    "1344x576",
    "2688x1152",
    "3360x1440",
}
IMAGE_MAX_SIDE_PX = 3840
IMAGE_SIZE_MULTIPLE_PX = 16
IMAGE_MAX_ASPECT_RATIO = 3
IMAGE_MIN_TOTAL_PIXELS = 655_360
IMAGE_MAX_TOTAL_PIXELS = 8_294_400
ALLOWED_IMAGE_QUALITIES = {"auto"}
ALLOWED_IMAGE_COUNTS = {1, 2, 4}
ALLOWED_IMAGE_RESPONSE_FORMATS = {"b64_json", "url"}
MAX_REFERENCE_IMAGES = 4
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_GENERATION_INSTRUCTIONS = "Use the image_generation tool to create an image from the user's prompt."
IMAGE_THUMBNAIL_MAX_SIDE_PX = 512
IMAGE_THUMBNAIL_SUFFIX = ".thumb.webp"
IMAGE_REFERENCES_DIR = "references"
IMAGE_OUTPUTS_DIR = "outputs"
IMAGE_DERIVED_DIR = "derived"
IMAGE_FILE_URL_PREFIX = "/api/images/files"


class ImageReferenceInput(BaseModel):
    file_name: str
    mime_type: str
    b64_json: str


class ImageReferenceData(BaseModel):
    id: str
    file_name: str
    file_url: str
    thumbnail_url: str | None = None
    original_file_name: str
    mime_type: str
    size_bytes: int


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: str | None = None
    size: str = "1024x1024"
    quality: str = "auto"
    n: int = 1
    response_format: str = "b64_json"
    reference_images: list[ImageReferenceInput] = Field(default_factory=list)
    conversation_id: str | None = None
    previous_response_id: str | None = None


class ImageData(BaseModel):
    b64_json: str | None = None
    url: str | None = None
    revised_prompt: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None
    saved_path: str | None = None


class ImageGenerationResponse(BaseModel):
    created: int
    model: str
    data: list[ImageData]
    response_id: str | None = None


class ImageGenerationJobResponse(BaseModel):
    id: str
    conversation_id: str | None = None
    prompt: str
    size: str
    quality: str
    n: int
    status: ImageJobStatus
    created_at: int
    updated_at: int
    previous_response_id: str | None = None
    upstream_response_id: str | None = None
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None


class ImageGenerationJobSummaryResponse(BaseModel):
    id: str
    conversation_id: str | None = None
    prompt: str
    size: str
    quality: str
    n: int
    status: ImageJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    error: IssueDetail | None = None


class ImageGenerationJobListResponse(BaseModel):
    items: list[ImageGenerationJobSummaryResponse]
    total_count: int


class ImageGalleryImageResponse(BaseModel):
    url: str | None = None
    revised_prompt: str | None = None
    file_name: str | None = None
    file_url: str | None = None
    thumbnail_url: str | None = None


class ImageGalleryJobResponse(BaseModel):
    id: str
    prompt: str
    size: str
    quality: str
    n: int
    status: ImageJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    error: IssueDetail | None = None


class ImageGalleryItemResponse(BaseModel):
    key: str
    job: ImageGalleryJobResponse
    image_index: int
    image: ImageGalleryImageResponse | None = None


class ImageGalleryListResponse(BaseModel):
    items: list[ImageGalleryItemResponse]
    total_count: int


class ImageGenerationError(Exception):
    def __init__(self, status_code: int, detail: IssueDetail) -> None:
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ImageStorageContext:
    task_dir: str | None = None
    output_index: int = 0
    reference_index: int = 0
    direct_uuid: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def resolve_task_dir(self, created: int) -> str:
        if self.task_dir is None:
            self.task_dir = f"{_image_month_dir(created)}/direct-{created}-{self.direct_uuid}"
        return self.task_dir


def _image_error(status_code: int, code: str, message: str) -> ImageGenerationError:
    return ImageGenerationError(status_code, issue_detail(code, message))


def _gallery_slot_count(job: ImageGenerationJobResponse) -> int:
    result_count = len(job.result.data) if job.result else 0
    if job.status in {"queued", "running"}:
        return max(job.n, result_count, 1)
    return max(result_count, 1)


def _gallery_job_from_job(job: ImageGenerationJobResponse) -> ImageGalleryJobResponse:
    return ImageGalleryJobResponse(
        id=job.id,
        prompt=job.prompt,
        size=job.size,
        quality=job.quality,
        n=job.n,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        position=job.position,
        references=job.references,
        error=job.error,
    )


def _job_summary_from_job(job: ImageGenerationJobResponse) -> ImageGenerationJobSummaryResponse:
    return ImageGenerationJobSummaryResponse(
        id=job.id,
        conversation_id=job.conversation_id,
        prompt=job.prompt,
        size=job.size,
        quality=job.quality,
        n=job.n,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        position=job.position,
        error=job.error,
    )


def _gallery_image_from_data(settings: Settings, data: ImageData | None) -> ImageGalleryImageResponse | None:
    if data is None:
        return None
    return ImageGalleryImageResponse(
        url=data.file_url or data.url,
        revised_prompt=data.revised_prompt,
        file_name=data.file_name,
        file_url=data.file_url,
        thumbnail_url=_thumbnail_url_for_data(settings, data),
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


def _responses_url(settings: Settings) -> str:
    if settings.image_responses_path.startswith(("http://", "https://")):
        return settings.image_responses_path
    return f"{settings.chatgpt_backend_base}{settings.image_responses_path}"


def _image_tool_model(settings: Settings, payload: ImageGenerationRequest) -> str:
    return payload.model or settings.image_model


def _image_generation_instructions(payload: ImageGenerationRequest) -> str:
    if payload.n == 1:
        return IMAGE_GENERATION_INSTRUCTIONS
    return f"{IMAGE_GENERATION_INSTRUCTIONS} Create exactly {payload.n} separate images."


def build_upstream_payload(settings: Settings, payload: ImageGenerationRequest) -> dict[str, object]:
    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": payload.prompt.strip(),
        }
    ]
    for reference in payload.reference_images:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{reference.mime_type};base64,{_normalized_base64(reference.b64_json)}",
            }
        )
    tool: dict[str, object] = {
        "type": "image_generation",
        "model": _image_tool_model(settings, payload),
        "size": payload.size,
        "quality": "auto",
    }
    if not payload.reference_images:
        tool["action"] = "generate"
    upstream_payload: dict[str, object] = {
        "model": settings.image_responses_model,
        "instructions": _image_generation_instructions(payload),
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "tools": [tool],
        "tool_choice": {"type": "image_generation"},
        "stream": True,
        "store": False,
    }
    if payload.previous_response_id:
        upstream_payload["previous_response_id"] = payload.previous_response_id
    return upstream_payload


def _value_for_debug(value: object) -> object:
    if isinstance(value, dict):
        if value.get("type") == "input_image" and "image_url" in value:
            return {**value, "image_url": "[image data redacted]"}
        if _is_image_generation_item(value) and "result" in value:
            return {**value, "result": "[image data redacted]"}
        return {key: _value_for_debug(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_value_for_debug(item) for item in value]
    return value


def _redact_sensitive(value: str, secrets: tuple[str | None, ...]) -> str:
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    return result


def _debug_log(settings: Settings, message: str, *args: object) -> None:
    if settings.image_debug:
        logger.warning("[image-debug] " + message, *args)


def _json_for_debug(value: object, access_token: str | None = None) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = repr(value)
    return _redact_sensitive(text, (access_token,))


def _upstream_error_message(response: httpx.Response, access_token: str) -> str:
    detail = ""
    content_type = response.headers.get("content-type", "")
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        raw_detail = payload.get("detail") or payload.get("error") or payload.get("message")
        if isinstance(raw_detail, dict):
            raw_detail = raw_detail.get("message") or raw_detail.get("code")
        if isinstance(raw_detail, str):
            detail = raw_detail
    elif isinstance(payload, str):
        detail = payload
    detail = _redact_sensitive(" ".join(detail.split()), (access_token,))[:240]
    if "text/html" in content_type.lower() or detail.lower().startswith("<html"):
        return (
            f"Image upstream returned HTTP {response.status_code} with an HTML challenge. "
            "The configured SWITCHBOARD_IMAGE_RESPONSES_PATH is likely not a bearer-token JSON endpoint."
        )
    if detail:
        return f"Image upstream returned HTTP {response.status_code}: {detail}"
    return f"Image upstream returned HTTP {response.status_code}"


def _auth_error_from_message(message: str) -> ImageGenerationError:
    if message == "auth.json does not contain ChatGPT tokens":
        return _image_error(400, "IMAGE_AUTH_TOKENS_MISSING", message)
    if message == "auth.json does not contain tokens.account_id":
        return _image_error(400, "IMAGE_AUTH_ACCOUNT_ID_MISSING", message)
    if message == "auth.json does not contain tokens.access_token":
        return _image_error(400, "IMAGE_AUTH_ACCESS_TOKEN_MISSING", message)
    return _image_error(400, "IMAGE_AUTH_INVALID", message)


def _current_auth_tokens(settings: Settings) -> tuple[str, str]:
    auth_path = current_auth_path(settings.codex_home)
    if not auth_path.exists():
        raise _image_error(400, "IMAGE_AUTH_NOT_FOUND", "Current Codex auth not found")
    try:
        auth = read_json(auth_path)
        account_id, access_token = auth_tokens(auth)
    except (OSError, ValueError) as exc:
        raise _auth_error_from_message(str(exc)) from exc
    return account_id, access_token


def _data_url_from_base64(value: str, output_format: object) -> str:
    image_format = output_format if isinstance(output_format, str) and output_format else "png"
    return f"data:image/{image_format};base64,{value}"


def _extension_from_format(output_format: object) -> str:
    image_format = output_format.lower().strip(".") if isinstance(output_format, str) else "png"
    known = {"png", "webp", "jpg", "jpeg"}
    if image_format not in known:
        return "png"
    return "jpg" if image_format == "jpeg" else image_format


def _walk_values(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _is_image_generation_item(item: dict[str, object]) -> bool:
    item_type = item.get("type")
    if item_type == "image_generation_call":
        return True
    return isinstance(item_type, str) and "image_generation" in item_type and isinstance(item.get("result"), str)


def normalize_image_generation_call(item: object, response_format: str) -> ImageData:
    if not isinstance(item, dict):
        return ImageData()
    result = item.get("result")
    if not isinstance(result, str) or not result:
        return ImageData()
    b64_json = _base64_from_data_url(result) or result
    url = result if result.startswith("data:image/") else None
    if response_format == "url" and url is None:
        url = _data_url_from_base64(b64_json, item.get("output_format"))
    revised_prompt = item.get("revised_prompt")
    output_format = item.get("output_format")
    data = ImageData(
        b64_json=b64_json,
        url=url,
        revised_prompt=revised_prompt if isinstance(revised_prompt, str) else None,
    )
    data.file_name = f"image.{_extension_from_format(output_format)}"
    return data


def _image_items_from_payloads(payloads: list[object], response_format: str) -> list[ImageData]:
    return [
        data
        for data in (
            normalize_image_generation_call(item, response_format)
            for payload in payloads
            for item in _walk_values(payload)
            if _is_image_generation_item(item)
        )
        if data.b64_json or data.url
    ]


def _sse_json_payloads(text: str) -> list[object]:
    payloads: list[object] = []
    data_lines: list[str] = []

    def flush_event() -> None:
        if not data_lines:
            return
        raw_data = "\n".join(data_lines).strip()
        data_lines.clear()
        if not raw_data or raw_data == "[DONE]":
            return
        try:
            payloads.append(json.loads(raw_data))
        except json.JSONDecodeError:
            return

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush_event()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    flush_event()
    return payloads


def _payload_from_sse_data(raw_data: str) -> object | None:
    value = raw_data.strip()
    if not value or value == "[DONE]":
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _payload_type(payload: object) -> str:
    if isinstance(payload, dict):
        item_type = payload.get("type")
        if isinstance(item_type, str):
            return item_type
        event = payload.get("event")
        if isinstance(event, str):
            return event
    return type(payload).__name__


def _payloads_from_text(text: str, settings: Settings, access_token: str) -> list[object]:
    payloads: list[object] = []
    data_lines: list[str] = []
    event_count = 0
    saw_sse_data = False

    def flush_event() -> None:
        nonlocal event_count
        if not data_lines:
            return
        raw_data = "\n".join(data_lines).strip()
        data_lines.clear()
        if raw_data == "[DONE]":
            _debug_log(settings, "sse done events=%s", event_count)
            return
        parsed = _payload_from_sse_data(raw_data)
        if parsed is None:
            _debug_log(settings, "sse ignored data=%s", _redact_sensitive(raw_data, (access_token,)))
            return
        event_count += 1
        payloads.append(parsed)
        _debug_log(
            settings,
            "sse event #%s type=%s payload=%s",
            event_count,
            _payload_type(parsed),
            _json_for_debug(_value_for_debug(parsed), access_token),
        )

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if not line:
            flush_event()
            continue
        if line.startswith("data:"):
            saw_sse_data = True
            data_lines.append(line[5:].lstrip())
    flush_event()
    if saw_sse_data:
        _debug_log(settings, "sse stream closed events=%s", event_count)
        return payloads
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        _debug_log(settings, "non-json response body=%s", _redact_sensitive(text, (access_token,)))
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned invalid JSON") from exc
    return [payload]


async def _payloads_from_streaming_response(
    response: httpx.Response,
    settings: Settings,
    access_token: str,
    on_payload: Callable[[object], Awaitable[None]] | None = None,
) -> list[object]:
    chunks: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        chunks.append(line)
        if line.startswith("data:"):
            payload = _payload_from_sse_data(line[5:].lstrip())
            if payload is None:
                _debug_log(settings, "sse line data=%s", _redact_sensitive(line[5:].lstrip(), (access_token,)))
            else:
                _debug_log(
                    settings,
                    "sse line type=%s payload=%s",
                    _payload_type(payload),
                    _json_for_debug(_value_for_debug(payload), access_token),
                )
                if on_payload is not None:
                    await on_payload(payload)
    return _payloads_from_text("\n".join(chunks), settings, access_token)


def _created_from_payloads(payloads: list[object]) -> int:
    for payload in payloads:
        for item in _walk_values(payload):
            created = item.get("created")
            if isinstance(created, int):
                return created
    return int(time.time())


def _response_id_from_payloads(payloads: list[object]) -> str | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        response = payload.get("response")
        if isinstance(response, dict):
            response_id = response.get("id")
            if isinstance(response_id, str) and response_id:
                return response_id
        payload_type = payload.get("type")
        response_id = payload.get("id")
        if isinstance(payload_type, str) and payload_type.startswith("response.") and isinstance(response_id, str) and response_id:
            return response_id
    for payload in payloads:
        for item in _walk_values(payload):
            response_id = item.get("id")
            if isinstance(response_id, str) and response_id.startswith("resp_"):
                return response_id
    return None


def _failed_response_error_from_payloads(payloads: list[object]) -> IssueDetail | None:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "response.failed":
            continue
        response = payload.get("response")
        if not isinstance(response, dict):
            continue
        error = response.get("error")
        if not isinstance(error, dict):
            continue
        message = error.get("message")
        code = error.get("code")
        if isinstance(message, str) and message:
            return issue_detail("IMAGE_UPSTREAM_ERROR", message)
        if isinstance(code, str) and code:
            return issue_detail("IMAGE_UPSTREAM_ERROR", code)
    return None


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


def _image_month_dir(created: int) -> str:
    return time.strftime("%Y/%m", time.gmtime(created))


def _image_job_task_dir(job_id: str, created: int) -> str:
    return f"{_image_month_dir(created)}/{job_id}"


def _image_path_parts(file_path: str) -> list[str]:
    if not file_path or file_path.startswith("/") or "\\" in file_path:
        raise ValueError("Invalid image filename")
    parts = file_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid image filename")
    if len(parts) != 5:
        raise ValueError("Invalid image filename")
    year, month, task_dir, role, filename = parts
    if len(year) != 4 or not year.isdigit() or len(month) != 2 or not month.isdigit():
        raise ValueError("Invalid image filename")
    if not task_dir or not filename:
        raise ValueError("Invalid image filename")
    if role in {IMAGE_REFERENCES_DIR, IMAGE_OUTPUTS_DIR, IMAGE_DERIVED_DIR}:
        return parts
    raise ValueError("Invalid image filename")


def _image_file_role(file_name: str) -> str | None:
    parts = _image_path_parts(file_name)
    role = parts[3]
    if role in {IMAGE_REFERENCES_DIR, IMAGE_OUTPUTS_DIR}:
        return role
    return None


def image_thumbnail_relative_path(file_name: str) -> str:
    thumbnail_name = image_thumbnail_filename(file_name)
    parts = _image_path_parts(file_name)
    return "/".join([*parts[:3], IMAGE_DERIVED_DIR, thumbnail_name])


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
            ]
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


ImageGenerator = Callable[[Settings, ImageGenerationRequest], Awaitable[ImageGenerationResponse]]
ImageProgressCallback = Callable[[ImageGenerationResponse], Awaitable[None]]


class ImageGenerationQueue:
    def __init__(self, settings: Settings, generator: ImageGenerator | None = None) -> None:
        self._settings = settings
        self._generator = generator
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task[None] | None = None
        init_db(settings.db_path)
        self._reset_running_jobs()

    async def enqueue(self, payload: ImageGenerationRequest) -> ImageGenerationJobResponse:
        _validate_payload(self._settings, payload)
        references = _validated_reference_images(payload)
        now = int(time.time())
        job_id = uuid.uuid4().hex
        async with self._lock:
            previous_response_id = payload.previous_response_id
            storage_context = ImageStorageContext(task_dir=_image_job_task_dir(job_id, now))
            saved_references = [
                _save_reference_file(self._settings, storage_context, reference, mime_type, data, now)
                for reference, mime_type, data in references
            ]
            with connect(self._settings.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO image_jobs (
                        id, conversation_id, prompt, model, size, quality, n, response_format, status,
                        created_at, updated_at, previous_response_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                    """,
                    (
                        job_id,
                        None,
                        payload.prompt.strip(),
                        payload.model,
                        payload.size,
                        payload.quality,
                        payload.n,
                        payload.response_format,
                        now,
                        now,
                        previous_response_id,
                    ),
                )
                conn.executemany(
                    """
                    INSERT INTO image_job_references (
                        id, job_id, position, original_file_name, mime_type, size_bytes, file_name, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            reference.id,
                            job_id,
                            index,
                            reference.original_file_name,
                            reference.mime_type,
                            reference.size_bytes,
                            reference.file_name,
                            now,
                        )
                        for index, reference in enumerate(saved_references)
                    ],
                )
            self._ensure_worker_locked()
            job = self._job_response_from_db(job_id)
            if job is None:
                raise _image_error(500, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
            return job

    async def get(self, job_id: str) -> ImageGenerationJobResponse | None:
        async with self._lock:
            return self._job_response_from_db(job_id)

    async def delete_result_image(self, job_id: str, image_index: int) -> None:
        if image_index < 0:
            raise _image_error(400, "IMAGE_INVALID_INDEX", "Image index is invalid")
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
                if job is None:
                    raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
                if job["status"] in {"queued", "running"}:
                    raise _image_error(409, "IMAGE_JOB_ACTIVE", "Image generation job is still active")
                job_created_at = int(job["created_at"])
                result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
                if result is None or image_index >= len(result.data):
                    raise _image_error(404, "IMAGE_NOT_FOUND", "Image not found")
                removed = result.data.pop(image_index)
                _delete_image_file(self._settings, file_name=removed.file_name, path_value=removed.saved_path)
                if result.data:
                    conn.execute(
                        """
                        UPDATE image_jobs
                        SET result_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (result.model_dump_json(), int(time.time()), job_id),
                    )
                    return
                reference_rows = list(
                    conn.execute(
                        """
                        SELECT file_name FROM image_job_references
                        WHERE job_id = ?
                        """,
                        (job_id,),
                    )
                )
                conn.execute("DELETE FROM image_jobs WHERE id = ?", (job_id,))
            for row in reference_rows:
                _delete_image_file(self._settings, file_name=str(row["file_name"]))
            _delete_image_task_dir(self._settings, job_id, job_created_at)

    async def delete_job(self, job_id: str) -> None:
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
                if job is None:
                    raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
                if job["status"] in {"queued", "running"}:
                    raise _image_error(409, "IMAGE_JOB_ACTIVE", "Image generation job is still active")
                job_created_at = int(job["created_at"])
                result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
                reference_rows = list(
                    conn.execute(
                        """
                        SELECT file_name FROM image_job_references
                        WHERE job_id = ?
                        """,
                        (job_id,),
                    )
                )
                conn.execute("DELETE FROM image_jobs WHERE id = ?", (job_id,))
            for item in result.data if result else []:
                _delete_image_file(self._settings, file_name=item.file_name, path_value=item.saved_path)
            for row in reference_rows:
                _delete_image_file(self._settings, file_name=str(row["file_name"]))
            _delete_image_task_dir(self._settings, job_id, job_created_at)

    async def list_recent(self, page: int = 1, limit: int = 20) -> ImageGenerationJobListResponse:
        if page < 1:
            raise _image_error(400, "IMAGE_JOB_INVALID_PAGE", "Image job page is invalid")
        async with self._lock:
            offset = (page - 1) * limit
            with connect(self._settings.db_path) as conn:
                total_count = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs").fetchone()["count"])
                job_ids = [
                    str(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id FROM image_jobs
                        ORDER BY created_at DESC, rowid DESC
                        LIMIT ?
                        OFFSET ?
                        """,
                        (limit, offset),
                    )
                ]
            return ImageGenerationJobListResponse(
                items=[
                    _job_summary_from_job(job)
                    for job_id in job_ids
                    if (job := self._job_response_from_db(job_id)) is not None
                ],
                total_count=total_count,
            )

    async def list_gallery_items(self, page: int = 1, limit: int = 20) -> ImageGalleryListResponse:
        if page < 1:
            raise _image_error(400, "IMAGE_JOB_INVALID_PAGE", "Image job page is invalid")
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                job_ids = [
                    str(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id FROM image_jobs
                        ORDER BY created_at DESC, rowid DESC
                        """
                    )
                ]
            jobs = [job for job_id in job_ids if (job := self._job_response_from_db(job_id)) is not None]
            slot_counts = [_gallery_slot_count(job) for job in jobs]
            total_count = sum(slot_counts)
            start = (page - 1) * limit
            end = start + limit
            items: list[ImageGalleryItemResponse] = []
            cursor = 0
            for job, slot_count in zip(jobs, slot_counts):
                if cursor + slot_count <= start:
                    cursor += slot_count
                    continue
                gallery_job = _gallery_job_from_job(job)
                for image_index in range(slot_count):
                    absolute_index = cursor + image_index
                    if start <= absolute_index < end:
                        image = job.result.data[image_index] if job.result and image_index < len(job.result.data) else None
                        items.append(
                            ImageGalleryItemResponse(
                                key=f"{job.id}:{image_index}",
                                job=gallery_job,
                                image_index=image_index,
                                image=_gallery_image_from_data(self._settings, image),
                            )
                        )
                cursor += slot_count
                if cursor >= end:
                    break
            return ImageGalleryListResponse(items=items, total_count=total_count)

    async def close(self) -> None:
        task = self._worker_task
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def start(self) -> None:
        async with self._lock:
            self._ensure_worker_locked()

    def _ensure_worker_locked(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run())

    def _reset_running_jobs(self) -> None:
        now = int(time.time())
        try:
            with connect(self._settings.db_path) as conn:
                conn.execute(
                    """
                    UPDATE image_jobs
                    SET status = 'queued', updated_at = ?
                    WHERE status = 'running'
                    """,
                    (now,),
                )
        except sqlite3.OperationalError as exc:
            if "readonly" not in str(exc).lower():
                raise
            raise RuntimeError(
                f"SwitchBoard data directory is not writable: {self._settings.db_path.parent}. "
                "Fix the owner/permissions of SWITCHBOARD_DATA_DIR or point SWITCHBOARD_DATA_DIR "
                "to a writable directory."
            ) from exc

    def _job_response_from_db(self, job_id: str) -> ImageGenerationJobResponse | None:
        with connect(self._settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return None
            reference_rows = list(
                conn.execute(
                    """
                    SELECT * FROM image_job_references
                    WHERE job_id = ?
                    ORDER BY position ASC
                    """,
                    (job_id,),
                )
            )
            queued_rows = list(
                conn.execute(
                    """
                    SELECT id FROM image_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC, rowid ASC
                    """
                )
            )
        position = None
        if job["status"] == "queued":
            queued_ids = [str(row["id"]) for row in queued_rows]
            with suppress(ValueError):
                position = queued_ids.index(job_id) + 1
        result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
        error = IssueDetail.model_validate_json(job["error_json"]) if job["error_json"] else None
        return ImageGenerationJobResponse(
            id=str(job["id"]),
            conversation_id=str(job["conversation_id"]) if job["conversation_id"] else None,
            prompt=str(job["prompt"]),
            size=str(job["size"]),
            quality=str(job["quality"]),
            n=int(job["n"]),
            status=job["status"],
            created_at=int(job["created_at"]),
            updated_at=int(job["updated_at"]),
            previous_response_id=str(job["previous_response_id"]) if job["previous_response_id"] else None,
            upstream_response_id=str(job["upstream_response_id"]) if job["upstream_response_id"] else None,
            position=position,
            references=[_reference_from_row(self._settings, row) for row in reference_rows],
            result=result,
            error=error,
        )

    def _payload_from_job_id(self, job_id: str) -> ImageGenerationRequest:
        with connect(self._settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            reference_rows = list(
                conn.execute(
                    """
                    SELECT * FROM image_job_references
                    WHERE job_id = ?
                    ORDER BY position ASC
                    """,
                    (job_id,),
                )
            )
        if job is None:
            raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
        references = []
        for row in reference_rows:
            path = image_file_path(self._settings, str(row["file_name"]))
            references.append(
                ImageReferenceInput(
                    file_name=str(row["original_file_name"]),
                    mime_type=str(row["mime_type"]),
                    b64_json=base64.b64encode(path.read_bytes()).decode("ascii"),
                )
            )
        return ImageGenerationRequest(
            prompt=str(job["prompt"]),
            model=str(job["model"]) if job["model"] else None,
            size=str(job["size"]),
            quality=str(job["quality"]),
            n=int(job["n"]),
            response_format=str(job["response_format"]),
            reference_images=references,
            conversation_id=str(job["conversation_id"]) if job["conversation_id"] else None,
            previous_response_id=str(job["previous_response_id"]) if job["previous_response_id"] else None,
        )

    def _storage_context_from_job_id(self, job_id: str) -> ImageStorageContext:
        with connect(self._settings.db_path) as conn:
            job = conn.execute("SELECT created_at FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
        return ImageStorageContext(task_dir=_image_job_task_dir(job_id, int(job["created_at"])))

    def _claim_next_job(self) -> str | None:
        now = int(time.time())
        with connect(self._settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT id FROM image_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC, rowid ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            job_id = str(row["id"])
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'running', updated_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
            return job_id

    def _finish_job(self, job_id: str, result: ImageGenerationResponse) -> None:
        now = int(time.time())
        stored_result = _response_for_storage(result)
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'succeeded', result_json = ?, error_json = NULL,
                    upstream_response_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (stored_result.model_dump_json(), stored_result.response_id, now, job_id),
            )

    def _update_job_result(self, job_id: str, result: ImageGenerationResponse) -> None:
        now = int(time.time())
        stored_result = _response_for_storage(result)
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET result_json = ?, error_json = NULL,
                    upstream_response_id = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (stored_result.model_dump_json(), stored_result.response_id, now, job_id),
            )

    def _fail_job(self, job_id: str, detail: IssueDetail) -> None:
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'failed', error_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (detail.model_dump_json(), int(time.time()), job_id),
            )

    async def _run(self) -> None:
        while True:
            async with self._lock:
                job_id = self._claim_next_job()
                if job_id is None:
                    return
                payload = self._payload_from_job_id(job_id)
                storage_context = self._storage_context_from_job_id(job_id)

            async def update_partial_result(result: ImageGenerationResponse) -> None:
                async with self._lock:
                    self._update_job_result(job_id, result)

            try:
                if self._generator is None:
                    result = await generate_image(
                        self._settings,
                        payload,
                        progress_callback=update_partial_result,
                        storage_context=storage_context,
                    )
                else:
                    result = await self._generator(self._settings, payload)
            except ImageGenerationError as exc:
                async with self._lock:
                    self._fail_job(job_id, exc.detail)
            except Exception:
                logger.exception("Queued image generation failed")
                async with self._lock:
                    self._fail_job(job_id, issue_detail("IMAGE_UPSTREAM_ERROR", "Image generation failed"))
            else:
                async with self._lock:
                    self._finish_job(job_id, result)


def _image_data_key(data: ImageData) -> str | None:
    return data.file_url or data.saved_path or data.b64_json or data.url


async def generate_image(
    settings: Settings,
    payload: ImageGenerationRequest,
    transport: httpx.AsyncBaseTransport | None = None,
    progress_callback: ImageProgressCallback | None = None,
    storage_context: ImageStorageContext | None = None,
) -> ImageGenerationResponse:
    _validate_payload(settings, payload)
    storage_context = storage_context or ImageStorageContext()
    if payload.n == 1:
        return await _generate_image_request(
            settings,
            payload,
            transport=transport,
            progress_callback=progress_callback,
            storage_context=storage_context,
        )

    accumulated: list[ImageData] = []
    seen_data: set[str] = set()
    created = int(time.time())
    response_id: str | None = None

    def merge_result(result: ImageGenerationResponse) -> bool:
        nonlocal created, response_id
        if not accumulated:
            created = result.created
        response_id = result.response_id or response_id
        changed = False
        for item in result.data:
            data_key = _image_data_key(item)
            if not data_key or data_key in seen_data:
                continue
            seen_data.add(data_key)
            accumulated.append(item)
            changed = True
        return changed

    async def publish_progress() -> None:
        if progress_callback is None or not accumulated:
            return
        await progress_callback(
            ImageGenerationResponse(
                created=created,
                model=_image_tool_model(settings, payload),
                data=list(accumulated),
                response_id=response_id,
            )
        )

    single_payload = payload.model_copy(update={"n": 1})
    for _ in range(payload.n):
        async def single_progress(result: ImageGenerationResponse) -> None:
            if merge_result(result):
                await publish_progress()

        result = await _generate_image_request(
            settings,
            single_payload,
            transport=transport,
            progress_callback=single_progress,
            storage_context=storage_context,
        )
        if merge_result(result):
            await publish_progress()

    if not accumulated:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned no image data")
    return ImageGenerationResponse(
        created=created,
        model=_image_tool_model(settings, payload),
        data=accumulated,
        response_id=response_id,
    )


async def _generate_image_request(
    settings: Settings,
    payload: ImageGenerationRequest,
    transport: httpx.AsyncBaseTransport | None = None,
    progress_callback: ImageProgressCallback | None = None,
    storage_context: ImageStorageContext | None = None,
) -> ImageGenerationResponse:
    _validate_payload(settings, payload)
    storage_context = storage_context or ImageStorageContext()
    account_id, access_token = _current_auth_tokens(settings)
    upstream_payload = build_upstream_payload(settings, payload)
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "text/event-stream",
        "Connection": "Keep-Alive",
        "Content-Type": "application/json",
        "User-Agent": CODEX_USER_AGENT,
        "Originator": CODEX_ORIGINATOR,
        "Chatgpt-Account-Id": account_id,
        "Session_id": str(uuid.uuid4()),
    }
    _debug_log(settings, "request url=%s", _responses_url(settings))
    _debug_log(
        settings,
        "request headers=%s",
        _json_for_debug({**headers, "Authorization": "Bearer [redacted]", "Chatgpt-Account-Id": account_id}),
    )
    _debug_log(settings, "request payload=%s", _json_for_debug(_value_for_debug(upstream_payload)))

    streamed_payloads: list[object] = []
    seen_image_results: set[str] = set()
    saved_data: list[ImageData] = []

    async def handle_stream_payload(stream_payload: object) -> None:
        streamed_payloads.append(stream_payload)
        if progress_callback is None:
            return
        new_items: list[ImageData] = []
        for item in _image_items_from_payloads([stream_payload], payload.response_format):
            image_key = item.b64_json or item.url
            if not image_key or image_key in seen_image_results:
                continue
            seen_image_results.add(image_key)
            new_items.append(item)
        if not new_items:
            return
        created = _created_from_payloads(streamed_payloads)
        saved_data.extend(_save_image_file(settings, item, created, storage_context) for item in new_items)
        for item in saved_data[-len(new_items) :]:
            _debug_log(settings, "saved partial image file=%s", item.saved_path)
        await progress_callback(
            ImageGenerationResponse(
                created=created,
                model=_image_tool_model(settings, payload),
                data=list(saved_data),
                response_id=_response_id_from_payloads(streamed_payloads),
            )
        )

    timeout = httpx.Timeout(settings.image_timeout_seconds, connect=min(10.0, settings.image_timeout_seconds))
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            async with client.stream(
                "POST",
                _responses_url(settings),
                headers=headers,
                json=upstream_payload,
            ) as response:
                _debug_log(settings, "response status=%s headers=%s", response.status_code, _json_for_debug(dict(response.headers)))
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    _debug_log(settings, "response body=%s", _redact_sensitive(body, (access_token,)))
                    raise _image_error(
                        502,
                        "IMAGE_UPSTREAM_ERROR",
                        _upstream_error_message(response, access_token),
                    )
                response_payloads = await _payloads_from_streaming_response(
                    response,
                    settings,
                    access_token,
                    on_payload=handle_stream_payload,
                )
    except httpx.TimeoutException as exc:
        raise _image_error(504, "IMAGE_UPSTREAM_TIMEOUT", "Image upstream request timed out") from exc
    except httpx.HTTPError as exc:
        raise _image_error(
            502,
            "IMAGE_UPSTREAM_ERROR",
            f"Image upstream request failed: {exc.__class__.__name__}",
        ) from exc

    _debug_log(settings, "parsed response events=%s", len(response_payloads))
    if not response_payloads:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned an invalid payload")

    failed_response_error = _failed_response_error_from_payloads(response_payloads)
    if failed_response_error is not None:
        raise ImageGenerationError(502, failed_response_error)

    final_new_items: list[ImageData] = []
    for item in _image_items_from_payloads(response_payloads, payload.response_format):
        image_key = item.b64_json or item.url
        if not image_key or image_key in seen_image_results:
            continue
        seen_image_results.add(image_key)
        final_new_items.append(item)
    if not saved_data and not final_new_items:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned no image data")
    created = _created_from_payloads(response_payloads)
    if final_new_items:
        saved_data.extend(_save_image_file(settings, item, created, storage_context) for item in final_new_items)
    for item in saved_data:
        _debug_log(settings, "saved image file=%s", item.saved_path)
    return ImageGenerationResponse(
        created=created,
        model=_image_tool_model(settings, payload),
        data=saved_data,
        response_id=_response_id_from_payloads(response_payloads),
    )
