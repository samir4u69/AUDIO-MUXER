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
docker compose logs -f bot      # follow the logs
docker compose down             # stop
```

This starts the bot **and** a MongoDB container, with persistent volumes.
Set `MONGO_URI=mongodb://mongo:27017` in `.env` (the compose service name).

### Run with plain Docker

Build the image and run it. With plain `docker run` there is **no MongoDB**,
so the bot runs without persistence (users/jobs are kept in memory only):

```bash
docker build -t audiomuxer .
docker run -d --name audiomuxer --env-file .env \
  -v audiomuxer_data:/data/audiomuxer \
  --restart unless-stopped \
  audiomuxer
docker logs -f audiomuxer       # follow the logs
docker stop audiomuxer          # stop
```

To run it together with a MongoDB container without compose:

```bash
docker network create audiomuxer_net
docker run -d --name mongo --network audiomuxer_net \
  -v mongo_data:/data/db mongo:7
docker run -d --name audiomuxer --network audiomuxer_net --env-file .env \
  -e MONGO_URI=mongodb://mongo:27017 \
  -v audiomuxer_data:/data/audiomuxer \
  --restart unless-stopped \
  audiomuxer
```

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
| `/update` | owner | `git pull` the repo to sync the latest code |
| `/restart` | owner | restart the bot process to load new code |
| `/broadcast <text>` | owner | message every user |
| `/ban <id>` / `/unban <id>` | owner | ban management |
| `/addadmin <id>` / `/deladmin <id>` | owner | role management |

## Environment variables

See `.env.example` for the full list. Required: `API_ID`, `API_HASH`,
`BOT_TOKEN`, `OWNER_ID`, `MONGO_URI`.

### Self-update (`/update`)

The bot can pull its own latest code with `/update` and reload with `/restart`.
For that to work inside Docker, the repo must be reachable in the container and
the image must include `git` (the provided Dockerfile already installs it).
Compose mounts the repo at `/repo` and sets `GIT_REPO_DIR=/repo` automatically.
With plain `docker run`, add:

```bash
-v /path/to/AUDIO-MUXER:/repo -e GIT_REPO_DIR=/repo
```

`/update` runs `git pull --ff-only` and, if the branch has diverged, force-syncs
to the upstream. Because the process runs the code baked into the image, send
`/restart` after an update to load the new code (Docker restarts it
automatically via `restart: unless-stopped`). Note: dependency changes still
need a rebuild (`docker compose up -d --build`).

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
