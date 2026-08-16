"""Tests for speech-onset detection (src/speech_onset.py)."""

from unittest.mock import patch

from src.speech_onset import SpeechOnsetDetector


class _Clock:
    """Mutable monotonic clock for deterministic cooldown control."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _det(clock, silence_db=-40.0, **kwargs):
    """A detector armed at clock.t + past the arm cooldown."""
    with patch("src.speech_onset.time.monotonic", clock):
        det = SpeechOnsetDetector(silence_threshold_db=silence_db, **kwargs)
        det.arm(silence_db)
        clock.t += kwargs.get("cooldown_s", 2.0) + 0.5  # cooldown expired
    return det


def test_below_threshold_no_onset():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        for _ in range(10):
            assert det.process_chunk(-50.0) is False


def test_consecutive_loud_chunks_fire_onset():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        assert det.process_chunk(-30.0) is False  # 1
        assert det.process_chunk(-30.0) is False  # 2
        assert det.process_chunk(-30.0) is True   # 3 → fire


def test_noise_spike_resets_counter():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-50.0) is False  # drop below → reset
        assert det.process_chunk(-30.0) is False  # counter restarted
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is True


def test_cooldown_after_fire():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        det.process_chunk(-30.0)
        det.process_chunk(-30.0)
        assert det.process_chunk(-30.0) is True
        # Immediately after firing, chunks are ignored (cooldown).
        assert det.process_chunk(-30.0) is False
        clock.t += 5.0  # cooldown over — counter must re-accumulate
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is True


def test_arm_cooldown_blocks_immediate_chunks():
    clock = _Clock()
    det = SpeechOnsetDetector(silence_threshold_db=-40.0)
    with patch("src.speech_onset.time.monotonic", clock):
        det.arm(-40.0)
        # Right after arming, everything is in the cooldown window.
        assert det.process_chunk(-30.0) is False
        clock.t += 3.0
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is True


def test_threshold_is_silence_line_plus_margin():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        # threshold = -40 + 6 = -34: -35 is below, -33 is above.
        assert det.process_chunk(-35.0) is False
        assert det.process_chunk(-33.0) is False
        assert det.process_chunk(-33.0) is False
        assert det.process_chunk(-33.0) is True


def test_reset_clears_hits():
    clock = _Clock()
    det = _det(clock)
    with patch("src.speech_onset.time.monotonic", clock):
        det.process_chunk(-30.0)
        det.process_chunk(-30.0)
        det.reset()
        assert det.process_chunk(-30.0) is False  # started over
        assert det.process_chunk(-30.0) is False
        assert det.process_chunk(-30.0) is True
