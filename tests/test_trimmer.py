"""Tests for trimming and silence removal."""

import pytest

from audio_muxer.core.trimmer import Trimmer, parse_timestamp
from audio_muxer.ffmpeg_wrapper import probe_duration


def test_parse_timestamp():
    assert parse_timestamp("90") == 90.0
    assert parse_timestamp("01:30") == 90.0
    assert parse_timestamp("00:01:30") == 90.0
    assert parse_timestamp("00:00:01.5") == 1.5


def test_parse_timestamp_invalid():
    with pytest.raises(ValueError):
        parse_timestamp("1:2:3:4")
    with pytest.raises(ValueError):
        parse_timestamp("99:99")
    with pytest.raises(ValueError):
        parse_timestamp("abc")


async def test_trim(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    out = await trimmer.trim(sample_video, start=1.0, end=4.0)
    dur = await probe_duration(out)
    assert dur == pytest.approx(3.0, abs=1.5)


async def test_trim_timestamps(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    out = await trimmer.trim(sample_video, start="00:00:01", duration="00:00:02")
    dur = await probe_duration(out)
    assert dur == pytest.approx(2.0, abs=1.5)


async def test_trim_beyond_duration(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="beyond"):
        await trimmer.trim(sample_video, start=100.0)


async def test_trim_negative_range(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="after start"):
        await trimmer.trim(sample_video, start=4.0, end=1.0)


async def test_detect_silence(audio_with_silence, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    segs = await trimmer.detect_silence(audio_with_silence)
    assert len(segs) == 1
    assert segs[0].start == pytest.approx(2.0, abs=0.5)
    assert segs[0].duration == pytest.approx(2.0, abs=0.6)


async def test_remove_silence(audio_with_silence, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    out, removed = await trimmer.remove_silence(audio_with_silence)
    assert len(removed) == 1
    dur = await probe_duration(out)
    # Original 6 s minus ~2 s silence (padding keeps ~0.2 s of it).
    assert dur < 5.5
    assert dur > 3.5


async def test_remove_silence_none_found(sample_audio, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="No silence"):
        await trimmer.remove_silence(sample_audio)


async def test_cut_segments(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    out = await trimmer.cut_segments(sample_video, [(2.0, 4.0)])
    dur = await probe_duration(out)
    assert dur == pytest.approx(4.0, abs=1.5)


async def test_split_at(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    parts = await trimmer.split_at(sample_video, ["00:00:03"])
    assert len(parts) == 2
    for p in parts:
        assert p.exists() and p.stat().st_size > 0


async def test_split_no_valid_points(sample_video, tmp_path):
    trimmer = Trimmer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="split points"):
        await trimmer.split_at(sample_video, [999.0])
