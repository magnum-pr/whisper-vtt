"""Speech-onset detection — starts a recording when the user speaks.

Used in session mode: while armed, the wake word stream keeps running
and its chunks feed this detector. N consecutive chunks above the
calibrated threshold (silence line + onset margin) fire an onset —
the controller then starts a recording, exactly like a wake word hit.

A short post-fire cooldown prevents echo/trailing noise from
immediately re-triggering.
"""

import time

ONSET_MARGIN_DB = 6.0   # above the calibrated silence line
ONSET_CHUNKS = 3        # consecutive 100ms chunks (300ms) of voice
ONSET_COOLDOWN_S = 2.0


class SpeechOnsetDetector:
    def __init__(
        self,
        silence_threshold_db: float,
        margin_db: float = ONSET_MARGIN_DB,
        consecutive_chunks: int = ONSET_CHUNKS,
        cooldown_s: float = ONSET_COOLDOWN_S,
    ):
        self.threshold_db = silence_threshold_db + margin_db
        self.consecutive_chunks = consecutive_chunks
        self.cooldown_s = cooldown_s
        self._hits = 0
        self._cooldown_until = 0.0

    def arm(self, silence_threshold_db: float) -> None:
        """(Re)configure the threshold and start the cooldown window.

        The cooldown covers the trailing echo right after a previous
        recording — the listener resumes with stale audio still in the
        pipe.
        """
        self.threshold_db = silence_threshold_db + ONSET_MARGIN_DB
        self._hits = 0
        self._cooldown_until = time.monotonic() + self.cooldown_s

    def reset(self) -> None:
        """Clear the hit counter (e.g. when recording actually starts)."""
        self._hits = 0

    def process_chunk(self, db: float) -> bool:
        """Feed one chunk's level. True when a speech onset fires."""
        if time.monotonic() < self._cooldown_until:
            return False
        if db > self.threshold_db:
            self._hits += 1
            if self._hits >= self.consecutive_chunks:
                self._hits = 0
                self._cooldown_until = time.monotonic() + self.cooldown_s
                return True
        else:
            self._hits = 0
        return False
