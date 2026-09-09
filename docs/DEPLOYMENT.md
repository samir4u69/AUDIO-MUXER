# Deployment guide

## Local setup

```bash
git clone <repo> && cd audio-muxer
python3 -m venv .venv && source .venv/bin/activate
pip install .[telegram]
sudo apt-get install ffmpeg   # or: brew install ffmpeg
audio-muxer --help
```

## Server (systemd)

```ini
# /etc/systemd/system/audiomuxer-bot.service
[Unit]
Description=AudioMuxer Pro Telegram bot
After=network.target

[Service]
Type=simple
User=audiomuxer
WorkingDirectory=/opt/audio-muxer
Environment=TELEGRAM_BOT_TOKEN=changeme
Environment=AUDIOMUXER_WORK_DIR=/var/lib/audiomuxer
Environment=AUDIOMUXER_MAX_JOBS=4
ExecStart=/opt/audio-muxer/.venv/bin/audio-muxer-bot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now audiomuxer-bot
```

## Docker

```bash
docker build -t audio-muxer .

# CLI one-shot
docker run --rm -v "$PWD/media:/media" audio-muxer info /media/movie.mkv

# Bot, persistent work dir
docker run -d --name audiomuxer \
  -e TELEGRAM_BOT_TOKEN="…" \
  -e AUDIOMUXER_MAX_JOBS=4 \
  -v audiomuxer-data:/data/audiomuxer \
  audio-muxer audio-muxer-bot
```

## Docker Compose

```yaml
services:
  bot:
    build: .
    command: audio-muxer-bot
    environment:
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      AUDIOMUXER_MAX_JOBS: "4"
    volumes:
      - audiomuxer-data:/data/audiomuxer
    restart: unless-stopped

volumes:
  audiomuxer-data:
```

## Cloud notes

- **Memory:** sync detection uses ~2 MB per analysis window; ffmpeg itself
  is the main consumer. 1 GB RAM handles 4 concurrent HD jobs.
- **Disk:** size the work-dir volume for `max_jobs × 2 GB` worst case;
  the janitor reclaims space after `AUDIOMUXER_TEMP_TTL` seconds.
- **Telegram file limits:** bots can download up to 20 MB (Bot API) and
  upload up to 50 MB. For larger files, run a [local Bot API
  server](https://core.telegram.org/bots/api#using-a-local-bot-api-server)
  (2 GB up/down) and point python-telegram-bot at it.
- **Scaling out:** the queue is in-process; run multiple bot replicas
  behind separate bot tokens, or front the engine with a task broker
  (e.g. move `JobQueue.submit` onto Celery/RQ) if you outgrow one host.
