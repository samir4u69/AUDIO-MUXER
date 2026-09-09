"""Generate tiny synthetic media files for tests using ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg fixture failed: {result.stderr.decode()[-500:]}")


@pytest.fixture(scope="session")
def workdir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("audiomuxer-tests")


@pytest.fixture(scope="session")
def sample_video(workdir) -> Path:
    """6 s 320x240 test video with a 440 Hz tone soundtrack."""
    out = workdir / "sample.mp4"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "testsrc=duration=6:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def sample_video_mkv(workdir) -> Path:
    """Same content in an MKV container."""
    out = workdir / "sample.mkv"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "testsrc=duration=6:size=320x240:rate=10",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def sample_audio(workdir) -> Path:
    """6 s 440 Hz tone as MP3."""
    out = workdir / "tone.mp3"
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:a", "libmp3lame", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def sample_audio_wav(workdir) -> Path:
    out = workdir / "tone.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        str(out),
    ])
    return out


@pytest.fixture(scope="session")
def audio_with_silence(workdir) -> Path:
    """2s tone, 2s silence, 2s tone — for silence detection tests."""
    out = workdir / "with_silence.wav"
    _run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=2",
        "-f", "lavfi", "-i", "sine=frequency=550:duration=2",
        "-filter_complex",
        "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", str(out),
    ])
    return out


@pytest.fixture(scope="session")
def offset_audio(workdir) -> Path:
    """440 Hz tone delayed by 500 ms — for sync detection tests."""
    out = workdir / "tone_delayed.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=6",
        "-af", "adelay=500:all=1", str(out),
    ])
    return out
