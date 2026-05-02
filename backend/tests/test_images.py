from __future__ import annotations

import asyncio
import base64
import importlib
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import images as images_module
from config import Settings
from db import connect, init_db
from images import (
    ImageData,
    ImageGenerationError,
    ImageGenerationQueue,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageReferenceInput,
    ImageUpstreamMetadata,
    build_upstream_payload,
    generate_image,
    image_thumbnail_filename,
    image_thumbnail_relative_path,
)
from issues import issue_detail

PNG_BYTES = b"\x89PNG\r\n\x1a\nreference"
PNG_B64 = "iVBORw0KGgpyZWZlcmVuY2U="
VALID_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


def _task_dir(job_id: str, created_at: int) -> str:
    return f"{time.strftime('%Y/%m', time.gmtime(created_at))}/{job_id}"


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "app_password": "secret",
        "codex_home": tmp_path / "codex",
        "db_path": tmp_path / "switchboard.sqlite",
        "chatgpt_backend_base": "https://chatgpt.example.test/backend-api",
        "static_dir": None,
        "image_model": "gpt-image-2",
        "image_responses_model": "gpt-5.4-mini",
        "image_responses_path": "/codex/responses",
        "image_timeout_seconds": 300.0,
        "image_max_prompt_chars": 4000,
    }
    values.update(overrides)
    values["codex_home"].mkdir(exist_ok=True)
    return Settings(**values)


def _write_auth(settings: Settings, tokens: dict[str, object] | None = None) -> None:
    value = {
        "tokens": {
            "account_id": "acct-one",
            "access_token": "codex-access-token",
        }
    }
    if tokens is not None:
        value["tokens"] = tokens
    (settings.codex_home / "auth.json").write_text(json.dumps(value), encoding="utf-8")


def _sse_response(*payloads: dict[str, object]) -> httpx.Response:
    body = "".join(f"data: {json.dumps(payload)}\n\n" for payload in payloads) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)


@pytest.mark.asyncio
async def test_generate_image_calls_responses_with_current_codex_token(tmp_path) -> None:
    settings = _settings(tmp_path, image_responses_path="/custom/responses")
    _write_auth(settings)
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.read())
        return _sse_response(
            {
                "id": "resp_first",
                "type": "response.completed",
                "created": 1776000000,
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": "aGVsbG8=",
                        "revised_prompt": "A calmer prompt",
                        "output_format": "png",
                    }
                ],
            }
        )

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="  neon city  "),
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == "https://chatgpt.example.test/backend-api/custom/responses"
    assert captured["headers"]["authorization"] == "Bearer codex-access-token"
    assert captured["headers"]["connection"] == "Keep-Alive"
    assert captured["headers"]["user-agent"] == (
        "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
    )
    assert captured["headers"]["originator"] == "codex-tui"
    assert captured["headers"]["chatgpt-account-id"] == "acct-one"
    assert captured["headers"]["session_id"]
    assert captured["payload"] == {
        "model": "gpt-5.4-mini",
        "instructions": "Use the image_generation tool to create an image from the user's prompt.",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "neon city"}],
            }
        ],
        "tools": [
            {
                "type": "image_generation",
                "action": "generate",
                "model": "gpt-image-2",
                "size": "1024x1024",
                "quality": "auto",
            }
        ],
        "tool_choice": {"type": "image_generation"},
        "stream": True,
        "store": False,
    }
    assert result.created == 1776000000
    assert result.model == "gpt-image-2"
    assert result.response_id == "resp_first"
    assert result.data[0].b64_json == "aGVsbG8="
    assert result.data[0].revised_prompt == "A calmer prompt"
    assert result.data[0].file_name
    assert result.data[0].file_url == f"/api/images/files/{result.data[0].file_name}"
    assert "/direct-" in result.data[0].file_name
    assert result.data[0].file_name.endswith("/outputs/o1.png")
    assert result.data[0].saved_path
    assert result.data[0].duration_seconds is not None
    assert Path(result.data[0].saved_path).read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_generate_image_accepts_full_responses_url(tmp_path) -> None:
    settings = _settings(tmp_path, image_responses_path="https://chatgpt.example.test/backend-api/codex/responses")
    _write_auth(settings)
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _sse_response({"output": [{"type": "image_generation_call", "result": "aGVsbG8="}]})

    await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster"),
        transport=httpx.MockTransport(handler),
    )

    assert captured["url"] == "https://chatgpt.example.test/backend-api/codex/responses"


@pytest.mark.asyncio
async def test_generate_image_reports_partial_results_while_streaming(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)
    partials: list[ImageGenerationResponse] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(
            {
                "id": "resp_partial",
                "type": "response.image_generation_call.completed",
                "created": 1776000001,
                "output": [{"type": "image_generation_call", "result": "aGVsbG8=", "output_format": "png"}],
            },
            {
                "id": "resp_partial",
                "type": "response.image_generation_call.completed",
                "created": 1776000002,
                "output": [{"type": "image_generation_call", "result": "d29ybGQ=", "output_format": "png"}],
            },
        )

    async def capture_partial(result: ImageGenerationResponse) -> None:
        partials.append(result)

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="two posters"),
        transport=httpx.MockTransport(handler),
        progress_callback=capture_partial,
    )

    assert [len(partial.data) for partial in partials] == [1, 2]
    assert partials[0].data[0].saved_path
    assert partials[0].data[0].duration_seconds is not None
    assert Path(partials[0].data[0].saved_path).read_bytes() == b"hello"
    assert partials[1].data[1].saved_path
    assert partials[1].data[1].duration_seconds is not None
    assert Path(partials[1].data[1].saved_path).read_bytes() == b"world"
    assert len(result.data) == 2
    assert [item.file_url for item in result.data] == [item.file_url for item in partials[-1].data]


@pytest.mark.asyncio
async def test_generate_image_extracts_sanitized_upstream_metadata(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(
            {
                "id": "resp_meta",
                "type": "response.image_generation_call.completed",
                "created": 1776000001,
                "output": [{"type": "image_generation_call", "result": VALID_PNG_B64, "output_format": "png"}],
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_meta",
                    "model": "gpt-5.4-mini-2026-03-17",
                    "created_at": 1776000000,
                    "completed_at": 1776000068,
                    "safety_identifier": "user-secret",
                    "prompt_cache_key": "cache-secret",
                    "usage": {
                        "input_tokens": 6409,
                        "input_tokens_details": {"cached_tokens": 2176},
                        "output_tokens": 269,
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 6678,
                    },
                    "tool_usage": {
                        "image_gen": {
                            "input_tokens": 1733,
                            "input_tokens_details": {"image_tokens": 1476, "text_tokens": 257},
                            "output_tokens": 1413,
                            "output_tokens_details": {"image_tokens": 1413, "text_tokens": 0},
                            "total_tokens": 3146,
                        }
                    },
                    "tools": [
                        {
                            "type": "image_generation",
                            "model": "gpt-image-2",
                            "size": "1152x2048",
                            "quality": "auto",
                            "output_format": "png",
                            "background": "auto",
                            "moderation": "auto",
                            "output_compression": 100,
                        }
                    ],
                },
            },
        )

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster", size="auto"),
        transport=httpx.MockTransport(handler),
    )

    assert len(result.upstream_metadata) == 1
    metadata = result.upstream_metadata[0]
    assert metadata.response_id == "resp_meta"
    assert metadata.response_model == "gpt-5.4-mini-2026-03-17"
    assert metadata.image_model == "gpt-image-2"
    assert metadata.requested_size == "auto"
    assert metadata.resolved_size == "1152x2048"
    assert metadata.duration_seconds == 68
    assert metadata.usage is not None
    assert metadata.usage.total_tokens == 6678
    assert metadata.usage.cached_tokens == 2176
    assert metadata.image_usage is not None
    assert metadata.image_usage.input_image_tokens == 1476
    assert metadata.image_usage.total_tokens == 3146
    metadata_json = metadata.model_dump_json()
    assert "user-secret" not in metadata_json
    assert "cache-secret" not in metadata_json


@pytest.mark.asyncio
async def test_generate_image_runs_multi_count_as_separate_upstream_requests(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)
    captured_payloads: list[dict[str, object]] = []
    partials: list[ImageGenerationResponse] = []
    results = ["aGVsbG8=", "d29ybGQ="]
    resolved_sizes = ["1024x1024", "1536x1536"]

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.read()))
        index = len(captured_payloads)
        result = results[len(captured_payloads) - 1]
        return _sse_response(
            {"output": [{"type": "image_generation_call", "result": result, "output_format": "png"}]},
            {
                "type": "response.completed",
                "response": {
                    "id": f"resp_multi_{index}",
                    "model": "gpt-5.4-mini-2026-03-17",
                    "created_at": 1776000000 + index,
                    "completed_at": 1776000010 + index,
                    "tools": [
                            {
                                "type": "image_generation",
                                "model": "gpt-image-2",
                                "size": resolved_sizes[index - 1],
                                "quality": "auto",
                            }
                    ],
                },
            },
        )

    async def capture_partial(result: ImageGenerationResponse) -> None:
        partials.append(result)

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="two posters", n=2),
        transport=httpx.MockTransport(handler),
        progress_callback=capture_partial,
    )

    assert len(captured_payloads) == 2
    assert all(payload["instructions"] == "Use the image_generation tool to create an image from the user's prompt." for payload in captured_payloads)
    assert all("n" not in payload["tools"][0] for payload in captured_payloads)
    assert [len(partial.data) for partial in partials] == [1, 2]
    assert len(result.data) == 2
    assert [metadata.response_id for metadata in result.upstream_metadata] == ["resp_multi_1", "resp_multi_2"]
    assert [metadata.resolved_size for metadata in result.upstream_metadata] == resolved_sizes
    assert all(item.duration_seconds is not None for item in result.data)
    assert Path(result.data[0].saved_path).read_bytes() == b"hello"
    assert Path(result.data[1].saved_path).read_bytes() == b"world"


@pytest.mark.asyncio
async def test_generate_image_parses_sse_without_content_type(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        body = 'data: {"output":[{"type":"image_generation_call","result":"aGVsbG8="}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster"),
        transport=httpx.MockTransport(handler),
    )

    assert result.data[0].b64_json == "aGVsbG8="


@pytest.mark.asyncio
async def test_generate_image_uses_request_model_as_image_tool_model(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return _sse_response(
            {
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": "aGVsbG8=",
                    }
                ],
            }
        )

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster", model="gpt-image-2-custom"),
        transport=httpx.MockTransport(handler),
    )

    assert captured["payload"]["tools"][0]["model"] == "gpt-image-2-custom"
    assert result.model == "gpt-image-2-custom"


@pytest.mark.asyncio
async def test_generate_image_can_return_data_url(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(
            {
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": "aGVsbG8=",
                        "output_format": "png",
                    }
                ],
            }
        )

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster", response_format="url"),
        transport=httpx.MockTransport(handler),
    )

    assert result.data[0].b64_json == "aGVsbG8="
    assert result.data[0].file_url
    assert result.data[0].url == result.data[0].file_url


@pytest.mark.asyncio
async def test_generate_image_saves_webp_thumbnail_for_valid_images(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return _sse_response(
            {
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": VALID_PNG_B64,
                        "output_format": "png",
                    }
                ],
            }
        )

    result = await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster"),
        transport=httpx.MockTransport(handler),
    )

    item = result.data[0]
    assert item.file_name is not None
    assert "/direct-" in item.file_name
    assert item.file_name.endswith("/outputs/o1.png")
    thumbnail_name = image_thumbnail_relative_path(item.file_name)
    assert item.thumbnail_url == f"/api/images/files/{thumbnail_name}"
    thumbnail_path = settings.db_path.parent / "images" / thumbnail_name
    assert thumbnail_path.exists()
    assert thumbnail_path.read_bytes().startswith(b"RIFF")


def test_build_upstream_payload_adds_reference_images_without_forcing_generate(tmp_path) -> None:
    settings = _settings(tmp_path)

    payload = build_upstream_payload(
        settings,
        ImageGenerationRequest(
            prompt="poster",
            reference_images=[
                ImageReferenceInput(file_name="ref.png", mime_type="image/png", b64_json=PNG_B64),
                ImageReferenceInput(file_name="ref-data-url.png", mime_type="image/png", b64_json=f"data:image/png;base64,{PNG_B64}"),
            ],
        ),
    )

    content = payload["input"][0]["content"]
    assert content == [
        {"type": "input_text", "text": "poster"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}"},
        {"type": "input_image", "image_url": f"data:image/png;base64,{PNG_B64}"},
    ]
    tool = payload["tools"][0]
    assert tool["type"] == "image_generation"
    assert tool["model"] == "gpt-image-2"
    assert "n" not in tool
    assert "action" not in tool
    assert payload["store"] is False


def test_common_frontend_image_sizes_satisfy_resolution_constraints() -> None:
    common_frontend_sizes = {
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
    for size in common_frontend_sizes:
        assert images_module._image_size_satisfies_constraints(size)


def test_build_upstream_payload_uses_resolution_size_auto_quality_and_count_instruction(tmp_path) -> None:
    settings = _settings(tmp_path)

    payload = build_upstream_payload(
        settings,
        ImageGenerationRequest(prompt="poster", size="3840x2160", quality="auto", n=4),
    )

    tool = payload["tools"][0]
    assert tool["size"] == "3840x2160"
    assert tool["quality"] == "auto"
    assert "n" not in tool
    assert payload["instructions"] == (
        "Use the image_generation tool to create an image from the user's prompt. "
        "Create exactly 4 separate images."
    )


def test_build_upstream_payload_supports_auto_size(tmp_path) -> None:
    settings = _settings(tmp_path)

    payload = build_upstream_payload(
        settings,
        ImageGenerationRequest(prompt="poster", size="auto", quality="auto"),
    )

    tool = payload["tools"][0]
    assert tool["size"] == "auto"
    assert tool["quality"] == "auto"


def test_build_upstream_payload_adds_previous_response_id(tmp_path) -> None:
    settings = _settings(tmp_path)

    payload = build_upstream_payload(
        settings,
        ImageGenerationRequest(prompt="make it realistic", previous_response_id="resp_previous"),
    )

    assert payload["previous_response_id"] == "resp_previous"
    assert payload["store"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size",
    [
        "3856x2144",
        "1000x1024",
        "3840x1264",
        "768x832",
        "3840x2176",
    ],
)
async def test_generate_image_enforces_resolution_constraints(tmp_path, size: str) -> None:
    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            _settings(tmp_path),
            ImageGenerationRequest(prompt="poster", size=size),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == "IMAGE_INVALID_SIZE"


@pytest.mark.asyncio
async def test_generate_image_accepts_custom_size_that_satisfies_resolution_constraints(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return _sse_response({"output": [{"type": "image_generation_call", "result": VALID_PNG_B64}]})

    await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster", size="2048x2048"),
        transport=httpx.MockTransport(handler),
    )

    tool = captured["payload"]["tools"][0]
    assert tool["size"] == "2048x2048"


@pytest.mark.asyncio
async def test_generate_image_accepts_auto_size(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.read())
        return _sse_response({"output": [{"type": "image_generation_call", "result": VALID_PNG_B64}]})

    await generate_image(
        settings,
        ImageGenerationRequest(prompt="poster", size="auto", quality="auto"),
        transport=httpx.MockTransport(handler),
    )

    tool = captured["payload"]["tools"][0]
    assert tool["size"] == "auto"
    assert tool["quality"] == "auto"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (ImageGenerationRequest(prompt=" "), "IMAGE_PROMPT_REQUIRED"),
        (ImageGenerationRequest(prompt="x", size="4096x4096"), "IMAGE_INVALID_SIZE"),
        (ImageGenerationRequest(prompt="x", quality="ultra"), "IMAGE_INVALID_QUALITY"),
        (ImageGenerationRequest(prompt="x", quality="high"), "IMAGE_INVALID_QUALITY"),
        (ImageGenerationRequest(prompt="x", n=3), "IMAGE_INVALID_COUNT"),
        (
            ImageGenerationRequest(
                prompt="x",
                reference_images=[ImageReferenceInput(file_name=f"{index}.png", mime_type="image/png", b64_json=PNG_B64) for index in range(5)],
            ),
            "IMAGE_REFERENCE_TOO_MANY",
        ),
        (
            ImageGenerationRequest(
                prompt="x",
                reference_images=[ImageReferenceInput(file_name="bad.png", mime_type="image/png", b64_json="not-base64")],
            ),
            "IMAGE_REFERENCE_INVALID",
        ),
        (
            ImageGenerationRequest(
                prompt="x",
                reference_images=[ImageReferenceInput(file_name="bad.txt", mime_type="text/plain", b64_json=PNG_B64)],
            ),
            "IMAGE_REFERENCE_UNSUPPORTED_TYPE",
        ),
        (
            ImageGenerationRequest(
                prompt="x",
                reference_images=[
                    ImageReferenceInput(
                        file_name="huge.png",
                        mime_type="image/png",
                        b64_json=base64.b64encode(b"\x89PNG\r\n\x1a\n" + (b"a" * (11 * 1024 * 1024))).decode("ascii"),
                    )
                ],
            ),
            "IMAGE_REFERENCE_TOO_LARGE",
        ),
    ],
)
async def test_generate_image_validates_payload(tmp_path, payload: ImageGenerationRequest, code: str) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            payload,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == code


@pytest.mark.asyncio
async def test_generate_image_reports_missing_auth(tmp_path) -> None:
    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            _settings(tmp_path),
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == "IMAGE_AUTH_NOT_FOUND"


@pytest.mark.asyncio
async def test_generate_image_reports_missing_tokens(tmp_path) -> None:
    settings = _settings(tmp_path)
    (settings.codex_home / "auth.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == "IMAGE_AUTH_TOKENS_MISSING"


@pytest.mark.asyncio
async def test_generate_image_reports_missing_access_token(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings, tokens={"account_id": "acct-one"})

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == "IMAGE_AUTH_ACCESS_TOKEN_MISSING"


@pytest.mark.asyncio
async def test_generate_image_reports_missing_account_id(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings, tokens={"access_token": "codex-access-token"})

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.code == "IMAGE_AUTH_ACCOUNT_ID_MISSING"


@pytest.mark.asyncio
async def test_generate_image_sanitizes_upstream_error(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="codex-access-token should not be surfaced")

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail.code == "IMAGE_UPSTREAM_ERROR"
    assert str(exc_info.value) == "Image upstream returned HTTP 500: [redacted] should not be surfaced"
    assert "codex-access-token" not in exc_info.value.detail.message


@pytest.mark.asyncio
async def test_generate_image_reports_html_challenge(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"content-type": "text/html"},
            text="<html>challenge page</html>",
        )

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail.code == "IMAGE_UPSTREAM_ERROR"
    assert exc_info.value.detail.message == (
        "Image upstream returned HTTP 403 with an HTML challenge. "
        "The configured SWITCHBOARD_IMAGE_RESPONSES_PATH is likely not a bearer-token JSON endpoint."
    )


@pytest.mark.asyncio
async def test_generate_image_translates_timeout(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail.code == "IMAGE_UPSTREAM_TIMEOUT"


@pytest.mark.asyncio
async def test_generate_image_reports_http_error_type(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail.code == "IMAGE_UPSTREAM_ERROR"
    assert exc_info.value.detail.message == "Image upstream request failed: ConnectError"


@pytest.mark.asyncio
async def test_generate_image_requires_image_generation_output(tmp_path) -> None:
    settings = _settings(tmp_path)
    _write_auth(settings)

    with pytest.raises(ImageGenerationError) as exc_info:
        await generate_image(
            settings,
            ImageGenerationRequest(prompt="poster"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"output": []})),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail.code == "IMAGE_UPSTREAM_ERROR"


@pytest.mark.asyncio
async def test_image_generation_queue_runs_jobs_sequentially(tmp_path) -> None:
    settings = _settings(tmp_path)
    started: list[str] = []
    release_first = asyncio.Event()

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        started.append(payload.prompt)
        if payload.prompt == "first":
            await release_first.wait()
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name=f"{payload.prompt}.png")],
        )

    queue = ImageGenerationQueue(settings, generator=generator)

    first = await queue.enqueue(ImageGenerationRequest(prompt="first"))
    second = await queue.enqueue(ImageGenerationRequest(prompt="second"))
    await asyncio.sleep(0)

    first_running = await queue.get(first.id)
    second_queued = await queue.get(second.id)
    assert started == ["first"]
    assert first_running is not None
    assert first_running.status == "running"
    assert second_queued is not None
    assert second_queued.status == "queued"
    assert second_queued.position == 1

    release_first.set()
    for _ in range(20):
        second_done = await queue.get(second.id)
        if second_done is not None and second_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    first_done = await queue.get(first.id)
    second_done = await queue.get(second.id)
    assert started == ["first", "second"]
    assert first_done is not None
    assert first_done.status == "succeeded"
    assert second_done is not None
    assert second_done.status == "succeeded"
    assert second_done.result is not None
    assert second_done.result.data[0].file_name == "second.png"
    recent = await queue.list_recent()
    assert recent.items[0].id == second.id
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_records_errors(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        raise ImageGenerationError(502, issue_detail("IMAGE_UPSTREAM_ERROR", "failed"))

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(ImageGenerationRequest(prompt="poster"))

    for _ in range(20):
        failed = await queue.get(job.id)
        if failed is not None and failed.status == "failed":
            break
        await asyncio.sleep(0.01)

    failed = await queue.get(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.code == "IMAGE_UPSTREAM_ERROR"
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_persists_jobs_and_references(tmp_path) -> None:
    settings = _settings(tmp_path)
    captured: list[ImageGenerationRequest] = []

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        captured.append(payload)
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name="image.png")],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(
        ImageGenerationRequest(
            prompt="with ref",
            reference_images=[ImageReferenceInput(file_name="ref.png", mime_type="image/png", b64_json=PNG_B64)],
        )
    )

    for _ in range(20):
        done = await queue.get(job.id)
        if done is not None and done.status == "succeeded":
            break
        await asyncio.sleep(0.01)
    await queue.close()

    restored = ImageGenerationQueue(settings, generator=generator)
    restored_job = await restored.get(job.id)

    assert captured[0].reference_images[0].b64_json == PNG_B64
    assert restored_job is not None
    assert restored_job.status == "succeeded"
    assert restored_job.references[0].original_file_name == "ref.png"
    assert restored_job.references[0].file_name == f"{_task_dir(job.id, job.created_at)}/references/r1.png"
    assert restored_job.references[0].file_url == f"/api/images/files/{restored_job.references[0].file_name}"
    assert (settings.db_path.parent / "images" / restored_job.references[0].file_name).read_bytes() == PNG_BYTES
    await restored.close()


@pytest.mark.asyncio
async def test_image_generation_queue_marks_running_jobs_failed_on_restart(tmp_path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status, n, created_at, updated_at
            )
            VALUES ('running-job', 'poster', NULL, '1024x1024', 'auto', 'b64_json', 'running', 1, 10, 20)
            """
        )

    called = False

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        nonlocal called
        called = True
        return ImageGenerationResponse(created=1776000000, model="gpt-image-2", data=[])

    queue = ImageGenerationQueue(settings, generator=generator)
    await queue.start()
    await asyncio.sleep(0)
    job = await queue.get("running-job")

    assert not called
    assert job is not None
    assert job.status == "failed"
    assert job.error is not None
    assert job.error.code == "IMAGE_JOB_INTERRUPTED"
    assert job.updated_at >= 20
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_keeps_partial_results_when_restart_interrupts_job(tmp_path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    partial_result = ImageGenerationResponse(
        created=1776000000,
        model="gpt-image-2",
        data=[
            ImageData(
                file_name="2026/05/running-job/outputs/o1.png",
                file_url="/api/images/files/2026/05/running-job/outputs/o1.png",
            )
        ],
        response_id="resp-partial",
    )
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status, n,
                result_json, upstream_response_id, created_at, updated_at
            )
            VALUES (
                'running-job', 'poster', NULL, '1024x1024', 'auto', 'b64_json', 'running', 4,
                ?, 'resp-partial', 10, 20
            )
            """,
            (partial_result.model_dump_json(),),
        )

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        raise AssertionError("Interrupted running jobs must not be generated again")

    queue = ImageGenerationQueue(settings, generator=generator)
    await queue.start()
    await asyncio.sleep(0)
    job = await queue.get("running-job")

    assert job is not None
    assert job.status == "failed"
    assert job.error is not None
    assert job.error.code == "IMAGE_JOB_INTERRUPTED"
    assert job.result is not None
    assert job.result.response_id == "resp-partial"
    assert [item.file_name for item in job.result.data] == ["2026/05/running-job/outputs/o1.png"]
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_restart_only_fails_running_slot_and_continues_queued_slots(tmp_path) -> None:
    settings = _settings(tmp_path)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        for job_id, status_value, created_at, result_json in [
            (
                "done-slot",
                "succeeded",
                10,
                ImageGenerationResponse(
                    created=1776000000,
                    model="gpt-image-2",
                    data=[ImageData(file_name="done.png")],
                ).model_dump_json(),
            ),
            ("running-slot", "running", 11, None),
            ("queued-slot-1", "queued", 12, None),
            ("queued-slot-2", "queued", 13, None),
        ]:
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, prompt, model, size, quality, response_format, status, n,
                    result_json, created_at, updated_at
                )
                VALUES (?, 'poster', NULL, '1024x1024', 'auto', 'b64_json', ?, 1, ?, ?, ?)
                """,
                (job_id, status_value, result_json, created_at, created_at),
            )

    generated: list[int] = []

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        generated.append(payload.n)
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name=f"slot-{len(generated)}.png")],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    await queue.start()
    for _ in range(20):
        first = await queue.get("queued-slot-1")
        second = await queue.get("queued-slot-2")
        if first is not None and first.status == "succeeded" and second is not None and second.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    done = await queue.get("done-slot")
    interrupted = await queue.get("running-slot")
    first = await queue.get("queued-slot-1")
    second = await queue.get("queued-slot-2")

    assert done is not None and done.status == "succeeded"
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.error is not None
    assert interrupted.error.code == "IMAGE_JOB_INTERRUPTED"
    assert first is not None and first.status == "succeeded"
    assert second is not None and second.status == "succeeded"
    assert generated == [1, 1]
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_stops_queued_job(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        raise AssertionError("Stopped queued jobs must not run")

    queue = ImageGenerationQueue(settings, generator=generator)
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status, n, created_at, updated_at
            )
            VALUES ('queued-job', 'poster', NULL, '1024x1024', 'auto', 'b64_json', 'queued', 1, 10, 10)
            """
        )

    await queue.stop_job("queued-job")
    await queue.start()
    await asyncio.sleep(0)
    job = await queue.get("queued-job")

    assert job is not None
    assert job.status == "failed"
    assert job.error is not None
    assert job.error.code == "IMAGE_JOB_STOPPED"
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_stop_running_job_is_not_overwritten_by_late_result(tmp_path) -> None:
    settings = _settings(tmp_path)
    running = asyncio.Event()
    release = asyncio.Event()

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        running.set()
        await release.wait()
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name="late.png")],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(ImageGenerationRequest(prompt="poster"))
    await asyncio.wait_for(running.wait(), timeout=1)

    await queue.stop_job(job.id)
    release.set()
    for _ in range(20):
        stopped = await queue.get(job.id)
        if stopped is not None and stopped.error is not None and stopped.error.code == "IMAGE_JOB_STOPPED":
            break
        await asyncio.sleep(0.01)
    stopped = await queue.get(job.id)

    assert stopped is not None
    assert stopped.status == "failed"
    assert stopped.error is not None
    assert stopped.error.code == "IMAGE_JOB_STOPPED"
    assert stopped.result is None
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_deletes_result_images(tmp_path) -> None:
    settings = _settings(tmp_path)
    image_dir = settings.db_path.parent / "images"
    image_dir.mkdir()
    first_path = image_dir / "first.png"
    second_path = image_dir / "second.png"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first_thumbnail_path = image_dir / image_thumbnail_filename(first_path.name)
    second_thumbnail_path = image_dir / image_thumbnail_filename(second_path.name)
    first_thumbnail_path.write_bytes(b"first-thumb")
    second_thumbnail_path.write_bytes(b"second-thumb")

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            created=123,
            model="gpt-image-2",
            data=[
                ImageData(b64_json="Zmlyc3Q=", file_name="first.png", file_url="/api/images/files/first.png", saved_path=str(first_path)),
                ImageData(b64_json="c2Vjb25k", file_name="second.png", file_url="/api/images/files/second.png", saved_path=str(second_path)),
            ],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(ImageGenerationRequest(prompt="poster", n=2))
    for _ in range(20):
        done = await queue.get(job.id)
        if done is not None and done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    await queue.delete_result_image(job.id, 0)
    updated = await queue.get(job.id)

    assert updated is not None
    assert updated.result is not None
    assert len(updated.result.data) == 1
    assert updated.result.data[0].file_name == "second.png"
    assert not first_path.exists()
    assert not first_thumbnail_path.exists()
    assert second_path.exists()
    assert second_thumbnail_path.exists()

    await queue.delete_result_image(job.id, 0)

    assert await queue.get(job.id) is None
    assert not second_path.exists()
    assert not second_thumbnail_path.exists()
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_deletes_failed_jobs_without_images(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        raise ImageGenerationError(502, issue_detail("IMAGE_UPSTREAM_ERROR", "failed"))

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(ImageGenerationRequest(prompt="poster"))
    for _ in range(20):
        failed = await queue.get(job.id)
        if failed is not None and failed.status == "failed":
            break
        await asyncio.sleep(0.01)

    await queue.delete_job(job.id)

    assert await queue.get(job.id) is None
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_deletes_job_images_references_and_thumbnails(tmp_path) -> None:
    settings = _settings(tmp_path)
    image_dir = settings.db_path.parent / "images"
    image_dir.mkdir()
    result_path = image_dir / "result.png"
    result_thumbnail = image_dir / image_thumbnail_filename(result_path.name)
    result_path.write_bytes(b"result")
    result_thumbnail.write_bytes(b"result-thumb")

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            created=123,
            model="gpt-image-2",
            data=[
                ImageData(
                    b64_json="cmVzdWx0",
                    file_name=result_path.name,
                    file_url=f"/api/images/files/{result_path.name}",
                    saved_path=str(result_path),
                )
            ],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    job = await queue.enqueue(
        ImageGenerationRequest(
            prompt="poster",
            reference_images=[ImageReferenceInput(file_name="ref.png", mime_type="image/png", b64_json=PNG_B64)],
        )
    )
    for _ in range(20):
        done = await queue.get(job.id)
        if done is not None and done.status == "succeeded":
            break
        await asyncio.sleep(0.01)
    done = await queue.get(job.id)
    assert done is not None
    reference_path = image_dir / done.references[0].file_name
    reference_thumbnail = image_dir / image_thumbnail_relative_path(done.references[0].file_name)
    reference_thumbnail.parent.mkdir(parents=True, exist_ok=True)
    reference_thumbnail.write_bytes(b"reference-thumb")

    await queue.delete_job(job.id)

    assert await queue.get(job.id) is None
    assert not result_path.exists()
    assert not result_thumbnail.exists()
    assert not reference_path.exists()
    assert not reference_thumbnail.exists()
    await queue.close()


def test_image_migration_keeps_legacy_jobs_visible_without_conversation(tmp_path) -> None:
    db_path = tmp_path / "switchboard.sqlite"
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE image_jobs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                model TEXT,
                size TEXT NOT NULL,
                quality TEXT NOT NULL,
                response_format TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                result_json TEXT,
                error_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status, created_at, updated_at
            )
            VALUES ('old-job', 'legacy prompt', NULL, '1024x1024', 'high', 'b64_json', 'succeeded', 10, 20)
            """
        )

    init_db(db_path)

    with connect(db_path) as conn:
        job = conn.execute("SELECT conversation_id FROM image_jobs WHERE id = 'old-job'").fetchone()
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(image_jobs)")}

    assert job["conversation_id"] is None
    assert "upstream_metadata_json" in columns


@pytest.mark.asyncio
async def test_image_generation_queue_keeps_jobs_without_auto_chaining_responses(tmp_path) -> None:
    settings = _settings(tmp_path)
    captured: list[ImageGenerationRequest] = []

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        captured.append(payload)
        if payload.prompt == "failed edit":
            raise ImageGenerationError(502, issue_detail("IMAGE_UPSTREAM_ERROR", "failed"))
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name=f"{payload.prompt}.png")],
            response_id=f"resp-{payload.prompt.replace(' ', '-')}",
            upstream_metadata=[
                ImageUpstreamMetadata(
                    response_id=f"resp-{payload.prompt.replace(' ', '-')}",
                    response_model="gpt-5.4-mini-2026-03-17",
                    image_model="gpt-image-2",
                    requested_size=payload.size,
                    resolved_size="1024x1024",
                )
            ],
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    first = await queue.enqueue(ImageGenerationRequest(prompt="base image"))
    for _ in range(20):
        first_done = await queue.get(first.id)
        if first_done is not None and first_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    first_done = await queue.get(first.id)
    assert first_done is not None
    assert first_done.conversation_id is None
    assert first_done.upstream_response_id == "resp-base-image"
    assert first_done.upstream_metadata[0].response_model == "gpt-5.4-mini-2026-03-17"
    with connect(settings.db_path) as conn:
        stored_metadata = conn.execute("SELECT upstream_metadata_json FROM image_jobs WHERE id = ?", (first.id,)).fetchone()
    assert stored_metadata is not None
    assert "gpt-5.4-mini-2026-03-17" in stored_metadata["upstream_metadata_json"]

    second = await queue.enqueue(ImageGenerationRequest(prompt="failed edit", conversation_id="ignored-conversation"))
    for _ in range(20):
        second_failed = await queue.get(second.id)
        if second_failed is not None and second_failed.status == "failed":
            break
        await asyncio.sleep(0.01)

    third = await queue.enqueue(ImageGenerationRequest(prompt="final edit", conversation_id="ignored-conversation"))
    for _ in range(20):
        third_done = await queue.get(third.id)
        if third_done is not None and third_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    second_failed = await queue.get(second.id)
    third_done = await queue.get(third.id)
    assert second_failed is not None
    assert second_failed.conversation_id is None
    assert second_failed.previous_response_id is None
    assert second_failed.upstream_response_id is None
    assert third_done is not None
    assert third_done.conversation_id is None
    assert third_done.previous_response_id is None
    assert [payload.previous_response_id for payload in captured] == [None, None, None]
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_paginates_recent_jobs(tmp_path) -> None:
    settings = _settings(tmp_path)

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[ImageData(b64_json="aGVsbG8=", file_name=f"{payload.prompt}.png")],
            response_id=f"resp-{payload.prompt}",
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    first = await queue.enqueue(ImageGenerationRequest(prompt="first"))
    other = await queue.enqueue(ImageGenerationRequest(prompt="other", conversation_id="ignored-conversation"))
    third = await queue.enqueue(ImageGenerationRequest(prompt="third"))
    for _ in range(20):
        third_done = await queue.get(third.id)
        if third_done is not None and third_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    first_page = await queue.list_recent(page=1, limit=2)
    second_page = await queue.list_recent(page=2, limit=2)

    assert first_page.total_count == 3
    assert [job.id for job in first_page.items] == [third.id, other.id]
    assert [job.id for job in second_page.items] == [first.id]
    assert all(job.conversation_id is None for job in first_page.items + second_page.items)
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_paginates_gallery_items_by_image_slots(tmp_path) -> None:
    settings = _settings(tmp_path)
    generated_counts: list[int] = []

    async def generator(settings: Settings, payload: ImageGenerationRequest) -> ImageGenerationResponse:
        generated_counts.append(payload.n)
        return ImageGenerationResponse(
            created=1776000000,
            model="gpt-image-2",
            data=[
                ImageData(b64_json="aGVsbG8=", file_name=f"{payload.prompt}-{index}.png")
                for index in range(payload.n)
            ],
            response_id=f"resp-{payload.prompt}",
        )

    queue = ImageGenerationQueue(settings, generator=generator)
    first = await queue.enqueue(ImageGenerationRequest(prompt="first", n=4))
    second = await queue.enqueue(ImageGenerationRequest(prompt="second", n=1))
    for _ in range(20):
        second_done = await queue.get(second.id)
        if second_done is not None and second_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    first_page = await queue.list_gallery_items(page=1, limit=3)
    second_page = await queue.list_gallery_items(page=2, limit=3)

    assert first_page.total_count == 5
    items = first_page.items + second_page.items
    first_items = [item for item in items if item.job.prompt == "first"]
    second_items = [item for item in items if item.job.prompt == "second"]
    assert len(first_items) == 4
    assert len({item.job.id for item in first_items}) == 4
    assert all(item.image_index == 0 for item in first_items)
    assert all(item.job.n == 1 for item in first_items)
    assert [(item.job.id, item.image_index) for item in second_items] == [(second.id, 0)]
    assert first.id in {item.job.id for item in first_items}
    assert generated_counts == [1, 1, 1, 1, 1]
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_gallery_only_hydrates_visible_jobs(monkeypatch, tmp_path) -> None:
    settings = _settings(tmp_path)
    queue = ImageGenerationQueue(settings)
    image_dir = settings.db_path.parent / "images"
    visible_output = "2026/05/success-job/outputs/o1.png"
    visible_thumbnail = image_thumbnail_relative_path(visible_output)
    visible_reference = "2026/05/success-job/references/r1.png"
    visible_reference_thumbnail = image_thumbnail_relative_path(visible_reference)
    visible_output_path = image_dir / visible_output
    visible_output_path.parent.mkdir(parents=True, exist_ok=True)
    visible_output_path.write_bytes(base64.b64decode(VALID_PNG_B64))
    for path in [image_dir / visible_thumbnail, image_dir / visible_reference_thumbnail]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"thumbnail")
    success_result = ImageGenerationResponse(
        created=1776000000,
        model="gpt-image-2",
        data=[
            ImageData(file_name=visible_output, file_url=f"/api/images/files/{visible_output}"),
            ImageData(file_name="2026/05/success-job/outputs/o2.png"),
        ],
    )
    running_result = ImageGenerationResponse(
        created=1776000001,
        model="gpt-image-2",
        data=[ImageData(file_name="2026/05/running-job/outputs/o1.png")],
    )
    failed_error = issue_detail("IMAGE_UPSTREAM_ERROR", "Image generation failed")
    with connect(settings.db_path) as conn:
        for job_id, prompt, status, n, created_at, result_json, error_json in [
            ("running-job", "Running", "running", 4, 300, running_result.model_dump_json(), None),
            ("failed-job", "Failed", "failed", 4, 200, None, failed_error.model_dump_json()),
            ("success-job", "Success", "succeeded", 2, 100, success_result.model_dump_json(), None),
        ]:
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, prompt, model, size, quality, response_format, status,
                    n, result_json, error_json, created_at, updated_at
                )
                VALUES (?, ?, NULL, '1024x1024', 'auto', 'b64_json', ?, ?, ?, ?, ?, ?)
                """,
                (job_id, prompt, status, n, result_json, error_json, created_at, created_at),
            )
        conn.execute(
            """
            INSERT INTO image_job_references (
                id, job_id, position, original_file_name, mime_type, size_bytes, file_name, created_at
            )
            VALUES ('ref-visible', 'success-job', 0, 'reference.png', 'image/png', 12, ?, 100)
            """,
            (visible_reference,),
        )
        for index in range(20):
            old_result = ImageGenerationResponse(
                created=1775990000 + index,
                model="gpt-image-2",
                data=[
                    ImageData(file_name=f"2026/05/old-{index}/outputs/o{image_index}.png")
                    for image_index in range(4)
                ],
            )
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, prompt, model, size, quality, response_format, status,
                    n, result_json, created_at, updated_at
                )
                VALUES (?, 'Old', NULL, '1024x1024', 'auto', 'b64_json', 'succeeded', 4, ?, ?, ?)
                """,
                (f"old-{index}", old_result.model_dump_json(), index, index),
            )

    def fail_if_full_job_is_loaded(job_id: str) -> None:
        pytest.fail(f"Gallery should not hydrate full job {job_id}")

    monkeypatch.setattr(queue, "_job_response_from_db", fail_if_full_job_is_loaded)

    page = await queue.list_gallery_items(page=2, limit=4)

    assert page.total_count == 87
    assert [(item.job.id, item.image_index) for item in page.items] == [
        ("failed-job", 0),
        ("success-job", 0),
        ("success-job", 1),
        ("old-19", 0),
    ]
    assert page.items[0].job.error == failed_error
    assert page.items[1].image is not None
    assert page.items[1].image.thumbnail_url == f"/api/images/files/{visible_thumbnail}"
    assert page.items[1].image.width == 1
    assert page.items[1].image.height == 1
    assert page.items[1].image.size_bytes == visible_output_path.stat().st_size
    assert page.items[1].job.references[0].file_url == f"/api/images/files/{visible_reference}"
    assert page.items[1].job.references[0].thumbnail_url == f"/api/images/files/{visible_reference_thumbnail}"
    await queue.close()


def test_image_api_requires_auth_and_reports_missing_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    response = client.post("/api/images/generations", json={"prompt": "poster"})
    assert response.status_code == 401

    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    response = client.post("/api/images/generations", json={"prompt": "poster"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "IMAGE_AUTH_NOT_FOUND", "message": "Current Codex auth not found"}
    }


def test_image_job_api_requires_auth_and_validates_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.post("/api/images/jobs", json={"prompt": "poster"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    response = client.post("/api/images/jobs", json={"prompt": " "})
    assert response.status_code == 400
    assert response.json() == {
        "detail": {"code": "IMAGE_PROMPT_REQUIRED", "message": "Prompt is required"}
    }

    response = client.get("/api/images/jobs/missing")
    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "IMAGE_JOB_NOT_FOUND", "message": "Image generation job not found"}
    }


def test_image_conversation_api_is_not_public(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    assert client.get("/api/images/conversations").status_code == 404
    assert client.post("/api/images/conversations").status_code == 404
    assert client.get("/api/images/conversations/missing/jobs").status_code == 404
    assert client.delete("/api/images/conversations/missing").status_code == 404


def test_image_job_api_paginates_global_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    settings = client.app.state.settings
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_conversations (id, title, created_at, updated_at)
            VALUES ('legacy-conversation', 'Legacy', 0, 0)
            """
        )
        for index in range(5):
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, conversation_id, prompt, model, size, quality, response_format, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, NULL, '1024x1024', 'auto', 'b64_json', 'succeeded', ?, ?)
                """,
                (
                    f"job-{index}",
                    "legacy-conversation" if index == 0 else None,
                    f"Prompt {index}",
                    index,
                    index,
                ),
            )

    first_page = client.get("/api/images/jobs", params={"page": 1, "limit": 3})
    second_page = client.get("/api/images/jobs", params={"page": 2, "limit": 3})
    bad_page = client.get("/api/images/jobs", params={"page": 0})

    assert first_page.status_code == 200
    assert first_page.json()["total_count"] == 5
    assert "result" not in first_page.json()["items"][0]
    assert "references" not in first_page.json()["items"][0]
    assert [item["id"] for item in first_page.json()["items"]] == [
        "job-4",
        "job-3",
        "job-2",
    ]
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [
        "job-1",
        "job-0",
    ]
    assert bad_page.status_code == 400
    assert bad_page.json() == {
        "detail": {"code": "IMAGE_JOB_INVALID_PAGE", "message": "Image job page is invalid"}
    }


def test_image_job_status_api_returns_tracked_jobs_and_active_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    settings = client.app.state.settings
    failed_detail = issue_detail("IMAGE_GENERATION_FAILED", "Generation failed")
    with connect(settings.db_path) as conn:
        for job_id, status_value, created_at, error_json in [
            ("queued-old", "queued", 1, None),
            ("running-job", "running", 2, None),
            ("queued-new", "queued", 3, None),
            ("untracked-failed", "failed", 4, failed_detail.model_dump_json()),
            ("tracked-failed", "failed", 5, failed_detail.model_dump_json()),
        ]:
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, prompt, model, size, quality, response_format, status,
                    created_at, updated_at, error_json
                )
                VALUES (?, 'Prompt', NULL, '1024x1024', 'auto', 'b64_json', ?, ?, ?, ?)
                """,
                (job_id, status_value, created_at, created_at + 10, error_json),
            )

    response = client.get(
        "/api/images/jobs/statuses",
        params=[("ids", "tracked-failed"), ("ids", "queued-old")],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 5
    assert payload["active_count"] == 3
    assert [item["id"] for item in payload["items"]] == ["tracked-failed", "queued-new", "running-job", "queued-old"]
    assert payload["items"][0] == {
        "id": "tracked-failed",
        "status": "failed",
        "updated_at": 15,
        "position": None,
        "error": {"code": "IMAGE_GENERATION_FAILED", "message": "Generation failed"},
    }
    assert payload["items"][1]["position"] == 2
    assert payload["items"][3]["position"] == 1
    assert "untracked-failed" not in {item["id"] for item in payload["items"]}
    assert "prompt" not in payload["items"][0]
    assert "result" not in payload["items"][0]
    assert "references" not in payload["items"][0]


def test_image_gallery_api_paginates_by_image_slots(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    settings = client.app.state.settings
    old_result = ImageGenerationResponse(
        created=1776000000,
        model="gpt-image-2",
        data=[ImageData(b64_json="aGVsbG8=", file_name=f"old-{index}.png") for index in range(4)],
    )
    new_result = ImageGenerationResponse(
        created=1776000001,
        model="gpt-image-2",
        data=[ImageData(b64_json="aGVsbG8=", file_name="new-0.png")],
    )
    image_dir = settings.db_path.parent / "images"
    image_dir.mkdir(parents=True)
    (image_dir / image_thumbnail_filename("new-0.png")).write_bytes(b"thumbnail")
    with connect(settings.db_path) as conn:
        for job_id, prompt, n, created_at, result in [
            ("old-job", "Old", 4, 1, old_result),
            ("new-job", "New", 1, 2, new_result),
        ]:
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, prompt, model, size, quality, response_format, status,
                    n, result_json, created_at, updated_at
                )
                VALUES (?, ?, NULL, '1024x1024', 'auto', 'b64_json', 'succeeded', ?, ?, ?, ?)
                """,
                (job_id, prompt, n, result.model_dump_json(), created_at, created_at),
            )

    first_page = client.get("/api/images/gallery", params={"page": 1, "limit": 3})
    second_page = client.get("/api/images/gallery", params={"page": 2, "limit": 3})

    assert first_page.status_code == 200
    assert first_page.json()["total_count"] == 5
    assert [(item["job"]["id"], item["image_index"]) for item in first_page.json()["items"]] == [
        ("new-job", 0),
        ("old-job", 0),
        ("old-job", 1),
    ]
    assert "result" not in first_page.json()["items"][0]["job"]
    assert first_page.json()["items"][0]["image"] == {
        "url": None,
        "revised_prompt": None,
        "file_name": "new-0.png",
        "file_url": None,
        "thumbnail_url": None,
        "width": None,
        "height": None,
        "size_bytes": None,
        "duration_seconds": None,
    }
    assert second_page.status_code == 200
    assert [(item["job"]["id"], item["image_index"]) for item in second_page.json()["items"]] == [
        ("old-job", 2),
        ("old-job", 3),
    ]


def test_migrate_image_storage_layout_moves_files_updates_db_and_creates_thumbnails(monkeypatch, tmp_path, capsys) -> None:
    data_dir = tmp_path / "switchboard-data"
    image_dir = data_dir / "images"
    codex_home = tmp_path / "codex"
    image_dir.mkdir(parents=True)
    codex_home.mkdir()
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(data_dir))

    import config
    from db import init_db
    from scripts.migrate_image_storage_layout import main as migrate_main

    config.get_settings.cache_clear()
    settings = _settings(tmp_path, db_path=data_dir / "switchboard.sqlite", image_output_dir=image_dir)
    init_db(settings.db_path)
    result = ImageGenerationResponse(
        created=1776000000,
        model="gpt-image-2",
        data=[
            ImageData(
                file_name="existing.png",
                file_url="/api/images/files/existing.png",
                saved_path=str(image_dir / "existing.png"),
            )
        ],
    )
    long_task_dir = _task_dir("job-two", 2)
    long_output_name = f"{long_task_dir}/outputs/output-1-long.png"
    long_reference_name = f"{long_task_dir}/references/reference-1-long-ref.png"
    long_output_thumb = f"{long_task_dir}/derived/output-1-long.thumb.webp"
    long_reference_thumb = f"{long_task_dir}/derived/reference-1-long-ref.thumb.webp"
    long_result = ImageGenerationResponse(
        created=1776000001,
        model="gpt-image-2",
        data=[
            ImageData(
                file_name=long_output_name,
                file_url=f"/api/images/files/{long_output_name}",
                thumbnail_url=f"/api/images/files/{long_output_thumb}",
                saved_path=str(image_dir / long_output_name),
            )
        ],
    )
    (image_dir / "existing.png").write_bytes(base64.b64decode(VALID_PNG_B64))
    (image_dir / "ref.png").write_bytes(base64.b64decode(VALID_PNG_B64))
    (image_dir / image_thumbnail_filename("ref.png")).write_bytes(b"old-thumb")
    (image_dir / long_output_name).parent.mkdir(parents=True)
    (image_dir / long_output_name).write_bytes(base64.b64decode(VALID_PNG_B64))
    (image_dir / long_reference_name).parent.mkdir(parents=True)
    (image_dir / long_reference_name).write_bytes(base64.b64decode(VALID_PNG_B64))
    (image_dir / long_output_thumb).parent.mkdir(parents=True)
    (image_dir / long_output_thumb).write_bytes(b"long-output-thumb")
    (image_dir / long_reference_thumb).parent.mkdir(parents=True, exist_ok=True)
    (image_dir / long_reference_thumb).write_bytes(b"long-reference-thumb")
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status,
                n, result_json, created_at, updated_at
            )
            VALUES ('job-one', 'Prompt', NULL, '1024x1024', 'auto', 'b64_json', 'succeeded', 1, ?, 1, 1)
            """,
            (result.model_dump_json(),),
        )
        conn.execute(
            """
            INSERT INTO image_job_references (
                id, job_id, position, original_file_name, mime_type, size_bytes, file_name, created_at
            )
            VALUES ('ref-one', 'job-one', 0, 'ref.png', 'image/png', 1, 'ref.png', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, prompt, model, size, quality, response_format, status,
                n, result_json, created_at, updated_at
            )
            VALUES ('job-two', 'Prompt two', NULL, '1024x1024', 'auto', 'b64_json', 'succeeded', 1, ?, 2, 2)
            """,
            (long_result.model_dump_json(),),
        )
        conn.execute(
            """
            INSERT INTO image_job_references (
                id, job_id, position, original_file_name, mime_type, size_bytes, file_name, created_at
            )
            VALUES ('ref-two', 'job-two', 0, 'long-ref.png', 'image/png', 1, ?, 2)
            """,
            (long_reference_name,),
        )

    assert migrate_main() == 0
    assert migrate_main() == 0
    output = capsys.readouterr().out

    assert "图片目录整理完成" in output
    assert not (image_dir / "existing.png").exists()
    assert not (image_dir / "ref.png").exists()
    task_dir = _task_dir("job-one", 1)
    assert (image_dir / task_dir / "outputs" / "o1.png").exists()
    assert (image_dir / task_dir / "references" / "r1.png").exists()
    assert (image_dir / task_dir / "derived" / image_thumbnail_filename("o1.png")).exists()
    assert (image_dir / task_dir / "derived" / image_thumbnail_filename("r1.png")).read_bytes() == b"old-thumb"
    assert not (image_dir / long_output_name).exists()
    assert not (image_dir / long_reference_name).exists()
    assert not (image_dir / long_output_thumb).exists()
    assert not (image_dir / long_reference_thumb).exists()
    assert (image_dir / long_task_dir / "outputs" / "o1.png").exists()
    assert (image_dir / long_task_dir / "references" / "r1.png").exists()
    assert (image_dir / long_task_dir / "derived" / "o1.thumb.webp").read_bytes() == b"long-output-thumb"
    assert (image_dir / long_task_dir / "derived" / "r1.thumb.webp").read_bytes() == b"long-reference-thumb"
    with connect(settings.db_path) as conn:
        stored_job = conn.execute("SELECT result_json FROM image_jobs WHERE id = 'job-one'").fetchone()
        stored_reference = conn.execute("SELECT file_name FROM image_job_references WHERE id = 'ref-one'").fetchone()
        stored_long_job = conn.execute("SELECT result_json FROM image_jobs WHERE id = 'job-two'").fetchone()
        stored_long_reference = conn.execute("SELECT file_name FROM image_job_references WHERE id = 'ref-two'").fetchone()
    migrated_result = ImageGenerationResponse.model_validate_json(stored_job["result_json"])
    migrated_long_result = ImageGenerationResponse.model_validate_json(stored_long_job["result_json"])
    assert migrated_result.data[0].file_name == f"{task_dir}/outputs/o1.png"
    assert migrated_result.data[0].file_url == f"/api/images/files/{task_dir}/outputs/o1.png"
    assert migrated_result.data[0].thumbnail_url == f"/api/images/files/{task_dir}/derived/o1.thumb.webp"
    assert stored_reference["file_name"] == f"{task_dir}/references/r1.png"
    assert migrated_long_result.data[0].file_name == f"{long_task_dir}/outputs/o1.png"
    assert migrated_long_result.data[0].thumbnail_url == f"/api/images/files/{long_task_dir}/derived/o1.thumb.webp"
    assert stored_long_reference["file_name"] == f"{long_task_dir}/references/r1.png"


def test_migrate_image_storage_layout_reports_missing_tables(monkeypatch, tmp_path, capsys) -> None:
    data_dir = tmp_path / "empty-data"
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(data_dir))

    import config
    from scripts.migrate_image_storage_layout import main as migrate_main

    config.get_settings.cache_clear()

    assert migrate_main() == 1
    captured = capsys.readouterr()

    assert "当前数据库缺少表 image_jobs, image_job_references" in captured.err
    assert str(data_dir / "switchboard.sqlite") in captured.err


def test_image_file_api_requires_auth_and_serves_saved_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DATA_DIR", str(tmp_path / "switchboard-data"))
    (tmp_path / "codex").mkdir()
    image_dir = tmp_path / "switchboard-data" / "images"
    sample_path = image_dir / "2026" / "05" / "job-one" / "outputs" / "sample.png"
    sample_path.parent.mkdir(parents=True)
    sample_path.write_bytes(b"image-bytes")

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.get("/api/images/files/2026/05/job-one/outputs/sample.png").status_code == 401
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    response = client.get("/api/images/files/2026/05/job-one/outputs/sample.png")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert client.get("/api/images/files/generated/sample.png").status_code == 400
    assert client.get("/api/images/files/2026/05/job-one/unknown/sample.png").status_code == 400
    assert client.get("/api/images/files/2026/05/job-one/outputs/%2E%2E/sample.png").status_code == 400
