from __future__ import annotations

import asyncio
import json
import base64
import binascii
import logging
import os
import time
import uuid
from pathlib import Path
from contextlib import suppress
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from codex_files import auth_tokens, current_auth_path, read_json
from config import Settings
from db import connect, init_db
from issues import IssueDetail, issue_detail

logger = logging.getLogger(__name__)
CODEX_USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
CODEX_ORIGINATOR = "codex-tui"

ImageSize = Literal["auto", "1024x1024", "1024x1536", "1536x1024"]
ImageQuality = Literal["auto", "low", "medium", "high"]
ImageResponseFormat = Literal["b64_json", "url"]
ImageJobStatus = Literal["queued", "running", "succeeded", "failed"]

ALLOWED_IMAGE_SIZES = {"auto", "1024x1024", "1024x1536", "1536x1024"}
ALLOWED_IMAGE_QUALITIES = {"auto", "low", "medium", "high"}
ALLOWED_IMAGE_RESPONSE_FORMATS = {"b64_json", "url"}
MAX_REFERENCE_IMAGES = 4
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_REFERENCE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_GENERATION_INSTRUCTIONS = "Use the image_generation tool to create an image from the user's prompt."
DEFAULT_IMAGE_CONVERSATION_ID = "default-image-conversation"
DEFAULT_IMAGE_CONVERSATION_TITLE = "New image session"


class ImageReferenceInput(BaseModel):
    file_name: str
    mime_type: str
    b64_json: str


class ImageReferenceData(BaseModel):
    id: str
    file_name: str
    file_url: str
    original_file_name: str
    mime_type: str
    size_bytes: int


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: str | None = None
    size: str = "1024x1024"
    quality: str = "high"
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
    status: ImageJobStatus
    created_at: int
    updated_at: int
    previous_response_id: str | None = None
    upstream_response_id: str | None = None
    position: int | None = None
    references: list[ImageReferenceData] = Field(default_factory=list)
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None


class ImageConversationResponse(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    job_count: int = 0


class ImageConversationListResponse(BaseModel):
    items: list[ImageConversationResponse]
    total_count: int


class ImageGenerationError(Exception):
    def __init__(self, status_code: int, detail: IssueDetail) -> None:
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail


def _image_error(status_code: int, code: str, message: str) -> ImageGenerationError:
    return ImageGenerationError(status_code, issue_detail(code, message))


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


def _validate_payload(settings: Settings, payload: ImageGenerationRequest) -> None:
    prompt = payload.prompt.strip()
    if not prompt:
        raise _image_error(400, "IMAGE_PROMPT_REQUIRED", "Prompt is required")
    if len(prompt) > settings.image_max_prompt_chars:
        raise _image_error(400, "IMAGE_PROMPT_TOO_LONG", "Prompt is too long")
    if payload.size not in ALLOWED_IMAGE_SIZES:
        raise _image_error(400, "IMAGE_INVALID_SIZE", "Invalid image size")
    if payload.quality not in ALLOWED_IMAGE_QUALITIES:
        raise _image_error(400, "IMAGE_INVALID_QUALITY", "Invalid image quality")
    if payload.response_format not in ALLOWED_IMAGE_RESPONSE_FORMATS:
        raise _image_error(400, "IMAGE_INVALID_RESPONSE_FORMAT", "Invalid image response format")
    _validated_reference_images(payload)


def _responses_url(settings: Settings) -> str:
    if settings.image_responses_path.startswith(("http://", "https://")):
        return settings.image_responses_path
    return f"{settings.chatgpt_backend_base}{settings.image_responses_path}"


def _image_tool_model(settings: Settings, payload: ImageGenerationRequest) -> str:
    return payload.model or settings.image_model


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
        "quality": payload.quality,
    }
    if not payload.reference_images:
        tool["action"] = "generate"
    upstream_payload: dict[str, object] = {
        "model": settings.image_responses_model,
        "instructions": IMAGE_GENERATION_INSTRUCTIONS,
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


async def _payloads_from_streaming_response(response: httpx.Response, settings: Settings, access_token: str) -> list[object]:
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


def _title_from_prompt(prompt: str) -> str:
    title = " ".join(prompt.strip().split())
    if not title:
        return DEFAULT_IMAGE_CONVERSATION_TITLE
    return title[:60]


def _image_output_dir(settings: Settings) -> Path:
    output_dir = settings.image_output_dir or settings.db_path.parent / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    return output_dir


def _decode_image_base64(data: ImageData) -> bytes:
    value = data.b64_json or _base64_from_data_url(data.url or "")
    if not value:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned no image bytes")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned invalid image data") from exc


def _save_image_file(settings: Settings, data: ImageData, created: int) -> ImageData:
    extension = Path(data.file_name or "image.png").suffix.lstrip(".") or "png"
    filename = f"{created}-{uuid.uuid4().hex}.{extension}"
    path = _image_output_dir(settings) / filename
    path.write_bytes(_decode_image_base64(data))
    os.chmod(path, 0o600)
    data.file_name = filename
    data.file_url = f"/api/images/files/{filename}"
    data.saved_path = str(path)
    data.url = data.file_url
    return data


def image_file_path(settings: Settings, filename: str) -> Path:
    if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ValueError("Invalid image filename")
    path = _image_output_dir(settings) / filename
    if path.parent.resolve() != _image_output_dir(settings).resolve():
        raise ValueError("Invalid image filename")
    return path


def _reference_from_row(row) -> ImageReferenceData:
    file_name = str(row["file_name"])
    return ImageReferenceData(
        id=str(row["id"]),
        file_name=file_name,
        file_url=f"/api/images/files/{file_name}",
        original_file_name=str(row["original_file_name"]),
        mime_type=str(row["mime_type"]),
        size_bytes=int(row["size_bytes"]),
    )


def _save_reference_file(
    settings: Settings,
    job_id: str,
    index: int,
    reference: ImageReferenceInput,
    mime_type: str,
    data: bytes,
    created_at: int,
) -> ImageReferenceData:
    reference_id = uuid.uuid4().hex
    extension = _extension_from_mime(mime_type)
    filename = f"{created_at}-{job_id}-reference-{index + 1}-{reference_id}.{extension}"
    path = _image_output_dir(settings) / filename
    path.write_bytes(data)
    os.chmod(path, 0o600)
    return ImageReferenceData(
        id=reference_id,
        file_name=filename,
        file_url=f"/api/images/files/{filename}",
        original_file_name=_safe_original_file_name(reference.file_name),
        mime_type=mime_type,
        size_bytes=len(data),
    )


ImageGenerator = Callable[[Settings, ImageGenerationRequest], Awaitable[ImageGenerationResponse]]


def _conversation_from_row(row) -> ImageConversationResponse:
    return ImageConversationResponse(
        id=str(row["id"]),
        title=str(row["title"]),
        created_at=int(row["created_at"]),
        updated_at=int(row["updated_at"]),
        job_count=int(row["job_count"] or 0),
    )


def create_image_conversation(settings: Settings, title: str | None = None) -> ImageConversationResponse:
    init_db(settings.db_path)
    now = int(time.time())
    conversation_id = uuid.uuid4().hex
    conversation_title = title.strip() if title and title.strip() else DEFAULT_IMAGE_CONVERSATION_TITLE
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, conversation_title, now, now),
        )
    conversation = get_image_conversation(settings, conversation_id)
    if conversation is None:
        raise _image_error(500, "IMAGE_CONVERSATION_NOT_FOUND", "Image conversation not found")
    return conversation


def get_image_conversation(settings: Settings, conversation_id: str) -> ImageConversationResponse | None:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT image_conversations.*, COUNT(image_jobs.id) AS job_count
            FROM image_conversations
            LEFT JOIN image_jobs ON image_jobs.conversation_id = image_conversations.id
            WHERE image_conversations.id = ?
            GROUP BY image_conversations.id
            """,
            (conversation_id,),
        ).fetchone()
    return _conversation_from_row(row) if row else None


def list_image_conversations(settings: Settings, page: int = 1, limit: int = 50) -> ImageConversationListResponse:
    if page < 1:
        raise _image_error(400, "IMAGE_CONVERSATION_INVALID_PAGE", "Image conversation page is invalid")
    init_db(settings.db_path)
    offset = (page - 1) * limit
    with connect(settings.db_path) as conn:
        total_count = int(conn.execute("SELECT COUNT(*) AS count FROM image_conversations").fetchone()["count"])
        rows = list(
            conn.execute(
                """
                SELECT image_conversations.*, COUNT(image_jobs.id) AS job_count
                FROM image_conversations
                LEFT JOIN image_jobs ON image_jobs.conversation_id = image_conversations.id
                GROUP BY image_conversations.id
                ORDER BY image_conversations.updated_at DESC, image_conversations.created_at DESC
                LIMIT ?
                OFFSET ?
                """,
                (limit, offset),
            )
        )
    return ImageConversationListResponse(
        items=[_conversation_from_row(row) for row in rows],
        total_count=total_count,
    )


def _file_names_from_generation_result(result_json: str | None) -> list[str]:
    if not result_json:
        return []
    try:
        result = ImageGenerationResponse.model_validate_json(result_json)
    except ValueError:
        return []
    return [item.file_name for item in result.data if item.file_name]


def _remove_image_files(settings: Settings, file_names: list[str]) -> None:
    for file_name in sorted(set(file_names)):
        try:
            path = image_file_path(settings, file_name)
        except ValueError:
            logger.warning("Skipped invalid image file during deletion: %s", file_name)
            continue
        with suppress(FileNotFoundError):
            path.unlink()


class ImageGenerationQueue:
    def __init__(self, settings: Settings, generator: ImageGenerator | None = None) -> None:
        self._settings = settings
        self._generator = generator or generate_image
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
            conversation_id = self._ensure_conversation_locked(payload.conversation_id, payload.prompt, now)
            previous_response_id = payload.previous_response_id
            saved_references = [
                _save_reference_file(self._settings, job_id, index, reference, mime_type, data, now)
                for index, (reference, mime_type, data) in enumerate(references)
            ]
            with connect(self._settings.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO image_jobs (
                        id, conversation_id, prompt, model, size, quality, response_format, status,
                        created_at, updated_at, previous_response_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                    """,
                    (
                        job_id,
                        conversation_id,
                        payload.prompt.strip(),
                        payload.model,
                        payload.size,
                        payload.quality,
                        payload.response_format,
                        now,
                        now,
                        previous_response_id,
                    ),
                )
                self._refresh_conversation_title_locked(conn, conversation_id, payload.prompt, now)
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

    async def list_recent(self, limit: int = 20) -> list[ImageGenerationJobResponse]:
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                job_ids = [
                    str(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id FROM image_jobs
                        ORDER BY created_at DESC, rowid DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )
                ]
            return [job for job_id in job_ids if (job := self._job_response_from_db(job_id)) is not None]

    async def list_for_conversation(self, conversation_id: str, limit: int = 100) -> list[ImageGenerationJobResponse]:
        async with self._lock:
            if self._conversation_exists_locked(conversation_id) is False:
                raise _image_error(404, "IMAGE_CONVERSATION_NOT_FOUND", "Image conversation not found")
            with connect(self._settings.db_path) as conn:
                job_ids = [
                    str(row["id"])
                    for row in conn.execute(
                        """
                        SELECT id FROM image_jobs
                        WHERE conversation_id = ?
                        ORDER BY created_at ASC, rowid ASC
                        LIMIT ?
                        """,
                        (conversation_id, limit),
                    )
                ]
            return [job for job_id in job_ids if (job := self._job_response_from_db(job_id)) is not None]

    async def delete_conversation(self, conversation_id: str) -> None:
        async with self._lock:
            self._delete_conversation_locked(conversation_id)

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
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'queued', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )

    def _conversation_exists_locked(self, conversation_id: str) -> bool:
        with connect(self._settings.db_path) as conn:
            row = conn.execute("SELECT 1 FROM image_conversations WHERE id = ?", (conversation_id,)).fetchone()
        return row is not None

    def _delete_conversation_locked(self, conversation_id: str) -> None:
        file_names: list[str] = []
        with connect(self._settings.db_path) as conn:
            conversation = conn.execute("SELECT 1 FROM image_conversations WHERE id = ?", (conversation_id,)).fetchone()
            if conversation is None:
                raise _image_error(404, "IMAGE_CONVERSATION_NOT_FOUND", "Image conversation not found")
            active = conn.execute(
                """
                SELECT 1 FROM image_jobs
                WHERE conversation_id = ? AND status IN ('queued', 'running')
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
            if active is not None:
                raise _image_error(409, "IMAGE_CONVERSATION_ACTIVE_JOBS", "Image conversation has active jobs")
            file_names.extend(
                str(row["file_name"])
                for row in conn.execute(
                    """
                    SELECT image_job_references.file_name
                    FROM image_job_references
                    JOIN image_jobs ON image_jobs.id = image_job_references.job_id
                    WHERE image_jobs.conversation_id = ?
                    """,
                    (conversation_id,),
                )
            )
            for row in conn.execute(
                "SELECT result_json FROM image_jobs WHERE conversation_id = ?",
                (conversation_id,),
            ):
                file_names.extend(_file_names_from_generation_result(row["result_json"]))
            conn.execute(
                """
                DELETE FROM image_job_references
                WHERE job_id IN (SELECT id FROM image_jobs WHERE conversation_id = ?)
                """,
                (conversation_id,),
            )
            conn.execute("DELETE FROM image_jobs WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM image_conversations WHERE id = ?", (conversation_id,))
        _remove_image_files(self._settings, file_names)

    def _ensure_conversation_locked(self, conversation_id: str | None, prompt: str, now: int) -> str:
        if conversation_id:
            if not self._conversation_exists_locked(conversation_id):
                raise _image_error(404, "IMAGE_CONVERSATION_NOT_FOUND", "Image conversation not found")
            return conversation_id
        with connect(self._settings.db_path) as conn:
            row = conn.execute("SELECT id FROM image_conversations WHERE id = ?", (DEFAULT_IMAGE_CONVERSATION_ID,)).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO image_conversations (id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (DEFAULT_IMAGE_CONVERSATION_ID, _title_from_prompt(prompt), now, now),
                )
        return DEFAULT_IMAGE_CONVERSATION_ID

    def _latest_successful_response_id_locked(self, conversation_id: str) -> str | None:
        with connect(self._settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT upstream_response_id FROM image_jobs
                WHERE conversation_id = ? AND status = 'succeeded' AND upstream_response_id IS NOT NULL
                ORDER BY updated_at DESC, rowid DESC
                LIMIT 1
                """,
                (conversation_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["upstream_response_id"])

    def _refresh_conversation_title_locked(self, conn, conversation_id: str, prompt: str, now: int) -> None:
        title = _title_from_prompt(prompt)
        conn.execute(
            """
            UPDATE image_conversations
            SET title = CASE
                    WHEN title = ? THEN ?
                    ELSE title
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (DEFAULT_IMAGE_CONVERSATION_TITLE, title, now, conversation_id),
        )

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
            status=job["status"],
            created_at=int(job["created_at"]),
            updated_at=int(job["updated_at"]),
            previous_response_id=str(job["previous_response_id"]) if job["previous_response_id"] else None,
            upstream_response_id=str(job["upstream_response_id"]) if job["upstream_response_id"] else None,
            position=position,
            references=[_reference_from_row(row) for row in reference_rows],
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
            response_format=str(job["response_format"]),
            reference_images=references,
            conversation_id=str(job["conversation_id"]) if job["conversation_id"] else None,
            previous_response_id=str(job["previous_response_id"]) if job["previous_response_id"] else None,
        )

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
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'succeeded', result_json = ?, error_json = NULL,
                    upstream_response_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (result.model_dump_json(), result.response_id, now, job_id),
            )
            conn.execute(
                """
                UPDATE image_conversations
                SET updated_at = ?
                WHERE id = (SELECT conversation_id FROM image_jobs WHERE id = ?)
                """,
                (now, job_id),
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
            try:
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


async def generate_image(
    settings: Settings,
    payload: ImageGenerationRequest,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ImageGenerationResponse:
    _validate_payload(settings, payload)
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
                response_payloads = await _payloads_from_streaming_response(response, settings, access_token)
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

    data = _image_items_from_payloads(response_payloads, payload.response_format)
    if not data:
        raise _image_error(502, "IMAGE_UPSTREAM_ERROR", "Image upstream returned no image data")
    created = _created_from_payloads(response_payloads)
    saved_data = [_save_image_file(settings, item, created) for item in data]
    for item in saved_data:
        _debug_log(settings, "saved image file=%s", item.saved_path)
    return ImageGenerationResponse(
        created=created,
        model=_image_tool_model(settings, payload),
        data=saved_data,
        response_id=_response_id_from_payloads(response_payloads),
    )
