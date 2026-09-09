"""Media inspection and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bot import config
from bot.ffmpeg_wrapper import probe


class UnsupportedFormatError(ValueError):
    pass


class FileValidationError(ValueError):
    pass


@dataclass
class AudioTrack:
    index: int
    audio_number: int
    codec: str
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    language: str | None
    title: str | None
    is_default: bool
    duration: float | None


@dataclass
class MediaInfo:
    path: Path
    format_name: str
    duration: float
    size_bytes: int
    bitrate: int | None
    has_video: bool = False
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitle_count: int = 0

    @property
    def is_video(self) -> bool:
        return self.has_video

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}" if self.width and self.height else "-"


def validate_input(path, expect: str = "any") -> Path:
    p = Path(path)
    if not p.exists():
        raise FileValidationError(f"File not found: {p}")
    if p.stat().st_size == 0:
        raise FileValidationError("File is empty")
    if p.stat().st_size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise FileValidationError(f"File exceeds {config.MAX_FILE_SIZE_MB} MB limit")
    ext = p.suffix.lower()
    if expect == "video" and ext not in config.VIDEO_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported video format '{ext}'")
    if expect == "audio" and ext not in config.AUDIO_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported audio format '{ext}'")
    return p


def _fps(rate):
    if not rate or "/" not in rate:
        return None
    num, den = rate.split("/", 1)
    try:
        return round(int(num) / max(int(den), 1), 3)
    except ValueError:
        return None


async def inspect(path) -> MediaInfo:
    p = Path(path)
    data = await probe(p)
    fmt = data.get("format", {})
    info = MediaInfo(
        path=p,
        format_name=fmt.get("format_name", "unknown"),
        duration=float(fmt.get("duration", 0) or 0),
        size_bytes=int(fmt.get("size", 0) or 0),
        bitrate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
    )
    audio_n = 0
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        tags = s.get("tags", {}) or {}
        if kind == "video":
            info.has_video = True
            info.video_codec = s.get("codec_name")
            info.width, info.height = s.get("width"), s.get("height")
            info.fps = _fps(s.get("avg_frame_rate"))
        elif kind == "audio":
            info.audio_tracks.append(AudioTrack(
                index=s["index"], audio_number=audio_n,
                codec=s.get("codec_name", "?"),
                sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
                channels=s.get("channels"),
                bitrate=int(s["bit_rate"]) if s.get("bit_rate") else None,
                language=tags.get("language"), title=tags.get("title"),
                is_default=s.get("disposition", {}).get("default", 0) == 1,
                duration=float(s["duration"]) if s.get("duration") else None,
            ))
            audio_n += 1
        elif kind == "subtitle":
            info.subtitle_count += 1
    return info


def format_info(info: MediaInfo) -> str:
    lines = [
        f"Format: {info.format_name} | Duration: {_fmt_duration(info.duration)}",
        f"Size: {info.size_bytes / 1024**2:.1f} MB",
    ]
    if info.has_video:
        fps = f" @ {info.fps:g}fps" if info.fps else ""
        lines.append(f"Video: {info.video_codec} {info.resolution}{fps}")
    for a in info.audio_tracks:
        parts = [a.codec]
        if a.sample_rate:
            parts.append(f"{a.sample_rate}Hz")
        if a.channels:
            parts.append(f"{a.channels}ch")
        if a.bitrate:
            parts.append(f"{a.bitrate // 1000}kbps")
        if a.language:
            parts.append(f"[{a.language}]")
        default = " (default)" if a.is_default else ""
        lines.append(f"Audio #{a.audio_number + 1}: {' '.join(parts)}{default}")
    if info.subtitle_count:
        lines.append(f"Subtitles: {info.subtitle_count} track(s)")
    return "\n".join(lines)


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
