# AudioMuxer Bot

A Telegram bot for audio muxing, auto-sync detection and trimming in video
files. Built on **Pyrogram** (MTProto), **MongoDB** (users/roles/jobs) and
**FFmpeg**.

## Features

- Extract / add / replace audio tracks (multi-language metadata, default-track flag)
- Remove and reorder audio tracks
- Auto-sync detection between a video and an external audio track (FFT
  cross-correlation, confidence-scored, with manual offset fallback)
- Trim by time range, remove silence
- Convert formats, adjust volume, loudness-normalize
- Inline-button menu with **live progress UI** — download, processing and
  upload each show an animated bar with %, transferred size, speed and ETA
  (throttled to respect Telegram rate limits)
- Owner / admin roles, ban/unban, broadcast, stats, `/logs` tail command
- Job queue with bounded concurrency; automatic temp-file cleanup

## Setup

### 1. Get credentials

- `API_ID` and `API_HASH` — https://my.telegram.org/apps
- `BOT_TOKEN` — @BotFather
- `OWNER_ID` — your Telegram user ID (from @userinfobot)

### 2. Configure

```bash
cp .env.example .env
# edit .env with your values
```

### 3. Run with Docker Compose (recommended)

```bash
docker compose up -d --build
```

This starts the bot **and** a MongoDB container, with persistent volumes.

### Run locally

```bash
pip install -r requirements.txt
sudo apt-get install ffmpeg        # or: brew install ffmpeg
# MongoDB must be running (MONGO_URI in .env)
python -m bot
```

## Usage

1. Send any video or audio file to the bot.
2. It replies with the file's metadata and an action menu:

```
[🎵 Extract Audio] [➕ Add Audio]
[🔄 Replace Audio] [📋 List Tracks]
[🔍 Auto Sync]     [🎯 Manual Sync]
[✂️ Trim]          [🔇 Remove Silence]
[🎚️ Volume]        [🔁 Convert]
```

3. Tap an action and follow the prompt (send the second file for
   add/replace/sync, or the parameters for trim/volume/convert).
4. Watch the live progress: download → processing → upload each show an
   animated bar with percentage, transferred size, speed and ETA.

```
📥 Downloading
[████████░░░░] 67%
📦 134.0 MB / 200.0 MB
⚡ 8.2 MB/s   ⏳ ETA 8s
⏱ 16s elapsed
```

### Commands

| Command | Who | Purpose |
|---------|-----|---------|
| `/start`, `/help` | all | intro & command list |
| `/myjobs` | all | your recent jobs |
| `/stats` | admins | users/jobs/admins counts |
| `/logs [lines]` | admins | tail of the bot log (default 100) |
| `/broadcast <text>` | owner | message every user |
| `/ban <id>` / `/unban <id>` | owner | ban management |
| `/addadmin <id>` / `/deladmin <id>` | owner | role management |

## Environment variables

See `.env.example` for the full list. Required: `API_ID`, `API_HASH`,
`BOT_TOKEN`, `OWNER_ID`, `MONGO_URI`.

## How sync detection works

The bot decodes a mono 8 kHz PCM window from the start (and end, for drift)
of both files and cross-correlates them via FFT. The peak lag gives the
offset in milliseconds; a confidence score (normalized peak × sharpness)
decides whether to auto-apply the fix or ask for a manual offset. Pure test
tones can alias — real speech/music is sample-accurate.

## Project layout

```
bot/
├── __main__.py        # entry point, config validation, janitor
├── config.py          # .env loading, all settings
├── handlers.py        # pyrogram handlers: commands, buttons, media flow
├── database.py        # MongoDB: users/roles/jobs/sessions/settings
├── muxer.py           # extract/add/replace/remove/reorder/convert/volume/normalize/merge
├── sync.py            # cross-correlation sync detection
├── trimmer.py         # trim, silence detection/removal, split
├── media_info.py      # ffprobe inspection + validation
└── ffmpeg_wrapper.py  # async ffmpeg/ffprobe with progress parsing
```

## License

MIT
