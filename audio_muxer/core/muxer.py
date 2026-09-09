"""Audio muxing / demuxing / conversion engine built on ffmpeg.

All operations are async and stream-copy the video whenever possible so
muxing a multi-GB file costs seconds, not a full re-encode.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from audio_muxer import config
from audio_muxer.ffmpeg_wrapper import run_ffmpeg, probe_duration
from audio_muxer.media_info import validate_input

log = logging.getLogger(__name__)


def _out_path(out_dir: Path, stem: str, ext: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}_{uuid.uuid4().hex[:8]}{ext}"


class AudioMuxer:
    """High-level video/audio muxing operations."""

    def __init__(self, work_dir: Path | None = None):
        self.work_dir = work_dir or config.WORK_DIR

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    async def extract_audio(
        self,
        video: str | Path,
        out_format: str = "mp3",
        audio_track: int = 0,
        bitrate: str = "192k",
        on_progress=None,
    ) -> Path:
        """Extract one audio track from a video file."""
        video = validate_input(video, "video")
        out_format = out_format.lstrip(".").lower()
        if f".{out_format}" not in config.AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported output audio format: {out_format}")

        out = _out_path(self.work_dir, video.stem, f".{out_format}")
        duration = await probe_duration(video)

        codec_args = self._audio_codec_args(out_format, bitrate)
        args = [
            "-i", str(video),
            "-map", f"0:a:{audio_track}",
            "-vn", *codec_args,
            str(out),
        ]
        log.info("extract_audio %s -> %s", video.name, out.name)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    # ------------------------------------------------------------------
    # Muxing
    # ------------------------------------------------------------------
    async def add_audio_track(
        self,
        video: str | Path,
        audio: str | Path,
        language: str | None = None,
        title: str | None = None,
        set_default: bool = False,
        audio_offset_ms: int = 0,
        out_format: str | None = None,
        on_progress=None,
    ) -> Path:
        """Add an external audio file as a new track. Video is stream-copied.

        ``audio_offset_ms`` > 0 delays the audio, < 0 cuts its head.
        """
        video = validate_input(video, "video")
        audio = validate_input(audio, "audio")

        ext = f".{out_format}" if out_format else video.suffix
        out = _out_path(self.work_dir, video.stem, ext)
        duration = await probe_duration(video)

        # Determine how many audio streams the video already has so we can
        # place metadata on the newly appended one.
        from audio_muxer.media_info import inspect
        info = await inspect(video)
        new_idx = len(info.audio_tracks)

        args = ["-i", str(video)]
        if audio_offset_ms < 0:
            args += ["-ss", str(abs(audio_offset_ms) / 1000.0)]
        args += ["-i", str(audio)]
        args += ["-map", "0", "-map", "1:a"]

        if audio_offset_ms > 0:
            # Re-encode only the new audio with an adelay filter.
            args += [f"-c:a:{new_idx}", "aac", f"-filter:a:{new_idx}", f"adelay={audio_offset_ms}:all=1"]

        args += ["-c", "copy", "-map_metadata", "0"]

        if language:
            code = config.LANGUAGE_CODES.get(language.lower(), language[:3].lower())
            args += [f"-metadata:s:a:{new_idx}", f"language={code}"]
        if title:
            args += [f"-metadata:s:a:{new_idx}", f"title={title}"]
        if set_default:
            args += ["-disposition:a", "0", f"-disposition:a:{new_idx}", "default"]

        args += [str(out)]
        log.info("add_audio_track %s + %s -> %s", video.name, audio.name, out.name)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def replace_audio(
        self,
        video: str | Path,
        audio: str | Path,
        replace_track: int = 0,
        language: str | None = None,
        title: str | None = None,
        audio_offset_ms: int = 0,
        on_progress=None,
    ) -> Path:
        """Replace an existing audio track with an external audio file."""
        video = validate_input(video, "video")
        audio = validate_input(audio, "audio")
        out = _out_path(self.work_dir, video.stem, video.suffix)
        duration = await probe_duration(video)

        from audio_muxer.media_info import inspect
        info = await inspect(video)
        n_audio = len(info.audio_tracks)
        if not 0 <= replace_track < n_audio:
            raise ValueError(f"Audio track {replace_track} not found ({n_audio} tracks)")

        args = ["-i", str(video)]
        if audio_offset_ms < 0:
            args += ["-ss", str(abs(audio_offset_ms) / 1000.0)]
        args += ["-i", str(audio)]

        # Map: all video, then audio streams with the chosen one swapped out.
        mapping: list[str] = []
        mapping += ["-map", "0:v?"]
        for i in range(n_audio):
            mapping += ["-map", "1:a:0" if i == replace_track else f"0:a:{i}"]
        mapping += ["-map", "0:s?"]
        args += mapping

        filter_args: list[str] = []
        if audio_offset_ms > 0:
            filter_args = ["-af", f"adelay={audio_offset_ms}:all=1"]

        # Re-encode the audio so the replacement track (which may have a
        # different codec or sample rate, or need an adelay filter) can be
        # written cleanly. Video and subtitles are stream-copied.
        args += ["-c:v", "copy", "-c:a", "aac", "-c:s", "copy"] + filter_args

        if language:
            code = config.LANGUAGE_CODES.get(language.lower(), language[:3].lower())
            args += [f"-metadata:s:a:{replace_track}", f"language={code}"]
        if title:
            args += [f"-metadata:s:a:{replace_track}", f"title={title}"]

        args += [str(out)]
        log.info("replace_audio track %d of %s", replace_track, video.name)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def remove_audio_tracks(
        self,
        video: str | Path,
        keep: list[int] | None = None,
        drop: list[int] | None = None,
        on_progress=None,
    ) -> Path:
        """Return video with only the wanted audio tracks (by audio ordinal).

        Provide either ``keep`` (whitelist) or ``drop`` (blacklist).
        """
        video = validate_input(video, "video")
        from audio_muxer.media_info import inspect
        info = await inspect(video)
        n_audio = len(info.audio_tracks)
        if n_audio == 0:
            raise ValueError("Video has no audio tracks")

        if keep is not None:
            wanted = sorted(set(keep))
        elif drop is not None:
            wanted = [i for i in range(n_audio) if i not in set(drop)]
        else:
            raise ValueError("Provide either keep= or drop=")
        if not wanted:
            raise ValueError("Cannot remove every audio track")
        for i in wanted:
            if not 0 <= i < n_audio:
                raise ValueError(f"Audio track {i} not found ({n_audio} tracks)")

        out = _out_path(self.work_dir, video.stem, video.suffix)
        args = ["-i", str(video), "-map", "0:v?"]
        for i in wanted:
            args += ["-map", f"0:a:{i}"]
        args += ["-map", "0:s?", "-c", "copy", str(out)]

        log.info("remove_audio_tracks keeping %s of %s", wanted, video.name)
        await run_ffmpeg(args, total_duration=info.duration, on_progress=on_progress)
        return out

    async def reorder_audio_tracks(
        self,
        video: str | Path,
        order: list[int],
        default_track: int | None = None,
        on_progress=None,
    ) -> Path:
        """Reorder audio tracks. ``order`` lists audio ordinals in new order."""
        video = validate_input(video, "video")
        from audio_muxer.media_info import inspect
        info = await inspect(video)
        n_audio = len(info.audio_tracks)
        if sorted(order) != list(range(n_audio)):
            raise ValueError(f"order must be a permutation of 0..{n_audio - 1}")

        out = _out_path(self.work_dir, video.stem, video.suffix)
        args = ["-i", str(video), "-map", "0:v?"]
        for i in order:
            args += ["-map", f"0:a:{i}"]
        args += ["-map", "0:s?", "-c", "copy"]

        if default_track is not None:
            if not 0 <= default_track < n_audio:
                raise ValueError(f"default_track {default_track} out of range")
            args += ["-disposition:a", "0", f"-disposition:a:{default_track}", "default"]

        args += [str(out)]
        log.info("reorder_audio_tracks %s order=%s", video.name, order)
        await run_ffmpeg(args, total_duration=info.duration, on_progress=on_progress)
        return out

    # ------------------------------------------------------------------
    # Audio-only operations
    # ------------------------------------------------------------------
    async def convert_audio(
        self,
        audio: str | Path,
        out_format: str,
        bitrate: str = "192k",
        sample_rate: int | None = None,
        on_progress=None,
    ) -> Path:
        """Convert an audio file to another format/bitrate."""
        audio = validate_input(audio, "audio")
        out_format = out_format.lstrip(".").lower()
        out = _out_path(self.work_dir, audio.stem, f".{out_format}")
        duration = await probe_duration(audio)

        args = ["-i", str(audio), *self._audio_codec_args(out_format, bitrate)]
        if sample_rate:
            if sample_rate not in config.SAMPLE_RATES:
                raise ValueError(f"Sample rate must be one of {config.SAMPLE_RATES}")
            args += ["-ar", str(sample_rate)]
        args += [str(out)]

        log.info("convert_audio %s -> %s", audio.name, out.name)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def adjust_volume(
        self,
        audio: str | Path,
        gain_db: float,
        on_progress=None,
    ) -> Path:
        """Adjust audio volume by ``gain_db`` decibels (can be negative)."""
        audio = validate_input(audio, "any")
        out = _out_path(self.work_dir, audio.stem, audio.suffix)
        duration = await probe_duration(audio)

        is_video = audio.suffix.lower() in config.VIDEO_EXTENSIONS
        args = ["-i", str(audio), "-af", f"volume={gain_db}dB"]
        args += ["-c:v", "copy"] if is_video else []
        args += [str(out)]

        log.info("adjust_volume %s %+gdB", audio.name, gain_db)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def normalize_audio(
        self,
        audio: str | Path,
        target_lufs: float = -14.0,
        on_progress=None,
    ) -> Path:
        """Normalize loudness (EBU R128) to ``target_lufs``."""
        audio = validate_input(audio, "any")
        out = _out_path(self.work_dir, audio.stem, audio.suffix)
        duration = await probe_duration(audio)

        is_video = audio.suffix.lower() in config.VIDEO_EXTENSIONS
        args = ["-i", str(audio), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"]
        args += ["-c:v", "copy"] if is_video else []
        args += [str(out)]

        log.info("normalize_audio %s to %.1f LUFS", audio.name, target_lufs)
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def merge_audio(
        self,
        audio_files: list[str | Path],
        out_format: str = "mp3",
        bitrate: str = "192k",
        on_progress=None,
    ) -> Path:
        """Concatenate multiple audio files into one.

        Uses the concat filter so files with different codecs/sample rates
        can be mixed; output is re-encoded to ``out_format``.
        """
        if len(audio_files) < 2:
            raise ValueError("Need at least 2 audio files to merge")
        files = [validate_input(f, "audio") for f in audio_files]

        out = _out_path(self.work_dir, files[0].stem, f".{out_format}")
        args: list[str] = []
        for f in files:
            args += ["-i", str(f)]
        inputs = "".join(f"[{i}:a]" for i in range(len(files)))
        args += [
            "-filter_complex", f"{inputs}concat=n={len(files)}:v=0:a=1[aout]",
            "-map", "[aout]",
            *self._audio_codec_args(out_format, bitrate),
            str(out),
        ]
        total = 0.0
        for f in files:
            total += await probe_duration(f)
        log.info("merge_audio %d files -> %s", len(files), out.name)
        await run_ffmpeg(args, total_duration=total, on_progress=on_progress)
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _audio_codec_args(fmt: str, bitrate: str) -> list[str]:
        codec_map = {
            "mp3": "libmp3lame", "aac": "aac", "m4a": "aac", "ogg": "libvorbis",
            "opus": "libopus", "flac": "flac", "wav": "pcm_s16le",
            "ac3": "ac3", "eac3": "eac3", "wma": "wmav2", "dts": "dca",
        }
        codec = codec_map.get(fmt)
        if codec is None:
            raise ValueError(f"No encoder mapping for format: {fmt}")
        args = ["-acodec", codec]
        if fmt not in {"wav", "flac"}:  # lossless: bitrate not applicable
            args += ["-b:a", bitrate]
        return args
