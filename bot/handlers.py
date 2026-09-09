"""AudioMuxer Telegram bot (Pyrogram + MongoDB).

Run with:  python -m bot
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from bot import config
from bot.database import Database, ROLE_ADMIN, ROLE_OWNER
from bot.media_info import (
    FileValidationError, UnsupportedFormatError, format_info, inspect,
)
from bot.muxer import AudioMuxer
from bot.sync import SyncDetector, SyncDetectionError
from bot.trimmer import Trimmer, parse_timestamp

log = logging.getLogger("audiomuxer.bot")

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
db = Database()
muxer = AudioMuxer()
trimmer = Trimmer()
detector = SyncDetector()
_queue_sem = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)

app = Client(
    "audiomuxer",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    in_memory=True,
)

MAIN_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🎵 Extract Audio", callback_data="op:extract"),
     InlineKeyboardButton("➕ Add Audio", callback_data="op:add")],
    [InlineKeyboardButton("🔄 Replace Audio", callback_data="op:replace"),
     InlineKeyboardButton("📋 List Tracks", callback_data="op:info")],
    [InlineKeyboardButton("🔍 Auto Sync", callback_data="op:sync"),
     InlineKeyboardButton("🎯 Manual Sync", callback_data="op:manual_sync")],
    [InlineKeyboardButton("✂️ Trim", callback_data="op:trim"),
     InlineKeyboardButton("🔇 Remove Silence", callback_data="op:denoise")],
    [InlineKeyboardButton("🎚️ Volume", callback_data="op:volume"),
     InlineKeyboardButton("🔁 Convert", callback_data="op:convert")],
])

PARAM_PROMPTS = {
    "extract": "Which audio format? Reply with mp3, aac, wav, flac, ogg or opus.",
    "trim": "Send start and end times, e.g. `00:10:00 00:20:00`",
    "denoise": "Send silence threshold in dB (e.g. `-40`) or `go` for defaults.",
    "volume": "Send the gain in dB, e.g. `+6` or `-3`.",
    "convert": "Which format? mp3, aac, wav, flac, ogg, opus…",
}
AUDIO_INPUT_OPS = {"add", "replace", "sync", "manual_sync"}


# ---------------------------------------------------------------------------
# Progress UI
# ---------------------------------------------------------------------------
def _bar(percent: float, width: int = 12) -> str:
    filled = int(round(percent / 100 * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _eta(seconds: float) -> str:
    if seconds != seconds or seconds < 0 or seconds == float("inf"):  # NaN/inf
        return "…"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


class Progress:
    """Throttle edits and render a detailed progress block.

    Tracks bytes (transfer) or percent (processing), computing speed & ETA.
    Edits the status message at most once per PROGRESS_UPDATE_INTERVAL.
    """

    def __init__(self, status: Message, label: str, total: int | None = None):
        self.status = status
        self.label = label
        self.total = total or 0
        self.started = time.monotonic()
        self._last_edit = 0.0
        self._pending: asyncio.Task | None = None

    # -- transfer-style update (pyrogram download/upload callback) --
    def update(self, current: int, total: int | None = None):
        if total:
            self.total = total
        pct = (current / self.total * 100) if self.total else 0.0
        self._maybe_edit(pct, current)

    # -- percent-style update (ffmpeg on_progress callback) --
    def update_percent(self, pct: float):
        self._maybe_edit(float(pct), None)

    def _maybe_edit(self, pct: float, current: int | None):
        now = time.monotonic()
        if pct < 100 and now - self._last_edit < config.PROGRESS_UPDATE_INTERVAL:
            return
        self._last_edit = now
        text = self._render(pct, current)
        if self._pending is None or self._pending.done():
            self._pending = asyncio.ensure_future(self._safe_edit(text))

    def _render(self, pct: float, current: int | None) -> str:
        elapsed = max(time.monotonic() - self.started, 1e-3)
        lines = [f"{self.label}", f"[{_bar(pct)}] {pct:.0f}%"]
        if current is not None and self.total:
            speed = current / elapsed
            remaining = (self.total - current) / speed if speed > 0 else float("inf")
            lines.append(f"📦 {_human(current)} / {_human(self.total)}")
            lines.append(f"⚡ {_human(speed)}/s   ⏳ ETA {_eta(remaining)}")
        lines.append(f"⏱ {_eta(elapsed)} elapsed")
        return "\n".join(lines)

    async def _safe_edit(self, text: str):
        try:
            await self.status.edit_text(text)
        except Exception:
            pass  # message deleted / not modified / flood — ignore

    async def finish(self, text: str):
        if self._pending is not None:
            try:
                await self._pending
            except Exception:
                pass
        await self._safe_edit(text)


async def _role(user_id: int) -> str:
    return await db.role_of(user_id)


async def _is_admin(user_id: int) -> bool:
    return (await _role(user_id)) in {ROLE_OWNER, ROLE_ADMIN}


async def _allowed(msg: Message) -> bool:
    """Register the user; reject banned users."""
    user_id = msg.from_user.id
    await db.add_user(user_id)
    if await db.is_banned(user_id):
        await msg.reply_text("🚫 You are banned from using this bot.")
        return False
    return True


def _owner_only(func):
    @functools.wraps(func)
    async def wrapper(client, msg: Message):
        if msg.from_user.id != config.OWNER_ID:
            await msg.reply_text("⛔ Owner only.")
            return
        return await func(client, msg)
    return wrapper


def _admin_only(func):
    @functools.wraps(func)
    async def wrapper(client, msg: Message):
        if not await _is_admin(msg.from_user.id):
            await msg.reply_text("⛔ Admins only.")
            return
        return await func(client, msg)
    return wrapper


async def _send_result(msg: Message, path: Path, status: Message | None = None,
                       caption: str | None = None) -> None:
    """Send a file back with live upload progress."""
    size = path.stat().st_size
    if status is None:
        status = await msg.reply_text("📤 Uploading…")
    up = Progress(status, "📤 **Uploading**", total=size)
    try:
        await msg.reply_document(
            str(path),
            caption=caption or f"📄 `{path.name}` ({_human(size)})",
            progress=up.update,
        )
        await up.finish(f"✅ Done — sent `{path.name}` ({_human(size)}).")
    except Exception as exc:
        await up.finish(f"❌ Upload failed: {exc}")
        raise


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
@app.on_message(filters.command("start"))
async def cmd_start(client, msg: Message):
    if not await _allowed(msg):
        return
    await msg.reply_text(
        "🎬 **AudioMuxer Pro Bot**\n\n"
        "Send me a video or audio file, then choose an operation.\n\n"
        "• Mux / demux audio tracks (multi-language)\n"
        "• Auto-detect & fix audio sync\n"
        "• Trim by time, remove silence\n"
        "• Convert, adjust volume, normalize\n\n"
        f"Limits: {config.MAX_FILE_SIZE_MB} MB, "
        f"{config.MAX_DURATION_SECONDS // 3600} h per file.\n"
        "Use /help for the full command list."
    )


@app.on_message(filters.command("help"))
async def cmd_help(client, msg: Message):
    text = (
        "**User commands**\n"
        "/start — welcome\n"
        "/help — this message\n"
        "/myjobs — your recent jobs\n\n"
        "Send any video/audio file to get the action menu.\n\n"
        "**Admin commands**\n"
        "/stats — bot statistics\n"
        "/logs [lines] — recent bot logs\n"
        "/broadcast <text> — message all users (owner)\n"
        "/ban <user_id> / /unban <user_id> (owner)\n"
        "/addadmin <user_id> / /deladmin <user_id> (owner)"
    )
    await msg.reply_text(text)


@app.on_message(filters.command("myjobs"))
async def cmd_myjobs(client, msg: Message):
    if not await _allowed(msg):
        return
    jobs = await db.recent_jobs(msg.from_user.id, limit=8)
    if not jobs:
        await msg.reply_text("No jobs yet.")
        return
    lines = [f"`{j['_id']}` {j['operation']} — {j['status']} ({j.get('progress', 0)}%)"
             for j in jobs]
    await msg.reply_text("**Your recent jobs:**\n" + "\n".join(lines))


@app.on_message(filters.command("stats"))
@_admin_only
async def cmd_stats(client, msg: Message):
    stats = await db.job_stats()
    users = await db.total_users()
    admins = await db.list_admins()
    await msg.reply_text(
        f"📊 **Stats**\n"
        f"Users: {users}\n"
        f"Admins: {len(admins)}\n"
        f"Jobs total: {stats.get('total', 0)}\n"
        f"  done: {stats.get('done', 0)}  failed: {stats.get('failed', 0)}  "
        f"running: {stats.get('running', 0)}"
    )


@app.on_message(filters.command("logs"))
@_admin_only
async def cmd_logs(client, msg: Message):
    """Send recent log lines. Usage: /logs [lines]"""
    try:
        n = int(msg.command[1]) if len(msg.command) > 1 else 100
    except ValueError:
        n = 100
    n = max(1, min(n, 4000))
    path = config.LOG_FILE
    if not path.exists() or path.stat().st_size == 0:
        await msg.reply_text("No log file yet.")
        return
    try:
        lines = path.read_text(errors="replace").splitlines()[-n:]
    except OSError as exc:
        await msg.reply_text(f"❌ Could not read logs: {exc}")
        return
    text = "\n".join(lines) or "(empty)"
    if len(text) <= 4000:
        await msg.reply_text(f"```\n{text}\n```")
        return
    tail = config.WORK_DIR / f"logs_tail_{n}.txt"
    tail.write_text(text)
    await _send_result(msg, tail, caption=f"📜 Last {len(lines)} log lines")
    tail.unlink(missing_ok=True)


@app.on_message(filters.command("addadmin"))
@_owner_only
async def cmd_addadmin(client, msg: Message):
    if len(msg.command) < 2:
        await msg.reply_text("Usage: /addadmin <user_id>")
        return
    await db.add_admin(int(msg.command[1]))
    await msg.reply_text(f"✅ {msg.command[1]} is now an admin.")


@app.on_message(filters.command("deladmin"))
@_owner_only
async def cmd_deladmin(client, msg: Message):
    if len(msg.command) < 2:
        await msg.reply_text("Usage: /deladmin <user_id>")
        return
    await db.remove_admin(int(msg.command[1]))
    await msg.reply_text(f"✅ {msg.command[1]} is no longer an admin.")


@app.on_message(filters.command("ban"))
@_owner_only
async def cmd_ban(client, msg: Message):
    if len(msg.command) < 2:
        await msg.reply_text("Usage: /ban <user_id>")
        return
    await db.set_banned(int(msg.command[1]), True)
    await msg.reply_text(f"🚫 Banned {msg.command[1]}.")


@app.on_message(filters.command("unban"))
@_owner_only
async def cmd_unban(client, msg: Message):
    if len(msg.command) < 2:
        await msg.reply_text("Usage: /unban <user_id>")
        return
    await db.set_banned(int(msg.command[1]), False)
    await msg.reply_text(f"✅ Unbanned {msg.command[1]}.")


@app.on_message(filters.command("broadcast"))
@_owner_only
async def cmd_broadcast(client, msg: Message):
    if len(msg.command) < 2:
        await msg.reply_text("Usage: /broadcast <text>")
        return
    text = msg.text.split(None, 1)[1]
    user_ids = await db.all_user_ids()
    sent, failed = 0, 0
    status = await msg.reply_text(f"📣 Broadcasting to {len(user_ids)} users…")
    for uid in user_ids:
        try:
            await client.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # rate-limit friendly
    await status.edit_text(f"📣 Done. Sent: {sent}, failed: {failed}.")


# ---------------------------------------------------------------------------
# Media handling
# ---------------------------------------------------------------------------
@app.on_message(filters.document | filters.video | filters.audio)
async def handle_media(client, msg: Message):
    if not await _allowed(msg):
        return
    user_id = msg.from_user.id
    state = await db.get_session(user_id)
    pending = state.get("pending_op")

    media = msg.document or msg.video or msg.audio
    file_name = getattr(media, "file_name", None) or f"file_{media.file_unique_id}"
    ext = Path(file_name).suffix.lower()
    if ext not in config.VIDEO_EXTENSIONS | config.AUDIO_EXTENSIONS:
        await msg.reply_text(
            f"❌ Unsupported format `{ext}`.\n"
            f"Video: {', '.join(sorted(config.VIDEO_EXTENSIONS))}\n"
            f"Audio: {', '.join(sorted(config.AUDIO_EXTENSIONS))}"
        )
        return
    if media.file_size and media.file_size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        await msg.reply_text(f"⚠️ File exceeds the {config.MAX_FILE_SIZE_MB} MB limit.")
        return

    status = await msg.reply_text("📥 Preparing download…")
    dest = config.WORK_DIR / f"{user_id}_{media.file_unique_id}{ext}"
    dl = Progress(status, "📥 **Downloading**", total=media.file_size)
    try:
        await msg.download(file_name=str(dest), progress=dl.update)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        await dl.finish(f"❌ Download failed: {exc}")
        return
    await dl.finish(f"📥 Download complete ({_human(dest.stat().st_size)}). Analyzing…")

    if pending in AUDIO_INPUT_OPS and state.get("file"):
        await _handle_audio_input(msg, status, user_id, state, dest)
        return

    try:
        info = await inspect(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        await status.edit_text("🔧 File appears corrupted and could not be probed.")
        return
    if info.duration > config.MAX_DURATION_SECONDS:
        dest.unlink(missing_ok=True)
        await status.edit_text("⚠️ File exceeds the duration limit.")
        return

    state.update({"file": str(dest), "kind": "video" if info.is_video else "audio"})
    state.pop("pending_op", None)
    await db.set_session(user_id, state)
    await status.edit_text(
        f"📹 **{file_name}** received!\n\n```\n{format_info(info)}\n```\n"
        "What would you like to do?",
        reply_markup=MAIN_KEYBOARD,
    )


async def _handle_audio_input(msg, status, user_id, state, audio: Path):
    video = state["file"]
    op = state["pending_op"]
    try:
        if op == "add":
            await _run_job(msg, user_id, "add track", muxer.add_audio_track, video, audio)
        elif op == "replace":
            await _run_job(msg, user_id, "replace track", muxer.replace_audio, video, audio)
        elif op == "sync":
            await status.edit_text("🔍 Analyzing audio sync…")
            result = await detector.detect(video, audio)
            if not result.reliable:
                await status.edit_text(
                    f"⚠️ {result.summary()}\n\nConfidence too low to auto-fix. "
                    "Use 🎯 Manual Sync instead."
                )
            elif abs(result.offset_ms) < 1:
                await status.edit_text("✅ Audio is already aligned (offset < 1 ms).")
            else:
                await status.edit_text(f"🔍 {result.summary()}\nApplying correction…")
                out = await muxer.add_audio_track(
                    video, audio, audio_offset_ms=-int(round(result.offset_ms))
                )
                await _send_result(msg, out, status)
        elif op == "manual_sync":
            state["sync_audio"] = str(audio)
            await db.set_session(user_id, state)
            await status.edit_text(
                "Send the offset in milliseconds "
                "(positive = audio late, negative = audio early), e.g. `-250`."
            )
            return
    except SyncDetectionError as exc:
        await status.edit_text(f"⚠️ Sync detection failed: {exc}")
    except Exception as exc:
        await status.edit_text(f"❌ {exc}")
    finally:
        if op != "manual_sync":
            state.pop("pending_op", None)
            await db.set_session(user_id, state)


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------
@app.on_callback_query()
async def on_button(client, query: CallbackQuery):
    user_id = query.from_user.id
    state = await db.get_session(user_id)
    action = query.data.split(":", 1)[1]

    if action == "info":
        file = state.get("file")
        if not file:
            await query.answer("Send a file first.", show_alert=True)
            return
        info = await inspect(file)
        await query.message.edit_text(f"```\n{format_info(info)}\n```",
                                      reply_markup=MAIN_KEYBOARD)
        await query.answer()
        return

    if not state.get("file"):
        await query.answer("Send a file first.", show_alert=True)
        return

    state["pending_op"] = action
    await db.set_session(user_id, state)

    if action in PARAM_PROMPTS:
        await query.message.edit_text(PARAM_PROMPTS[action])
    elif action in AUDIO_INPUT_OPS:
        note = {
            "add": "as the new track",
            "replace": "as the replacement",
            "sync": "for auto-sync detection",
            "manual_sync": "you'll set the offset after sending it",
        }[action]
        await query.message.edit_text(f"Now send me the **audio file** {note}.")
    await query.answer()


# ---------------------------------------------------------------------------
# Text parameters
# ---------------------------------------------------------------------------
@app.on_message(filters.text & filters.private & ~filters.regex(r"^/"))
async def handle_text(client, msg: Message):
    user_id = msg.from_user.id
    state = await db.get_session(user_id)
    op = state.get("pending_op")
    file = state.get("file")
    if not op or not file:
        return  # not in an operation flow; ignore
    try:
        if op == "manual_sync":
            offset = int(msg.text.strip())
            audio = state.get("sync_audio")
            if not audio:
                await msg.reply_text("Send the audio file first.")
                return
            await _run_job(msg, user_id, "manual sync",
                           muxer.add_audio_track, file, audio, audio_offset_ms=offset)
        elif op in {"extract", "convert"}:
            fmt = msg.text.strip().lower().lstrip(".")
            func = muxer.extract_audio if op == "extract" else muxer.convert_audio
            await _run_job(msg, user_id, op, func, file, out_format=fmt)
        elif op == "trim":
            parts = msg.text.split()
            if len(parts) < 2:
                await msg.reply_text("Send start and end, e.g. `00:10:00 00:20:00`")
                return
            parse_timestamp(parts[0]); parse_timestamp(parts[1])
            await _run_job(msg, user_id, "trim", trimmer.trim, file,
                           start=parts[0], end=parts[1])
        elif op == "denoise":
            kw = {}
            if msg.text.strip().lower() != "go":
                kw["threshold_db"] = float(msg.text.strip())
            status = await msg.reply_text("🔇 Detecting silence…")
            out, segs = await trimmer.remove_silence(file, **kw)
            await status.edit_text(
                f"✅ Silence removed ({len(segs)} segments, "
                f"saved {sum(s.duration for s in segs):.1f}s)"
            )
            await _send_result(msg, out)
        elif op == "volume":
            gain = float(msg.text.strip().lstrip("+"))
            await _run_job(msg, user_id, "volume", muxer.adjust_volume, file, gain_db=gain)
        else:
            return
    except (ValueError, FileValidationError, UnsupportedFormatError) as exc:
        await msg.reply_text(f"❌ {exc}")
        return
    finally:
        state.pop("pending_op", None)
        state.pop("sync_audio", None)
        await db.set_session(user_id, state)


# ---------------------------------------------------------------------------
# Job runner
# ---------------------------------------------------------------------------
async def _run_job(msg, user_id: int, name: str, func, *args, **kwargs):
    job_id = uuid.uuid4().hex[:12]
    await db.create_job(job_id, user_id, name, [str(a) for a in args[:1]])
    status = await msg.reply_text(f"🔄 {name}: queued…")
    prog = Progress(status, f"⚙️ **{name}**")

    async with _queue_sem:
        await db.update_job(job_id, status="running")
        try:
            out = await func(*args, on_progress=prog.update_percent, **kwargs)
            await db.update_job(job_id, status="done", progress=100,
                                result=str(out) if isinstance(out, Path) else None)
            if isinstance(out, Path):
                await _send_result(msg, out, status)
            else:
                await prog.finish(f"✅ {name} finished!")
        except Exception as exc:
            await db.update_job(job_id, status="failed", error=str(exc))
            await prog.finish(f"❌ {name} failed: {exc}")
