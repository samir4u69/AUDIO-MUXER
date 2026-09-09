"""Entry point: validates config, starts the janitor, runs the bot."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from bot import config
from bot.ffmpeg_wrapper import check_ffmpeg

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("audiomuxer")


async def _janitor() -> None:
    """Delete temp files older than the TTL, once an hour."""
    while True:
        removed = 0
        now = time.time()
        for f in config.WORK_DIR.iterdir():
            if f.is_file() and now - f.stat().st_mtime > config.TEMP_TTL_SECONDS:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        if removed:
            log.info("Janitor removed %d temp files", removed)
        await asyncio.sleep(3600)


def main() -> None:
    problems = config.validate()
    if problems:
        for p in problems:
            log.error("Config: %s", p)
        raise SystemExit("Fix the .env file (see .env.example) and restart.")

    ok, msg = check_ffmpeg()
    if not ok:
        raise SystemExit(f"ffmpeg check failed: {msg}")

    from bot.handlers import app, db  # noqa: WPS433 (imports register handlers)

    async def startup():
        if await db.ping():
            log.info("MongoDB connected (%s)", config.MONGO_DB)
        else:
            log.warning("MongoDB not reachable — sessions/roles will not persist")
        asyncio.create_task(_janitor())
        log.info("Bot starting (owner=%s, admins=%s)", config.OWNER_ID, config.ADMIN_IDS)

    app.startup_tasks = [startup()]  # run before polling
    app.run()


if __name__ == "__main__":
    main()
