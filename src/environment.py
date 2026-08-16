"""Environment monitor — ambient noise floor + OS default input device.

Two refresh concerns live here, both fed by the single existing mic
stream (never a second PortAudio stream — two input streams on macOS
fail with -9986):

1. **Rolling noise floor** — chunks published by the idle wake word
   stream accumulate here; a low percentile over the recent window
   gives the ambient floor (fan, AC, room tone). The VAD silence
   threshold is derived as floor + margin, clamped, so auto-stop
   adapts without a restart.

2. **OS default device ticks** — a daemon thread polls
   `sd.default.device[0]` every `refresh_interval_s`. When the OS
   default changes (menu bar switch, plug/unplug), the change is
   latched once and the controller restarts the wake word stream on
   the new device.

Recorder streams also publish chunks with `recording=True` — those
update nothing here (speech would corrupt the floor).
"""

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

SYSTEM_DEVICE = "system"  # [audio] device_name value meaning "follow OS default"
AUTO_DEVICE = "auto"        # output-paired input routing (preferred)

# Input device names that identify the built-in MacBook microphone,
# the default fallback when no device is paired with the current output.
MACBOOK_MIC_MARKERS = ("macbook", "mac mini")

# Pairing fallback: strip these suffixes before comparing input and
# output device names ("MacBook Pro Speakers" ↔ "MacBook Pro Microphone").
_PAIR_SUFFIXES = ("speakers", "speaker", "microphone", "mic", "output", "input")

FLOOR_WINDOW_S = 120.0      # rolling window for the percentile floor
FLOOR_PERCENTILE = 20.0     # reject speech bursts contaminating the window
FLOOR_MIN_SAMPLES = 30      # ~3s of 100ms chunks before the floor counts
THRESHOLD_MIN_DB = -60.0    # clamp bounds for floor + margin
THRESHOLD_MAX_DB = -28.0
DEFAULT_MARGIN_DB = 8.0     # above the floor → silence line


class EnvironmentMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._floor_history: deque[tuple[float, float]] = deque()
        self._pending_device_change: Optional[int] = None
        self._last_default_device: Optional[int] = None
        self._refresh_interval_s: float = 120.0
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_running = threading.Event()

    # ── Noise floor (fed by the idle wake word stream) ─────────────────

    def update_from_samples(self, samples, *, recording: bool = False) -> None:
        """Publish one audio chunk's level. Only idle chunks feed the floor."""
        if recording or samples is None or len(samples) == 0:
            return
        rms = float(np.sqrt(np.mean(np.asarray(samples, dtype=np.float64) ** 2)))
        if rms == 0.0:
            return  # digital silence — carries no information
        db = float(20.0 * np.log10(max(rms, 1e-12)))
        now = time.monotonic()
        with self._lock:
            self._floor_history.append((now, db))
            self._prune_floor(now)

    def _prune_floor(self, now: float) -> None:
        """Drop floor samples older than the rolling window. Caller holds
        the lock."""
        cutoff = now - FLOOR_WINDOW_S
        while self._floor_history and self._floor_history[0][0] < cutoff:
            self._floor_history.popleft()

    def floor_db(self) -> Optional[float]:
        """Ambient floor (low percentile of recent idle audio), or None
        while the window is still warming up."""
        with self._lock:
            self._prune_floor(time.monotonic())
            if len(self._floor_history) < FLOOR_MIN_SAMPLES:
                return None
            values = sorted(db for _, db in self._floor_history)
            idx = max(0, int(len(values) * FLOOR_PERCENTILE / 100.0))
            return values[idx]

    def silence_threshold_db(self, margin_db: float = DEFAULT_MARGIN_DB) -> Optional[float]:
        """VAD silence threshold derived from the floor, clamped.

        None while the floor is warming up — callers fall back to the
        configured static threshold.
        """
        floor = self.floor_db()
        if floor is None:
            return None
        return float(min(THRESHOLD_MAX_DB, max(THRESHOLD_MIN_DB, floor + margin_db)))

    # ── Input device resolution ────────────────────────────────────────

    @staticmethod
    def resolve_input_device(configured_name: Optional[str]) -> Optional[int]:
        """Resolve the input device for the next stream open.

        - None / "" / "auto" / "system" → output-paired input routing:
          the mic belonging to whatever the user is currently HEARING
          from (AirPods out → AirPods mic, MacBook speakers → MacBook
          mic), falling back to the MacBook microphone, then the OS
          default input as a last resort.
        - a saved name → that device's current index; None when it's
          gone (callers fall back to the OS default).

        Called at every stream open, so output switches and plug/unplug
        take effect on the next dictation.
        """
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not available — no device resolution.")
            return None

        name = (configured_name or "").strip().lower()
        if name and name not in (AUTO_DEVICE, SYSTEM_DEVICE):
            return EnvironmentMonitor._find_input_by_name(name)
        return EnvironmentMonitor.resolve_paired_input()

    @staticmethod
    def _input_devices() -> list:
        """All input-capable devices as sd.query_devices() dicts."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception as e:
            logger.warning("Could not query audio devices: %s", e)
            return []
        return [d for d in devices if d.get("max_input_channels", 0) > 0]

    @staticmethod
    def _find_input_by_name(name: str) -> Optional[int]:
        """Index of an input device matching name (exact, case-insensitive)."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
        except Exception:
            return None
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and (
                d.get("name") or ""
            ).lower() == name:
                return idx
        return None

    @staticmethod
    def _output_device_name() -> Optional[str]:
        """Name of the current OS default OUTPUT device, or None."""
        try:
            import sounddevice as sd
            default_out = sd.default.device[1] if sd.default.device else -1
            if default_out < 0:
                return None
            return (sd.query_devices()[default_out].get("name") or "").lower()
        except Exception as e:
            logger.warning("Could not resolve default output device: %s", e)
            return None

    @staticmethod
    def _strip_pair_suffixes(name: str) -> str:
        """'MacBook Pro Speakers' → 'macbook pro' (word tokens minus
        direction suffixes), so output/input pairs share a stem."""
        tokens = name.lower().split()
        return " ".join(t for t in tokens if t not in _PAIR_SUFFIXES)

    @staticmethod
    def resolve_paired_input() -> Optional[int]:
        """The input device paired with the current default OUTPUT.

        Order: exact name match (AirPods, USB headsets) → stem match
        ("MacBook Pro Speakers" ↔ "MacBook Pro Microphone") → MacBook
        mic fallback → OS default input (last resort).
        """
        out_name = EnvironmentMonitor._output_device_name()
        inputs = EnvironmentMonitor._input_devices()
        if not inputs:
            return None

        if out_name:
            # 1. Exact: AirPods etc. report the same name for in and out.
            for d in inputs:
                if (d.get("name") or "").lower() == out_name:
                    return d.get("index")
            # 2. Stem: built-in Mac speakers ↔ built-in Mac microphone.
            out_stem = EnvironmentMonitor._strip_pair_suffixes(out_name)
            if out_stem:
                for d in inputs:
                    if EnvironmentMonitor._strip_pair_suffixes(
                        d.get("name") or ""
                    ) == out_stem:
                        return d.get("index")

        # 3. Default fallback: the built-in MacBook microphone.
        for d in inputs:
            lowered = (d.get("name") or "").lower()
            if any(marker in lowered for marker in MACBOOK_MIC_MARKERS):
                return d.get("index")

        # 4. Last resort: whatever the OS default input is.
        try:
            import sounddevice as sd
            default_in = sd.default.device[0] if sd.default.device else -1
            if default_in >= 0:
                return default_in
        except Exception:
            pass
        return None

    # ── Refresh thread (device ticks) ──────────────────────────────────

    def start_refresh(self, interval_s: float) -> None:
        """Start the periodic refresh thread (idempotent)."""
        if self._refresh_thread is not None:
            return
        self._refresh_interval_s = max(10.0, float(interval_s))
        self._last_default_device = self.resolve_paired_input()
        self._refresh_running.set()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="environment-refresh",
        )
        self._refresh_thread.start()
        logger.info(
            "Environment refresh started (every %.0fs).",
            self._refresh_interval_s,
        )

    def stop_refresh(self) -> None:
        """Stop the refresh thread."""
        self._refresh_running.clear()
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=2.0)
            self._refresh_thread = None

    def _refresh_loop(self) -> None:
        while self._refresh_running.wait(timeout=self._refresh_interval_s):
            try:
                current = self.resolve_paired_input()
            except Exception as e:
                logger.warning("Device refresh tick failed: %s", e)
                continue
            if current is not None and current != self._last_default_device:
                logger.info(
                    "Paired input device changed (%r → %r).",
                    self._last_default_device, current,
                )
                self._last_default_device = current
                with self._lock:
                    self._pending_device_change = current

    def consume_device_change(self) -> Optional[int]:
        """Return the new OS default device index once, then None until
        the next change. Thread-safe, polled by the controller."""
        with self._lock:
            change, self._pending_device_change = self._pending_device_change, None
            return change

    def pending_device_change(self) -> Optional[int]:
        """Peek at the latched device change without consuming it."""
        with self._lock:
            return self._pending_device_change


# Module-level singleton — the one true environment monitor.
GLOBAL_ENV = EnvironmentMonitor()
