FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY audio_muxer ./audio_muxer
RUN pip install --no-cache-dir .[telegram]

ENV AUDIOMUXER_WORK_DIR=/data/audiomuxer
VOLUME ["/data/audiomuxer"]

# Default: CLI. For the Telegram bot:
#   docker run -e TELEGRAM_BOT_TOKEN=... <image> audio-muxer-bot
ENTRYPOINT ["audio-muxer"]
CMD ["--help"]
