"""Tests for muxing operations."""

import pytest

from audio_muxer.core.muxer import AudioMuxer
from audio_muxer.media_info import inspect


async def test_extract_audio(sample_video, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.extract_audio(sample_video, out_format="mp3")
    assert out.exists() and out.stat().st_size > 0
    info = await inspect(out)
    assert len(info.audio_tracks) == 1
    assert not info.is_video


async def test_extract_bad_format(sample_video, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="Unsupported output audio format"):
        await muxer.extract_audio(sample_video, out_format="xyz")


async def test_add_audio_track(sample_video, sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.add_audio_track(sample_video, sample_audio,
                                      language="Hindi", title="Hindi dub")
    info = await inspect(out)
    assert len(info.audio_tracks) == 2
    new_track = info.audio_tracks[1]
    assert new_track.language == "hin"


async def test_add_audio_track_default(sample_video, sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.add_audio_track(sample_video, sample_audio, set_default=True)
    info = await inspect(out)
    assert info.audio_tracks[1].is_default
    assert not info.audio_tracks[0].is_default


async def test_replace_audio(sample_video, sample_audio_wav, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.replace_audio(sample_video, sample_audio_wav, replace_track=0)
    info = await inspect(out)
    assert len(info.audio_tracks) == 1


async def test_replace_audio_out_of_range(sample_video, sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="not found"):
        await muxer.replace_audio(sample_video, sample_audio, replace_track=5)


async def test_remove_audio_tracks(sample_video, sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    two_tracks = await muxer.add_audio_track(sample_video, sample_audio)
    out = await muxer.remove_audio_tracks(two_tracks, drop=[0])
    info = await inspect(out)
    assert len(info.audio_tracks) == 1


async def test_remove_all_tracks_rejected(sample_video, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="every audio track"):
        await muxer.remove_audio_tracks(sample_video, drop=[0])


async def test_reorder_tracks(sample_video, sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    two = await muxer.add_audio_track(sample_video, sample_audio, language="Hindi")
    out = await muxer.reorder_audio_tracks(two, order=[1, 0], default_track=0)
    info = await inspect(out)
    assert len(info.audio_tracks) == 2
    assert info.audio_tracks[0].language == "hin"
    assert info.audio_tracks[0].is_default


async def test_convert_audio(sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.convert_audio(sample_audio, out_format="ogg")
    assert out.suffix == ".ogg"
    info = await inspect(out)
    assert info.audio_tracks[0].codec in {"vorbis", "opus"}


async def test_convert_bad_sample_rate(sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="Sample rate"):
        await muxer.convert_audio(sample_audio, out_format="mp3", sample_rate=12345)


async def test_adjust_volume(sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.adjust_volume(sample_audio, gain_db=-6.0)
    assert out.exists() and out.stat().st_size > 0


async def test_normalize(sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.normalize_audio(sample_audio, target_lufs=-16.0)
    assert out.exists() and out.stat().st_size > 0


async def test_merge_audio(sample_audio, sample_audio_wav, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    out = await muxer.merge_audio([sample_audio, sample_audio_wav])
    info = await inspect(out)
    assert info.duration == pytest.approx(12, abs=2.5)


async def test_merge_requires_two_files(sample_audio, tmp_path):
    muxer = AudioMuxer(work_dir=tmp_path)
    with pytest.raises(ValueError, match="at least 2"):
        await muxer.merge_audio([sample_audio])
