"""Tests for the MongoDB layer (mocked)."""

import pytest

from bot.database import Database, ROLE_ADMIN, ROLE_OWNER, ROLE_USER


@pytest.fixture
async def db():
    from mongomock_motor import AsyncMongoMockClient
    d = Database(client=AsyncMongoMockClient())
    yield d


async def test_add_and_get_user(db):
    await db.add_user(123)
    user = await db.get_user(123)
    assert user["role"] == ROLE_USER
    assert user["banned"] is False


async def test_owner_role(db, monkeypatch):
    from bot import config
    monkeypatch.setattr(config, "OWNER_ID", 999)
    assert await db.role_of(999) == ROLE_OWNER


async def test_admin_role(db):
    await db.add_admin(42)
    assert await db.role_of(42) == ROLE_ADMIN
    await db.remove_admin(42)
    assert await db.role_of(42) == ROLE_USER


async def test_ban(db):
    await db.set_banned(7, True)
    assert await db.is_banned(7)
    await db.set_banned(7, False)
    assert not await db.is_banned(7)


async def test_jobs(db):
    await db.create_job("j1", 123, "extract", ["/tmp/a.mp4"])
    await db.update_job("j1", status="done", progress=100, result="/tmp/out.mp3")
    stats = await db.job_stats()
    assert stats["done"] == 1 and stats["total"] == 1
    recent = await db.recent_jobs(123)
    assert recent[0]["_id"] == "j1"
    assert recent[0]["status"] == "done"


async def test_session(db):
    await db.set_session(5, {"file": "/tmp/x.mp4", "pending_op": "trim"})
    assert (await db.get_session(5))["pending_op"] == "trim"
    await db.clear_session(5)
    assert await db.get_session(5) == {}
