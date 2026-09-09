"""Audio sync detection via cross-correlation.

Strategy
--------
1. Decode a mono, low-rate PCM window from the start (and, for drift
   detection, the end) of the reference video and the target audio/video.
2. Cross-correlate the two signals with FFT (scipy) and find the lag of
   the correlation peak.
3. Convert the lag to milliseconds. Positive offset means the target
   audio STARTS LATE (must be advanced); negative means it starts EARLY.
4. Confidence is the normalized correlation peak height. Below the
   configured threshold the caller should fall back to manual sync.

For long videos, comparing the start window offset with the end window
offset yields the drift rate (ms per hour), which can be corrected by
resampling with ``atempo``.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

from audio_muxer import config
from audio_muxer.ffmpeg_wrapper import run_ffmpeg, probe_duration

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    offset_ms: float                # how much the target is shifted
    confidence: float               # 0..1 correlation peak height
    method: str = "cross_correlation"
    drift_ms_per_hour: float = 0.0  # non-zero if the two ends disagree
    start_offset_ms: float = 0.0
    end_offset_ms: float | None = None
    reliable: bool = field(default=False)

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
            text += f" Drift detected: {self.drift_ms_per_hour:+.1f}ms/hour."
        text += f" (confidence {self.confidence:.0%})"
        return text


class SyncDetectionError(RuntimeError):
    pass


class SyncDetector:
    def __init__(
        self,
        analysis_window: float | None = None,
        max_offset: float | None = None,
        rate: int | None = None,
        confidence_threshold: float | None = None,
    ):
        cfg = config.SYNC_CONFIG
        self.window = analysis_window if analysis_window is not None else cfg["analysis_window"]
        self.max_offset = max_offset if max_offset is not None else cfg["max_offset"]
        self.rate = rate if rate is not None else cfg["correlation_rate"]
        self.threshold = (
            confidence_threshold if confidence_threshold is not None
            else cfg["confidence_threshold"]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def detect(
        self,
        reference: str | Path,
        target: str | Path,
        audio_track_ref: int = 0,
        audio_track_target: int = 0,
        check_drift: bool | None = None,
    ) -> SyncResult:
        """Detect the sync offset of ``target`` relative to ``reference``.

        Both files can be video or audio; the chosen audio track is used.
        """
        check_drift = config.SYNC_CONFIG["drift_check"] if check_drift is None else check_drift

        ref_dur, tgt_dur = await asyncio.gather(
            probe_duration(reference), probe_duration(target)
        )
        window = min(self.window, ref_dur * 0.9, tgt_dur * 0.9)
        if window < 2:
            raise SyncDetectionError("Files too short for sync analysis")

        ref_start, tgt_start = await asyncio.gather(
            self._decode_window(reference, 0, window, audio_track_ref),
            self._decode_window(target, 0, window, audio_track_target),
        )
        start_offset, start_conf = self._correlate(ref_start, tgt_start)
        log.info("start window: offset=%.1fms conf=%.2f", start_offset, start_conf)

        result = SyncResult(
            offset_ms=start_offset,
            confidence=start_conf,
            start_offset_ms=start_offset,
            reliable=start_conf >= self.threshold,
        )

        if check_drift and ref_dur > 2 * window and tgt_dur > 2 * window:
            ref_end, tgt_end = await asyncio.gather(
                self._decode_window(reference, ref_dur - window, window, audio_track_ref),
                self._decode_window(target, tgt_dur - window, window, audio_track_target),
            )
            end_offset, end_conf = self._correlate(ref_end, tgt_end)
            log.info("end window: offset=%.1fms conf=%.2f", end_offset, end_conf)
            if end_conf >= self.threshold:
                result.end_offset_ms = end_offset
                hours = ref_dur / 3600.0
                if hours > 0:
                    result.drift_ms_per_hour = (end_offset - start_offset) / hours

        return result

    # ------------------------------------------------------------------
    # PCM decoding
    # ------------------------------------------------------------------
    async def _decode_window(
        self, path: str | Path, start: float, duration: float, audio_track: int
    ) -> np.ndarray:
        """Decode a mono s16 PCM window through ffmpeg into a numpy array."""
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
            raw_path = Path(tmp.name)
        try:
            await run_ffmpeg([
                "-ss", f"{start:.3f}",
                "-i", str(path),
                "-map", f"0:a:{audio_track}",
                "-t", f"{duration:.3f}",
                "-ac", "1", "-ar", str(self.rate),
                "-f", "s16le", "-acodec", "pcm_s16le",
                str(raw_path),
            ])
            samples = np.fromfile(raw_path, dtype=np.int16)
        finally:
            raw_path.unlink(missing_ok=True)

        if samples.size == 0:
            raise SyncDetectionError(f"Could not decode audio from {path}")
        return samples.astype(np.float32) / 32768.0

    # ------------------------------------------------------------------
    # Correlation
    # ------------------------------------------------------------------
    def _correlate(self, ref: np.ndarray, target: np.ndarray) -> tuple[float, float]:
        """Return (offset_ms, confidence) via normalized FFT cross-correlation.

        The peak is picked by largest *signed* magnitude (positive and
        negative lobes compared), which avoids sign-flip aliasing on
        periodic material. Confidence combines:

        * the peak height normalized by the signals' energy (0..1), and
        * peak sharpness — the fraction of lags whose correlation exceeds
          half the peak. Broadband content (speech, effects) gives a single
          sharp peak; unrelated noise gives a flat curve.
        """
        ref = ref - ref.mean()
        target = target - target.mean()
        if ref.std() < 1e-6 or target.std() < 1e-6:
            raise SyncDetectionError("One of the audio windows is silent")

        corr = fftconvolve(ref, target[::-1], mode="full")
        lags = np.arange(-(target.size - 1), ref.size)
        max_lag = int(self.max_offset * self.rate)
        mask = np.abs(lags) <= max_lag
        corr_w = corr[mask]
        lag_w = lags[mask]
        if corr_w.size == 0:
            raise SyncDetectionError("Correlation window empty")

        pos_i = int(np.argmax(corr_w))
        neg_i = int(np.argmin(corr_w))
        if corr_w[pos_i] >= -corr_w[neg_i]:
            peak_lag, peak_val = int(lag_w[pos_i]), float(corr_w[pos_i])
        else:
            peak_lag, peak_val = int(lag_w[neg_i]), float(-corr_w[neg_i])

        norm = float(np.linalg.norm(ref) * np.linalg.norm(target))
        norm_peak = peak_val / max(norm, 1e-9)
        sharpness = float(np.mean(np.abs(corr_w) > 0.5 * peak_val))
        confidence = float(np.clip(
            0.7 * norm_peak + 0.3 * min(1.0, sharpness / 0.05), 0.0, 1.0
        ))

        offset_ms = -peak_lag / self.rate * 1000.0  # positive = target late
        return offset_ms, confidence

    # ------------------------------------------------------------------
    # Correction
    # ------------------------------------------------------------------
    async def correction_args(self, result: SyncResult) -> list[str]:
        """FFmpeg args that apply the detected correction to the target audio.

        Caller applies these to the *target* stream when remuxing.
        """
        if not result.reliable:
            raise SyncDetectionError(
                f"Sync confidence too low ({result.confidence:.0%}); use manual sync"
            )
        ms = result.offset_ms
        if abs(ms) < 1:
            return []
        if ms > 0:
            # Target audio starts late: it needs to be delayed? No — audio
            # that is *late* plays after the video event, so we cut its head
            # to advance it... Actually with our sign convention (positive =
            # target late relative to reference), the fix is to trim the
            # first ``ms`` milliseconds of the target.
            return ["-ss", f"{ms / 1000.0:.3f}"]
        # Target audio starts early: pad with silence.
        return ["-af", f"adelay={abs(ms):.0f}:all=1"]
