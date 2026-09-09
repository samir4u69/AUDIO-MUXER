#!/usr/bin/env bash
# Generate tiny sample media files for manual testing.
set -euo pipefail
OUT="${1:-./samples}"
mkdir -p "$OUT"

echo "→ 10s 720p test video with 440Hz tone"
ffmpeg -y -f lavfi -i testsrc=duration=10:size=1280x720:rate=30 \
       -f lavfi -i "sine=frequency=440:duration=10" \
       -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT/sample.mp4"

echo "→ MKV variant"
ffmpeg -y -f lavfi -i testsrc=duration=10:size=1280x720:rate=30 \
       -f lavfi -i "sine=frequency=440:duration=10" \
       -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$OUT/sample.mkv"

echo "→ 330Hz MP3 (second 'language' track)"
ffmpeg -y -f lavfi -i "sine=frequency=330:duration=10" -c:a libmp3lame "$OUT/track2.mp3"

echo "→ 440Hz WAV delayed by 500ms (sync test)"
ffmpeg -y -f lavfi -i "sine=frequency=440:duration=10" \
       -af "adelay=500:all=1" "$OUT/delayed_500ms.wav"

echo "→ Speech-with-silence WAV (trim test)"
ffmpeg -y \
  -f lavfi -i "sine=frequency=440:duration=3" \
  -f lavfi -i "anullsrc=r=44100:cl=mono:d=2" \
  -f lavfi -i "sine=frequency=550:duration=3" \
  -filter_complex "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]" \
  -map "[out]" "$OUT/with_silence.wav"

echo "Done. Files in $OUT"
