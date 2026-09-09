"""Central configuration for AudioMuxer Pro.

All limits, supported formats, and processing parameters live here so the
bot layer and the processing engines share one source of truth.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = Path(os.environ.get("AUDIOMUXER_WORK_DIR") or (tempfile.gettempdir() + "/audiomuxer"))
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Temp files older than this many seconds are removed by the janitor.
TEMP_TTL_SECONDS = int(os.environ.get("AUDIOMUXER_TEMP_TTL", 24 * 3600))

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_FILE_SIZE_BYTES = int(os.environ.get("AUDIOMUXER_MAX_FILE_SIZE", 2 * 1024**3))  # 2 GB
MAX_DURATION_SECONDS = int(os.environ.get("AUDIOMUXER_MAX_DURATION", 4 * 3600))     # 4 h
MAX_CONCURRENT_JOBS = int(os.environ.get("AUDIOMUXER_MAX_JOBS", 4))

# ---------------------------------------------------------------------------
# Supported formats
# ---------------------------------------------------------------------------
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus",
    ".m4a", ".ac3", ".eac3", ".dts", ".wma",
}

VIDEO_CODECS = {"h264", "hevc", "vp9", "av1", "mpeg2video", "mpeg4"}
AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac", "ac3", "eac3", "dts", "pcm_s16le", "wmav2"}

# ---------------------------------------------------------------------------
# Audio processing defaults
# ---------------------------------------------------------------------------
AUDIO_BITRATES = ["64k", "96k", "128k", "160k", "192k", "256k", "320k"]
SAMPLE_RATES = [44100, 48000, 96000]
DEFAULT_SAMPLE_RATE = 48000

# ---------------------------------------------------------------------------
# Sync detection
# ---------------------------------------------------------------------------
SYNC_CONFIG = {
    # Seconds of audio sampled from the start of each file for correlation.
    "analysis_window": 120.0,
    # Maximum offset (seconds) the detector will consider, either direction.
    "max_offset": 30.0,
    # Mono down-mix rate used for correlation (lower = faster).
    "correlation_rate": 8000,
    # Minimum normalized correlation peak to accept an auto-sync result.
    # Unrelated content scores ~0.3 with the blended confidence metric;
    # genuine matches score >=0.6.
    "confidence_threshold": 0.4,
    # Drift correction: analyse windows at the start AND the end.
    "drift_check": True,
}

# ---------------------------------------------------------------------------
# Silence detection / smart trim
# ---------------------------------------------------------------------------
SILENCE_CONFIG = {
    "threshold_db": -40.0,        # audio below this level counts as silence
    "min_silence_duration": 0.5,  # seconds; shorter silences are kept
    "padding": 0.1,               # seconds of context kept around speech
}

SMART_TRIM_CONFIG = {
    "keep_context": 2.0,          # seconds of context around detected cues
}

# ---------------------------------------------------------------------------
# Quality presets used by convert operations
# ---------------------------------------------------------------------------
QUALITY_PRESETS = {
    "low":    {"audio_bitrate": "96k",  "crf": "30"},
    "medium": {"audio_bitrate": "160k", "crf": "23"},
    "high":   {"audio_bitrate": "256k", "crf": "18"},
    "copy":   {"audio_bitrate": None,   "crf": None},
}

# ---------------------------------------------------------------------------
# Language support for multi-track muxing
# ---------------------------------------------------------------------------
SUPPORTED_LANGUAGES = [
    "English", "Spanish", "French", "German", "Chinese", "Japanese",
    "Korean", "Hindi", "Arabic", "Portuguese", "Russian", "Italian",
    "Dutch", "Polish", "Turkish", "Vietnamese", "Thai", "Indonesian",
]

# ISO 639-2/T codes used for stream metadata.
LANGUAGE_CODES = {
    "english": "eng", "spanish": "spa", "french": "fre", "german": "ger",
    "chinese": "chi", "japanese": "jpn", "korean": "kor", "hindi": "hin",
    "arabic": "ara", "portuguese": "por", "russian": "rus", "italian": "ita",
    "dutch": "dut", "polish": "pol", "turkish": "tur", "vietnamese": "vie",
    "thai": "tha", "indonesian": "ind",
}

# ---------------------------------------------------------------------------
# External tools
# ---------------------------------------------------------------------------
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
