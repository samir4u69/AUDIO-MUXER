"""Tests for the muxing engine."""

import pytest

from bot.media_info import inspect
from bot.muxer import AudioMuxer


async def test_extract_audio(sample_video, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    out = await m.extract_audio(sample_video, out_format="mp3")
    info = await inspect(out)
    assert len(info.audio_tracks) == 1 and not info.is_video


async def test_add_audio_track(sample_video, sample_audio, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    out = await m.add_audio_track(sample_video, sample_audio,
                                  language="Hindi", set_default=True)
    info = await inspect(out)
    assert len(info.audio_tracks) == 2
    assert info.audio_tracks[1].language == "hin"
    assert info.audio_tracks[1].is_default


async def test_replace_audio(sample_video, sample_audio, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    out = await m.replace_audio(sample_video, sample_audio, replace_track=0)
    info = await inspect(out)
    assert len(info.audio_tracks) == 1


async def test_remove_audio_tracks(sample_video, sample_audio, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    two = await m.add_audio_track(sample_video, sample_audio)
    out = await m.remove_audio_tracks(two, drop=[0])
    info = await inspect(out)
    assert len(info.audio_tracks) == 1


async def test_adjust_volume(sample_audio, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    out = await m.adjust_volume(sample_audio, gain_db=-6.0)
    assert out.exists() and out.stat().st_size > 0


async def test_merge_audio(sample_audio, tmp_path):
    m = AudioMuxer(work_dir=tmp_path)
    out = await m.merge_audio([sample_audio, sample_audio])
    info = await inspect(out)
    assert info.duration == pytest.approx(12, abs=2.5)
