# Architecture

## Overview

```
┌──────────────────────────────────────────────────────────────┐
│ Interfaces                                                   │
│   audio_muxer/__main__.py  (CLI)   bot/telegram_bot.py (TG)  │
└──────────────┬───────────────────────────────┬───────────────┘
               │                               │
┌──────────────▼──────────────┐   ┌────────────▼─────────────┐
│ queue.py                    │   │ database.py              │
│ JobQueue (semaphore-bound   │   │ SQLite: jobs, events,    │
│ concurrency), TempJanitor   │   │ user_sessions            │
└──────────────┬──────────────┘   └──────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│ Core engines                                                 │
│   core/muxer.py    extract/add/replace/remove/reorder,       │
│                    convert, volume, normalize, merge         │
│   core/sync.py     cross-correlation sync detection + drift  │
│   core/trimmer.py  trim, silence detect/remove, cut, split   │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────┐   ┌───────────────────────────┐
│ ffmpeg_wrapper.py           │   │ media_info.py             │
│ async ffmpeg/ffprobe runner,│   │ probing, validation,      │
│ progress parsing            │   │ track listing             │
└─────────────────────────────┘   └───────────────────────────┘
```

## Data flow

1. **Upload** (bot) or **path** (CLI) → `media_info.validate_input`
   checks existence, size, extension; `inspect` probes streams.
2. The chosen operation becomes a `Job` in `JobQueue`, persisted in
   SQLite; ffmpeg runs under a semaphore (default 4 concurrent).
3. `run_ffmpeg` parses `time=HH:MM:SS.xx` from stderr and reports
   percentage through the job's `on_progress` callback.
4. Output lands in `AUDIOMUXER_WORK_DIR`; the `TempJanitor` removes files
   older than the TTL.

## Key design decisions

- **Stream copy first.** Add/remove/reorder audio tracks never re-encode
  the video, so muxing a 2 GB file takes seconds. Re-encoding only happens
  when content actually changes (bounded trims, silence removal, delayed
  audio insertion).
- **Correlation-based sync.** Decoding 120 s at 8 kHz mono costs ~2 MB of
  RAM per file — fast and memory-safe even for 4 h sources. The confidence
  metric (normalized peak × sharpness) separates true matches (~0.6+) from
  noise (~0.3); low-confidence results demand manual offsets instead of
  silently applying a wrong shift.
- **Frame-accurate cuts by default.** `-ss` after `-i` (output seek) plus
  re-encode for bounded trims; input seek + stream copy only for open-ended
  tails.
- **Everything async.** ffmpeg runs as a subprocess with
  `asyncio.create_subprocess_exec`, so the Telegram bot stays responsive
  while jobs run.

## Sign conventions

- `offset_ms > 0` → target audio is **late** (fix: trim its head).
- `offset_ms < 0` → target audio is **early** (fix: `adelay` padding).
