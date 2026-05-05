from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import suppress

from config import Settings
from db import connect, init_db
from issues import IssueDetail, issue_detail
from .common import upstream_metadata_json
from .models import (
    ImageGenerationError,
    ImageGenerationResponse,
    ImageJobLease,
    ImageRunningExternalTaskResponse,
    _image_error,
)
from .storage import _delete_image_file, _delete_image_task_dir, _response_for_storage


class ImageJobStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        init_db(settings.db_path)

    def recover_interrupted_jobs(self) -> None:
        now = int(time.time())
        detail = issue_detail(
            "IMAGE_JOB_INTERRUPTED",
            "Image generation was interrupted by a service restart. Retry the job to generate again.",
        )
        try:
            with connect(self.settings.db_path) as conn:
                conn.execute(
                    """
                    UPDATE image_jobs
                    SET status = 'failed', error_json = ?, lease_owner = NULL, lease_token = NULL,
                        lease_expires_at = NULL, finished_at = COALESCE(finished_at, ?), updated_at = ?
                    WHERE status IN ('leased', 'running')
                    """,
                    (detail.model_dump_json(), now, now),
                )
                for row in conn.execute(
                    """
                    SELECT DISTINCT submission_id
                    FROM image_jobs
                    WHERE submission_id IS NOT NULL
                      AND status = 'failed'
                      AND error_json = ?
                    """,
                    (detail.model_dump_json(),),
                ):
                    statuses = [
                        str(item["status"])
                        for item in conn.execute(
                            "SELECT status FROM image_jobs WHERE submission_id = ?",
                            (row["submission_id"],),
                        )
                    ]
                    if statuses and all(status in {"failed", "succeeded", "canceled"} for status in statuses):
                        submission_status = "failed" if "failed" in statuses else "canceled" if "canceled" in statuses else "succeeded"
                        conn.execute(
                            "UPDATE image_submissions SET status = ?, error_json = COALESCE(error_json, ?), updated_at = ? WHERE id = ?",
                            (submission_status, detail.model_dump_json(), now, row["submission_id"]),
                        )
        except sqlite3.OperationalError as exc:
            if "readonly" not in str(exc).lower():
                raise
            raise RuntimeError(
                f"SwitchBoard data directory is not writable: {self.settings.db_path.parent}. "
                "Fix the owner/permissions of SWITCHBOARD_DATA_DIR or point SWITCHBOARD_DATA_DIR "
                "to a writable directory."
            ) from exc

    def claim_next(self, *, owner: str, lease_seconds: int = 300) -> ImageJobLease | None:
        now = int(time.time())
        expires_at = now + lease_seconds
        lease_token = uuid.uuid4().hex
        conn = connect(self.settings.db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id
                FROM image_jobs
                WHERE status = 'queued'
                   OR (status IN ('leased', 'running') AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                ORDER BY priority DESC, created_at ASC, rowid ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            job_id = str(row["id"])
            cursor = conn.execute(
                """
                UPDATE image_jobs
                SET status = 'leased', lease_owner = ?, lease_token = ?, lease_expires_at = ?,
                    updated_at = ?, attempt_count = attempt_count + 1
                WHERE id = ?
                  AND (
                    status = 'queued'
                    OR (status IN ('leased', 'running') AND lease_expires_at IS NOT NULL AND lease_expires_at < ?)
                  )
                """,
                (owner, lease_token, expires_at, now, job_id, now),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            attempt_count = int(
                conn.execute("SELECT attempt_count FROM image_jobs WHERE id = ?", (job_id,)).fetchone()["attempt_count"]
            )
            self._refresh_submission_status(conn, job_id)
            conn.commit()
            return ImageJobLease(
                job_id=job_id,
                lease_owner=owner,
                lease_token=lease_token,
                lease_expires_at=expires_at,
                attempt_count=attempt_count,
            )
        finally:
            conn.close()

    def mark_running(self, lease: ImageJobLease) -> bool:
        now = int(time.time())
        with connect(self.settings.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE image_jobs
                SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
                WHERE id = ? AND lease_token = ? AND status IN ('leased', 'running')
                """,
                (now, now, lease.job_id, lease.lease_token),
            )
            if cursor.rowcount == 1:
                self._refresh_submission_status(conn, lease.job_id)
            return cursor.rowcount == 1

    def update_result(self, lease: ImageJobLease, result: ImageGenerationResponse) -> bool:
        now = int(time.time())
        stored_result = _response_for_storage(result)
        metadata_json = upstream_metadata_json(result)
        with connect(self.settings.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE image_jobs
                SET result_json = ?, error_json = NULL,
                    upstream_response_id = ?, upstream_metadata_json = COALESCE(?, upstream_metadata_json),
                    updated_at = ?
                WHERE id = ? AND lease_token = ? AND status IN ('leased', 'running')
                """,
                (stored_result.model_dump_json(), stored_result.response_id, metadata_json, now, lease.job_id, lease.lease_token),
            )
            return cursor.rowcount == 1

    def finish(self, lease: ImageJobLease, result: ImageGenerationResponse) -> bool:
        now = int(time.time())
        stored_result = _response_for_storage(result)
        metadata_json = upstream_metadata_json(result)
        with connect(self.settings.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE image_jobs
                SET status = 'succeeded', result_json = ?, error_json = NULL,
                    upstream_response_id = ?, upstream_metadata_json = ?, lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ? AND lease_token = ? AND status IN ('leased', 'running')
                """,
                (
                    stored_result.model_dump_json(),
                    stored_result.response_id,
                    metadata_json,
                    now,
                    now,
                    lease.job_id,
                    lease.lease_token,
                ),
            )
            if cursor.rowcount == 1:
                self._refresh_submission_status(conn, lease.job_id)
                return True
            return False

    def fail(self, lease: ImageJobLease, detail: IssueDetail) -> bool:
        now = int(time.time())
        with connect(self.settings.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE image_jobs
                SET status = 'failed', error_json = ?, lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ? AND lease_token = ? AND status IN ('leased', 'running')
                """,
                (detail.model_dump_json(), now, now, lease.job_id, lease.lease_token),
            )
            if cursor.rowcount == 1:
                self._refresh_submission_status(conn, lease.job_id)
                return True
            return False

    def stop(self, job_id: str) -> None:
        detail = issue_detail(
            "IMAGE_JOB_STOPPED",
            "Image generation was stopped by the user. Retry the job to generate again.",
        )
        now = int(time.time())
        with connect(self.settings.db_path) as conn:
            job = conn.execute("SELECT status FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
            if job["status"] not in {"queued", "leased", "running"}:
                raise _image_error(409, "IMAGE_JOB_NOT_ACTIVE", "Image generation job is not active")
            conn.execute(
                """
                UPDATE image_jobs
                SET status = 'canceled', error_json = ?, lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, finished_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'leased', 'running')
                """,
                (detail.model_dump_json(), now, now, job_id),
            )
            self._refresh_submission_status(conn, job_id)

    def delete_result_image(self, job_id: str, image_index: int) -> None:
        if image_index < 0:
            raise _image_error(400, "IMAGE_INVALID_INDEX", "Image index is invalid")
        with connect(self.settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
            if job["status"] in {"queued", "leased", "running"}:
                raise _image_error(409, "IMAGE_JOB_ACTIVE", "Image generation job is still active")
            result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
            if result is None or image_index >= len(result.data):
                raise _image_error(404, "IMAGE_NOT_FOUND", "Image not found")
            removed = result.data.pop(image_index)
            _delete_image_file(self.settings, file_name=removed.file_name, path_value=removed.saved_path)
            if result.data:
                conn.execute(
                    "UPDATE image_jobs SET result_json = ?, updated_at = ? WHERE id = ?",
                    (result.model_dump_json(), int(time.time()), job_id),
                )
                return
            reference_rows = list(conn.execute("SELECT file_name FROM image_job_references WHERE job_id = ?", (job_id,)))
            conn.execute("DELETE FROM image_jobs WHERE id = ?", (job_id,))
        for row in reference_rows:
            _delete_image_file(self.settings, file_name=str(row["file_name"]))
        _delete_image_task_dir(self.settings, job_id, int(job["created_at"]))

    def delete_job(self, job_id: str) -> None:
        with connect(self.settings.db_path) as conn:
            job = conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
            if job is None:
                raise _image_error(404, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
            if job["status"] in {"queued", "leased", "running"}:
                raise _image_error(409, "IMAGE_JOB_ACTIVE", "Image generation job is still active")
            result = ImageGenerationResponse.model_validate_json(job["result_json"]) if job["result_json"] else None
            reference_rows = list(conn.execute("SELECT file_name FROM image_job_references WHERE job_id = ?", (job_id,)))
            conn.execute("DELETE FROM image_jobs WHERE id = ?", (job_id,))
        for item in result.data if result else []:
            _delete_image_file(self.settings, file_name=item.file_name, path_value=item.saved_path)
        for row in reference_rows:
            _delete_image_file(self.settings, file_name=str(row["file_name"]))
        _delete_image_task_dir(self.settings, job_id, int(job["created_at"]))

    def lease_counts(self) -> tuple[int, int, int]:
        with connect(self.settings.db_path) as conn:
            active_leases = int(
                conn.execute("SELECT COUNT(*) AS count FROM image_jobs WHERE status IN ('leased', 'running')").fetchone()["count"]
            )
            queued_jobs = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs WHERE status = 'queued'").fetchone()["count"])
            running_jobs = int(conn.execute("SELECT COUNT(*) AS count FROM image_jobs WHERE status = 'running'").fetchone()["count"])
        return active_leases, queued_jobs, running_jobs

    def running_external_tasks(self, dispatcher_id: str | None = None) -> list[ImageRunningExternalTaskResponse]:
        dispatcher_filter = ""
        params: tuple[str, ...] = ()
        if dispatcher_id is not None:
            dispatcher_filter = "AND dispatcher_id = ?"
            params = (dispatcher_id,)
        with connect(self.settings.db_path) as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, dispatcher_id, source_task_id, prompt, status, started_at, updated_at, lease_owner
                    FROM image_jobs
                    WHERE source = 'external_dispatcher'
                      AND status IN ('leased', 'running')
                      {dispatcher_filter}
                    ORDER BY COALESCE(started_at, updated_at) ASC, created_at ASC, id ASC
                    """.format(dispatcher_filter=dispatcher_filter),
                    params,
                )
            )
        return [
            ImageRunningExternalTaskResponse(
                id=str(row["id"]),
                dispatcher_id=str(row["dispatcher_id"]) if row["dispatcher_id"] else None,
                source_task_id=str(row["source_task_id"]) if row["source_task_id"] else None,
                prompt=str(row["prompt"]),
                status=str(row["status"]),
                started_at=int(row["started_at"]) if row["started_at"] else None,
                updated_at=int(row["updated_at"]),
                lease_owner=str(row["lease_owner"]) if row["lease_owner"] else None,
            )
            for row in rows
        ]

    def _refresh_submission_status(self, conn, job_id: str) -> None:
        row = conn.execute("SELECT submission_id FROM image_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None or not row["submission_id"]:
            return
        submission_id = str(row["submission_id"])
        statuses = [str(item["status"]) for item in conn.execute("SELECT status FROM image_jobs WHERE submission_id = ?", (submission_id,))]
        if not statuses:
            return
        if all(status == "succeeded" for status in statuses):
            status = "succeeded"
        elif any(status == "failed" for status in statuses):
            status = "failed"
        elif any(status == "canceled" for status in statuses):
            status = "canceled"
        elif any(status == "running" for status in statuses):
            status = "running"
        elif any(status == "leased" for status in statuses):
            status = "leased"
        else:
            status = "queued"
        error_json = None
        if status in {"failed", "canceled"}:
            row = conn.execute(
                """
                SELECT error_json
                FROM image_jobs
                WHERE submission_id = ? AND error_json IS NOT NULL
                ORDER BY updated_at ASC, rowid ASC
                LIMIT 1
                """,
                (submission_id,),
            ).fetchone()
            error_json = str(row["error_json"]) if row is not None and row["error_json"] else None
        conn.execute(
            "UPDATE image_submissions SET status = ?, error_json = COALESCE(?, error_json), updated_at = ? WHERE id = ?",
            (status, error_json, int(time.time()), submission_id),
        )
