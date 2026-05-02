from __future__ import annotations

import asyncio
import base64
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress

from pydantic import ValidationError

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
    ImageGenerationJobStatusListResponse,
    ImageGenerationJobStatusResponse,
    ImageGenerationJobSummaryResponse,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageReferenceInput,
    ImageUpstreamMetadata,
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
    image_file_metadata,
    image_file_path,
)
from .upstream import generate_image
from .validation import _validate_payload, _validated_reference_images
from issues import IssueDetail, issue_detail

logger = logging.getLogger(__name__)


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


def _upstream_metadata_json(result: ImageGenerationResponse) -> str | None:
    if not result.upstream_metadata:
        return None
    return json.dumps(
        [item.model_dump(mode="json", exclude_none=True) for item in result.upstream_metadata],
        ensure_ascii=False,
    )


def _upstream_metadata_from_json(value: str | None) -> list[ImageUpstreamMetadata]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    metadata_items: list[ImageUpstreamMetadata] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            metadata_items.append(ImageUpstreamMetadata.model_validate(item))
        except ValidationError:
            continue
    return metadata_items


def _gallery_image_from_data(settings: Settings, data: ImageData | None) -> ImageGalleryImageResponse | None:
    if data is None:
        return None
    width = data.width
    height = data.height
    size_bytes = data.size_bytes
    if data.file_name and (width is None or height is None or size_bytes is None):
        with suppress(ValueError, OSError):
            metadata_width, metadata_height, metadata_size_bytes = image_file_metadata(image_file_path(settings, data.file_name))
            width = width if width is not None else metadata_width
            height = height if height is not None else metadata_height
            size_bytes = size_bytes if size_bytes is not None else metadata_size_bytes
    return ImageGalleryImageResponse(
        url=data.file_url or data.url,
        revised_prompt=data.revised_prompt,
        file_name=data.file_name,
        file_url=data.file_url,
        thumbnail_url=_thumbnail_url_for_data(settings, data),
        width=width,
        height=height,
        size_bytes=size_bytes,
        duration_seconds=data.duration_seconds,
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
        job_ids = [uuid.uuid4().hex for _ in range(payload.n)]
        async with self._lock:
            previous_response_id = payload.previous_response_id
            with connect(self._settings.db_path) as conn:
                for job_id in job_ids:
                    storage_context = ImageStorageContext(task_dir=_image_job_task_dir(job_id, now))
                    saved_references = [
                        _save_reference_file(self._settings, storage_context, reference, mime_type, data, now)
                        for reference, mime_type, data in references
                    ]
                    conn.execute(
                        """
                        INSERT INTO image_jobs (
                            id, conversation_id, prompt, model, size, quality, n, response_format, status,
                            created_at, updated_at, previous_response_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'queued', ?, ?, ?)
                        """,
                        (
                            job_id,
                            None,
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
            job = self._job_response_from_db(job_ids[0])
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

    async def stop_job(self, job_id: str) -> None:
        detail = issue_detail(
            "IMAGE_JOB_STOPPED",
            "Image generation was stopped by the user. Retry the job to generate again.",
        )
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                job = conn.execute("SELECT status FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
                if job is None:
                    raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
                if job["status"] not in {"queued", "running"}:
                    raise _image_error(409, "IMAGE_JOB_NOT_ACTIVE", "Image generation job is not active")
                conn.execute(
                    """
                    UPDATE image_jobs
                    SET status = 'failed', error_json = ?, updated_at = ?
                    WHERE id = ? AND status IN ('queued', 'running')
                    """,
                    (detail.model_dump_json(), int(time.time()), job_id),
                )

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

    async def list_statuses(self, tracked_job_ids: list[str] | None = None) -> ImageGenerationJobStatusListResponse:
        tracked_job_ids = list(dict.fromkeys(tracked_job_ids or []))
        async with self._lock:
            with connect(self._settings.db_path) as conn:
                total_count = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs").fetchone()["count"])
                active_count = int(
                    conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM image_jobs
                        WHERE status IN ('queued', 'running')
                        """
                    ).fetchone()["count"]
                )
                tracked_filter = ""
                params: tuple[str, ...] = ()
                if tracked_job_ids:
                    placeholders = ", ".join("?" for _ in tracked_job_ids)
                    tracked_filter = f" OR id IN ({placeholders})"
                    params = tuple(tracked_job_ids)
                rows = list(
                    conn.execute(
                        f"""
                        WITH queued_positions AS (
                            SELECT
                                id,
                                ROW_NUMBER() OVER (ORDER BY created_at ASC, rowid ASC) AS position
                            FROM image_jobs
                            WHERE status = 'queued'
                        ),
                        watched_jobs AS (
                            SELECT id, status, updated_at, error_json, created_at, rowid
                            FROM image_jobs
                            WHERE status IN ('queued', 'running') {tracked_filter}
                        )
                        SELECT
                            watched_jobs.id,
                            watched_jobs.status,
                            watched_jobs.updated_at,
                            watched_jobs.error_json,
                            queued_positions.position
                        FROM watched_jobs
                        LEFT JOIN queued_positions ON queued_positions.id = watched_jobs.id
                        ORDER BY watched_jobs.created_at DESC, watched_jobs.rowid DESC
                        """,
                        params,
                    )
                )
            return ImageGenerationJobStatusListResponse(
                items=[
                    ImageGenerationJobStatusResponse(
                        id=str(row["id"]),
                        status=row["status"],
                        updated_at=int(row["updated_at"]),
                        position=int(row["position"]) if row["position"] is not None else None,
                        error=IssueDetail.model_validate_json(row["error_json"]) if row["error_json"] else None,
                    )
                    for row in rows
                ],
                total_count=total_count,
                active_count=active_count,
            )

    async def list_gallery_items(self, page: int = 1, limit: int = 20) -> ImageGalleryListResponse:
        if page < 1:
            raise _image_error(400, "IMAGE_JOB_INVALID_PAGE", "Image job page is invalid")
        async with self._lock:
            start = (page - 1) * limit
            end = start + limit
            with connect(self._settings.db_path) as conn:
                total_count = int(
                    conn.execute(
                        """
                        WITH counted AS (
                            SELECT
                                CASE
                                    WHEN status IN ('queued', 'running') THEN max(
                                        n,
                                        COALESCE(json_array_length(result_json, '$.data'), 0),
                                        1
                                    )
                                    ELSE max(COALESCE(json_array_length(result_json, '$.data'), 0), 1)
                                END AS slot_count
                            FROM image_jobs
                        )
                        SELECT COALESCE(SUM(slot_count), 0) AS total_count
                        FROM counted
                        """
                    ).fetchone()["total_count"]
                )
                job_rows = list(
                    conn.execute(
                        """
                        WITH counted AS (
                            SELECT
                                rowid AS job_rowid,
                                id,
                                status,
                                n,
                                created_at,
                                CASE
                                    WHEN status IN ('queued', 'running') THEN max(
                                        n,
                                        COALESCE(json_array_length(result_json, '$.data'), 0),
                                        1
                                    )
                                    ELSE max(COALESCE(json_array_length(result_json, '$.data'), 0), 1)
                                END AS slot_count
                            FROM image_jobs
                        ),
                        positioned AS (
                            SELECT
                                id,
                                job_rowid,
                                status,
                                created_at,
                                slot_count,
                                COALESCE(
                                    SUM(slot_count) OVER (
                                        ORDER BY created_at DESC, job_rowid DESC
                                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                                    ),
                                    0
                                ) AS slot_start,
                                CASE
                                    WHEN status = 'queued' THEN
                                        SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END) OVER (
                                            ORDER BY created_at ASC, job_rowid ASC
                                            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                                        )
                                    ELSE NULL
                                END AS position
                            FROM counted
                        )
                        SELECT *
                        FROM positioned
                        WHERE slot_start < ? AND slot_start + slot_count > ?
                        ORDER BY created_at DESC, job_rowid DESC
                        """,
                        (end, start),
                    )
                )
                job_ids = [str(row["id"]) for row in job_rows]
                jobs_by_id: dict[str, sqlite3.Row] = {}
                references_by_job_id: dict[str, list[sqlite3.Row]] = {job_id: [] for job_id in job_ids}
                if references_by_job_id:
                    placeholders = ", ".join("?" for _ in references_by_job_id)
                    jobs_by_id = {
                        str(row["id"]): row
                        for row in conn.execute(
                            f"""
                            SELECT *
                            FROM image_jobs
                            WHERE id IN ({placeholders})
                            """,
                            tuple(references_by_job_id),
                        )
                    }
                    for row in conn.execute(
                        f"""
                        SELECT *
                        FROM image_job_references
                        WHERE job_id IN ({placeholders})
                        ORDER BY job_id ASC, position ASC
                        """,
                        tuple(references_by_job_id),
                    ):
                        references_by_job_id[str(row["job_id"])].append(row)
            items: list[ImageGalleryItemResponse] = []
            for row in job_rows:
                job_id = str(row["id"])
                job = jobs_by_id.get(job_id)
                if job is None:
                    continue
                result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
                error = IssueDetail.model_validate_json(job["error_json"]) if job["error_json"] else None
                upstream_metadata = _upstream_metadata_from_json(job["upstream_metadata_json"])
                gallery_job = ImageGalleryJobResponse(
                    id=job_id,
                    prompt=str(job["prompt"]),
                    size=str(job["size"]),
                    quality=str(job["quality"]),
                    n=int(job["n"]),
                    status=job["status"],
                    created_at=int(job["created_at"]),
                    updated_at=int(job["updated_at"]),
                    position=int(row["position"]) if row["position"] is not None else None,
                    references=[
                        _reference_from_row(self._settings, reference_row)
                        for reference_row in references_by_job_id[job_id]
                    ],
                    upstream_metadata=upstream_metadata,
                    error=error,
                )
                slot_start = int(row["slot_start"])
                slot_count = int(row["slot_count"])
                for image_index in range(slot_count):
                    absolute_index = slot_start + image_index
                    if start <= absolute_index < end:
                        image = result.data[image_index] if result and image_index < len(result.data) else None
                        items.append(
                            ImageGalleryItemResponse(
                                key=f"{job_id}:{image_index}",
                                job=gallery_job,
                                image_index=image_index,
                                image=_gallery_image_from_data(self._settings, image),
                            )
                        )
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
        detail = issue_detail(
            "IMAGE_JOB_INTERRUPTED",
            "Image generation was interrupted by a service restart. Retry the job to generate again.",
        )
        try:
            with connect(self._settings.db_path) as conn:
                conn.execute(
                    """
                    UPDATE image_jobs
                    SET status = 'failed', error_json = ?, updated_at = ?
                    WHERE status = 'running'
                    """,
                    (detail.model_dump_json(), now),
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
        upstream_metadata = _upstream_metadata_from_json(job["upstream_metadata_json"])
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
            upstream_metadata=upstream_metadata,
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
        upstream_metadata_json = _upstream_metadata_json(result)
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'succeeded', result_json = ?, error_json = NULL,
                    upstream_response_id = ?, upstream_metadata_json = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (stored_result.model_dump_json(), stored_result.response_id, upstream_metadata_json, now, job_id),
            )

    def _update_job_result(self, job_id: str, result: ImageGenerationResponse) -> None:
        now = int(time.time())
        stored_result = _response_for_storage(result)
        upstream_metadata_json = _upstream_metadata_json(result)
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET result_json = ?, error_json = NULL,
                    upstream_response_id = ?, upstream_metadata_json = COALESCE(?, upstream_metadata_json), updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (stored_result.model_dump_json(), stored_result.response_id, upstream_metadata_json, now, job_id),
            )

    def _fail_job(self, job_id: str, detail: IssueDetail) -> None:
        with connect(self._settings.db_path) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'failed', error_json = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
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
