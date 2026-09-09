"""Tests for media inspection and input validation."""

import pytest

from audio_muxer.media_info import (
    FileValidationError, UnsupportedFormatError, inspect, validate_input,
)


async def test_inspect_video(sample_video):
    info = await inspect(sample_video)
    assert info.is_video
    assert len(info.audio_tracks) == 1
    assert info.video_tracks[0].width == 320
    assert info.duration == pytest.approx(6, abs=1.5)


async def test_inspect_audio(sample_audio):
    info = await inspect(sample_audio)
    assert not info.is_video
    assert len(info.audio_tracks) == 1
    assert info.audio_tracks[0].codec == "mp3"


def test_validate_missing_file(tmp_path):
    with pytest.raises(FileValidationError, match="not found"):
        validate_input(tmp_path / "nope.mp4")


def test_validate_empty_file(tmp_path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    with pytest.raises(FileValidationError, match="empty"):
        validate_input(f)


def test_validate_unsupported_video(tmp_path):
    f = tmp_path / "movie.xyz"
    f.write_bytes(b"data")
    with pytest.raises(UnsupportedFormatError):
        validate_input(f, "video")


def test_validate_audio_as_video(tmp_path):
    f = tmp_path / "song.mp3"
    f.write_bytes(b"data")
    with pytest.raises(UnsupportedFormatError):
        validate_input(f, "video")
