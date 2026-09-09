"""Tests for sync detection and trimming."""

import pytest

from bot.ffmpeg_wrapper import probe_duration
from bot.sync import SyncDetector
from bot.trimmer import Trimmer, parse_timestamp


def test_parse_timestamp():
    assert parse_timestamp("90") == 90.0
    assert parse_timestamp("01:30") == 90.0
    assert parse_timestamp("00:01:30") == 90.0
    with pytest.raises(ValueError):
        parse_timestamp("99:99")
    with pytest.raises(ValueError):
        parse_timestamp("abc")


async def test_sync_no_offset(sample_video, sample_audio):
    det = SyncDetector(analysis_window=5, max_offset=2)
    result = await det.detect(sample_video, sample_audio, check_drift=False)
    assert result.reliable
    assert abs(result.offset_ms) < 150


async def test_trim(sample_video, tmp_path):
    t = Trimmer(work_dir=tmp_path)
    out = await t.trim(sample_video, start=1.0, end=4.0)
    assert await probe_duration(out) == pytest.approx(3.0, abs=1.5)


async def test_detect_and_remove_silence(audio_with_silence, tmp_path):
    t = Trimmer(work_dir=tmp_path)
    segs = await t.detect_silence(audio_with_silence)
    assert len(segs) == 1
    assert segs[0].duration == pytest.approx(2.0, abs=0.6)
    out, removed = await t.remove_silence(audio_with_silence)
    assert len(removed) == 1
    assert await probe_duration(out) < 5.5
