"""Media file inspection: track listing, validation, human-readable info."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from audio_muxer import config
from audio_muxer.ffmpeg_wrapper import probe


class UnsupportedFormatError(ValueError):
    pass


class FileValidationError(ValueError):
    pass


@dataclass
class AudioTrack:
    index: int            # stream index within the container
    audio_number: int     # ordinal among audio streams (0-based)
    codec: str
    sample_rate: int | None
    channels: int | None
    bitrate: int | None
    language: str | None
    title: str | None
    is_default: bool
    duration: float | None


@dataclass
class VideoTrack:
    index: int
    codec: str
    width: int | None
    height: int | None
    fps: float | None
    bitrate: int | None


@dataclass
class MediaInfo:
    path: Path
    format_name: str
    duration: float
    size_bytes: int
    bitrate: int | None
    video_tracks: list[VideoTrack] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    subtitle_count: int = 0

    @property
    def is_video(self) -> bool:
        return bool(self.video_tracks)

    @property
    def resolution(self) -> str:
        if not self.video_tracks:
            return "-"
        v = self.video_tracks[0]
        return f"{v.width}x{v.height}" if v.width and v.height else "-"


def validate_input(path: str | Path, expect: str = "any") -> Path:
    """Validate size/extension of an input file. ``expect``: video|audio|any."""
    p = Path(path)
    if not p.exists():
        raise FileValidationError(f"File not found: {p}")
    if not p.is_file():
        raise FileValidationError(f"Not a regular file: {p}")
    size = p.stat().st_size
    if size == 0:
        raise FileValidationError("File is empty")
    if size > config.MAX_FILE_SIZE_BYTES:
        raise FileValidationError(
            f"File exceeds {config.MAX_FILE_SIZE_BYTES // 1024**3}GB limit "
            f"({size / 1024**3:.2f}GB)"
        )
    ext = p.suffix.lower()
    if expect == "video" and ext not in config.VIDEO_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported video format '{ext}'. Supported: {sorted(config.VIDEO_EXTENSIONS)}"
        )
    if expect == "audio" and ext not in config.AUDIO_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported audio format '{ext}'. Supported: {sorted(config.AUDIO_EXTENSIONS)}"
        )
    if expect == "any" and ext not in config.VIDEO_EXTENSIONS | config.AUDIO_EXTENSIONS:
        raise UnsupportedFormatError(f"Unsupported file format '{ext}'")
    return p


def _fps(rate: str | None) -> float | None:
    if not rate or "/" not in rate:
        return None
    num, den = rate.split("/", 1)
    try:
        return round(int(num) / max(int(den), 1), 3)
    except ValueError:
        return None


async def inspect(path: str | Path) -> MediaInfo:
    """Probe a media file and return structured info."""
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
            info.video_tracks.append(VideoTrack(
                index=s["index"],
                codec=s.get("codec_name", "?"),
                width=s.get("width"), height=s.get("height"),
                fps=_fps(s.get("avg_frame_rate")),
                bitrate=int(s["bit_rate"]) if s.get("bit_rate") else None,
            ))
        elif kind == "audio":
            info.audio_tracks.append(AudioTrack(
                index=s["index"],
                audio_number=audio_n,
                codec=s.get("codec_name", "?"),
                sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
                channels=s.get("channels"),
                bitrate=int(s["bit_rate"]) if s.get("bit_rate") else None,
                language=tags.get("language"),
                title=tags.get("title"),
                is_default=s.get("disposition", {}).get("default", 0) == 1,
                duration=float(s["duration"]) if s.get("duration") else None,
            ))
            audio_n += 1
        elif kind == "subtitle":
            info.subtitle_count += 1
    return info


def format_info(info: MediaInfo) -> str:
    """Human-readable summary shown to users after upload."""
    lines = [
        f"Format: {info.format_name} | Duration: {_fmt_duration(info.duration)}",
        f"Size: {info.size_bytes / 1024**2:.1f} MB",
    ]
    for v in info.video_tracks:
        fps = f" @ {v.fps:g}fps" if v.fps else ""
        lines.append(f"Video: {v.codec} {info.resolution}{fps}")
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
        label = f" #{a.audio_number + 1}"
        default = " (default)" if a.is_default else ""
        lines.append(f"Audio{label}: {' '.join(parts)}{default}")
    if info.subtitle_count:
        lines.append(f"Subtitles: {info.subtitle_count} track(s)")
    return "\n".join(lines)


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
