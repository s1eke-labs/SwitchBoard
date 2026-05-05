from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from config import Settings
from issues import issue_detail
from .models import (
    ImageGenerationError,
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageJobLease,
    ImageWorkerRunResult,
)
from .queries import ImageJobQueries
from .storage import ImageStorageContext, _image_job_task_dir
from .store import ImageJobStore
from .upstream import generate_image

logger = logging.getLogger(__name__)

ImageGenerator = Callable[[Settings, ImageGenerationRequest], Awaitable[ImageGenerationResponse]]


class ImageJobExecutor:
    def __init__(self, settings: Settings, store: ImageJobStore, queries: ImageJobQueries, generator: ImageGenerator | None = None) -> None:
        self.settings = settings
        self.store = store
        self.queries = queries
        self.generator = generator

    async def execute(self, lease: ImageJobLease) -> ImageWorkerRunResult:
        if not self.store.mark_running(lease):
            return ImageWorkerRunResult(status="failed", job_id=lease.job_id, error=issue_detail("IMAGE_JOB_LEASE_LOST", "Image job lease was lost"))
        payload = self.queries.payload_from_job_id(lease.job_id)
        job = self.queries.get(lease.job_id)
        created_at = job.created_at if job is not None else 0
        storage_context = ImageStorageContext(task_dir=_image_job_task_dir(lease.job_id, created_at))

        async def update_partial_result(result: ImageGenerationResponse) -> None:
            self.store.update_result(lease, result)

        try:
            if self.generator is None:
                result = await generate_image(
                    self.settings,
                    payload,
                    progress_callback=update_partial_result,
                    storage_context=storage_context,
                )
            else:
                result = await self.generator(self.settings, payload)
        except ImageGenerationError as exc:
            self.store.fail(lease, exc.detail)
            return ImageWorkerRunResult(status="failed", job_id=lease.job_id, error=exc.detail)
        except Exception:
            logger.exception("Queued image generation failed")
            detail = issue_detail("IMAGE_UPSTREAM_ERROR", "Image generation failed")
            self.store.fail(lease, detail)
            return ImageWorkerRunResult(status="failed", job_id=lease.job_id, error=detail)
        if not self.store.finish(lease, result):
            return ImageWorkerRunResult(status="failed", job_id=lease.job_id, error=issue_detail("IMAGE_JOB_LEASE_LOST", "Image job lease was lost"))
        return ImageWorkerRunResult(status="executed", job_id=lease.job_id)

