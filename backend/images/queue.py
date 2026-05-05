from __future__ import annotations

import asyncio
import uuid

from config import Settings
from .executor import ImageGenerator, ImageJobExecutor
from .external import ExternalImageTaskDispatcherAdapter
from .models import (
    ImageGalleryListResponse,
    ImageGenerationJobListResponse,
    ImageGenerationJobResponse,
    ImageGenerationJobStatusListResponse,
    ImageGenerationRequest,
    ImageJobSubmitPayload,
    ImageJobSubmitRequest,
    ImageWorkerStatusResponse,
)
from .queries import ImageJobQueries
from .store import ImageJobStore
from .submission import ImageJobSubmission
from .workers import ActiveImageWorker, ImageWorkerCoordinator, PassiveImageWorker


class ImageGenerationQueue:
    """兼容旧调用方的 facade，核心行为已拆到 store/submission/executor/workers。"""

    def __init__(self, settings: Settings, generator: ImageGenerator | None = None) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self.coordinator = ImageWorkerCoordinator()
        self.store = ImageJobStore(settings)
        self.store.recover_interrupted_jobs()
        self.queries = ImageJobQueries(settings)
        self.submission = ImageJobSubmission(settings, notify_new_job=self.coordinator.notify_new_job)
        self.executor = ImageJobExecutor(settings, self.store, self.queries, generator)
        self.passive_worker = PassiveImageWorker(self.store, self.executor)
        self.active_worker = ActiveImageWorker(settings, self.store, self.executor, self.coordinator)
        self.external_dispatcher = ExternalImageTaskDispatcherAdapter(settings, self.submission)

    async def enqueue(self, payload: ImageGenerationRequest) -> ImageGenerationJobResponse:
        async with self._lock:
            response = await self.submission.submit(
                ImageJobSubmitRequest(
                    source="local_ui",
                    idempotency_key=f"local-{uuid.uuid4().hex}",
                    queue="default",
                    priority="normal",
                    payload=ImageJobSubmitPayload.model_validate(payload.model_dump()),
                )
            )
            await self.active_worker.start()
        job = self.queries.get(response.job_ids[0])
        if job is None:
            from .models import _image_error

            raise _image_error(500, "IMAGE_JOB_NOT_FOUND", "Image generation job not found")
        return job

    async def get(self, job_id: str) -> ImageGenerationJobResponse | None:
        return self.queries.get(job_id)

    async def delete_result_image(self, job_id: str, image_index: int) -> None:
        async with self._lock:
            self.store.delete_result_image(job_id, image_index)

    async def delete_job(self, job_id: str) -> None:
        async with self._lock:
            self.store.delete_job(job_id)

    async def stop_job(self, job_id: str) -> None:
        async with self._lock:
            self.store.stop(job_id)
            self.coordinator.notify_new_job()

    async def list_recent(self, page: int = 1, limit: int = 20) -> ImageGenerationJobListResponse:
        return self.queries.list_recent(page=page, limit=limit)

    async def list_statuses(self, tracked_job_ids: list[str] | None = None) -> ImageGenerationJobStatusListResponse:
        return self.queries.list_statuses(tracked_job_ids=tracked_job_ids)

    async def list_gallery_items(self, page: int = 1, limit: int = 20, source: str = "all") -> ImageGalleryListResponse:
        return self.queries.list_gallery_items(page=page, limit=limit, source=source)

    async def close(self) -> None:
        await self.external_dispatcher.close()
        await self.active_worker.close()

    async def start(self) -> None:
        await self.active_worker.start()
        await self.external_dispatcher.start()

    def worker_status(self) -> ImageWorkerStatusResponse:
        active_leases, queued_jobs, running_jobs = self.store.lease_counts()
        return ImageWorkerStatusResponse(
            active_worker_running=self.active_worker.running,
            active_worker_slots=self.active_worker.slot_count,
            dispatcher=self.external_dispatcher.get_settings(),
            active_leases=active_leases,
            queued_jobs=queued_jobs,
            running_jobs=running_jobs,
            running_external_tasks=self.store.running_external_tasks(),
        )

    def _job_response_from_db(self, job_id: str) -> ImageGenerationJobResponse | None:
        return self.queries.get(job_id)
