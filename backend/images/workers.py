from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import suppress

from config import Settings
from .executor import ImageJobExecutor
from .models import ImageWorkerDrainResult, ImageWorkerRunResult
from .store import ImageJobStore


class ImageWorkerCoordinator:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def notify_new_job(self) -> None:
        self._event.set()

    async def wait_for_new_job(self, timeout_seconds: float = 0.25) -> None:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return
        finally:
            self._event.clear()


class PassiveImageWorker:
    def __init__(self, store: ImageJobStore, executor: ImageJobExecutor) -> None:
        self.store = store
        self.executor = executor
        self._default_owner = f"passive:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    async def run_once(self, *, owner: str | None = None) -> ImageWorkerRunResult:
        lease = self.store.claim_next(owner=owner or self._default_owner)
        if lease is None:
            return ImageWorkerRunResult(status="no_job")
        return await self.executor.execute(lease)

    async def drain(
        self,
        *,
        owner: str | None = None,
        max_jobs: int | None = None,
        timeout_seconds: float | None = None,
    ) -> ImageWorkerDrainResult:
        started_at = time.monotonic()
        executed = 0
        failed = 0
        while True:
            if max_jobs is not None and executed + failed >= max_jobs:
                return ImageWorkerDrainResult(executed=executed, failed=failed, stopped_reason="max_jobs")
            if timeout_seconds is not None and time.monotonic() - started_at >= timeout_seconds:
                return ImageWorkerDrainResult(executed=executed, failed=failed, stopped_reason="timeout")
            result = await self.run_once(owner=owner)
            if result.status == "no_job":
                return ImageWorkerDrainResult(executed=executed, failed=failed, stopped_reason="no_job")
            if result.status == "executed":
                executed += 1
            else:
                failed += 1


class ActiveImageWorker:
    def __init__(
        self,
        settings: Settings,
        store: ImageJobStore,
        executor: ImageJobExecutor,
        coordinator: ImageWorkerCoordinator,
    ) -> None:
        self.settings = settings
        self.store = store
        self.executor = executor
        self.coordinator = coordinator
        self._owner_prefix = f"active:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def running(self) -> bool:
        self._tasks = {task for task in self._tasks if not task.done()}
        return bool(self._tasks)

    @property
    def slot_count(self) -> int:
        return len({task for task in self._tasks if not task.done()})

    async def start(self) -> None:
        self._closed = False
        self._tasks = {task for task in self._tasks if not task.done()}
        while len(self._tasks) < self.settings.image_concurrency:
            index = len(self._tasks) + 1
            task = asyncio.create_task(self._run_slot(index))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        self.coordinator.notify_new_job()

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.difference_update(tasks)

    async def _run_slot(self, index: int) -> None:
        owner = f"{self._owner_prefix}:{index}"
        while not self._closed:
            lease = self.store.claim_next(owner=owner)
            if lease is None:
                await self.coordinator.wait_for_new_job()
                continue
            await self.executor.execute(lease)

