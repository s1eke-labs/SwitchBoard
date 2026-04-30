from __future__ import annotations

import asyncio
import base64
import importlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Settings
from db import connect, init_db
from images import (
    ImageData,
    ImageGenerationError,
    ImageGenerationQueue,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageReferenceInput,
    build_upstream_payload,
    generate_image,
)
from issues import issue_detail

PNG_BYTES = b"\x89PNG\r\n\x1a\nreference"
PNG_B64 = "iVBORw0KGgpyZWZlcmVuY2U="


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
                "quality": "high",
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
    assert result.data[0].saved_path
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
    assert "action" not in tool
    assert payload["store"] is False


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
    ("payload", "code"),
    [
        (ImageGenerationRequest(prompt=" "), "IMAGE_PROMPT_REQUIRED"),
        (ImageGenerationRequest(prompt="x", size="2048x2048"), "IMAGE_INVALID_SIZE"),
        (ImageGenerationRequest(prompt="x", quality="ultra"), "IMAGE_INVALID_QUALITY"),
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
    assert recent[0].id == second.id
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
    assert restored_job.references[0].file_url == f"/api/images/files/{restored_job.references[0].file_name}"
    assert (settings.db_path.parent / "images" / restored_job.references[0].file_name).read_bytes() == PNG_BYTES
    await restored.close()


def test_image_migration_moves_legacy_jobs_to_history_conversation(tmp_path) -> None:
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
        conversation = conn.execute("SELECT title FROM image_conversations WHERE id = ?", (job["conversation_id"],)).fetchone()

    assert job["conversation_id"] == "legacy-image-history"
    assert conversation["title"] == "Image history"


@pytest.mark.asyncio
async def test_image_generation_queue_keeps_sessions_without_auto_chaining_responses(tmp_path) -> None:
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
    assert first_done.conversation_id is not None
    assert first_done.upstream_response_id == "resp-base-image"

    second = await queue.enqueue(ImageGenerationRequest(prompt="failed edit", conversation_id=first_done.conversation_id))
    for _ in range(20):
        second_failed = await queue.get(second.id)
        if second_failed is not None and second_failed.status == "failed":
            break
        await asyncio.sleep(0.01)

    third = await queue.enqueue(ImageGenerationRequest(prompt="final edit", conversation_id=first_done.conversation_id))
    for _ in range(20):
        third_done = await queue.get(third.id)
        if third_done is not None and third_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    second_failed = await queue.get(second.id)
    third_done = await queue.get(third.id)
    assert second_failed is not None
    assert second_failed.previous_response_id is None
    assert second_failed.upstream_response_id is None
    assert third_done is not None
    assert third_done.previous_response_id is None
    assert [payload.previous_response_id for payload in captured] == [None, None, None]
    await queue.close()


@pytest.mark.asyncio
async def test_image_generation_queue_lists_jobs_by_conversation(tmp_path) -> None:
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
    other = await queue.enqueue(ImageGenerationRequest(prompt="other", conversation_id=None))
    for _ in range(20):
        other_done = await queue.get(other.id)
        if other_done is not None and other_done.status == "succeeded":
            break
        await asyncio.sleep(0.01)

    first_done = await queue.get(first.id)
    assert first_done is not None
    jobs = await queue.list_for_conversation(first_done.conversation_id or "")

    assert [job.id for job in jobs] == [first.id, other.id]
    await queue.close()


def test_image_api_requires_auth_and_reports_missing_auth(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
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
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
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


def test_image_conversation_api_requires_auth_and_lists_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.get("/api/images/conversations").status_code == 401
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    created = client.post("/api/images/conversations")
    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == "New image session"
    assert conversation["job_count"] == 0

    listed = client.get("/api/images/conversations")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == conversation["id"]
    assert listed.json()["total_count"] == 1

    bad_page = client.get("/api/images/conversations", params={"page": 0})
    assert bad_page.status_code == 400
    assert bad_page.json() == {
        "detail": {"code": "IMAGE_CONVERSATION_INVALID_PAGE", "message": "Image conversation page is invalid"}
    }

    jobs = client.get(f"/api/images/conversations/{conversation['id']}/jobs")
    assert jobs.status_code == 200
    assert jobs.json() == []

    missing = client.get("/api/images/conversations/missing/jobs")
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": {"code": "IMAGE_CONVERSATION_NOT_FOUND", "message": "Image conversation not found"}
    }


def test_image_conversation_api_paginates(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    settings = client.app.state.settings
    with connect(settings.db_path) as conn:
        for index in range(5):
            conn.execute(
                """
                INSERT INTO image_conversations (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (f"conversation-{index}", f"Conversation {index}", index, index),
            )

    first_page = client.get("/api/images/conversations", params={"page": 1, "limit": 3})
    second_page = client.get("/api/images/conversations", params={"page": 2, "limit": 3})

    assert first_page.status_code == 200
    assert first_page.json()["total_count"] == 5
    assert [item["id"] for item in first_page.json()["items"]] == [
        "conversation-4",
        "conversation-3",
        "conversation-2",
    ]
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == [
        "conversation-1",
        "conversation-0",
    ]


def test_image_conversation_delete_api_removes_history_and_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.delete("/api/images/conversations/gone").status_code == 401
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200
    assert client.delete("/api/images/conversations/gone").status_code == 404

    settings = client.app.state.settings
    image_dir = tmp_path / "images"
    image_dir.mkdir(exist_ok=True)
    generated_path = image_dir / "generated.png"
    reference_path = image_dir / "reference.png"
    generated_path.write_bytes(b"generated")
    reference_path.write_bytes(b"reference")
    result = ImageGenerationResponse(
        created=1776000000,
        model="gpt-image-2",
        data=[ImageData(file_name="generated.png", file_url="/api/images/files/generated.png")],
    )
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO image_conversations (id, title, created_at, updated_at)
            VALUES ('delete-me', 'Delete me', 1, 2)
            """
        )
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, conversation_id, prompt, model, size, quality, response_format, status,
                created_at, updated_at, result_json
            )
            VALUES (
                'job-delete', 'delete-me', 'poster', NULL, '1024x1024', 'auto',
                'b64_json', 'succeeded', 1, 2, ?
            )
            """,
            (result.model_dump_json(),),
        )
        conn.execute(
            """
            INSERT INTO image_job_references (
                id, job_id, position, original_file_name, mime_type, size_bytes, file_name, created_at
            )
            VALUES ('ref-delete', 'job-delete', 0, 'ref.png', 'image/png', 9, 'reference.png', 1)
            """
        )

    response = client.delete("/api/images/conversations/delete-me")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert generated_path.exists() is False
    assert reference_path.exists() is False
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT 1 FROM image_conversations WHERE id = 'delete-me'").fetchone() is None
        assert conn.execute("SELECT 1 FROM image_jobs WHERE id = 'job-delete'").fetchone() is None
        assert conn.execute("SELECT 1 FROM image_job_references WHERE id = 'ref-delete'").fetchone() is None
    listed = client.get("/api/images/conversations", params={"page": 1, "limit": 3})
    assert listed.status_code == 200
    assert listed.json()["total_count"] == 0


def test_image_conversation_delete_api_rejects_active_jobs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
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
            VALUES ('active-conversation', 'Active', 1, 2)
            """
        )
        conn.execute(
            """
            INSERT INTO image_jobs (
                id, conversation_id, prompt, model, size, quality, response_format, status,
                created_at, updated_at
            )
            VALUES (
                'active-job', 'active-conversation', 'poster', NULL, '1024x1024', 'auto',
                'b64_json', 'queued', 1, 2
            )
            """
        )

    response = client.delete("/api/images/conversations/active-conversation")

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "IMAGE_CONVERSATION_ACTIVE_JOBS", "message": "Image conversation has active jobs"}
    }
    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT 1 FROM image_conversations WHERE id = 'active-conversation'").fetchone() is not None
        assert conn.execute("SELECT 1 FROM image_jobs WHERE id = 'active-job'").fetchone() is not None


def test_image_file_api_requires_auth_and_serves_saved_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("SWITCHBOARD_DB", str(tmp_path / "switchboard.sqlite"))
    (tmp_path / "codex").mkdir()
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "sample.png").write_bytes(b"image-bytes")

    import config

    config.get_settings.cache_clear()
    import main

    importlib.reload(main)
    client = TestClient(main.create_app())

    assert client.get("/api/images/files/sample.png").status_code == 401
    assert client.post("/api/auth/login", json={"password": "secret"}).status_code == 200

    response = client.get("/api/images/files/sample.png")

    assert response.status_code == 200
    assert response.content == b"image-bytes"
