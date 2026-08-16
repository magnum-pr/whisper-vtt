"""Tests for data models."""

import numpy as np
import pytest

from src.models import (
    AppConfig,
    AppStatus,
    AudioBuffer,
    ClipboardContents,
    HotkeyCombo,
    HotkeyEvent,
    OutputMode,
    RecordingMode,
)


class TestRecordingMode:
    def test_values(self):
        assert RecordingMode.PUSH_TO_TALK.value == "push_to_talk"
        assert RecordingMode.TOGGLE.value == "toggle"

    def test_from_value(self):
        assert RecordingMode("toggle") == RecordingMode.TOGGLE
        assert RecordingMode("push_to_talk") == RecordingMode.PUSH_TO_TALK


class TestOutputMode:
    def test_values(self):
        assert OutputMode.AUTO_PASTE.value == "auto_paste"
        assert OutputMode.CLIPBOARD.value == "clipboard"


class TestAppStatus:
    def test_values(self):
        assert AppStatus.IDLE.value == "idle"
        assert AppStatus.RECORDING.value == "recording"
        assert AppStatus.TRANSCRIBING.value == "transcribing"
        assert AppStatus.ERROR.value == "error"


class TestHotkeyCombo:
    def test_frozen_immutable(self):
        combo = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="space")
        with pytest.raises(Exception):
            combo.key = "x"  # type: ignore[misc]

    def test_equality(self):
        a = HotkeyCombo(modifiers=frozenset({"ctrl", "shift"}), key="f1")
        b = HotkeyCombo(modifiers=frozenset({"shift", "ctrl"}), key="f1")
        assert a == b

    def test_inequality(self):
        a = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="a")
        b = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="b")
        assert a != b


class TestHotkeyEvent:
    def test_creation(self):
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        event = HotkeyEvent(combo=combo, pressed=True, timestamp_ms=12345)
        assert event.combo == combo
        assert event.pressed is True
        assert event.timestamp_ms == 12345


class TestAudioBuffer:
    def test_duration_seconds(self):
        samples = np.zeros(16000, dtype=np.float32)  # exactly 1 second at 16kHz
        buf = AudioBuffer(samples=samples)
        assert buf.duration_seconds == 1.0

    def test_duration_empty(self):
        samples = np.array([], dtype=np.float32)
        buf = AudioBuffer(samples=samples)
        assert buf.duration_seconds == 0.0

    def test_defaults(self):
        samples = np.array([0.1, 0.2], dtype=np.float32)
        buf = AudioBuffer(samples=samples)
        assert buf.sample_rate == 16000
        assert buf.channels == 1



class TestClipboardContents:
    def test_text_only(self):
        c = ClipboardContents(text="hello", has_non_text=False)
        assert c.text == "hello"
        assert not c.has_non_text

    def test_none_text(self):
        c = ClipboardContents(text=None, has_non_text=True)
        assert c.text is None
        assert c.has_non_text


class TestAppConfig:
    def test_frozen_immutable(self):
        config = AppConfig(
            hotkey=HotkeyCombo(modifiers=frozenset(), key="`"),
            recording_mode=RecordingMode.TOGGLE,
            output_mode=OutputMode.AUTO_PASTE,
            silence_threshold_ms=5000,
            volume_threshold_db=-15.0,
            model_path="models/ggml-base.en.bin",
        )
        with pytest.raises(Exception):
            config.silence_threshold_ms = 100  # type: ignore[misc]
