"""Shared microphone level meter.

Exactly one PortAudio stream owns the mic at any moment — the wake word
listener while idle, the recorder while dictating. Both publish their
chunk RMS here; the menu bar meter and the silence watchdog read from
here. No extra audio streams, no device contention.

All methods are thread-safe (audio callbacks publish, the UI thread reads).
"""

import threading
import time

import numpy as np

SILENCE_DB = -60.0  # below this counts as "digital silence" (no signal)


class LevelMeter:
    def __init__(self, silent_alert_after: float = 10.0):
        self._lock = threading.Lock()
        self._last_db: float = float("-inf")
        self._last_update: float = 0.0
        self._last_audible: float = 0.0  # monotonic time of last non-silent audio
        self._silent_alert_after = silent_alert_after

    def update_from_samples(self, samples) -> None:
        """Publish the RMS level of one audio chunk (any numeric array)."""
        if samples is None or len(samples) == 0:
            return
        rms = float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))
        db = float("-inf") if rms == 0.0 else float(20.0 * np.log10(max(rms, 1e-12)))
        now = time.monotonic()
        with self._lock:
            self._last_db = db
            self._last_update = now
            if db > SILENCE_DB:
                self._last_audible = now

    def level_db(self) -> float:
        with self._lock:
            return self._last_db

    def silent_for_seconds(self) -> float:
        """How long since the mic last heard audible signal.

        0.0 while the most recent chunk was audible (silence hasn't
        started yet); otherwise seconds since the last audible chunk.
        """
        with self._lock:
            if self._last_db > SILENCE_DB:
                return 0.0
            if self._last_audible == 0.0:
                return 0.0
            return time.monotonic() - self._last_audible

    @property
    def silent_too_long(self) -> bool:
        return self.silent_for_seconds() >= self._silent_alert_after

    @staticmethod
    def level_bar(db: float, blocks: int = 10) -> str:
        """Render a level bar from a dB value (-60 → empty, -10 → full)."""
        if db == float("-inf") or db <= SILENCE_DB:
            return "▁" * 1 + "·" * (blocks - 1)
        frac = (db - SILENCE_DB) / (-10.0 - SILENCE_DB)
        filled = max(1, min(blocks, int(round(frac * blocks))))
        return "▄" * filled + "·" * (blocks - filled)


# Module-level singleton — the one true meter.
GLOBAL_METER = LevelMeter()
