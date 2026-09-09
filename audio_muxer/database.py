"""SQLite persistence for processing jobs and user sessions.

Schema
------
jobs            — one row per processing job (mux, sync, trim, ...)
job_events      — progress / status history per job
user_sessions   — per-chat upload state for the Telegram bot flow
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from audio_muxer import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    operation   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    progress    INTEGER NOT NULL DEFAULT 0,
    inputs      TEXT NOT NULL DEFAULT '[]',   -- JSON array of input paths
    result      TEXT,                         -- JSON array of output paths
    error       TEXT,
    created_at  REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS job_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    ts          REAL NOT NULL,
    event       TEXT NOT NULL,
    payload     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id);

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id     TEXT PRIMARY KEY,
    state       TEXT NOT NULL DEFAULT '{}',   -- JSON blob (uploaded file, pending op)
    updated_at  REAL NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (config.WORK_DIR / "audiomuxer.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------
    def create_job(self, job_id: str, user_id: str, operation: str, inputs: list[str]) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO jobs (id, user_id, operation, inputs, created_at) VALUES (?,?,?,?,?)",
                (job_id, user_id, operation, json.dumps(inputs), time.time()),
            )
            self._event(job_id, "created", {"operation": operation})

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        result: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        sets, vals = [], []
        if status is not None:
            sets.append("status=?"); vals.append(status)
            if status in {"done", "failed", "cancelled"}:
                sets.append("finished_at=?"); vals.append(time.time())
        if progress is not None:
            sets.append("progress=?"); vals.append(int(progress))
        if result is not None:
            sets.append("result=?"); vals.append(json.dumps(result))
        if error is not None:
            sets.append("error=?"); vals.append(error)
        if not sets:
            return
        vals.append(job_id)
        with self._conn:
            self._conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)
            self._event(job_id, "update", {"status": status, "progress": progress})

    def get_job(self, job_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def user_jobs(self, user_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        row = self._conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(status='done') AS done,
                      SUM(status='failed') AS failed,
                      SUM(status='running') AS running
               FROM jobs"""
        ).fetchone()
        return dict(row)

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def get_session(self, user_id: str) -> dict:
        row = self._conn.execute(
            "SELECT state FROM user_sessions WHERE user_id=?", (user_id,)
        ).fetchone()
        return json.loads(row["state"]) if row else {}

    def set_session(self, user_id: str, state: dict) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT INTO user_sessions (user_id, state, updated_at) VALUES (?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET state=excluded.state,
                   updated_at=excluded.updated_at""",
                (user_id, json.dumps(state), time.time()),
            )

    # ------------------------------------------------------------------
    def _event(self, job_id: str, event: str, payload: dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO job_events (job_id, ts, event, payload) VALUES (?,?,?,?)",
            (job_id, time.time(), event, json.dumps(payload or {})),
        )

    def close(self) -> None:
        self._conn.close()
