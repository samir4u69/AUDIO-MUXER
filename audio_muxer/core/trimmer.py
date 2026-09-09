"""Trimming and silence-removal engine."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from audio_muxer import config
from audio_muxer.ffmpeg_wrapper import run_ffmpeg, probe_duration
from audio_muxer.media_info import validate_input

log = logging.getLogger(__name__)

_SILENCE_START_RE = re.compile(r"silence_start: ([\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end: ([\d.]+)")


@dataclass
class SilenceSegment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_timestamp(ts: str) -> float:
    """Parse 'SS[.mmm]', 'MM:SS' or 'HH:MM:SS[.mmm]' into seconds."""
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
        # 'MM:SS' / 'HH:MM:SS' forms must be well-formed; bare seconds may
        # exceed 60 (e.g. '90' = 90 seconds).
        raise ValueError(f"Invalid timestamp: {ts!r}")
    return hours * 3600 + mins * 60 + secs


class Trimmer:
    def __init__(self, work_dir: Path | None = None):
        self.work_dir = work_dir or config.WORK_DIR

    # ------------------------------------------------------------------
    # Time-based trimming
    # ------------------------------------------------------------------
    async def trim(
        self,
        media: str | Path,
        start: float | str | None = None,
        end: float | str | None = None,
        duration: float | str | None = None,
        reencode: bool = False,
        on_progress=None,
    ) -> Path:
        """Cut media to [start, end] (or start + duration).

        Timestamps may be seconds or 'HH:MM:SS' strings. With both bounds
        given the file is re-encoded for frame-accurate cuts; without an end
        bound the video is stream-copied (fast, keyframe-accurate).
        """
        media = validate_input(media, "any")
        start_s = parse_timestamp(start) if isinstance(start, str) else (start or 0.0)
        if isinstance(end, str):
            end_s = parse_timestamp(end)
            dur = end_s - start_s
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
            reencode = True  # bounded video cuts must be frame-accurate

        out = self.work_dir / f"{media.stem}_trim_{uuid.uuid4().hex[:8]}{media.suffix}"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        args = []
        if not reencode:
            args += ["-ss", f"{start_s:.3f}"]  # input seek: fast, keyframe-level
        args += ["-i", str(media)]
        if reencode:
            args += ["-ss", f"{start_s:.3f}"]  # output seek: frame-accurate
        if dur is not None:
            args += ["-t", f"{dur:.3f}"]
        if reencode:
            args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac"]
        else:
            args += ["-c", "copy"]
        args += ["-avoid_negative_ts", "make_zero", str(out)]

        log.info("trim %s [%.2f -> %s]", media.name, start_s, dur and f"+{dur:.2f}")
        await run_ffmpeg(args, total_duration=dur or (total - start_s), on_progress=on_progress)
        return out

    # ------------------------------------------------------------------
    # Silence handling
    # ------------------------------------------------------------------
    async def detect_silence(
        self,
        media: str | Path,
        threshold_db: float | None = None,
        min_duration: float | None = None,
    ) -> list[SilenceSegment]:
        """Detect silent segments with ffmpeg's silencedetect filter."""
        cfg = config.SILENCE_CONFIG
        threshold = threshold_db if threshold_db is not None else cfg["threshold_db"]
        min_dur = min_duration if min_duration is not None else cfg["min_silence_duration"]

        stderr = await run_ffmpeg([
            "-i", str(media),
            "-af", f"silencedetect=noise={threshold}dB:d={min_dur}",
            "-f", "null", "-",
        ])
        starts = [float(m.group(1)) for m in _SILENCE_START_RE.finditer(stderr)]
        ends = [float(m.group(1)) for m in _SILENCE_END_RE.finditer(stderr)]

        total = await probe_duration(media)
        segments: list[SilenceSegment] = []
        for i, s in enumerate(starts):
            e = ends[i] if i < len(ends) else total
            segments.append(SilenceSegment(start=s, end=min(e, total)))
        log.info("detect_silence: %d segments in %s", len(segments), Path(media).name)
        return segments

    async def remove_silence(
        self,
        media: str | Path,
        threshold_db: float | None = None,
        min_duration: float | None = None,
        padding: float | None = None,
        on_progress=None,
    ) -> tuple[Path, list[SilenceSegment]]:
        """Remove silent segments, keeping ``padding`` seconds around speech.

        Returns (output_path, removed_segments). The kept parts are
        concatenated with the concat filter (audio re-encoded, video
        re-encoded only if present).
        """
        media = validate_input(media, "any")
        cfg = config.SILENCE_CONFIG
        pad = padding if padding is not None else cfg["padding"]

        silences = await self.detect_silence(media, threshold_db, min_duration)
        if not silences:
            raise ValueError("No silence detected — nothing to remove")

        total = await probe_duration(media)
        # Build keep segments = complement of the silences (with padding).
        keep: list[tuple[float, float]] = []
        cursor = 0.0
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

        is_video = media.suffix.lower() in config.VIDEO_EXTENSIONS
        out = self.work_dir / f"{media.stem}_nosil_{uuid.uuid4().hex[:8]}{media.suffix}"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        if len(keep) == 1:
            return await self.trim(media, start=keep[0][0], end=keep[0][1], reencode=True,
                                   on_progress=on_progress), silences

        # Multi-segment: use trim + concat filter.
        # concat expects per-segment pairs: [v0][a0][v1][a1]...
        filters = []
        pairs: list[str] = []
        for i, (s, e) in enumerate(keep):
            if is_video:
                filters.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
            filters.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
            pairs.append((f"[v{i}]" if is_video else "") + f"[a{i}]")
        n = len(keep)
        if is_video:
            filters.append(f"{''.join(pairs)}concat=n={n}:v=1:a=1[vout][aout]")
            map_args = ["-map", "[vout]", "-map", "[aout]", "-c:v", "libx264",
                        "-preset", "fast", "-crf", "18", "-c:a", "aac"]
        else:
            filters.append(f"{''.join(pairs)}concat=n={n}:v=0:a=1[aout]")
            map_args = ["-map", "[aout]", "-c:a", "libmp3lame" if out.suffix == ".mp3" else "aac"]

        args = ["-i", str(media), "-filter_complex", ";".join(filters), *map_args, str(out)]
        new_duration = sum(e - s for s, e in keep)
        log.info("remove_silence: %s %.1fs -> %.1fs", media.name, total, new_duration)
        await run_ffmpeg(args, total_duration=new_duration, on_progress=on_progress)
        return out, silences

    # ------------------------------------------------------------------
    # Segment cutting
    # ------------------------------------------------------------------
    async def cut_segments(
        self,
        media: str | Path,
        segments: list[tuple[float, float]],
        on_progress=None,
    ) -> Path:
        """Remove the given (start, end) segments, keeping everything else."""
        media = validate_input(media, "any")
        total = await probe_duration(media)
        keep: list[tuple[float, float]] = []
        cursor = 0.0
        for s, e in sorted(segments):
            if s > cursor:
                keep.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < total:
            keep.append((cursor, total))
        keep = [(s, e) for s, e in keep if e - s > 0.05]
        if not keep:
            raise ValueError("Cutting those segments would leave an empty file")

        out = self.work_dir / f"{media.stem}_cut_{uuid.uuid4().hex[:8]}{media.suffix}"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        if len(keep) == 1:
            return await self.trim(media, start=keep[0][0], end=keep[0][1], on_progress=on_progress)

        is_video = media.suffix.lower() in config.VIDEO_EXTENSIONS
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
            map_args = ["-map", "[aout]", "-c:a", "aac"]

        args = ["-i", str(media), "-filter_complex", ";".join(filters), *map_args, str(out)]
        await run_ffmpeg(args, total_duration=sum(e - s for s, e in keep),
                         on_progress=on_progress)
        return out

    async def split_at(
        self,
        media: str | Path,
        timestamps: list[float | str],
        on_progress=None,
    ) -> list[Path]:
        """Split media into parts at the given timestamps."""
        media = validate_input(media, "any")
        points = sorted(
            parse_timestamp(t) if isinstance(t, str) else t for t in timestamps
        )
        total = await probe_duration(media)
        points = [p for p in points if 0 < p < total]
        if not points:
            raise ValueError("No valid split points within file duration")

        bounds = [0.0] + points + [total]
        parts: list[Path] = []
        for i in range(len(bounds) - 1):
            part = await self.trim(media, start=bounds[i], end=bounds[i + 1],
                                   on_progress=on_progress)
            parts.append(part)
        return parts
