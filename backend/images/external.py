from __future__ import annotations

import asyncio
import base64
import binascii
import json
import mimetypes
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx

from config import Settings
from db import connect
from issues import issue_detail
from vault_crypto import decrypt_auth, encrypt_auth
from version import __version__
from .models import (
    ImageData,
    ImageDispatcherActionResponse,
    ImageDispatcherTestRequest,
    ImageExternalResultImage,
    ImageExternalResultPayload,
    ImageJobSubmitPayload,
    ImageJobSubmitRequest,
    ImageTaskDispatcherSettingsRequest,
    ImageTaskDispatcherSettingsResponse,
    ImageWorkerStatusResponse,
)
from .submission import ImageJobSubmission
from .storage import image_file_path
from .upstream import _debug_log, _json_for_debug


TOKEN_FILE_NAME = "image-task-dispatcher-token.json"
SENSITIVE_DEBUG_KEYS = {
    "authorization",
    "access_token",
    "token",
    "b64_json",
    "image_url",
    "presigned_url",
    "signed_url",
}


def _now() -> int:
    return int(time.time())


def _redact_error(exc: Exception) -> str:
    lines = str(exc).splitlines()
    message = (lines[0] if lines else exc.__class__.__name__)[:500]
    for marker in ("Authorization", "access_token", "token="):
        message = message.replace(marker, "[redacted]")
    return message


def _vault_token_path(settings: Settings) -> Path:
    root = settings.auth_vault_dir or settings.db_path.parent / "auth-vault"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root / TOKEN_FILE_NAME


def _write_token(settings: Settings, token: str) -> None:
    path = _vault_token_path(settings)
    payload = encrypt_auth(settings, {"token": token})
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _read_token(settings: Settings) -> str | None:
    path = _vault_token_path(settings)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = decrypt_auth(settings, payload)
    token = value.get("token")
    return token if isinstance(token, str) and token else None


def _token_preview(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:2]}...{token[-4:]}"


def _external_value_for_debug(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, child in value.items():
            lowered = key.lower()
            if lowered in SENSITIVE_DEBUG_KEYS or lowered.endswith("_token"):
                redacted[key] = "[redacted]"
            elif lowered in {"url", "file_url"} and isinstance(child, str):
                redacted[key] = child.partition("?")[0] + ("?[query redacted]" if "?" in child else "")
            else:
                redacted[key] = _external_value_for_debug(child)
        return redacted
    if isinstance(value, list):
        return [_external_value_for_debug(item) for item in value]
    return value


class ExternalImageTaskDispatcherAdapter:
    def __init__(self, settings: Settings, submission: ImageJobSubmission, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.submission = submission
        self._transport = transport
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    def get_settings(self) -> ImageTaskDispatcherSettingsResponse:
        with connect(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM image_task_dispatcher_config WHERE id = 1").fetchone()
        token = _read_token(self.settings)
        if row is None:
            return ImageTaskDispatcherSettingsResponse(configured=False)
        return ImageTaskDispatcherSettingsResponse(
            configured=bool(row["name"] and row["api_base_url"] and token),
            name=str(row["name"]) if row["name"] else None,
            api_base_url=str(row["api_base_url"]) if row["api_base_url"] else None,
            token={"configured": bool(token), "preview": _token_preview(token)},
            paused=bool(row["paused"]),
            external_runner_id=str(row["runner_id"]) if row["runner_id"] else None,
            external_runner_status=str(row["runner_status"] or "unconfigured"),
            external_heartbeat_interval_seconds=int(row["heartbeat_interval_seconds"]) if row["heartbeat_interval_seconds"] else None,
            external_poll_interval_seconds=int(row["poll_interval_seconds"]) if row["poll_interval_seconds"] else None,
            external_last_heartbeat_at=int(row["last_heartbeat_at"]) if row["last_heartbeat_at"] else None,
            external_last_claim_at=int(row["last_claim_at"]) if row["last_claim_at"] else None,
            external_current_task_id=str(row["current_source_task_id"]) if row["current_source_task_id"] else None,
            external_last_error=str(row["last_error"]) if row["last_error"] else None,
        )

    async def save_settings(self, payload: ImageTaskDispatcherSettingsRequest) -> ImageTaskDispatcherSettingsResponse:
        name = payload.name.strip()
        api_base_url = payload.api_base_url.strip().rstrip("/")
        if not name or not api_base_url:
            raise ValueError("Task dispatcher name and API base URL are required")
        if payload.token is not None and payload.token.strip():
            _write_token(self.settings, payload.token.strip())
        now = _now()
        with connect(self.settings.db_path) as conn:
            conn.execute(
                """
                INSERT INTO image_task_dispatcher_config (
                    id, name, api_base_url, paused, runner_status, created_at, updated_at
                )
                VALUES (1, ?, ?, 0, 'registering', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    api_base_url = excluded.api_base_url,
                    paused = 0,
                    runner_status = 'registering',
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (name, api_base_url, now, now),
            )
        await self.register()
        await self.start()
        return self.get_settings()

    async def test(self, payload: ImageDispatcherTestRequest) -> ImageDispatcherActionResponse:
        settings = self.get_settings()
        base_url = (payload.api_base_url or settings.api_base_url or "").strip().rstrip("/")
        token = (payload.token or _read_token(self.settings) or "").strip()
        if not base_url or not token:
            raise ValueError("Task dispatcher API base URL and token are required")
        async with self._client(timeout=10) as client:
            response = await client.post(
                f"{base_url}/runners/register",
                headers={"Authorization": f"Bearer {token}"},
                json=self._registration_payload(payload.name or settings.name or "SwitchBoard", dry_run=True),
            )
            response.raise_for_status()
        return ImageDispatcherActionResponse(ok=True, settings=self.get_settings())

    async def register(self) -> ImageTaskDispatcherSettingsResponse:
        settings = self.get_settings()
        token = _read_token(self.settings)
        if not settings.api_base_url or not settings.name or not token:
            self._save_status("unconfigured", None)
            return self.get_settings()
        if settings.paused:
            self._save_status("paused", None)
            return self.get_settings()
        self._save_status("registering", None)
        try:
            async with self._client(timeout=15) as client:
                response = await client.post(
                    f"{settings.api_base_url.rstrip('/')}/runners/register",
                    headers={"Authorization": f"Bearer {token}"},
                    json=self._registration_payload(settings.name),
                )
                response.raise_for_status()
                data = response.json()
            self._save_registration(data)
        except httpx.HTTPStatusError as exc:
            status = "auth_failed" if exc.response.status_code in {401, 403} else "offline"
            self._save_status(status, _redact_error(exc))
        except Exception as exc:
            self._save_status("offline", _redact_error(exc))
        return self.get_settings()

    async def pause(self) -> ImageTaskDispatcherSettingsResponse:
        settings = self.get_settings()
        await self.close()
        last_error = None
        reported_at = None
        try:
            if await self._send_runner_status(settings, "offline"):
                reported_at = _now()
        except Exception as exc:
            last_error = _redact_error(exc)
        with connect(self.settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_task_dispatcher_config
                SET paused = 1, runner_status = 'paused',
                    last_heartbeat_at = COALESCE(?, last_heartbeat_at),
                    last_error = ?, updated_at = ?
                WHERE id = 1
                """,
                (reported_at, last_error, _now()),
            )
        return self.get_settings()

    async def resume(self) -> ImageTaskDispatcherSettingsResponse:
        with connect(self.settings.db_path) as conn:
            conn.execute(
                "UPDATE image_task_dispatcher_config SET paused = 0, runner_status = 'registering', updated_at = ? WHERE id = 1",
                (_now(),),
            )
        await self.register()
        await self.start()
        return self.get_settings()

    async def start(self) -> None:
        settings = self.get_settings()
        if not settings.configured or settings.paused:
            return
        if self._task is not None and not self._task.done():
            return
        self._closed = False
        self._task = asyncio.create_task(self._loop())

    async def close(self) -> None:
        self._closed = True
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while not self._closed:
            settings = self.get_settings()
            if not settings.configured or settings.paused:
                await asyncio.sleep(1)
                continue
            if not settings.external_runner_id or settings.external_runner_status != "online":
                await self.register()
                await asyncio.sleep(1)
                continue
            await self._heartbeat(settings)
            await self._claim_remote_tasks(settings)
            await self._report_pending_status_updates(settings)
            await self._deliver_pending_results(settings)
            await asyncio.sleep(max(1, settings.external_poll_interval_seconds or 10))

    async def _heartbeat(self, settings: ImageTaskDispatcherSettingsResponse) -> None:
        try:
            if not await self._send_runner_status(settings, "online"):
                return
            with connect(self.settings.db_path) as conn:
                conn.execute(
                    "UPDATE image_task_dispatcher_config SET last_heartbeat_at = ?, runner_status = 'online', last_error = NULL, updated_at = ? WHERE id = 1",
                    (_now(), _now()),
                )
        except Exception as exc:
            self._save_status("offline", _redact_error(exc))

    async def _send_runner_status(self, settings: ImageTaskDispatcherSettingsResponse, status: str) -> bool:
        token = _read_token(self.settings)
        if not token or not settings.api_base_url or not settings.external_runner_id:
            return False
        async with self._client(timeout=10) as client:
            response = await client.post(
                f"{settings.api_base_url.rstrip('/')}/runners/{settings.external_runner_id}/heartbeat",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "status": status,
                    "version": __version__,
                    "capabilities": {"image_generation": True},
                },
            )
            response.raise_for_status()
        return True

    async def _claim_remote_tasks(self, settings: ImageTaskDispatcherSettingsResponse) -> None:
        token = _read_token(self.settings)
        if not token or not settings.api_base_url or not settings.external_runner_id:
            return
        try:
            async with self._client(timeout=20) as client:
                response = await client.post(
                    f"{settings.api_base_url.rstrip('/')}/runners/{settings.external_runner_id}/tasks/claim",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"limit": 1},
                )
                response.raise_for_status()
                data = response.json()
            tasks = self._tasks_from_claim_response(data)
            _debug_log(
                self.settings,
                "dispatcher claim response tasks=%s payload=%s",
                len(tasks),
                _json_for_debug(_external_value_for_debug(data)),
            )
            for task in tasks:
                await self._submit_external_task(task)
            with connect(self.settings.db_path) as conn:
                conn.execute(
                    """
                    UPDATE image_task_dispatcher_config
                    SET last_claim_at = ?, current_source_task_id = ?, updated_at = ?
                    WHERE id = 1
                    """,
                    (_now(), str(tasks[0].get("source_task_id") or tasks[0].get("id")) if tasks else None, _now()),
                )
        except Exception as exc:
            self._save_status("offline", _redact_error(exc))

    async def _submit_external_task(self, task: dict[str, Any]) -> None:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else task
        source_task_id = str(task.get("source_task_id") or task.get("id") or "")
        idempotency_key = str(task.get("idempotency_key") or source_task_id)
        _debug_log(
            self.settings,
            "dispatcher task received source_task_id=%s idempotency_key=%s payload=%s",
            source_task_id,
            idempotency_key,
            _json_for_debug(_external_value_for_debug(payload)),
        )
        try:
            submit_payload = ImageJobSubmitPayload.model_validate(payload)
            _debug_log(
                self.settings,
                "dispatcher task normalized source_task_id=%s response_format=%s size=%s quality=%s n=%s",
                source_task_id,
                submit_payload.response_format,
                submit_payload.size,
                submit_payload.quality,
                submit_payload.n,
            )
            request = ImageJobSubmitRequest(
                source="external_dispatcher",
                source_task_id=source_task_id,
                idempotency_key=idempotency_key,
                queue=str(task.get("queue") or "default"),
                priority=str(task.get("priority") or "normal"),
                payload=submit_payload,
                metadata={"requester": str(task.get("requester") or ""), "trace_id": str(task.get("trace_id") or "")},
            )
            await self.submission.submit(request)
        except Exception as exc:
            self._record_external_claim_failure(task, source_task_id, idempotency_key, exc)
            _debug_log(
                self.settings,
                "dispatcher task submit failed source_task_id=%s error=%s payload=%s",
                source_task_id,
                _redact_error(exc),
                _json_for_debug(_external_value_for_debug(payload)),
            )

    async def _deliver_pending_results(self, settings: ImageTaskDispatcherSettingsResponse) -> None:
        token = _read_token(self.settings)
        if not token or not settings.api_base_url:
            return
        now = _now()
        with connect(self.settings.db_path) as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT * FROM image_submissions
                    WHERE source = 'external_dispatcher'
                      AND source_task_id IS NOT NULL
                      AND status IN ('succeeded', 'failed', 'canceled')
                      AND COALESCE(external_delivery_status, 'pending') != 'delivered'
                    ORDER BY updated_at ASC
                    LIMIT 5
                    """
                )
            )
        for submission in rows:
            if not self._delivery_retry_due(submission["external_delivery_error_json"], now):
                continue
            body = self._result_payload(str(submission["id"]))
            try:
                async with self._client(timeout=20) as client:
                    url = f"{settings.api_base_url.rstrip('/')}/tasks/{submission['source_task_id']}/result"
                    headers = {"Authorization": f"Bearer {token}"}
                    if body.get("status") == "succeeded":
                        response = await client.post(
                            url,
                            headers=headers,
                            data=self._result_form_fields(body),
                            files=self._result_image_files(str(submission["id"])),
                        )
                    else:
                        response = await client.post(url, headers=headers, json=body)
                    response.raise_for_status()
                with connect(self.settings.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE image_submissions
                        SET external_delivery_status = 'delivered',
                            external_delivery_error_json = NULL,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (_now(), submission["id"]),
                    )
                    conn.execute(
                        """
                        UPDATE image_jobs
                        SET external_delivery_status = 'delivered', external_delivery_error_json = NULL, updated_at = ?
                        WHERE submission_id = ?
                        """,
                        (_now(), submission["id"]),
                    )
            except Exception as exc:
                error_json = self._delivery_error_json(submission["external_delivery_error_json"], exc)
                with connect(self.settings.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE image_submissions
                        SET external_delivery_status = 'failed', external_delivery_error_json = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (error_json, _now(), submission["id"]),
            )

    async def _report_pending_status_updates(self, settings: ImageTaskDispatcherSettingsResponse) -> None:
        token = _read_token(self.settings)
        if not token or not settings.api_base_url:
            return
        now = _now()
        with connect(self.settings.db_path) as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, source_task_id, status, external_status_reported_status, external_status_report_error_json
                    FROM image_submissions
                    WHERE source = 'external_dispatcher'
                      AND source_task_id IS NOT NULL
                      AND (
                        COALESCE(external_status_reported_status, '') != status
                        OR external_status_report_error_json IS NOT NULL
                      )
                    ORDER BY updated_at ASC
                    LIMIT 10
                    """
                )
            )
        for submission in rows:
            if submission["external_status_reported_status"] == submission["status"] and not self._delivery_retry_due(
                submission["external_status_report_error_json"],
                now,
            ):
                continue
            body = self._status_payload(str(submission["id"]))
            try:
                async with self._client(timeout=10) as client:
                    response = await client.post(
                        f"{settings.api_base_url.rstrip('/')}/tasks/{submission['source_task_id']}/status",
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                    )
                    response.raise_for_status()
                with connect(self.settings.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE image_submissions
                        SET external_status_reported_status = ?,
                            external_status_reported_at = ?,
                            external_status_report_error_json = NULL
                        WHERE id = ?
                        """,
                        (submission["status"], _now(), submission["id"]),
                    )
            except Exception as exc:
                error_json = self._delivery_error_json(submission["external_status_report_error_json"], exc)
                with connect(self.settings.db_path) as conn:
                    conn.execute(
                        """
                        UPDATE image_submissions
                        SET external_status_report_error_json = ?
                        WHERE id = ?
                        """,
                        (error_json, submission["id"]),
                    )

    def _record_external_claim_failure(
        self,
        task: dict[str, Any],
        source_task_id: str,
        idempotency_key: str,
        exc: Exception,
    ) -> None:
        if not source_task_id:
            raise exc
        now = _now()
        detail = issue_detail("IMAGE_EXTERNAL_TASK_REJECTED", _redact_error(exc))
        metadata = {
            key: str(task.get(key) or "")[:512]
            for key in ("requester", "trace_id")
            if task.get(key) is not None
        }
        with connect(self.settings.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM image_submissions WHERE source = 'external_dispatcher' AND source_task_id = ?",
                (source_task_id,),
            ).fetchone()
            if existing is not None:
                return
            conn.execute(
                """
                INSERT OR IGNORE INTO image_submissions (
                    id, source, source_task_id, idempotency_key, queue, priority, status,
                    created_at, updated_at, external_delivery_status, error_json, metadata_json
                )
                VALUES (?, 'external_dispatcher', ?, ?, ?, 0, 'failed', ?, ?, 'pending', ?, ?)
                """,
                (
                    f"sub_{uuid.uuid4().hex}",
                    source_task_id,
                    idempotency_key or source_task_id,
                    str(task.get("queue") or "default"),
                    now,
                    now,
                    detail.model_dump_json(),
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                ),
            )

    def _status_payload(self, submission_id: str) -> dict[str, Any]:
        with connect(self.settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    s.id,
                    s.source_task_id,
                    s.status,
                    s.created_at,
                    s.updated_at,
                    s.error_json AS submission_error_json,
                    MIN(j.started_at) AS started_at,
                    MAX(j.finished_at) AS finished_at,
                    MAX(j.error_json) AS job_error_json
                FROM image_submissions s
                LEFT JOIN image_jobs j ON j.submission_id = s.id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (submission_id,),
            ).fetchone()
        if row is None:
            raise FileNotFoundError("External image submission is unavailable")
        body: dict[str, Any] = {
            "source_task_id": str(row["source_task_id"]),
            "submission_id": str(row["id"]),
            "status": str(row["status"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }
        if row["started_at"]:
            body["started_at"] = int(row["started_at"])
        if row["finished_at"]:
            body["finished_at"] = int(row["finished_at"])
        error_json = row["submission_error_json"] or row["job_error_json"]
        if error_json and row["status"] in {"failed", "canceled"}:
            with suppress(json.JSONDecodeError):
                body["error"] = json.loads(error_json)
        return body

    def _result_payload(self, submission_id: str) -> dict[str, Any]:
        with connect(self.settings.db_path) as conn:
            submission = conn.execute("SELECT * FROM image_submissions WHERE id = ?", (submission_id,)).fetchone()
            jobs = list(
                conn.execute(
                    "SELECT * FROM image_jobs WHERE submission_id = ? ORDER BY created_at ASC, rowid ASC",
                    (submission_id,),
                )
            )
        images: list[ImageExternalResultImage] = []
        upstream: dict[str, Any] = {}
        error = None
        for job in jobs:
            if job["result_json"]:
                from .models import ImageGenerationResponse

                result = ImageGenerationResponse.model_validate_json(job["result_json"])
                for index, item in enumerate(result.data):
                    images.append(
                        ImageExternalResultImage(
                            index=index,
                            file_url=item.file_url,
                            width=item.width,
                            height=item.height,
                            size_bytes=item.size_bytes,
                            duration_seconds=item.duration_seconds,
                        )
                    )
                if result.response_id:
                    upstream["response_id"] = result.response_id
            if job["error_json"] and error is None:
                error = json.loads(job["error_json"])
        if error is None and submission["error_json"]:
            error = json.loads(submission["error_json"])
        finished_at = (
            max(int(job["finished_at"] or job["updated_at"]) for job in jobs)
            if jobs
            else int(submission["updated_at"])
        )
        body = ImageExternalResultPayload(
            source_task_id=str(submission["source_task_id"]) if submission["source_task_id"] else None,
            submission_id=submission_id,
            status=submission["status"],
            created_at=int(submission["created_at"]),
            finished_at=finished_at,
        )
        if submission["status"] == "succeeded":
            body.images = images
            body.upstream = upstream
        elif submission["status"] in {"failed", "canceled"}:
            from issues import IssueDetail

            body.error = IssueDetail.model_validate(error or {"code": "IMAGE_UPSTREAM_ERROR", "message": "Image generation failed"})
        return body.model_dump(mode="json", exclude_none=True)

    def _result_form_fields(self, body: dict[str, Any]) -> dict[str, str]:
        fields: dict[str, str] = {}
        for key in ("source_task_id", "submission_id", "status", "created_at", "finished_at"):
            if body.get(key) is not None:
                fields[key] = str(body[key])
        upstream = body.get("upstream")
        if isinstance(upstream, dict) and upstream.get("response_id"):
            fields["upstream_response_id"] = str(upstream["response_id"])
        return fields

    def _result_image_files(self, submission_id: str) -> list[tuple[str, tuple[str, bytes, str]]]:
        with connect(self.settings.db_path) as conn:
            jobs = list(
                conn.execute(
                    "SELECT result_json FROM image_jobs WHERE submission_id = ? ORDER BY created_at ASC, rowid ASC",
                    (submission_id,),
                )
            )
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for job in jobs:
            if not job["result_json"]:
                continue
            from .models import ImageGenerationResponse

            result = ImageGenerationResponse.model_validate_json(job["result_json"])
            for index, item in enumerate(result.data):
                filename, content, content_type = self._result_image_part(item, index)
                files.append(("image", (filename, content, content_type)))
        if not files:
            raise FileNotFoundError("No generated image file is available for external delivery")
        return files

    def _result_image_part(self, item: ImageData, index: int) -> tuple[str, bytes, str]:
        filename = (
            Path(item.file_name or item.saved_path or f"result-{index + 1}.png").name
            or f"result-{index + 1}.png"
        )
        path: Path | None = None
        if item.file_name:
            with suppress(ValueError):
                path = image_file_path(self.settings, item.file_name)
        elif item.saved_path:
            path = Path(item.saved_path)
        if path is not None and path.exists():
            content = path.read_bytes()
        elif item.b64_json:
            try:
                content = base64.b64decode(item.b64_json, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Stored generated image data is invalid") from exc
        else:
            raise FileNotFoundError(f"Generated image file is unavailable: {filename}")
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return filename, content, content_type

    def _registration_payload(self, name: str, *, dry_run: bool = False) -> dict[str, Any]:
        return {
            "name": name,
            "version": __version__,
            "dry_run": dry_run,
            "capabilities": {
                "image_generation": True,
                "max_concurrency": self.settings.image_concurrency,
                "response_format": "b64_json",
            },
        }

    def _delivery_retry_due(self, error_json: str | None, now: int) -> bool:
        if not error_json:
            return True
        try:
            payload = json.loads(error_json)
        except json.JSONDecodeError:
            return True
        if not isinstance(payload, dict):
            return True
        next_retry_at = payload.get("next_retry_at")
        return not isinstance(next_retry_at, int) or next_retry_at <= now

    def _delivery_error_json(self, previous_error_json: str | None, exc: Exception) -> str:
        previous_attempts = 0
        if previous_error_json:
            try:
                previous = json.loads(previous_error_json)
            except json.JSONDecodeError:
                previous = {}
            if isinstance(previous, dict) and isinstance(previous.get("attempt_count"), int):
                previous_attempts = int(previous["attempt_count"])
        attempt_count = previous_attempts + 1
        delay_seconds = min(300, 2 ** min(attempt_count, 8))
        return json.dumps(
            {
                "message": _redact_error(exc),
                "attempt_count": attempt_count,
                "next_retry_at": _now() + delay_seconds,
            },
            ensure_ascii=False,
        )

    def _client(self, *, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _save_registration(self, data: dict[str, Any]) -> None:
        now = _now()
        with connect(self.settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_task_dispatcher_config
                SET runner_id = ?, runner_status = 'online',
                    heartbeat_interval_seconds = ?, poll_interval_seconds = ?,
                    last_error = NULL, updated_at = ?
                WHERE id = 1
                """,
                (
                    str(data.get("runner_id") or data.get("id") or ""),
                    int(data.get("heartbeat_interval_seconds") or data.get("heartbeat_interval") or 30),
                    int(data.get("poll_interval_seconds") or data.get("poll_interval") or 10),
                    now,
                ),
            )

    def _save_status(self, status: str, error: str | None) -> None:
        now = _now()
        with connect(self.settings.db_path) as conn:
            conn.execute(
                """
                INSERT INTO image_task_dispatcher_config (id, runner_status, last_error, created_at, updated_at)
                VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET runner_status = excluded.runner_status,
                    last_error = excluded.last_error, updated_at = excluded.updated_at
                """,
                (status, error, now, now),
            )

    def _tasks_from_claim_response(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            if isinstance(data.get("tasks"), list):
                return [item for item in data["tasks"] if isinstance(item, dict)]
            if isinstance(data.get("task"), dict):
                return [data["task"]]
        return []
