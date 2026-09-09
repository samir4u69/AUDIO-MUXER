"""MongoDB persistence: users, roles, jobs, sessions.

Collections
-----------
users    {_id: user_id, role: "owner"|"admin"|"user", banned: bool,
          first_seen: datetime, jobs: int}
jobs     {_id, user_id, operation, status, progress, inputs, result,
          error, created_at, finished_at}
sessions {_id: user_id, state: {...}, updated_at}
settings {_id: "global", force_sub_channel: int|None, ...}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bot import config

log = logging.getLogger(__name__)

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_USER = "user"


def _now():
    return datetime.now(timezone.utc)


class Database:
    """Async MongoDB access layer (motor)."""

    def __init__(self, client=None):
        if client is None:
            from motor.motor_asyncio import AsyncIOMotorClient
            client = AsyncIOMotorClient(config.MONGO_URI)
        self.client = client
        self.db = client[config.MONGO_DB]
        self.users = self.db["users"]
        self.jobs = self.db["jobs"]
        self.sessions = self.db["sessions"]
        self.settings = self.db["settings"]

    # ------------------------------------------------------------------
    # Users & roles
    # ------------------------------------------------------------------
    async def add_user(self, user_id: int, role: str = ROLE_USER) -> None:
        await self.users.update_one(
            {"_id": user_id},
            {"$setOnInsert": {"role": role, "banned": False,
                              "first_seen": _now(), "jobs": 0}},
            upsert=True,
        )

    async def get_user(self, user_id: int) -> dict | None:
        return await self.users.find_one({"_id": user_id})

    async def role_of(self, user_id: int) -> str:
        if user_id == config.OWNER_ID:
            return ROLE_OWNER
        user = await self.get_user(user_id)
        if user and user.get("role") == ROLE_ADMIN:
            return ROLE_ADMIN
        if user_id in config.ADMIN_IDS:
            return ROLE_ADMIN
        return ROLE_USER

    async def is_banned(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return bool(user and user.get("banned"))

    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self.add_user(user_id)
        await self.users.update_one({"_id": user_id}, {"$set": {"banned": banned}})

    async def add_admin(self, user_id: int) -> None:
        await self.add_user(user_id)
        await self.users.update_one({"_id": user_id}, {"$set": {"role": ROLE_ADMIN}})

    async def remove_admin(self, user_id: int) -> None:
        await self.users.update_one({"_id": user_id}, {"$set": {"role": ROLE_USER}})

    async def list_admins(self) -> list[int]:
        cursor = self.users.find({"role": ROLE_ADMIN})
        return [u["_id"] async for u in cursor]

    async def total_users(self) -> int:
        return await self.users.count_documents({})

    async def all_user_ids(self) -> list[int]:
        cursor = self.users.find({}, {"_id": 1})
        return [u["_id"] async for u in cursor]

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    async def create_job(self, job_id: str, user_id: int, operation: str, inputs: list[str]) -> None:
        await self.jobs.insert_one({
            "_id": job_id, "user_id": user_id, "operation": operation,
            "status": "queued", "progress": 0, "inputs": inputs,
            "result": None, "error": None,
            "created_at": _now(), "finished_at": None,
        })
        await self.users.update_one({"_id": user_id}, {"$inc": {"jobs": 1}})

    async def update_job(self, job_id: str, **fields) -> None:
        fields = {k: v for k, v in fields.items() if v is not None}
        if fields.get("status") in {"done", "failed", "cancelled"}:
            fields["finished_at"] = _now()
        if fields:
            await self.jobs.update_one({"_id": job_id}, {"$set": fields})

    async def job_stats(self) -> dict:
        pipeline = [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        counts = {doc["_id"]: doc["n"] async for doc in self.jobs.aggregate(pipeline)}
        counts["total"] = sum(counts.values())
        return counts

    async def recent_jobs(self, user_id: int, limit: int = 10) -> list[dict]:
        cursor = self.jobs.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        return [doc async for doc in cursor]

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    async def get_session(self, user_id: int) -> dict:
        doc = await self.sessions.find_one({"_id": user_id})
        return doc.get("state", {}) if doc else {}

    async def set_session(self, user_id: int, state: dict) -> None:
        await self.sessions.update_one(
            {"_id": user_id},
            {"$set": {"state": state, "updated_at": _now()}},
            upsert=True,
        )

    async def clear_session(self, user_id: int) -> None:
        await self.sessions.delete_one({"_id": user_id})

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    async def get_setting(self, key: str, default=None):
        doc = await self.settings.find_one({"_id": "global"})
        return doc.get(key, default) if doc else default

    async def set_setting(self, key: str, value) -> None:
        await self.settings.update_one(
            {"_id": "global"}, {"$set": {key: value}}, upsert=True,
        )

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
            return True
        except Exception as exc:
            log.error("MongoDB ping failed: %s", exc)
            return False

    def close(self) -> None:
        self.client.close()
