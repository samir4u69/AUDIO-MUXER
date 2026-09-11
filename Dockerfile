FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# tgcrypto ships no prebuilt wheel; build it, then drop the toolchain to
# keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc python3-dev && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY bot ./bot

ENV WORK_DIR=/data/audiomuxer
VOLUME ["/data/audiomuxer"]

CMD ["python", "-m", "bot"]
