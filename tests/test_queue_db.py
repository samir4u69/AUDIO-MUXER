"""Tests for the job queue and database."""

import asyncio
import os
import time

import pytest

from audio_muxer.database import Database
from audio_muxer.queue import JobQueue, JobStatus, TempJanitor


async def _work(value, on_progress=None):
    if on_progress:
        on_progress(50)
    await asyncio.sleep(0.05)
    if on_progress:
        on_progress(100)
    return value


async def test_queue_success():
    q = JobQueue(max_concurrent=2)
    job = q.create("test-op")
    result = await q.submit(job, _work, 42)
    assert result == 42
    assert job.status == JobStatus.DONE
    assert job.progress == 100


async def test_queue_failure():
    q = JobQueue()

    async def boom(on_progress=None):
        raise RuntimeError("kaboom")

    job = q.create("failing-op")
    with pytest.raises(RuntimeError, match="kaboom"):
        await q.submit(job, boom)
    assert job.status == JobStatus.FAILED
    assert "kaboom" in job.error


async def test_queue_concurrency_limit():
    q = JobQueue(max_concurrent=1)
    running = 0
    max_running = 0

    async def tracked(on_progress=None):
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.05)
        running -= 1

    jobs = [q.create(f"op{i}") for i in range(3)]
    await asyncio.gather(*[q.submit(j, tracked) for j in jobs])
    assert max_running == 1


def test_database_roundtrip(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_job("j1", "user1", "extract", ["/tmp/a.mp4"])
    db.update_job("j1", status="running", progress=50)
    db.update_job("j1", status="done", progress=100, result=["/tmp/out.mp3"])

    job = db.get_job("j1")
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert job["finished_at"] is not None

    assert db.user_jobs("user1")[0]["id"] == "j1"
    stats = db.stats()
    assert stats["total"] == 1 and stats["done"] == 1
    db.close()


def test_database_session(tmp_path):
    db = Database(tmp_path / "test.db")
    db.set_session("u1", {"file": "/tmp/x.mp4"})
    assert db.get_session("u1") == {"file": "/tmp/x.mp4"}
    db.set_session("u1", {"file": "/tmp/y.mp4"})
    assert db.get_session("u1") == {"file": "/tmp/y.mp4"}
    assert db.get_session("nobody") == {}
    db.close()


def test_janitor(tmp_path):
    old = tmp_path / "old.tmp"
    old.write_text("x")
    old_time = time.time() - 100000
    os.utime(old, (old_time, old_time))
    new = tmp_path / "new.tmp"
    new.write_text("x")

    janitor = TempJanitor(work_dir=tmp_path, ttl=3600)
    removed = janitor.sweep()
    assert removed == 1
    assert not old.exists()
    assert new.exists()
