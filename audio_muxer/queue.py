"""Job queue: concurrent processing with bounded parallelism, tracking and cleanup."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

from audio_muxer import config

log = logging.getLogger(__name__)


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    operation: str
    user_id: str = "local"
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    result: Path | list[Path] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    inputs: list[str] = field(default_factory=list)

    def set_progress(self, percent: int) -> None:
        self.progress = int(percent)


class JobQueue:
    """Async queue running up to ``max_concurrent`` ffmpeg jobs at once."""

    def __init__(self, max_concurrent: int | None = None):
        self.max_concurrent = max_concurrent or config.MAX_CONCURRENT_JOBS
        self._sem = asyncio.Semaphore(self.max_concurrent)
        self.jobs: dict[str, Job] = {}

    # ------------------------------------------------------------------
    def create(self, operation: str, user_id: str = "local", inputs: list[str] | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], operation=operation,
                  user_id=user_id, inputs=inputs or [])
        self.jobs[job.id] = job
        return job

    async def submit(
        self,
        job: Job,
        coro_factory: Callable[..., Awaitable[Any]],
        *args,
        **kwargs,
    ) -> Any:
        """Run ``coro_factory`` under the concurrency semaphore.

        ``on_progress=job.set_progress`` is injected automatically when the
        callable accepts it (all engine operations do).
        """
        async with self._sem:
            job.status = JobStatus.RUNNING
            log.info("job %s started: %s (user=%s)", job.id, job.operation, job.user_id)
            try:
                kwargs.setdefault("on_progress", job.set_progress)
                result = await coro_factory(*args, **kwargs)
                job.result = result if isinstance(result, (Path, list)) else None
                job.status = JobStatus.DONE
                job.progress = 100
                return result
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                raise
            except Exception as exc:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                log.exception("job %s failed", job.id)
                raise
            finally:
                job.finished_at = time.time()

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def summary(self, job: Job) -> str:
        icon = {
            JobStatus.QUEUED: "⏳", JobStatus.RUNNING: "🔄",
            JobStatus.DONE: "✅", JobStatus.FAILED: "❌",
            JobStatus.CANCELLED: "🚫",
        }[job.status]
        line = f"{icon} [{job.id}] {job.operation}: {job.status.value}"
        if job.status == JobStatus.RUNNING:
            line += f" {job.progress}%"
        if job.error:
            line += f" — {job.error}"
        return line


# ---------------------------------------------------------------------------
# Temp file janitor
# ---------------------------------------------------------------------------
class TempJanitor:
    """Deletes work-dir files older than the configured TTL."""

    def __init__(self, work_dir: Path | None = None, ttl: int | None = None):
        self.work_dir = work_dir or config.WORK_DIR
        self.ttl = ttl if ttl is not None else config.TEMP_TTL_SECONDS
        self._task: asyncio.Task | None = None

    def sweep(self) -> int:
        now = time.time()
        removed = 0
        if not self.work_dir.exists():
            return 0
        for f in self.work_dir.iterdir():
            if f.is_file() and now - f.stat().st_mtime > self.ttl:
                try:
                    f.unlink()
                    removed += 1
                except OSError as exc:
                    log.warning("janitor could not remove %s: %s", f, exc)
        if removed:
            log.info("janitor removed %d temp files", removed)
        return removed

    async def run_forever(self, interval: int = 3600) -> None:
        while True:
            self.sweep()
            await asyncio.sleep(interval)

    def start(self, interval: int = 3600) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(interval))

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
