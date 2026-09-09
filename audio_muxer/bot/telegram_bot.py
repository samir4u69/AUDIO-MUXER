"""Telegram bot frontend for AudioMuxer Pro.

Requires: python-telegram-bot>=20.0  (optional dependency)
Set TELEGRAM_BOT_TOKEN in the environment, then run:

    python -m audio_muxer.bot.telegram_bot

Flow
----
1. User sends a video/audio document → bot validates, probes, shows the
   inline-button menu and stores the file in the session.
2. Single-file ops (extract, trim, remove silence, volume, convert) ask for
   their parameters in plain text and run immediately.
3. Two-file ops (add / replace / auto sync) set a ``pending_op``; the next
   document the user sends is treated as the audio input.
4. Manual sync asks for the offset in ms after receiving the audio file.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from audio_muxer import config
from audio_muxer.core.muxer import AudioMuxer
from audio_muxer.core.sync import SyncDetector, SyncDetectionError
from audio_muxer.core.trimmer import Trimmer, parse_timestamp
from audio_muxer.database import Database
from audio_muxer.media_info import (
    FileValidationError, UnsupportedFormatError, format_info, inspect,
)
from audio_muxer.queue import JobQueue, TempJanitor

log = logging.getLogger("audiomuxer.telegram")

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application, CallbackQueryHandler, CommandHandler, ContextTypes,
        MessageHandler, filters,
    )
except ImportError:  # pragma: no cover
    raise SystemExit(
        "python-telegram-bot is not installed. "
        "Install it with: pip install audio-muxer[telegram]"
    )


MUXER = AudioMuxer()
TRIMMER = Trimmer()
DETECTOR = SyncDetector()
QUEUE = JobQueue()
DB = Database()
JANITOR = TempJanitor()

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

# Prompts shown when a button needs a text parameter next.
PARAM_PROMPTS = {
    "extract": "Which audio format? Reply with mp3, aac, wav, flac, ogg or opus.",
    "trim": "Send start and end times, e.g. `00:10:00 00:20:00`",
    "denoise": "Send silence threshold in dB (e.g. `-40`) or `go` for defaults.",
    "volume": "Send the gain in dB, e.g. `+6` or `-3`.",
    "convert": "Which format? mp3, aac, wav, flac, ogg, opus…",
}

# Two-file operations: the next document is the audio input.
AUDIO_INPUT_OPS = {"add", "replace", "sync", "manual_sync"}


def _session(user_id: int) -> dict:
    return DB.get_session(str(user_id))


def _save_session(user_id: int, state: dict) -> None:
    DB.set_session(str(user_id), state)


def _bar(percent: int) -> str:
    filled = percent // 10
    return "█" * filled + "░" * (10 - filled)


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎬 *AudioMuxer Pro Bot*\n\n"
        "Send me a video or audio file, then choose an operation.\n\n"
        "• Mux / demux audio tracks (multi-language)\n"
        "• Auto-detect & fix audio sync\n"
        "• Trim by time, remove silence\n"
        "• Convert, adjust volume, normalize\n\n"
        f"Limits: {config.MAX_FILE_SIZE_BYTES // 1024**2} MB, "
        f"{config.MAX_DURATION_SECONDS // 3600} h per file.",
        parse_mode="Markdown",
    )


async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Receive a file; route it as a new upload or as an operation input."""
    msg = update.message
    user_id = update.effective_user.id
    state = _session(user_id)
    pending = state.get("pending_op")

    doc = msg.document or msg.video or msg.audio
    if doc is None:
        await msg.reply_text("Please send the file as a document.")
        return

    file_name = getattr(doc, "file_name", None) or f"file_{doc.file_unique_id}"
    ext = Path(file_name).suffix.lower()
    allowed = config.VIDEO_EXTENSIONS | config.AUDIO_EXTENSIONS
    if ext not in allowed:
        await msg.reply_text(
            f"❌ Unsupported format '{ext}'.\n"
            f"Video: {', '.join(sorted(config.VIDEO_EXTENSIONS))}\n"
            f"Audio: {', '.join(sorted(config.AUDIO_EXTENSIONS))}"
        )
        return
    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE_BYTES:
        await msg.reply_text("⚠️ File exceeds the 2 GB limit. Please compress or split it.")
        return

    status = await msg.reply_text("📥 Downloading…")
    dest = config.WORK_DIR / f"{user_id}_{doc.file_unique_id}{ext}"
    tg_file = await ctx.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(dest)

    # ----- second file for a pending two-file operation -----------------
    if pending in AUDIO_INPUT_OPS and state.get("file"):
        await _handle_audio_input(msg, status, user_id, state, dest)
        return

    # ----- fresh upload -------------------------------------------------
    try:
        info = await inspect(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        await status.edit_text("🔧 File appears corrupted and could not be probed.")
        return

    if info.duration > config.MAX_DURATION_SECONDS:
        dest.unlink(missing_ok=True)
        await status.edit_text("⚠️ File exceeds the 4 h duration limit.")
        return

    state.update({"file": str(dest), "kind": "video" if info.is_video else "audio"})
    state.pop("pending_op", None)
    _save_session(user_id, state)

    await status.edit_text(
        f"📹 *{file_name}* received!\n\n```\n{format_info(info)}\n```\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def _handle_audio_input(msg, status, user_id: int, state: dict, audio: Path) -> None:
    """Process the audio file for add/replace/sync operations."""
    video = state["file"]
    op = state["pending_op"]
    try:
        if op == "add":
            await _run_job(msg, user_id, "add track",
                           MUXER.add_audio_track, video, audio)
        elif op == "replace":
            await _run_job(msg, user_id, "replace track",
                           MUXER.replace_audio, video, audio)
        elif op == "sync":
            await status.edit_text("🔍 Analyzing audio sync…")
            result = await DETECTOR.detect(video, audio)
            if not result.reliable:
                await status.edit_text(
                    f"⚠️ {result.summary()}\n\nConfidence too low to auto-fix. "
                    "Use 🎯 Manual Sync to set the offset yourself."
                )
            elif abs(result.offset_ms) < 1:
                await status.edit_text("✅ Audio is already aligned (offset < 1 ms).")
            else:
                await status.edit_text(
                    f"🔍 {result.summary()}\nApplying correction…"
                )
                out = await MUXER.add_audio_track(
                    video, audio, audio_offset_ms=-int(round(result.offset_ms))
                )
                await status.edit_text("✅ Sync corrected! Audio now aligned.")
                await msg.reply_document(out)
        elif op == "manual_sync":
            state["sync_audio"] = str(audio)
            _save_session(user_id, state)  # keep pending_op for the ms input
            await status.edit_text(
                "Send the offset in milliseconds "
                "(positive = audio plays late, negative = audio early), e.g. `-250`."
            )
            return
    except SyncDetectionError as exc:
        await status.edit_text(f"⚠️ Sync detection failed: {exc}")
    except Exception as exc:
        await status.edit_text(f"❌ {exc}")
    finally:
        if op != "manual_sync":
            state.pop("pending_op", None)
            _save_session(user_id, state)


async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch inline-keyboard actions."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    state = _session(user_id)
    action = query.data.split(":", 1)[1]

    if action == "info":
        file = state.get("file")
        if not file:
            await query.edit_message_text("Send me a file first.")
            return
        info = await inspect(file)
        await query.edit_message_text(f"```\n{format_info(info)}\n```",
                                      parse_mode="Markdown",
                                      reply_markup=MAIN_KEYBOARD)
        return

    if not state.get("file"):
        await query.edit_message_text("Send me a file first.")
        return

    state["pending_op"] = action
    _save_session(user_id, state)

    if action in PARAM_PROMPTS:
        await query.edit_message_text(PARAM_PROMPTS[action], parse_mode="Markdown")
    elif action in AUDIO_INPUT_OPS:
        note = {
            "add": "as the new track",
            "replace": "as the replacement",
            "sync": "for auto-sync detection",
            "manual_sync": "you'll set the offset after sending it",
        }[action]
        await query.edit_message_text(
            f"Now send me the *audio file* {note}.", parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("Unknown action.", reply_markup=MAIN_KEYBOARD)


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text parameters for pending operations."""
    msg = update.message
    user_id = update.effective_user.id
    state = _session(user_id)
    op = state.get("pending_op")
    file = state.get("file")
    if not op or not file:
        await msg.reply_text("Send me a file first, then pick an operation.")
        return

    try:
        if op == "manual_sync":
            offset = int(msg.text.strip())
            audio = state.get("sync_audio")
            if not audio:
                await msg.reply_text("Send the audio file first.")
                return
            await _run_job(msg, user_id, "manual sync",
                           MUXER.add_audio_track, file, audio,
                           audio_offset_ms=offset)
        elif op in {"extract", "convert"}:
            fmt = msg.text.strip().lower().lstrip(".")
            func = MUXER.extract_audio if op == "extract" else MUXER.convert_audio
            await _run_job(msg, user_id, op, func, file, out_format=fmt)
        elif op == "trim":
            parts = msg.text.split()
            if len(parts) < 2:
                await msg.reply_text("Send start and end, e.g. `00:10:00 00:20:00`")
                return
            parse_timestamp(parts[0]); parse_timestamp(parts[1])  # validate
            await _run_job(msg, user_id, "trim", TRIMMER.trim, file,
                           start=parts[0], end=parts[1])
        elif op == "denoise":
            kw = {}
            if msg.text.strip().lower() != "go":
                kw["threshold_db"] = float(msg.text.strip())
            status = await msg.reply_text("🔇 Detecting silence…")
            out, segs = await TRIMMER.remove_silence(file, **kw)
            saved = sum(s.duration for s in segs)
            await status.edit_text(
                f"✅ Silence removed ({len(segs)} segments, saved {saved:.1f}s)")
            await msg.reply_document(out)
        elif op == "volume":
            gain = float(msg.text.strip().lstrip("+"))
            await _run_job(msg, user_id, "volume", MUXER.adjust_volume, file, gain_db=gain)
        else:
            await msg.reply_text("That operation needs an audio file. Send it as a document.")
            return
    except (ValueError, FileValidationError, UnsupportedFormatError) as exc:
        await msg.reply_text(f"❌ {exc}")
        return
    finally:
        state.pop("pending_op", None)
        state.pop("sync_audio", None)
        _save_session(user_id, state)


async def _run_job(msg, user_id: int, name: str, func, *args, **kwargs):
    """Run an engine operation through the queue with progress updates."""
    job = QUEUE.create(name, user_id=str(user_id), inputs=[str(a) for a in args[:1]])
    DB.create_job(job.id, str(user_id), name, job.inputs)
    status = await msg.reply_text(f"🔄 {name} started…")
    state = {"last": -10}

    def progress(p: int):
        if p - state["last"] >= 10 and p < 100:
            state["last"] = p
            asyncio.ensure_future(
                status.edit_text(f"🔄 {name}: [{_bar(p)}] {p}%")
            )

    try:
        out = await QUEUE.submit(job, func, *args, on_progress=progress, **kwargs)
        DB.update_job(job.id, status="done", progress=100,
                      result=[str(out)] if isinstance(out, Path) else None)
        await status.edit_text(f"✅ {name} finished!")
        if isinstance(out, Path):
            await msg.reply_document(out)
    except Exception as exc:
        DB.update_job(job.id, status="failed", error=str(exc))
        await status.edit_text(f"❌ {name} failed: {exc}")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO, handle_media))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    JANITOR.start()
    log.info("Telegram bot starting…")
    app.run_polling()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
