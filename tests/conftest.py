"""Generate tiny synthetic media fixtures with ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[-500:])


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    return tmp_path_factory.mktemp("bot-tests")


@pytest.fixture(scope="session")
def sample_video(workdir) -> Path:
    out = workdir / "sample.mp4"
    _run(["ffmpeg", "-y", "-f", "lavfi",
          "-i", "testsrc=duration=6:size=320x240:rate=10",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
          "-shortest", str(out)])
    return out


@pytest.fixture(scope="session")
def sample_audio(workdir) -> Path:
    out = workdir / "tone.mp3"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
          "-c:a", "libmp3lame", str(out)])
    return out


@pytest.fixture(scope="session")
def audio_with_silence(workdir) -> Path:
    out = workdir / "with_silence.wav"
    _run(["ffmpeg", "-y",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
          "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2",
          "-f", "lavfi", "-i", "sine=frequency=550:duration=2",
          "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
          "-map", "[out]", str(out)])
    return out
