"""Entry point: validates config, starts the janitor, runs the bot."""

from __future__ import annotations

import asyncio
import logging
import time

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

    async def _run() -> None:
        await app.start()
        mongo_ok = await db.ping()
        if mongo_ok:
            log.info("MongoDB connected (%s)", config.MONGO_DB)
        else:
            log.warning("MongoDB not reachable — running without persistence")
        asyncio.create_task(_janitor())
        log.info("Bot started (owner=%s, admins=%s). Press Ctrl+C to stop.",
                 config.OWNER_ID, config.ADMIN_IDS)
        await _idle()
        await app.stop()

    async def _idle() -> None:
        from pyrogram import idle
        await idle()

    app.loop.run_until_complete(_run())


if __name__ == "__main__":
    main()
