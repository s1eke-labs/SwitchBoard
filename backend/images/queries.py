from __future__ import annotations

import sqlite3
from contextlib import suppress

from config import Settings
from db import connect
from issues import IssueDetail
from .common import local_or_dispatcher_source, public_job_status, upstream_metadata_from_json
from .models import (
    ImageData,
    ImageGalleryImageResponse,
    ImageGalleryItemResponse,
    ImageGalleryJobResponse,
    ImageGalleryListResponse,
    ImageGenerationRequest,
    ImageGenerationJobListResponse,
    ImageGenerationJobResponse,
    ImageGenerationJobStatusListResponse,
    ImageGenerationJobStatusResponse,
    ImageGenerationJobSummaryResponse,
    ImageGenerationResponse,
    ImageReferenceInput,
    _image_error,
)
from .storage import (
    _reference_from_row,
    _thumbnail_url_for_data,
    image_file_metadata,
    image_file_path,
)


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


def _source_fields(row, dispatcher_labels: dict[str, str]) -> dict[str, str | None]:
    raw_source = str(row["source"] or "local_ui") if "source" in row.keys() else "local_ui"
    source = local_or_dispatcher_source(raw_source)
    if source == "external_dispatcher":
        dispatcher_id = str(row["dispatcher_id"] or "default") if "dispatcher_id" in row.keys() else "default"
        return {
            "source": "external_dispatcher",
            "source_label": dispatcher_labels.get(dispatcher_id, "任务分发方"),
            "dispatcher_id": dispatcher_id,
            "source_task_id": str(row["source_task_id"]) if row["source_task_id"] else None,
        }
    return {"source": "local", "source_label": "本地", "dispatcher_id": None, "source_task_id": None}


class ImageJobQueries:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def dispatcher_labels(self) -> dict[str, str]:
        with connect(self.settings.db_path) as conn:
            rows = list(conn.execute("SELECT id, name FROM image_task_dispatchers"))
        labels = {str(row["id"]): str(row["name"]) for row in rows if row["name"]}
        if "default" not in labels:
            with connect(self.settings.db_path) as conn:
                row = conn.execute("SELECT name FROM image_task_dispatcher_config WHERE id = 1").fetchone()
            if row is not None and row["name"]:
                labels["default"] = str(row["name"])
        return labels

    def dispatcher_label(self) -> str:
        return self.dispatcher_labels().get("default", "任务分发方")

    def get(self, job_id: str) -> ImageGenerationJobResponse | None:
        with connect(self.settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                return None
            reference_rows = list(
                conn.execute(
                    "SELECT * FROM image_job_references WHERE job_id = ? ORDER BY position ASC",
                    (job_id,),
                )
            )
            queued_rows = list(
                conn.execute("SELECT id FROM image_jobs WHERE status = 'queued' ORDER BY created_at ASC, rowid ASC")
            )
        position = None
        if job["status"] == "queued":
            queued_ids = [str(row["id"]) for row in queued_rows]
            with suppress(ValueError):
                position = queued_ids.index(job_id) + 1
        result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
        error = IssueDetail.model_validate_json(job["error_json"]) if job["error_json"] else None
        source_fields = _source_fields(job, self.dispatcher_labels())
        return ImageGenerationJobResponse(
            id=str(job["id"]),
            conversation_id=str(job["conversation_id"]) if job["conversation_id"] else None,
            prompt=str(job["prompt"]),
            size=str(job["size"]),
            quality=str(job["quality"]),
            n=int(job["n"]),
            status=public_job_status(str(job["status"])),
            created_at=int(job["created_at"]),
            updated_at=int(job["updated_at"]),
            previous_response_id=str(job["previous_response_id"]) if job["previous_response_id"] else None,
            upstream_response_id=str(job["upstream_response_id"]) if job["upstream_response_id"] else None,
            upstream_metadata=upstream_metadata_from_json(job["upstream_metadata_json"]),
            position=position,
            references=[_reference_from_row(self.settings, row) for row in reference_rows],
            result=result,
            error=error,
            submission_id=str(job["submission_id"]) if job["submission_id"] else None,
            **source_fields,
        )

    def list_recent(self, page: int = 1, limit: int = 20) -> ImageGenerationJobListResponse:
        if page < 1:
            raise _image_error(400, "IMAGE_JOB_INVALID_PAGE", "Image job page is invalid")
        offset = (page - 1) * limit
        with connect(self.settings.db_path) as conn:
            total_count = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs").fetchone()["count"])
            job_ids = [
                str(row["id"])
                for row in conn.execute(
                    "SELECT id FROM image_jobs ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
        return ImageGenerationJobListResponse(
            items=[self._summary_from_job(job) for job_id in job_ids if (job := self.get(job_id)) is not None],
            total_count=total_count,
        )

    def list_statuses(self, tracked_job_ids: list[str] | None = None) -> ImageGenerationJobStatusListResponse:
        tracked_job_ids = list(dict.fromkeys(tracked_job_ids or []))
        with connect(self.settings.db_path) as conn:
            total_count = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs").fetchone()["count"])
            active_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS count FROM image_jobs WHERE status IN ('queued', 'leased', 'running')"
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
                        SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC, rowid ASC) AS position
                        FROM image_jobs
                        WHERE status = 'queued'
                    ),
                    watched_jobs AS (
                        SELECT id, status, updated_at, error_json, created_at, rowid
                        FROM image_jobs
                        WHERE status IN ('queued', 'leased', 'running') {tracked_filter}
                    )
                    SELECT watched_jobs.id, watched_jobs.status, watched_jobs.updated_at,
                           watched_jobs.error_json, queued_positions.position
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
                    status=public_job_status(str(row["status"])),
                    updated_at=int(row["updated_at"]),
                    position=int(row["position"]) if row["position"] is not None else None,
                    error=IssueDetail.model_validate_json(row["error_json"]) if row["error_json"] else None,
                )
                for row in rows
            ],
            total_count=total_count,
            active_count=active_count,
        )

    def list_gallery_items(self, page: int = 1, limit: int = 20, source: str = "all") -> ImageGalleryListResponse:
        if page < 1:
            raise _image_error(400, "IMAGE_JOB_INVALID_PAGE", "Image job page is invalid")
        start = (page - 1) * limit
        end = start + limit
        where_sql, where_params = self._source_where(source)
        with connect(self.settings.db_path) as conn:
            total_count = int(
                conn.execute(
                    f"""
                    WITH counted AS (
                        SELECT
                            CASE
                                WHEN status IN ('queued', 'leased', 'running') THEN max(
                                    n,
                                    COALESCE(json_array_length(result_json, '$.data'), 0),
                                    1
                                )
                                ELSE max(COALESCE(json_array_length(result_json, '$.data'), 0), 1)
                            END AS slot_count
                        FROM image_jobs
                        {where_sql}
                    )
                    SELECT COALESCE(SUM(slot_count), 0) AS total_count
                    FROM counted
                    """,
                    where_params,
                ).fetchone()["total_count"]
            )
            job_rows = list(
                conn.execute(
                    f"""
                    WITH counted AS (
                        SELECT
                            rowid AS job_rowid,
                            id,
                            status,
                            n,
                            created_at,
                            CASE
                                WHEN status IN ('queued', 'leased', 'running') THEN max(
                                    n,
                                    COALESCE(json_array_length(result_json, '$.data'), 0),
                                    1
                                )
                                ELSE max(COALESCE(json_array_length(result_json, '$.data'), 0), 1)
                            END AS slot_count
                        FROM image_jobs
                        {where_sql}
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
                    (*where_params, end, start),
                )
            )
            job_ids = [str(row["id"]) for row in job_rows]
            jobs_by_id: dict[str, sqlite3.Row] = {}
            references_by_job_id: dict[str, list[sqlite3.Row]] = {job_id: [] for job_id in job_ids}
            if references_by_job_id:
                placeholders = ", ".join("?" for _ in references_by_job_id)
                jobs_by_id = {
                    str(row["id"]): row
                    for row in conn.execute(f"SELECT * FROM image_jobs WHERE id IN ({placeholders})", tuple(references_by_job_id))
                }
                for row in conn.execute(
                    f"SELECT * FROM image_job_references WHERE job_id IN ({placeholders}) ORDER BY job_id ASC, position ASC",
                    tuple(references_by_job_id),
                ):
                    references_by_job_id[str(row["job_id"])].append(row)
        dispatcher_labels = self.dispatcher_labels()
        items: list[ImageGalleryItemResponse] = []
        for row in job_rows:
            job_id = str(row["id"])
            job = jobs_by_id.get(job_id)
            if job is None:
                continue
            result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
            error = IssueDetail.model_validate_json(job["error_json"]) if job["error_json"] else None
            gallery_job = ImageGalleryJobResponse(
                id=job_id,
                prompt=str(job["prompt"]),
                size=str(job["size"]),
                quality=str(job["quality"]),
                n=int(job["n"]),
                status=public_job_status(str(job["status"])),
                created_at=int(job["created_at"]),
                updated_at=int(job["updated_at"]),
                position=int(row["position"]) if row["position"] is not None else None,
                references=[_reference_from_row(self.settings, reference_row) for reference_row in references_by_job_id[job_id]],
                upstream_metadata=upstream_metadata_from_json(job["upstream_metadata_json"]),
                error=error,
                submission_id=str(job["submission_id"]) if job["submission_id"] else None,
                **_source_fields(job, dispatcher_labels),
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
                            image=_gallery_image_from_data(self.settings, image),
                        )
                    )
        return ImageGalleryListResponse(items=items, total_count=total_count)

    def payload_from_job_id(self, job_id: str) -> ImageGenerationRequest:
        import base64

        with connect(self.settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            reference_rows = list(
                conn.execute(
                    "SELECT * FROM image_job_references WHERE job_id = ? ORDER BY position ASC",
                    (job_id,),
                )
            )
        if job is None:
            raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
        references = []
        for row in reference_rows:
            path = image_file_path(self.settings, str(row["file_name"]))
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

    def _summary_from_job(self, job: ImageGenerationJobResponse) -> ImageGenerationJobSummaryResponse:
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
            submission_id=job.submission_id,
            source=job.source,
            source_label=job.source_label,
            dispatcher_id=job.dispatcher_id,
            source_task_id=job.source_task_id,
        )

    def _source_where(self, source: str) -> tuple[str, tuple[str, ...]]:
        if source in {"", "all"}:
            return "", ()
        if source == "local":
            return "WHERE source != 'external_dispatcher'", ()
        if source.startswith("dispatcher:"):
            dispatcher_id = source.split(":", 1)[1].strip()
            if not dispatcher_id:
                raise _image_error(400, "IMAGE_SUBMISSION_INVALID", "Image source filter is invalid")
            return "WHERE source = 'external_dispatcher' AND dispatcher_id = ?", (dispatcher_id,)
        raise _image_error(400, "IMAGE_SUBMISSION_INVALID", "Image source filter is invalid")
