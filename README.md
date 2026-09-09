# AudioMuxer Pro

Audio muxing, auto-sync detection and trimming for video files — with a CLI
and an optional Telegram bot interface. Built on FFmpeg with async Python.

## Features

- **Video operations** — extract / add / replace / remove / reorder audio
  tracks; multi-language dubbing with language + title metadata and
  default-track flags. Video is stream-copied whenever possible (no
  re-encode).
- **Audio operations** — convert formats, adjust volume (dB), loudness
  normalization (EBU R128), merge multiple files.
- **Auto-sync detection** — FFT cross-correlation finds the offset between
  a reference video and an external audio track in milliseconds, with a
  confidence score and drift estimation (start vs. end of file).
  Unreliable results are flagged so you can fall back to manual offsets.
- **Trimming** — trim by time range (`HH:MM:SS` or seconds), silence
  detection and removal, cutting arbitrary segments, splitting at
  timestamps. Bounded cuts are re-encoded for frame accuracy.
- **Bot infrastructure** — Telegram bot with inline-button menus, progress
  bars, a bounded-concurrency job queue, SQLite job/session persistence,
  and automatic temp-file cleanup.

## Requirements

- Python 3.10+
- FFmpeg 4.4+ (`ffmpeg` and `ffprobe` on the PATH)
- `numpy`, `scipy` (installed automatically)
- `python-telegram-bot` (only for the Telegram bot: `pip install .[telegram]`)

## Installation

```bash
# Ubuntu / Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Install the package
pip install .

# With Telegram bot support
pip install .[telegram]

# For development / running tests
pip install .[dev]
```

## CLI usage

```bash
# Inspect a file (streams, codecs, languages, duration)
audio-muxer info movie.mkv

# Extract audio (default: first track → mp3)
audio-muxer extract movie.mkv -o mp3 --track 0

# Add a second audio track (multi-language dubbing)
audio-muxer add movie.mkv dub_hindi.mp3 --language Hindi --title "Hindi dub" --default

# Replace the first audio track
audio-muxer replace movie.mkv new_audio.aac --track 0

# Remove the second audio track / keep only tracks 0 and 2
audio-muxer remove-track movie.mkv --drop 1
audio-muxer remove-track movie.mkv --keep 0 2

# Reorder tracks and set the default
audio-muxer reorder movie.mkv --order 1 0 --default 0

# Detect sync offset between the video and an external audio file
audio-muxer sync-detect movie.mkv dub.mp3

# Auto-detect and mux the corrected track (or pass --offset-ms manually)
audio-muxer sync-fix movie.mkv dub.mp3 --language English
audio-muxer add movie.mkv dub.mp3 --offset-ms -250   # manual: audio 250ms early

# Trim / silence / split
audio-muxer trim movie.mkv --start 00:10:00 --end 00:20:00
audio-muxer detect-silence podcast.wav
audio-muxer remove-silence podcast.wav --threshold -40 --min-duration 0.5
audio-muxer split movie.mkv --at 00:30:00 01:00:00

# Audio utilities
audio-muxer volume song.mp3 --gain -3
audio-muxer normalize song.mp3 --lufs -14
audio-muxer convert song.wav --format mp3 --bitrate 320k
audio-muxer merge part1.mp3 part2.mp3 -o mp3
```

Every long-running command prints a live progress bar.

## Telegram bot

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF…"
audio-muxer-bot
```

Send any video/audio file to the bot; it replies with the file's metadata
and an inline-button menu:

```
[🎵 Extract Audio] [➕ Add Audio]
[🔄 Replace Audio] [📋 List Tracks]
[🔍 Auto Sync]     [🎯 Manual Sync]
[✂️ Trim]          [🔇 Remove Silence]
[🎚️ Volume]        [🔁 Convert]
```

Jobs run through a queue (max 4 concurrent ffmpeg processes by default),
progress is edited into the status message, and results are sent back as
documents. Temp files are swept automatically after 24 h.

## Configuration

All knobs live in `audio_muxer/config.py` and can be overridden via
environment variables:

| Variable                  | Default            | Meaning                        |
|---------------------------|--------------------|--------------------------------|
| `AUDIOMUXER_WORK_DIR`     | `/tmp/audiomuxer`  | temp/output directory          |
| `AUDIOMUXER_MAX_FILE_SIZE`| `2147483648` (2GB) | upload limit in bytes          |
| `AUDIOMUXER_MAX_DURATION` | `14400` (4 h)      | duration limit in seconds      |
| `AUDIOMUXER_MAX_JOBS`     | `4`                | concurrent ffmpeg processes    |
| `AUDIOMUXER_TEMP_TTL`     | `86400`            | temp file lifetime in seconds  |
| `FFMPEG_BIN` / `FFPROBE_BIN` | `ffmpeg` / `ffprobe` | binary names/paths          |

Sync detection parameters (`SYNC_CONFIG`): analysis window 120 s, max
offset ±30 s, 8 kHz correlation rate, confidence threshold 0.4.
Silence detection defaults: −40 dB threshold, 0.5 s minimum duration,
0.1 s padding.

## How sync detection works

1. A mono 8 kHz PCM window (default 120 s) is decoded from the start of
   both the reference and the target file.
2. The signals are cross-correlated via FFT; the lag of the correlation
   peak gives the offset with sub-millisecond resolution.
3. Confidence combines the energy-normalized peak height with a
   peak-sharpness measure. Unrelated audio yields a flat correlation curve
   (~0.3) and is rejected; matching content scores ≥ 0.6.
4. For long files a second window at the end is measured too; the
   difference between start and end offsets reports the drift in ms/hour.

> Note: periodic signals (pure test tones, metronomes) alias under
> correlation — offsets can be off by whole periods. Real programme audio
> (speech, music, effects) is sample-accurate.

## Database

Jobs and user sessions are stored in SQLite (`$AUDIOMUXER_WORK_DIR/
audiomuxer.db`). Schema: `jobs` (status, progress, inputs, result, error,
timestamps), `job_events` (progress history), `user_sessions` (per-chat
upload state for the bot).

## Docker

```bash
docker build -t audio-muxer .
docker run --rm -v "$PWD/media:/media" audio-muxer info /media/movie.mkv

# Telegram bot
docker run -e TELEGRAM_BOT_TOKEN="…" -v audiomuxer-data:/data/audiomuxer \
  audio-muxer audio-muxer-bot
```

## Development

```bash
pip install .[dev]
python -m pytest        # 44 tests: muxing, sync, trimming, queue, DB
```

The test suite generates its own synthetic fixtures with ffmpeg
(test pattern videos, tones, silence gaps) — no sample downloads needed.

## Troubleshooting

- **`ffmpeg check failed: 'ffmpeg' not found in PATH`** — install FFmpeg
  (see above) or set `FFMPEG_BIN`/`FFPROBE_BIN`.
- **`File exceeds 2GB limit`** — raise `AUDIOMUXER_MAX_FILE_SIZE` or
  compress/split the input first.
- **`Could not auto-detect sync` / low confidence** — the audio tracks
  don't actually match (different cut, different language recording) or
  are too short. Use `--offset-ms` for manual correction.
- **MP4 output with exotic audio codecs fails** — MP4 only supports a
  limited codec set. Use MKV (`--out-format mkv` via the API) for
  DTS/TrueHD/PCM tracks.
- **Trimmed file starts slightly early** — stream-copy cuts snap to
  keyframes. Bounded trims already re-encode; if you force `-c copy`
  via the API, expect keyframe-level accuracy only.
