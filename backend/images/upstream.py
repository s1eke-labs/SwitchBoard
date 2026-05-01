from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import httpx

from codex_files import auth_tokens, current_auth_path, read_json
from config import Settings
from .models import (
    CODEX_ORIGINATOR,
    CODEX_USER_AGENT,
    IMAGE_GENERATION_INSTRUCTIONS,
    ImageData,
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResponse,
    _image_error,
)
from .storage import ImageStorageContext, _save_image_file
from .validation import _base64_from_data_url, _normalized_base64, _validate_payload
from issues import IssueDetail, issue_detail

logger = logging.getLogger(__name__)


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




ImageProgressCallback = Callable[[ImageGenerationResponse], Awaitable[None]]


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
    request_started_at = int(time.time())

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
        completed_at = int(time.time())
        saved_data.extend(
            _save_image_file(
                settings,
                item,
                created,
                storage_context,
                generation_started_at=request_started_at,
                generation_completed_at=completed_at,
            )
            for item in new_items
        )
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
        completed_at = int(time.time())
        saved_data.extend(
            _save_image_file(
                settings,
                item,
                created,
                storage_context,
                generation_started_at=request_started_at,
                generation_completed_at=completed_at,
            )
            for item in final_new_items
        )
    for item in saved_data:
        _debug_log(settings, "saved image file=%s", item.saved_path)
    return ImageGenerationResponse(
        created=created,
        model=_image_tool_model(settings, payload),
        data=saved_data,
        response_id=_response_id_from_payloads(response_payloads),
    )
