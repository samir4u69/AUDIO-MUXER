"""MongoDB persistence: users, roles, jobs, sessions.

All reads/writes are wrapped in short timeouts so a missing MongoDB server
degrades the bot to a non-persistent mode instead of crashing handlers.

Collections
-----------
users    {_id: user_id, role, banned, first_seen, jobs}
jobs     {_id, user_id, operation, status, progress, inputs, result, error, ...}
sessions {_id: user_id, state, updated_at}
settings {_id: "global", ...}
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from bot import config

log = logging.getLogger(__name__)

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_USER = "user"

_OP_TIMEOUT = 3  # seconds


def install_asyncio_filter(loop) -> None:
    """Suppress 'Future exception was never retrieved' noise from MongoDB.

    When Mongo is down, pymongo runs each op in an executor thread; the
    operation fails after our short timeout already returned a fallback, and
    the orphaned future would otherwise dump a full traceback per DB call.
    Real (non-Mongo) errors are still reported.
    """
    previous = loop.get_exception_handler()

    def handler(loop, context):
        exc = context.get("exception")
        if exc is not None and type(exc).__name__ == "ServerSelectionTimeoutError":
            return  # Mongo down; already handled via fallback
        if previous:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def _now():
    return datetime.now(timezone.utc)


class Database:
    """Async MongoDB access layer (motor), tolerant of Mongo being down."""

    def __init__(self, client=None):
        if client is None:
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=_OP_TIMEOUT * 1000,
            )
        self.client = client
        self.db = client[config.MONGO_DB]
        self.users = self.db["users"]
        self.jobs = self.db["jobs"]
        self.sessions = self.db["sessions"]
        self.settings = self.db["settings"]
        # In-memory fallbacks when Mongo is unreachable.
        self._mem_users: dict[int, dict] = {}
        self._mem_sessions: dict[int, dict] = {}
        # Circuit breaker: skip Mongo while it is down, retry after cooldown.
        self._down_since: float | None = None

    _DOWN_RETRY_AFTER = 30.0  # seconds

    async def _run(self, coro, fallback=None):
        """Run a Mongo op with a short timeout; degrade to a fallback if Mongo
        is down. A circuit breaker skips Mongo while it is down and retries
        after a cooldown."""
        import time
        if self._down_since is not None:
            if time.monotonic() - self._down_since < self._DOWN_RETRY_AFTER:
                return fallback
            self._down_since = None  # cooldown elapsed, try Mongo again
        try:
            result = await asyncio.wait_for(coro, _OP_TIMEOUT)
            self._down_since = None
            return result
        except Exception as exc:
            if self._down_since is None:
                log.warning("MongoDB unavailable: %s", type(exc).__name__)
            self._down_since = time.monotonic()
            return fallback

    # ------------------------------------------------------------------
    # Users & roles
    # ------------------------------------------------------------------
    async def add_user(self, user_id: int, role: str = ROLE_USER) -> None:
        self._mem_users.setdefault(user_id, {"role": role, "banned": False, "jobs": 0})
        await self._run(self.users.update_one(
            {"_id": user_id},
            {"$setOnInsert": {"role": role, "banned": False,
                              "first_seen": _now(), "jobs": 0}},
            upsert=True,
        ))

    async def get_user(self, user_id: int) -> dict | None:
        doc = await self._run(self.users.find_one({"_id": user_id}))
        return doc if doc is not None else self._mem_users.get(user_id)

    async def role_of(self, user_id: int) -> str:
        if user_id == config.OWNER_ID:
            return ROLE_OWNER
        if user_id in config.ADMIN_IDS:
            return ROLE_ADMIN
        user = await self.get_user(user_id)
        return ROLE_ADMIN if user and user.get("role") == ROLE_ADMIN else ROLE_USER

    async def is_banned(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.get("banned"))

    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self.add_user(user_id)
        self._mem_users[user_id]["banned"] = banned
        await self._run(self.users.update_one({"_id": user_id}, {"$set": {"banned": banned}}))

    async def add_admin(self, user_id: int) -> None:
        await self.add_user(user_id)
        self._mem_users[user_id]["role"] = ROLE_ADMIN
        await self._run(self.users.update_one({"_id": user_id}, {"$set": {"role": ROLE_ADMIN}}))

    async def remove_admin(self, user_id: int) -> None:
        if user_id in self._mem_users:
            self._mem_users[user_id]["role"] = ROLE_USER
        await self._run(self.users.update_one({"_id": user_id}, {"$set": {"role": ROLE_USER}}))

    async def list_admins(self) -> list[int]:
        cursor = self.users.find({"role": ROLE_ADMIN})
        docs = await self._run(cursor.to_list(length=1000), fallback=[])
        ids = [d["_id"] for d in docs]
        ids += [u for u, d in self._mem_users.items() if d.get("role") == ROLE_ADMIN]
        return sorted(set(ids))

    async def total_users(self) -> int:
        n = await self._run(self.users.count_documents({}), fallback=0)
        return max(n, len(self._mem_users))

    async def all_user_ids(self) -> list[int]:
        cursor = self.users.find({}, {"_id": 1})
        docs = await self._run(cursor.to_list(length=100000), fallback=[])
        ids = {d["_id"] for d in docs} | set(self._mem_users)
        return sorted(ids)

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    async def create_job(self, job_id: str, user_id: int, operation: str, inputs: list) -> None:
        await self._run(self.jobs.insert_one({
            "_id": job_id, "user_id": user_id, "operation": operation,
            "status": "queued", "progress": 0, "inputs": list(inputs),
            "result": None, "error": None, "created_at": _now(), "finished_at": None,
        }))
        if user_id in self._mem_users:
            self._mem_users[user_id]["jobs"] = self._mem_users[user_id].get("jobs", 0) + 1

    async def update_job(self, job_id: str, **fields) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if fields.get("status") in {"done", "failed", "cancelled"}:
            fields["finished_at"] = _now()
        if fields:
            await self._run(self.jobs.update_one({"_id": job_id}, {"$set": fields}))

    async def job_stats(self) -> dict:
        pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        docs = await self._run(self.jobs.aggregate(pipeline).to_list(length=100), fallback=[])
        counts = {d["_id"]: d["n"] for d in docs}
        counts["total"] = sum(counts.values())
        return counts

    async def recent_jobs(self, user_id: int, limit: int = 10) -> list:
        cursor = self.jobs.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return await self._run(cursor.to_list(length=limit), fallback=[])

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    async def get_session(self, user_id: int) -> dict:
        doc = await self._run(self.sessions.find_one({"_id": user_id}))
        if doc is not None:
            return doc.get("state", {})
        return self._mem_sessions.get(user_id, {})

    async def set_session(self, user_id: int, state: dict) -> None:
        self._mem_sessions[user_id] = dict(state)
        await self._run(self.sessions.update_one(
            {"_id": user_id},
            {"$set": {"state": state, "updated_at": _now()}},
            upsert=True,
        ))

    async def clear_session(self, user_id: int) -> None:
        self._mem_sessions.pop(user_id, None)
        await self._run(self.sessions.delete_one({"_id": user_id}))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    async def get_setting(self, key: str, default=None):
        doc = await self._run(self.settings.find_one({"_id": "global"}))
        return doc.get(key, default) if doc else default

    async def set_setting(self, key: str, value) -> None:
        await self._run(self.settings.update_one(
            {"_id": "global"}, {"$set": {key: value}}, upsert=True,
        ))

    async def ping(self) -> bool:
        try:
            await asyncio.wait_for(self.client.admin.command("ping"), _OP_TIMEOUT)
            return True
        except Exception as exc:
            log.warning("MongoDB ping failed: %s", type(exc).__name__)
            return False

    def close(self) -> None:
        self.client.close()
