"""Command-line interface for AudioMuxer Pro.

Examples
--------
    python -m audio_muxer info movie.mkv
    python -m audio_muxer extract movie.mkv -o audio.mp3
    python -m audio_muxer add movie.mkv dub.aac --language Hindi --default
    python -m audio_muxer replace movie.mkv new.aac --track 0
    python -m audio_muxer remove-track movie.mkv --drop 1
    python -m audio_muxer reorder movie.mkv --order 1 0 --default 0
    python -m audio_muxer sync-detect movie.mkv dub.mp3
    python -m audio_muxer sync-fix movie.mkv dub.mp3 --language English
    python -m audio_muxer trim movie.mkv --start 00:10:00 --end 00:20:00
    python -m audio_muxer remove-silence podcast.wav
    python -m audio_muxer volume song.mp3 --gain -3
    python -m audio_muxer normalize song.mp3
    python -m audio_muxer convert song.wav --format mp3 --bitrate 320k
    python -m audio_muxer merge part1.mp3 part2.mp3 -o full.mp3
    python -m audio_muxer split movie.mkv --at 00:30:00 01:00:00
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from audio_muxer import config
from audio_muxer.core.muxer import AudioMuxer
from audio_muxer.core.sync import SyncDetector, SyncDetectionError
from audio_muxer.core.trimmer import Trimmer
from audio_muxer.ffmpeg_wrapper import check_ffmpeg
from audio_muxer.media_info import (
    FileValidationError, UnsupportedFormatError, format_info, inspect,
)

log = logging.getLogger("audiomuxer")


def _progress(percent: int) -> None:
    bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    print(f"\r  [{bar}] {percent}%", end="", flush=True)
    if percent >= 100:
        print()


async def cmd_info(args) -> int:
    info = await inspect(args.input)
    print(format_info(info))
    return 0


async def cmd_extract(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.extract_audio(args.input, out_format=args.format,
                                    audio_track=args.track, bitrate=args.bitrate,
                                    on_progress=_progress)
    print(f"✅ Extracted: {out}")
    return 0


async def cmd_add(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.add_audio_track(
        args.input, args.audio, language=args.language, title=args.title,
        set_default=args.default, audio_offset_ms=args.offset_ms,
        on_progress=_progress,
    )
    info = await inspect(out)
    print(f"✅ Audio added: {out}")
    print(f"   Now {len(info.audio_tracks)} audio track(s)")
    return 0


async def cmd_replace(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.replace_audio(args.input, args.audio, replace_track=args.track,
                                    language=args.language, title=args.title,
                                    audio_offset_ms=args.offset_ms,
                                    on_progress=_progress)
    print(f"✅ Audio replaced: {out}")
    return 0


async def cmd_remove_track(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.remove_audio_tracks(args.input, keep=args.keep, drop=args.drop,
                                          on_progress=_progress)
    print(f"✅ Track(s) removed: {out}")
    return 0


async def cmd_reorder(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.reorder_audio_tracks(args.input, order=args.order,
                                           default_track=args.default,
                                           on_progress=_progress)
    print(f"✅ Tracks reordered: {out}")
    return 0


async def cmd_sync_detect(args) -> int:
    detector = SyncDetector()
    result = await detector.detect(args.reference, args.target)
    print(f"🔍 {result.summary()}")
    if not result.reliable:
        print("⚠️  Confidence below threshold — manual sync recommended.")
        return 2
    return 0


async def cmd_sync_fix(args) -> int:
    detector = SyncDetector()
    result = await detector.detect(args.reference, args.target)
    print(f"🔍 {result.summary()}")
    if not result.reliable and args.offset_ms is None:
        print("❌ Auto-sync unreliable. Re-run with --offset-ms for manual sync.")
        return 2

    offset = args.offset_ms if args.offset_ms is not None else -int(round(result.offset_ms))
    muxer = AudioMuxer()
    out = await muxer.add_audio_track(
        args.reference, args.target, language=args.language, title=args.title,
        audio_offset_ms=offset, on_progress=_progress,
    )
    print(f"✅ Sync-corrected track muxed: {out}")
    return 0


async def cmd_trim(args) -> int:
    trimmer = Trimmer()
    out = await trimmer.trim(args.input, start=args.start, end=args.end,
                             duration=args.duration, reencode=args.frame_accurate,
                             on_progress=_progress)
    print(f"✅ Trimmed: {out}")
    return 0


async def cmd_remove_silence(args) -> int:
    trimmer = Trimmer()
    out, removed = await trimmer.remove_silence(
        args.input, threshold_db=args.threshold, min_duration=args.min_duration,
        padding=args.padding, on_progress=_progress,
    )
    total_removed = sum(s.duration for s in removed)
    print(f"✅ Silence removed: {out}")
    print(f"   {len(removed)} silent segment(s), saved {total_removed:.1f}s")
    return 0


async def cmd_detect_silence(args) -> int:
    trimmer = Trimmer()
    segs = await trimmer.detect_silence(args.input, args.threshold, args.min_duration)
    if not segs:
        print("No silence detected.")
        return 0
    print(f"Found {len(segs)} silent segment(s):")
    for s in segs:
        print(f"  {s.start:>9.2f}s – {s.end:>9.2f}s  ({s.duration:.2f}s)")
    return 0


async def cmd_volume(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.adjust_volume(args.input, args.gain, on_progress=_progress)
    print(f"✅ Volume adjusted: {out}")
    return 0


async def cmd_normalize(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.normalize_audio(args.input, target_lufs=args.lufs,
                                      on_progress=_progress)
    print(f"✅ Normalized: {out}")
    return 0


async def cmd_convert(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.convert_audio(args.input, args.format, bitrate=args.bitrate,
                                    sample_rate=args.sample_rate, on_progress=_progress)
    print(f"✅ Converted: {out}")
    return 0


async def cmd_merge(args) -> int:
    muxer = AudioMuxer()
    out = await muxer.merge_audio(args.inputs, out_format=args.format,
                                  bitrate=args.bitrate, on_progress=_progress)
    print(f"✅ Merged: {out}")
    return 0


async def cmd_split(args) -> int:
    trimmer = Trimmer()
    parts = await trimmer.split_at(args.input, args.at, on_progress=_progress)
    print(f"✅ Split into {len(parts)} parts:")
    for p in parts:
        print(f"   {p}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audio-muxer",
        description="AudioMuxer Pro — mux, sync and trim audio in video files.",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    def add_input(sp, name="input", nargs=None):
        sp.add_argument(name, type=Path, nargs=nargs, help="input media file")

    sp = sub.add_parser("info", help="show media file information")
    add_input(sp); sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("extract", help="extract audio from video")
    add_input(sp)
    sp.add_argument("-o", "--format", default="mp3", help="output format (default mp3)")
    sp.add_argument("--track", type=int, default=0, help="audio track index (default 0)")
    sp.add_argument("--bitrate", default="192k")
    sp.set_defaults(func=cmd_extract)

    sp = sub.add_parser("add", help="add an audio track to a video")
    add_input(sp); sp.add_argument("audio", type=Path)
    sp.add_argument("--language", choices=config.SUPPORTED_LANGUAGES + ["other"], default=None)
    sp.add_argument("--title", default=None)
    sp.add_argument("--default", action="store_true", help="set as default track")
    sp.add_argument("--offset-ms", type=int, default=0, help="+delay / -advance the new track (ms)")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("replace", help="replace an audio track")
    add_input(sp); sp.add_argument("audio", type=Path)
    sp.add_argument("--track", type=int, default=0)
    sp.add_argument("--language", default=None)
    sp.add_argument("--title", default=None)
    sp.add_argument("--offset-ms", type=int, default=0)
    sp.set_defaults(func=cmd_replace)

    sp = sub.add_parser("remove-track", help="remove audio tracks (keep or drop)")
    add_input(sp)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--keep", type=int, nargs="+", help="audio ordinals to keep")
    g.add_argument("--drop", type=int, nargs="+", help="audio ordinals to drop")
    sp.set_defaults(func=cmd_remove_track)

    sp = sub.add_parser("reorder", help="reorder audio tracks")
    add_input(sp)
    sp.add_argument("--order", type=int, nargs="+", required=True,
                    help="audio ordinals in new order, e.g. 1 0")
    sp.add_argument("--default", type=int, default=None, help="new default track index")
    sp.set_defaults(func=cmd_reorder)

    sp = sub.add_parser("sync-detect", help="detect sync offset between two files")
    sp.add_argument("reference", type=Path, help="reference (usually the video)")
    sp.add_argument("target", type=Path, help="target audio/video to measure")
    sp.set_defaults(func=cmd_sync_detect)

    sp = sub.add_parser("sync-fix", help="auto-detect sync and mux corrected track")
    sp.add_argument("reference", type=Path)
    sp.add_argument("target", type=Path)
    sp.add_argument("--offset-ms", type=int, default=None,
                    help="manual offset; skips auto-detection failure")
    sp.add_argument("--language", default=None)
    sp.add_argument("--title", default=None)
    sp.set_defaults(func=cmd_sync_fix)

    sp = sub.add_parser("trim", help="trim media by time range")
    add_input(sp)
    sp.add_argument("--start", default=None, help="start (seconds or HH:MM:SS)")
    sp.add_argument("--end", default=None, help="end time")
    sp.add_argument("--duration", default=None, help="duration instead of end")
    sp.add_argument("--frame-accurate", action="store_true", help="re-encode for exact cuts")
    sp.set_defaults(func=cmd_trim)

    sp = sub.add_parser("detect-silence", help="list silent segments")
    add_input(sp)
    sp.add_argument("--threshold", type=float, default=None, help="dB threshold (default -40)")
    sp.add_argument("--min-duration", type=float, default=None, help="seconds (default 0.5)")
    sp.set_defaults(func=cmd_detect_silence)

    sp = sub.add_parser("remove-silence", help="remove silent parts")
    add_input(sp)
    sp.add_argument("--threshold", type=float, default=None)
    sp.add_argument("--min-duration", type=float, default=None)
    sp.add_argument("--padding", type=float, default=None, help="context kept around speech (s)")
    sp.set_defaults(func=cmd_remove_silence)

    sp = sub.add_parser("volume", help="adjust volume by dB")
    add_input(sp)
    sp.add_argument("--gain", type=float, required=True, help="gain in dB (e.g. -3, +6)")
    sp.set_defaults(func=cmd_volume)

    sp = sub.add_parser("normalize", help="EBU R128 loudness normalization")
    add_input(sp)
    sp.add_argument("--lufs", type=float, default=-14.0)
    sp.set_defaults(func=cmd_normalize)

    sp = sub.add_parser("convert", help="convert audio format")
    add_input(sp)
    sp.add_argument("--format", required=True, help="target format (mp3, aac, wav, ...)")
    sp.add_argument("--bitrate", default="192k")
    sp.add_argument("--sample-rate", type=int, default=None, choices=config.SAMPLE_RATES)
    sp.set_defaults(func=cmd_convert)

    sp = sub.add_parser("merge", help="concatenate audio files")
    add_input(sp, name="inputs", nargs="+")
    sp.add_argument("-o", "--format", default="mp3")
    sp.add_argument("--bitrate", default="192k")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("split", help="split media at timestamps")
    add_input(sp)
    sp.add_argument("--at", nargs="+", required=True, help="split points (HH:MM:SS or seconds)")
    sp.set_defaults(func=cmd_split)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ok, msg = check_ffmpeg()
    if not ok:
        print(f"❌ ffmpeg check failed: {msg}", file=sys.stderr)
        print("   Install ffmpeg: https://ffmpeg.org/download.html", file=sys.stderr)
        return 127

    try:
        return asyncio.run(args.func(args))
    except (FileValidationError, UnsupportedFormatError, ValueError, SyncDetectionError) as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n🚫 Cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
