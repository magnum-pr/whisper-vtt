"""Data models and enums for Whisper VTT."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np


class RecordingMode(Enum):
    PUSH_TO_TALK = "push_to_talk"
    TOGGLE = "toggle"
    WAKE_WORD = "wake_word"


class OutputMode(Enum):
    AUTO_PASTE = "auto_paste"
    CLIPBOARD = "clipboard"


class AppStatus(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


@dataclass(frozen=True)
class HotkeyCombo:
    modifiers: frozenset[str]  # e.g., frozenset({"ctrl", "shift"})
    key: str  # e.g., "space", "`", "f1"


@dataclass(frozen=True)
class AppConfig:
    hotkey: HotkeyCombo
    recording_mode: RecordingMode
    output_mode: OutputMode
    silence_threshold_ms: int
    volume_threshold_db: float
    model_path: Path
    wake_word: str = "alexa"
    wake_word_threshold: float = 1e-30
    audio_device_name: Optional[str] = None  # saved device name; None = use system default


@dataclass(frozen=True)
class HotkeyEvent:
    combo: HotkeyCombo
    pressed: bool  # True = activated, False = released
    timestamp_ms: int


@dataclass
class AudioBuffer:
    samples: np.ndarray  # float32, 16kHz mono
    sample_rate: int = 16000
    channels: int = 1

    @property
    def duration_seconds(self) -> float:
        return len(self.samples) / self.sample_rate


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    sample_rate: int
    channels: int
    is_available: bool


@dataclass
class ClipboardContents:
    text: Optional[str]
    has_non_text: bool
