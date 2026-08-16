"""Tests for the environment monitor (src/environment.py).

Covers the rolling noise floor, output-paired input resolution, and
the device-change refresh latch.
"""

from unittest.mock import patch

import numpy as np

from src.environment import EnvironmentMonitor


def _samples_for_db(db: float) -> np.ndarray:
    """Synthetic chunk whose RMS reads ~db dB."""
    rms = 10 ** (db / 20.0)
    rng = np.random.default_rng(7)
    return (rng.standard_normal(1600) * rms).astype(np.float32)


class TestNoiseFloor:
    def test_floor_needs_warm_up(self):
        env = EnvironmentMonitor()
        for _ in range(5):
            env.update_from_samples(_samples_for_db(-45.0))
        assert env.floor_db() is None  # fewer than FLOOR_MIN_SAMPLES

    def test_floor_is_low_percentile_of_ambient(self):
        env = EnvironmentMonitor()
        # 29 chunks of quiet ambient + 1 loud speech spike: the floor
        # must ignore the spike (20th percentile of 30 = 6th lowest).
        for _ in range(29):
            env.update_from_samples(_samples_for_db(-50.0))
        env.update_from_samples(_samples_for_db(-20.0))
        floor = env.floor_db()
        assert floor is not None
        assert floor < -45.0  # spike did not drag the floor up

    def test_recording_chunks_do_not_feed_floor(self):
        env = EnvironmentMonitor()
        for _ in range(40):
            env.update_from_samples(_samples_for_db(-20.0), recording=True)
        assert env.floor_db() is None  # window never warmed up

    def test_old_chunks_age_out(self):
        env = EnvironmentMonitor()
        with patch("src.environment.time.monotonic", return_value=0.0):
            for _ in range(40):
                env.update_from_samples(_samples_for_db(-50.0))
            assert env.floor_db() is not None
        with patch("src.environment.time.monotonic", return_value=500.0):
            assert env.floor_db() is None  # everything expired

    def test_threshold_is_floor_plus_margin_clamped(self):
        env = EnvironmentMonitor()
        for _ in range(40):
            env.update_from_samples(_samples_for_db(-50.0))
        threshold = env.silence_threshold_db(margin_db=8.0)
        assert threshold is not None
        assert -60.0 <= threshold <= -28.0
        assert threshold > -50.0  # above the floor

    def test_threshold_none_while_warming_up(self):
        env = EnvironmentMonitor()
        assert env.silence_threshold_db() is None


class TestPairedInputResolution:
    def _devices(self):
        return [
            {"name": "MacBook Pro Microphone", "index": 0,
             "max_input_channels": 1, "max_output_channels": 0},
            {"name": "MacBook Pro Speakers", "index": 1,
             "max_input_channels": 0, "max_output_channels": 2},
            {"name": "AirPods Pro", "index": 2,
             "max_input_channels": 1, "max_output_channels": 2},
            {"name": "Scarlett 2i2 USB", "index": 3,
             "max_input_channels": 2, "max_output_channels": 2},
        ]

    def test_pinned_name_resolves_index(self):
        with patch("sounddevice.query_devices",
                   side_effect=lambda: self._devices()):
            env = EnvironmentMonitor()
            assert env.resolve_input_device("Scarlett 2i2 USB") == 3

    def test_pinned_name_missing_returns_none(self):
        with patch("sounddevice.query_devices",
                   side_effect=lambda: self._devices()):
            env = EnvironmentMonitor()
            assert env.resolve_input_device("Zoom H6") is None

    def test_auto_pairs_exact_name_with_output(self):
        # AirPods are the default output → AirPods mic.
        with patch("sounddevice.query_devices",
                   side_effect=lambda: self._devices()), \
             patch("sounddevice.default.device", (3, 2)):
            env = EnvironmentMonitor()
            assert env.resolve_input_device(None) == 2

    def test_auto_pairs_stem_when_names_differ(self):
        # MacBook speakers are the default output → MacBook microphone
        # (stem match: "MacBook Pro Speakers" ↔ "MacBook Pro Microphone").
        with patch("sounddevice.query_devices",
                   side_effect=lambda: self._devices()), \
             patch("sounddevice.default.device", (0, 1)):
            env = EnvironmentMonitor()
            assert env.resolve_input_device("auto") == 0

    def test_auto_falls_back_to_macbook_mic(self):
        # Output has no input pair at all (e.g. HDMI display) → MacBook mic.
        devices = self._devices() + [
            {"name": "HDMI Display", "index": 4,
             "max_input_channels": 0, "max_output_channels": 2},
        ]
        with patch("sounddevice.query_devices",
                   side_effect=lambda: devices), \
             patch("sounddevice.default.device", (0, 4)):
            env = EnvironmentMonitor()
            assert env.resolve_input_device(None) == 0

    def test_auto_last_resort_os_default_input(self):
        # No MacBook mic, no pair — whatever the OS default input is.
        devices = [
            {"name": "Scarlett 2i2 USB", "index": 3,
             "max_input_channels": 2, "max_output_channels": 2},
        ]
        with patch("sounddevice.query_devices",
                   side_effect=lambda: devices), \
             patch("sounddevice.default.device", (3, 3)):
            env = EnvironmentMonitor()
            assert env.resolve_input_device(None) == 3

    def test_system_and_blank_mean_auto(self):
        with patch("sounddevice.query_devices",
                   side_effect=lambda: self._devices()), \
             patch("sounddevice.default.device", (3, 2)):
            env = EnvironmentMonitor()
            assert env.resolve_input_device("system") == 2
            assert env.resolve_input_device("") == 2


class TestDeviceChangeLatch:
    def test_consume_returns_once(self):
        env = EnvironmentMonitor()
        with env._lock:
            env._pending_device_change = 7
        assert env.pending_device_change() == 7
        assert env.consume_device_change() == 7
        assert env.pending_device_change() is None
        assert env.consume_device_change() is None

    def test_refresh_tick_latches_change(self):
        env = EnvironmentMonitor()
        env._last_default_device = 0
        with patch.object(env, "resolve_paired_input", return_value=2), \
             patch.object(env._refresh_running, "wait", side_effect=[True, False]):
            env._refresh_loop()
        assert env.pending_device_change() == 2

    def test_refresh_tick_no_change_no_latch(self):
        env = EnvironmentMonitor()
        env._last_default_device = 2
        with patch.object(env, "resolve_paired_input", return_value=2), \
             patch.object(env._refresh_running, "wait", side_effect=[True, False]):
            env._refresh_loop()
        assert env.pending_device_change() is None
