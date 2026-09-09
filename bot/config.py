"""Configuration, loaded from environment / .env file."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _list(name: str) -> list[int]:
    raw = os.environ.get(name, "")
    out = []
    for part in raw.replace(",", " ").split():
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out


# --- Telegram (required) -----------------------------------------------------
API_ID = _int("API_ID", 0)
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# --- Access control ----------------------------------------------------------
OWNER_ID = _int("OWNER_ID", 0)
ADMIN_IDS = _list("ADMIN_IDS")

# --- MongoDB -----------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "audiomuxer")

# --- Limits ------------------------------------------------------------------
MAX_FILE_SIZE_MB = _int("MAX_FILE_SIZE_MB", 2000)
MAX_DURATION_SECONDS = _int("MAX_DURATION_SECONDS", 4 * 3600)
MAX_CONCURRENT_JOBS = _int("MAX_CONCURRENT_JOBS", 4)
TEMP_TTL_SECONDS = _int("TEMP_TTL_SECONDS", 24 * 3600)

# --- Paths -------------------------------------------------------------------
WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/audiomuxer"))
WORK_DIR.mkdir(parents=True, exist_ok=True)
# Where processed files are written (downloaded inputs stay in WORK_DIR).
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", WORK_DIR / "outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Logging -----------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = Path(os.environ.get("LOG_FILE", WORK_DIR / "audiomuxer.log"))

_PROGRESS_ENV = os.environ.get("PROGRESS_UPDATE_INTERVAL", "1.5")
try:
    PROGRESS_UPDATE_INTERVAL = max(0.5, float(_PROGRESS_ENV))
except ValueError:
    PROGRESS_UPDATE_INTERVAL = 1.5

# ---------------------------------------------------------------------------
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".m2ts",
}
AUDIO_EXTENSIONS = {
    ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus",
    ".m4a", ".ac3", ".eac3", ".dts", ".wma",
}

SUPPORTED_LANGUAGES = [
    "English", "Spanish", "French", "German", "Chinese", "Japanese",
    "Korean", "Hindi", "Arabic", "Portuguese", "Russian", "Italian",
    "Dutch", "Polish", "Turkish", "Vietnamese", "Thai", "Indonesian",
]
LANGUAGE_CODES = {
    "english": "eng", "spanish": "spa", "french": "fre", "german": "ger",
    "chinese": "chi", "japanese": "jpn", "korean": "kor", "hindi": "hin",
    "arabic": "ara", "portuguese": "por", "russian": "rus", "italian": "ita",
    "dutch": "dut", "polish": "pol", "turkish": "tur", "vietnamese": "vie",
    "thai": "tha", "indonesian": "ind",
}

SYNC_CONFIG = {
    "analysis_window": 120.0,
    "max_offset": 30.0,
    "correlation_rate": 8000,
    "confidence_threshold": 0.4,
    "drift_check": True,
}

SILENCE_CONFIG = {
    "threshold_db": -40.0,
    "min_silence_duration": 0.5,
    "padding": 0.1,
}

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")


def validate() -> list[str]:
    """Return a list of missing/invalid required settings."""
    problems = []
    if not API_ID:
        problems.append("API_ID is not set")
    if not API_HASH:
        problems.append("API_HASH is not set")
    if not BOT_TOKEN:
        problems.append("BOT_TOKEN is not set")
    if not OWNER_ID:
        problems.append("OWNER_ID is not set")
    return problems
