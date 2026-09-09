"""Thin async wrapper around the ffmpeg/ffprobe binaries."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path

from audio_muxer import config

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe exits non-zero."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        self.cmd, self.returncode, self.stderr = cmd, returncode, stderr
        tail = "\n".join(stderr.strip().splitlines()[-5:])
        super().__init__(f"ffmpeg exited {returncode}: {tail}")


def check_ffmpeg() -> tuple[bool, str]:
    """Return (ok, version_or_error) for the ffmpeg binary."""
    for binary in (config.FFMPEG_BIN, config.FFPROBE_BIN):
        if shutil.which(binary) is None:
            return False, f"'{binary}' not found in PATH"
    return True, "ok"


def require_ffmpeg() -> None:
    ok, msg = check_ffmpeg()
    if not ok:
        raise FFmpegError([], 127, msg)


_DURATION_RE = re.compile(rb"Duration: (\d+):(\d+):([\d.]+)")
_TIME_RE = re.compile(rb"time=(\d+):(\d+):([\d.]+)")


async def run_ffmpeg(
    args: list[str],
    total_duration: float | None = None,
    on_progress=None,
    timeout: float | None = None,
) -> str:
    """Run ffmpeg asynchronously.

    Args:
        args: arguments after the ffmpeg binary name.
        total_duration: if given, ``on_progress(percent)`` is called as
            ``time=`` updates are parsed from stderr.
        on_progress: callable receiving an int 0-100.
        timeout: hard kill after this many seconds.
    """
    require_ffmpeg()
    cmd = [config.FFMPEG_BIN, "-hide_banner", "-y", *args]
    log.debug("ffmpeg cmd: %s", " ".join(map(str, cmd)))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_chunks: list[bytes] = []
    try:
        while True:
            chunk = await asyncio.wait_for(proc.stderr.read(4096), timeout)
            if not chunk:
                break
            stderr_chunks.append(chunk)
            if on_progress and total_duration:
                for m in _TIME_RE.finditer(chunk):
                    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    elapsed = h * 3600 + mnt * 60 + s
                    on_progress(min(99, int(elapsed / total_duration * 100)))
        await asyncio.wait_for(proc.wait(), timeout)
    except (asyncio.TimeoutError, TimeoutError):
        proc.kill()
        await proc.wait()
        raise FFmpegError(cmd, -9, "ffmpeg timed out")

    stderr = b"".join(stderr_chunks).decode("utf-8", "replace")
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, stderr)
    if on_progress:
        on_progress(100)
    return stderr


async def run_ffprobe(args: list[str]) -> str:
    """Run ffprobe asynchronously and return stdout."""
    require_ffmpeg()
    cmd = [config.FFPROBE_BIN, "-hide_banner", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.returncode, err.decode("utf-8", "replace"))
    return out.decode("utf-8", "replace")


async def probe(path: str | Path) -> dict:
    """Return ffprobe JSON metadata for a media file."""
    raw = await run_ffprobe([
        "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FFmpegError([], 1, f"ffprobe returned invalid JSON: {exc}") from exc


async def probe_duration(path: str | Path) -> float:
    """Return container duration in seconds."""
    data = await probe(path)
    try:
        return float(data["format"]["duration"])
    except (KeyError, ValueError):
        # Fall back to the longest stream duration.
        durations = [float(s["duration"]) for s in data.get("streams", []) if "duration" in s]
        if durations:
            return max(durations)
        raise FFmpegError([], 1, "Could not determine file duration")
