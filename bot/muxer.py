"""Audio muxing / demuxing / conversion engine (async, ffmpeg-based)."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from bot import config
from bot.ffmpeg_wrapper import run_ffmpeg, probe_duration
from bot.media_info import validate_input

log = logging.getLogger(__name__)


def _out(out_dir: Path, stem: str, ext: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{stem}_{uuid.uuid4().hex[:8]}{ext}"


class AudioMuxer:
    def __init__(self, work_dir: Path | None = None):
        self.work_dir = work_dir or config.WORK_DIR

    async def extract_audio(self, video, out_format="mp3", audio_track=0,
                            bitrate="192k", on_progress=None) -> Path:
        video = validate_input(video, "video")
        out_format = out_format.lstrip(".").lower()
        out = _out(self.work_dir, video.stem, f".{out_format}")
        duration = await probe_duration(video)
        args = ["-i", str(video), "-map", f"0:a:{audio_track}", "-vn",
                *self._codec_args(out_format, bitrate), str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def add_audio_track(self, video, audio, language=None, title=None,
                              set_default=False, audio_offset_ms=0,
                              out_format=None, on_progress=None) -> Path:
        video = validate_input(video, "video")
        audio = validate_input(audio, "audio")
        ext = f".{out_format}" if out_format else video.suffix
        out = _out(self.work_dir, video.stem, ext)
        duration = await probe_duration(video)

        from bot.media_info import inspect
        info = await inspect(video)
        new_idx = len(info.audio_tracks)

        args = ["-i", str(video)]
        if audio_offset_ms < 0:
            args += ["-ss", str(abs(audio_offset_ms) / 1000.0)]
        args += ["-i", str(audio), "-map", "0", "-map", "1:a"]
        if audio_offset_ms > 0:
            args += [f"-c:a:{new_idx}", "aac",
                     f"-filter:a:{new_idx}", f"adelay={audio_offset_ms}:all=1"]
        args += ["-c", "copy", "-map_metadata", "0"]
        if language:
            code = config.LANGUAGE_CODES.get(language.lower(), language[:3].lower())
            args += [f"-metadata:s:a:{new_idx}", f"language={code}"]
        if title:
            args += [f"-metadata:s:a:{new_idx}", f"title={title}"]
        if set_default:
            args += ["-disposition:a", "0", f"-disposition:a:{new_idx}", "default"]
        args += [str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def replace_audio(self, video, audio, replace_track=0, language=None,
                            title=None, audio_offset_ms=0, on_progress=None) -> Path:
        video = validate_input(video, "video")
        audio = validate_input(audio, "audio")
        out = _out(self.work_dir, video.stem, video.suffix)
        duration = await probe_duration(video)

        from bot.media_info import inspect
        info = await inspect(video)
        n_audio = len(info.audio_tracks)
        if not 0 <= replace_track < n_audio:
            raise ValueError(f"Audio track {replace_track} not found ({n_audio} tracks)")

        args = ["-i", str(video)]
        if audio_offset_ms < 0:
            args += ["-ss", str(abs(audio_offset_ms) / 1000.0)]
        args += ["-i", str(audio)]
        mapping = ["-map", "0:v?"]
        for i in range(n_audio):
            mapping += ["-map", "1:a:0" if i == replace_track else f"0:a:{i}"]
        mapping += ["-map", "0:s?"]
        args += mapping

        filter_args = []
        if audio_offset_ms > 0:
            filter_args = ["-af", f"adelay={audio_offset_ms}:all=1"]
        # Re-encode audio so a different-codec/delayed replacement can be written.
        args += ["-c:v", "copy", "-c:a", "aac", "-c:s", "copy"] + filter_args

        if language:
            code = config.LANGUAGE_CODES.get(language.lower(), language[:3].lower())
            args += [f"-metadata:s:a:{replace_track}", f"language={code}"]
        if title:
            args += [f"-metadata:s:a:{replace_track}", f"title={title}"]
        args += [str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def remove_audio_tracks(self, video, keep=None, drop=None, on_progress=None) -> Path:
        video = validate_input(video, "video")
        from bot.media_info import inspect
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

        out = _out(self.work_dir, video.stem, video.suffix)
        args = ["-i", str(video), "-map", "0:v?"]
        for i in wanted:
            args += ["-map", f"0:a:{i}"]
        args += ["-map", "0:s?", "-c", "copy", str(out)]
        await run_ffmpeg(args, total_duration=info.duration, on_progress=on_progress)
        return out

    async def reorder_audio_tracks(self, video, order, default_track=None, on_progress=None) -> Path:
        video = validate_input(video, "video")
        from bot.media_info import inspect
        info = await inspect(video)
        n_audio = len(info.audio_tracks)
        if sorted(order) != list(range(n_audio)):
            raise ValueError(f"order must be a permutation of 0..{n_audio - 1}")
        out = _out(self.work_dir, video.stem, video.suffix)
        args = ["-i", str(video), "-map", "0:v?"]
        for i in order:
            args += ["-map", f"0:a:{i}"]
        args += ["-map", "0:s?", "-c", "copy"]
        if default_track is not None:
            args += ["-disposition:a", "0", f"-disposition:a:{default_track}", "default"]
        args += [str(out)]
        await run_ffmpeg(args, total_duration=info.duration, on_progress=on_progress)
        return out

    async def convert_audio(self, audio, out_format, bitrate="192k",
                            sample_rate=None, on_progress=None) -> Path:
        audio = validate_input(audio, "audio")
        out_format = out_format.lstrip(".").lower()
        out = _out(self.work_dir, audio.stem, f".{out_format}")
        duration = await probe_duration(audio)
        args = ["-i", str(audio), *self._codec_args(out_format, bitrate)]
        if sample_rate:
            args += ["-ar", str(sample_rate)]
        args += [str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def adjust_volume(self, audio, gain_db, on_progress=None) -> Path:
        audio = validate_input(audio, "any")
        out = _out(self.work_dir, audio.stem, audio.suffix)
        duration = await probe_duration(audio)
        is_video = audio.suffix.lower() in config.VIDEO_EXTENSIONS
        args = ["-i", str(audio), "-af", f"volume={gain_db}dB"]
        args += ["-c:v", "copy"] if is_video else []
        args += [str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def normalize_audio(self, audio, target_lufs=-14.0, on_progress=None) -> Path:
        audio = validate_input(audio, "any")
        out = _out(self.work_dir, audio.stem, audio.suffix)
        duration = await probe_duration(audio)
        is_video = audio.suffix.lower() in config.VIDEO_EXTENSIONS
        args = ["-i", str(audio), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"]
        args += ["-c:v", "copy"] if is_video else []
        args += [str(out)]
        await run_ffmpeg(args, total_duration=duration, on_progress=on_progress)
        return out

    async def merge_audio(self, audio_files, out_format="mp3", bitrate="192k",
                          on_progress=None) -> Path:
        if len(audio_files) < 2:
            raise ValueError("Need at least 2 audio files to merge")
        files = [validate_input(f, "audio") for f in audio_files]
        out = _out(self.work_dir, files[0].stem, f".{out_format}")
        args = []
        for f in files:
            args += ["-i", str(f)]
        inputs = "".join(f"[{i}:a]" for i in range(len(files)))
        args += ["-filter_complex", f"{inputs}concat=n={len(files)}:v=0:a=1[aout]",
                 "-map", "[aout]", *self._codec_args(out_format, bitrate), str(out)]
        total = sum([await probe_duration(f) for f in files])
        await run_ffmpeg(args, total_duration=total, on_progress=on_progress)
        return out

    @staticmethod
    def _codec_args(fmt, bitrate):
        codec_map = {
            "mp3": "libmp3lame", "aac": "aac", "m4a": "aac", "ogg": "libvorbis",
            "opus": "libopus", "flac": "flac", "wav": "pcm_s16le",
            "ac3": "ac3", "eac3": "eac3", "wma": "wmav2",
        }
        codec = codec_map.get(fmt)
        if codec is None:
            raise ValueError(f"No encoder for format: {fmt}")
        args = ["-acodec", codec]
        if fmt not in {"wav", "flac"}:
            args += ["-b:a", bitrate]
        return args
