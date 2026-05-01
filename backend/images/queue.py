from __future__ import annotations

import asyncio
import base64
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress

from config import Settings
from db import connect, init_db
from .models import (
    ImageData,
    ImageGalleryImageResponse,
    ImageGalleryItemResponse,
    ImageGalleryJobResponse,
    ImageGalleryListResponse,
    ImageGenerationError,
    ImageGenerationJobListResponse,
    ImageGenerationJobResponse,
    ImageGenerationJobSummaryResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageReferenceInput,
    _image_error,
)
from .storage import (
    ImageStorageContext,
    _delete_image_file,
    _delete_image_task_dir,
    _image_job_task_dir,
    _reference_from_row,
    _response_for_storage,
    _save_reference_file,
    _thumbnail_url_for_data,
    image_file_path,
)
from .upstream import generate_image
from .validation import _validate_payload, _validated_reference_images
from issues import IssueDetail, issue_detail

logger = logging.getLogger(__name__)


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


ImageGenerator = Callable[[Settings, ImageGenerationRequest], Awaitable[ImageGenerationResponse]]


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
