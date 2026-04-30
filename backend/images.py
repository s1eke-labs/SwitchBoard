from __future__ import annotations

import asyncio
import json
import base64
import binascii
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from contextlib import suppress
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from pydantic import BaseModel

from codex_files import auth_tokens, current_auth_path, read_json
from config import Settings
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
IMAGE_GENERATION_INSTRUCTIONS = "Use the image_generation tool to create an image from the user's prompt."


class ImageGenerationRequest(BaseModel):
    prompt: str
    model: str | None = None
    size: str = "1024x1024"
    quality: str = "high"
    response_format: str = "b64_json"


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


class ImageGenerationJobResponse(BaseModel):
    id: str
    prompt: str
    status: ImageJobStatus
    created_at: int
    updated_at: int
    position: int | None = None
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None


class ImageGenerationError(Exception):
    def __init__(self, status_code: int, detail: IssueDetail) -> None:
        super().__init__(detail.message)
        self.status_code = status_code
        self.detail = detail


def _image_error(status_code: int, code: str, message: str) -> ImageGenerationError:
    return ImageGenerationError(status_code, issue_detail(code, message))


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


def _responses_url(settings: Settings) -> str:
    if settings.image_responses_path.startswith(("http://", "https://")):
        return settings.image_responses_path
    return f"{settings.chatgpt_backend_base}{settings.image_responses_path}"


def _image_tool_model(settings: Settings, payload: ImageGenerationRequest) -> str:
    return payload.model or settings.image_model


def build_upstream_payload(settings: Settings, payload: ImageGenerationRequest) -> dict[str, object]:
    return {
        "model": settings.image_responses_model,
        "instructions": IMAGE_GENERATION_INSTRUCTIONS,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": payload.prompt.strip(),
                    }
                ],
            }
        ],
        "tools": [
            {
                "type": "image_generation",
                "action": "generate",
                "model": _image_tool_model(settings, payload),
                "size": payload.size,
                "quality": payload.quality,
            }
        ],
        "tool_choice": {"type": "image_generation"},
        "stream": True,
        "store": False,
    }


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


def _base64_from_data_url(value: str) -> str | None:
    prefix, separator, data = value.partition(",")
    if separator and prefix.startswith("data:image/") and ";base64" in prefix:
        return data
    return None


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
        _debug_log(settings, "sse event #%s type=%s payload=%s", event_count, _payload_type(parsed), _json_for_debug(parsed, access_token))

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
                _debug_log(settings, "sse line type=%s payload=%s", _payload_type(payload), _json_for_debug(payload, access_token))
    return _payloads_from_text("\n".join(chunks), settings, access_token)


def _created_from_payloads(payloads: list[object]) -> int:
    for payload in payloads:
        for item in _walk_values(payload):
            created = item.get("created")
            if isinstance(created, int):
                return created
    return int(time.time())


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


@dataclass
class _ImageGenerationJob:
    id: str
    payload: ImageGenerationRequest
    status: ImageJobStatus
    created_at: int
    updated_at: int
    result: ImageGenerationResponse | None = None
    error: IssueDetail | None = None


ImageGenerator = Callable[[Settings, ImageGenerationRequest], Awaitable[ImageGenerationResponse]]


class ImageGenerationQueue:
    def __init__(self, settings: Settings, generator: ImageGenerator | None = None) -> None:
        self._settings = settings
        self._generator = generator or generate_image
        self._jobs: dict[str, _ImageGenerationJob] = {}
        self._pending: deque[str] = deque()
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task[None] | None = None

    async def enqueue(self, payload: ImageGenerationRequest) -> ImageGenerationJobResponse:
        _validate_payload(self._settings, payload)
        now = int(time.time())
        job = _ImageGenerationJob(
            id=uuid.uuid4().hex,
            payload=payload,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._jobs[job.id] = job
            self._pending.append(job.id)
            self._ensure_worker_locked()
            return self._response_for_job_locked(job)

    async def get(self, job_id: str) -> ImageGenerationJobResponse | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._response_for_job_locked(job)

    async def list_recent(self, limit: int = 20) -> list[ImageGenerationJobResponse]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return [self._response_for_job_locked(job) for job in jobs[:limit]]

    async def close(self) -> None:
        task = self._worker_task
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _ensure_worker_locked(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._run())

    def _response_for_job_locked(self, job: _ImageGenerationJob) -> ImageGenerationJobResponse:
        position = None
        if job.status == "queued":
            with suppress(ValueError):
                position = list(self._pending).index(job.id) + 1
        return ImageGenerationJobResponse(
            id=job.id,
            prompt=job.payload.prompt.strip(),
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            position=position,
            result=job.result,
            error=job.error,
        )

    async def _run(self) -> None:
        while True:
            async with self._lock:
                if not self._pending:
                    return
                job = self._jobs[self._pending.popleft()]
                job.status = "running"
                job.updated_at = int(time.time())
            try:
                result = await self._generator(self._settings, job.payload)
            except ImageGenerationError as exc:
                async with self._lock:
                    job.status = "failed"
                    job.error = exc.detail
                    job.updated_at = int(time.time())
            except Exception:
                logger.exception("Queued image generation failed")
                async with self._lock:
                    job.status = "failed"
                    job.error = issue_detail("IMAGE_UPSTREAM_ERROR", "Image generation failed")
                    job.updated_at = int(time.time())
            else:
                async with self._lock:
                    job.status = "succeeded"
                    job.result = result
                    job.updated_at = int(time.time())


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
    _debug_log(settings, "request payload=%s", _json_for_debug(upstream_payload))

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
    )
