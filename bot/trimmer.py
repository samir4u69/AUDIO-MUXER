"""Trimming and silence removal."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from bot import config
from bot.ffmpeg_wrapper import run_ffmpeg, probe_duration
from bot.media_info import validate_input

log = logging.getLogger(__name__)

_SIL_START = re.compile(r"silence_start: ([\d.]+)")
_SIL_END = re.compile(r"silence_end: ([\d.]+)")


@dataclass
class SilenceSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_timestamp(ts: str) -> float:
    ts = ts.strip()
    if not ts:
        raise ValueError("Empty timestamp")
    parts = ts.split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {ts!r} (use HH:MM:SS)")
    if any(not p or not all(c.isdigit() or c == "." for c in p) for p in parts):
        raise ValueError(f"Invalid timestamp: {ts!r}")
    secs = float(parts[-1])
    mins = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) == 3 else 0
    if mins < 0 or hours < 0 or secs < 0:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    if len(parts) >= 2 and (mins >= 60 or secs >= 60):
        raise ValueError(f"Invalid timestamp: {ts!r}")
    return hours * 3600 + mins * 60 + secs


class Trimmer:
    def __init__(self, work_dir: Path | None = None):
        self.work_dir = work_dir or config.WORK_DIR

    async def trim(self, media, start=None, end=None, duration=None,
                   reencode=False, on_progress=None) -> Path:
        media = validate_input(media, "any")
        start_s = parse_timestamp(start) if isinstance(start, str) else (start or 0.0)
        if isinstance(end, str):
            dur = parse_timestamp(end) - start_s
        elif end is not None:
            dur = end - start_s
        elif isinstance(duration, str):
            dur = parse_timestamp(duration)
        else:
            dur = duration
        if dur is not None and dur <= 0:
            raise ValueError("End time must be after start time")
        total = await probe_duration(media)
        if start_s >= total:
            raise ValueError(f"Start {start_s:.1f}s is beyond file duration {total:.1f}s")

        is_video = media.suffix.lower() in config.VIDEO_EXTENSIONS
        if dur is not None and is_video:
            reencode = True

        out = self.work_dir / f"{media.stem}_trim_{uuid.uuid4().hex[:8]}{media.suffix}"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        args = []
        if not reencode:
            args += ["-ss", f"{start_s:.3f}"]
        args += ["-i", str(media)]
        if reencode:
            args += ["-ss", f"{start_s:.3f}"]
        if dur is not None:
            args += ["-t", f"{dur:.3f}"]
        if reencode:
            args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac"]
        else:
            args += ["-c", "copy"]
        args += ["-avoid_negative_ts", "make_zero", str(out)]
        await run_ffmpeg(args, total_duration=dur or (total - start_s), on_progress=on_progress)
        return out

    async def detect_silence(self, media, threshold_db=None, min_duration=None) -> list[SilenceSegment]:
        cfg = config.SILENCE_CONFIG
        threshold = threshold_db if threshold_db is not None else cfg["threshold_db"]
        min_dur = min_duration if min_duration is not None else cfg["min_silence_duration"]
        stderr = await run_ffmpeg([
            "-i", str(media),
            "-af", f"silencedetect=noise={threshold}dB:d={min_dur}",
            "-f", "null", "-",
        ])
        starts = [float(m.group(1)) for m in _SIL_START.finditer(stderr)]
        ends = [float(m.group(1)) for m in _SIL_END.finditer(stderr)]
        total = await probe_duration(media)
        return [SilenceSegment(s, min(ends[i] if i < len(ends) else total, total))
                for i, s in enumerate(starts)]

    async def remove_silence(self, media, threshold_db=None, min_duration=None,
                             padding=None, on_progress=None) -> tuple[Path, list[SilenceSegment]]:
        media = validate_input(media, "any")
        cfg = config.SILENCE_CONFIG
        pad = padding if padding is not None else cfg["padding"]
        silences = await self.detect_silence(media, threshold_db, min_duration)
        if not silences:
            raise ValueError("No silence detected — nothing to remove")
        total = await probe_duration(media)

        keep, cursor = [], 0.0
        for seg in silences:
            keep_end = min(seg.start + pad, total)
            if keep_end > cursor:
                keep.append((cursor, keep_end))
            cursor = max(cursor, seg.end - pad)
        if cursor < total:
            keep.append((cursor, total))
        keep = [(s, e) for s, e in keep if e - s > 0.05]
        if not keep:
            raise ValueError("Removing silence would leave an empty file")
        if len(keep) == 1:
            out = await self.trim(media, start=keep[0][0], end=keep[0][1],
                                  reencode=True, on_progress=on_progress)
            return out, silences

        is_video = media.suffix.lower() in config.VIDEO_EXTENSIONS
        out = self.work_dir / f"{media.stem}_nosil_{uuid.uuid4().hex[:8]}{media.suffix}"
        filters, pairs = [], []
        for i, (s, e) in enumerate(keep):
            if is_video:
                filters.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
            filters.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
            pairs.append((f"[v{i}]" if is_video else "") + f"[a{i}]")
        if is_video:
            filters.append(f"{''.join(pairs)}concat=n={len(keep)}:v=1:a=1[vout][aout]")
            map_args = ["-map", "[vout]", "-map", "[aout]", "-c:v", "libx264",
                        "-preset", "fast", "-crf", "18", "-c:a", "aac"]
        else:
            filters.append(f"{''.join(pairs)}concat=n={len(keep)}:v=0:a=1[aout]")
            map_args = ["-map", "[aout]", "-c:a", "libmp3lame" if out.suffix == ".mp3" else "aac"]
        args = ["-i", str(media), "-filter_complex", ";".join(filters), *map_args, str(out)]
        await run_ffmpeg(args, total_duration=sum(e - s for s, e in keep), on_progress=on_progress)
        return out, silences

    async def split_at(self, media, timestamps, on_progress=None) -> list[Path]:
        media = validate_input(media, "any")
        points = sorted(parse_timestamp(t) if isinstance(t, str) else t for t in timestamps)
        total = await probe_duration(media)
        points = [p for p in points if 0 < p < total]
        if not points:
            raise ValueError("No valid split points within file duration")
        bounds = [0.0] + points + [total]
        return [await self.trim(media, start=bounds[i], end=bounds[i + 1],
                                on_progress=on_progress) for i in range(len(bounds) - 1)]
