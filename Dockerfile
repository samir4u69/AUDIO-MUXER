FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

ENV WORK_DIR=/data/audiomuxer
VOLUME ["/data/audiomuxer"]

CMD ["python", "-m", "bot"]
