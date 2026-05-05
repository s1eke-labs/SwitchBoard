from __future__ import annotations

import json
import time
import uuid

from config import Settings
from db import connect
from .common import priority_value
from .models import (
    ImageJobSubmitRequest,
    ImageJobSubmitResponse,
    _image_error,
)
from .storage import ImageStorageContext, _image_job_task_dir, _save_reference_file
from .validation import _validate_payload, _validated_reference_images


SAFE_METADATA_KEYS = {"requester", "trace_id", "dispatcher", "queue", "client"}


def _sanitized_metadata(value: dict[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, item in value.items():
        if key not in SAFE_METADATA_KEYS:
            continue
        if isinstance(item, str):
            sanitized[key] = item[:512]
        elif isinstance(item, (int, float, bool)) or item is None:
            sanitized[key] = item
    return sanitized


class ImageJobSubmission:
    def __init__(self, settings: Settings, notify_new_job=None) -> None:
        self.settings = settings
        self._notify_new_job = notify_new_job

    async def submit(self, request: ImageJobSubmitRequest) -> ImageJobSubmitResponse:
        payload = request.payload.to_generation_request()
        _validate_payload(self.settings, payload)
        references = _validated_reference_images(payload)
        if request.source == "external_dispatcher" and not request.source_task_id:
            raise _image_error(400, "IMAGE_SUBMISSION_INVALID", "External dispatcher submissions require source_task_id")
        dispatcher_id = (request.dispatcher_id or "default").strip() if request.source == "external_dispatcher" else None
        if request.source == "external_dispatcher" and not dispatcher_id:
            raise _image_error(400, "IMAGE_SUBMISSION_INVALID", "External dispatcher id is required")
        if not request.idempotency_key.strip():
            raise _image_error(400, "IMAGE_SUBMISSION_INVALID", "Image submission is invalid")
        if request.queue != "default":
            raise _image_error(403, "IMAGE_SUBMISSION_FORBIDDEN", "Image submission queue is not allowed")

        now = int(time.time())
        priority = priority_value(request.priority)
        metadata_json = json.dumps(_sanitized_metadata(request.metadata), ensure_ascii=False) if request.metadata else None
        source_task_id = request.source_task_id.strip() if request.source_task_id else None
        idempotency_key = request.idempotency_key.strip()

        with connect(self.settings.db_path) as conn:
            existing = conn.execute(
                """
                SELECT id FROM image_submissions
                WHERE source = ? AND idempotency_key = ?
                  AND COALESCE(dispatcher_id, '') = COALESCE(?, '')
                """,
                (request.source, idempotency_key, dispatcher_id),
            ).fetchone()
            if existing is not None:
                submission_id = str(existing["id"])
                job_ids = [
                    str(row["id"])
                    for row in conn.execute(
                        "SELECT id FROM image_jobs WHERE submission_id = ? ORDER BY created_at ASC, rowid ASC",
                        (submission_id,),
                    )
                ]
                return ImageJobSubmitResponse(submission_id=submission_id, job_ids=job_ids, created=False)
            if source_task_id:
                conflict = conn.execute(
                    """
                    SELECT id FROM image_submissions
                    WHERE source = ? AND source_task_id = ?
                      AND COALESCE(dispatcher_id, '') = COALESCE(?, '')
                    """,
                    (request.source, source_task_id, dispatcher_id),
                ).fetchone()
                if conflict is not None:
                    raise _image_error(409, "IMAGE_SUBMISSION_CONFLICT", "Image submission conflicts with an existing task")

            submission_id = f"sub_{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO image_submissions (
                    id, source, dispatcher_id, source_task_id, idempotency_key, queue, priority, status,
                    created_at, updated_at, external_delivery_status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    request.source,
                    dispatcher_id,
                    source_task_id,
                    idempotency_key,
                    request.queue,
                    priority,
                    now,
                    now,
                    "pending" if request.source == "external_dispatcher" else None,
                    metadata_json,
                ),
            )
            job_ids = [uuid.uuid4().hex for _ in range(payload.n)]
            previous_response_id = payload.previous_response_id
            for job_id in job_ids:
                storage_context = ImageStorageContext(task_dir=_image_job_task_dir(job_id, now))
                saved_references = [
                    _save_reference_file(self.settings, storage_context, reference, mime_type, data, now)
                    for reference, mime_type, data in references
                ]
                conn.execute(
                    """
                    INSERT INTO image_jobs (
                        id, submission_id, conversation_id, prompt, model, size, quality, n, response_format,
                        status, created_at, updated_at, previous_response_id, source, dispatcher_id, source_task_id,
                        idempotency_key, priority, external_delivery_status
                    )
                    VALUES (?, ?, NULL, ?, ?, ?, ?, 1, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        submission_id,
                        payload.prompt.strip(),
                        payload.model,
                        payload.size,
                        payload.quality,
                        payload.response_format,
                        now,
                        now,
                        previous_response_id,
                        request.source,
                        dispatcher_id,
                        source_task_id,
                        idempotency_key,
                        priority,
                        "pending" if request.source == "external_dispatcher" else None,
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
        if self._notify_new_job is not None:
            self._notify_new_job()
        return ImageJobSubmitResponse(submission_id=submission_id, job_ids=job_ids, created=True)
