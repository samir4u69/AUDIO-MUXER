"""Audio sync detection via FFT cross-correlation."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

from bot import config
from bot.ffmpeg_wrapper import run_ffmpeg, probe_duration

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    offset_ms: float
    confidence: float
    drift_ms_per_hour: float = 0.0
    reliable: bool = False

    @property
    def direction(self) -> str:
        if abs(self.offset_ms) < 1:
            return "aligned"
        return "late" if self.offset_ms > 0 else "early"

    def summary(self) -> str:
        if self.direction == "aligned":
            text = "Audio is already aligned (offset < 1ms)."
        else:
            text = f"Audio is {abs(self.offset_ms):.0f}ms {self.direction}."
        if self.drift_ms_per_hour and abs(self.drift_ms_per_hour) > 1:
            text += f" Drift: {self.drift_ms_per_hour:+.1f}ms/hour."
        return text + f" (confidence {self.confidence:.0%})"


class SyncDetectionError(RuntimeError):
    pass


class SyncDetector:
    def __init__(self, analysis_window=None, max_offset=None, rate=None, confidence_threshold=None):
        cfg = config.SYNC_CONFIG
        self.window = analysis_window if analysis_window is not None else cfg["analysis_window"]
        self.max_offset = max_offset if max_offset is not None else cfg["max_offset"]
        self.rate = rate if rate is not None else cfg["correlation_rate"]
        self.threshold = confidence_threshold if confidence_threshold is not None else cfg["confidence_threshold"]

    async def detect(self, reference, target, audio_track_ref=0, audio_track_target=0,
                     check_drift=None) -> SyncResult:
        check_drift = config.SYNC_CONFIG["drift_check"] if check_drift is None else check_drift
        ref_dur, tgt_dur = await asyncio.gather(probe_duration(reference), probe_duration(target))
        window = min(self.window, ref_dur * 0.9, tgt_dur * 0.9)
        if window < 2:
            raise SyncDetectionError("Files too short for sync analysis")

        ref_start, tgt_start = await asyncio.gather(
            self._decode(reference, 0, window, audio_track_ref),
            self._decode(target, 0, window, audio_track_target),
        )
        offset, conf = self._correlate(ref_start, tgt_start)
        result = SyncResult(offset_ms=offset, confidence=conf, reliable=conf >= self.threshold)

        if check_drift and ref_dur > 2 * window and tgt_dur > 2 * window:
            ref_end, tgt_end = await asyncio.gather(
                self._decode(reference, ref_dur - window, window, audio_track_ref),
                self._decode(target, tgt_dur - window, window, audio_track_target),
            )
            end_off, end_conf = self._correlate(ref_end, tgt_end)
            if end_conf >= self.threshold and ref_dur > 0:
                result.drift_ms_per_hour = (end_off - offset) / (ref_dur / 3600.0)
        return result

    async def _decode(self, path, start, duration, audio_track) -> np.ndarray:
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
            raw = Path(tmp.name)
        try:
            await run_ffmpeg([
                "-ss", f"{start:.3f}", "-i", str(path), "-map", f"0:a:{audio_track}",
                "-t", f"{duration:.3f}", "-ac", "1", "-ar", str(self.rate),
                "-f", "s16le", "-acodec", "pcm_s16le", str(raw),
            ])
            samples = np.fromfile(raw, dtype=np.int16)
        finally:
            raw.unlink(missing_ok=True)
        if samples.size == 0:
            raise SyncDetectionError(f"Could not decode audio from {path}")
        return samples.astype(np.float32) / 32768.0

    def _correlate(self, ref, target) -> tuple[float, float]:
        ref = ref - ref.mean()
        target = target - target.mean()
        if ref.std() < 1e-6 or target.std() < 1e-6:
            raise SyncDetectionError("One of the audio windows is silent")
        corr = fftconvolve(ref, target[::-1], mode="full")
        lags = np.arange(-(target.size - 1), ref.size)
        mask = np.abs(lags) <= int(self.max_offset * self.rate)
        cw, lw = corr[mask], lags[mask]
        if cw.size == 0:
            raise SyncDetectionError("Correlation window empty")
        pi, ni = int(np.argmax(cw)), int(np.argmin(cw))
        if cw[pi] >= -cw[ni]:
            peak_lag, peak_val = int(lw[pi]), float(cw[pi])
        else:
            peak_lag, peak_val = int(lw[ni]), float(-cw[ni])
        norm = float(np.linalg.norm(ref) * np.linalg.norm(target))
        norm_peak = peak_val / max(norm, 1e-9)
        sharpness = float(np.mean(np.abs(cw) > 0.5 * peak_val))
        confidence = float(np.clip(0.7 * norm_peak + 0.3 * min(1.0, sharpness / 0.05), 0, 1))
        return -peak_lag / self.rate * 1000.0, confidence
