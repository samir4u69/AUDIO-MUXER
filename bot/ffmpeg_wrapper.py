"""Thin async wrapper around ffmpeg/ffprobe."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path

from bot import config

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd, self.returncode, self.stderr = cmd, returncode, stderr
        tail = "\n".join(stderr.strip().splitlines()[-5:])
        super().__init__(f"ffmpeg exited {returncode}: {tail}")


def check_ffmpeg() -> tuple[bool, str]:
    for binary in (config.FFMPEG_BIN, config.FFPROBE_BIN):
        if shutil.which(binary) is None:
            return False, f"'{binary}' not found in PATH"
    return True, "ok"


def require_ffmpeg() -> None:
    ok, msg = check_ffmpeg()
    if not ok:
        raise FFmpegError([], 127, msg)


_TIME_RE = re.compile(rb"time=(\d+):(\d+):([\d.]+)")


async def run_ffmpeg(args, total_duration=None, on_progress=None, timeout=None) -> str:
    require_ffmpeg()
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-y", *args]
    log.debug("ffmpeg: %s", " ".join(map(str, cmd)))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    chunks: list[bytes] = []
    try:
        while True:
            chunk = await asyncio.wait_for(proc.stderr.read(4096), timeout)
            if not chunk:
                break
            chunks.append(chunk)
            if on_progress and total_duration:
                for m in _TIME_RE.finditer(chunk):
                    elapsed = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                    on_progress(min(99, int(elapsed / total_duration * 100)))
        await asyncio.wait_for(proc.wait(), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        proc.kill()
        await proc.wait()
        raise FFmpegError(cmd, -9, "ffmpeg timed out")
    except asyncio.CancelledError:
        # Task was cancelled (user pressed Cancel): kill ffmpeg so it doesn't
        # keep running in the background, then propagate.
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        raise
    stderr = b"".join(chunks).decode("utf-8", "replace")
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, stderr)
    if on_progress:
        on_progress(100)
    return stderr


async def run_ffprobe(args) -> str:
    require_ffmpeg()
    cmd = [config.FFPROBE_BIN, "-hide_banner", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, err.decode("utf-8", "replace"))
    return out.decode("utf-8", "replace")


async def probe(path) -> dict:
    raw = await run_ffprobe([
        "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    return json.loads(raw)


async def probe_duration(path) -> float:
    data = await probe(path)
    try:
        return float(data["format"]["duration"])
    except (KeyError, ValueError):
        durations = [float(s["duration"]) for s in data.get("streams", []) if "duration" in s]
        if durations:
            return max(durations)
        raise FFmpegError([], 1, "Could not determine duration")
