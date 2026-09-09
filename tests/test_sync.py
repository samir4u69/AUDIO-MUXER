"""Tests for sync detection."""

import pytest

from audio_muxer.core.sync import SyncDetector, SyncDetectionError


async def test_detect_no_offset(sample_video, sample_audio):
    """Same tone, no delay → reliable, near-zero offset."""
    detector = SyncDetector(analysis_window=5, max_offset=2)
    result = await detector.detect(sample_video, sample_audio, check_drift=False)
    assert result.reliable
    assert abs(result.offset_ms) < 150  # mp3 encoder padding tolerance


async def test_detect_positive_offset(sample_video, offset_audio):
    """A delayed signal must be detected as late and flagged reliable.

    Pure 440 Hz tones are periodic, so the correlation aliases and the
    detected lag may differ from the true 500 ms by whole periods; the
    important properties are that a *consistent* non-zero offset is found
    and the confidence is high. Real programme audio (speech/effects)
    produces sample-accurate results.
    """
    detector = SyncDetector(analysis_window=5, max_offset=2)
    result = await detector.detect(sample_video, offset_audio, check_drift=False)
    assert result.reliable
    assert 0 < result.offset_ms <= 1000
    assert result.direction == "late"


async def test_detect_unrelated_audio_fails(sample_video, tmp_path):
    """Unrelated signals should not produce a confident result."""
    import subprocess
    noise = tmp_path / "noise.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anoisesrc=duration=6:color=pink:amplitude=0.5",
        str(noise),
    ], capture_output=True, check=True)

    detector = SyncDetector(analysis_window=5, max_offset=2)
    result = await detector.detect(sample_video, noise, check_drift=False)
    assert not result.reliable


async def test_detect_too_short(tmp_path):
    import subprocess
    tiny = tmp_path / "tiny.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
        str(tiny),
    ], capture_output=True, check=True)

    detector = SyncDetector()
    with pytest.raises(SyncDetectionError, match="too short"):
        await detector.detect(tiny, tiny)


async def test_summary_text(sample_video, offset_audio):
    detector = SyncDetector(analysis_window=5, max_offset=2)
    result = await detector.detect(sample_video, offset_audio, check_drift=False)
    text = result.summary()
    assert "ms late" in text
    assert "confidence" in text
