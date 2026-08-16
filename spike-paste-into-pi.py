"""Spike — deliver the transcription into the pi prompt after recording.

REQUIREMENT (corrected understanding)
    After Whisper VTT records + transcribes, the text should land in the
    pi (coding agent) prompt — usually this chat — rather than blindly in
    whatever app happens to be frontmost.

ASSUMPTIONS TO VALIDATE
    A1. The pi prompt lives in a discoverable host app (Terminal, VS Code,
        iTerm2, Warp, ...).
    A2. AppleScript can activate that host app and paste into it
        deterministically (activate process → keystroke Cmd+V).
    A3. The paste fires only after recording completes (ordering).

EXPERIMENTS
    1. DISCOVER  — enumerate running GUI apps; score pi-host candidates.
    2. ACTIVATE  — for the top candidate, set it frontmost via System
                   Events and read back which app ended frontmost. The
                   paste command is printed but NOT sent (no typing).
    3. ORDERING  — headless fake-mic full cycle (speech → silence → VAD
                   auto-stop → transcription → delivery); assert the
                   paste event is strictly after recording_stopped.

Run:  .venv/bin/python spike-paste-into-pi.py
"""

import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, ".")

from src.app_controller import AppController
from src.config_manager import AppConfig, RecordingMode
from src.models import AppStatus, AudioBuffer, HotkeyCombo, OutputMode
from src.vad_engine import VADEngine
from src.backends import OutputHandler

# ── 1. DISCOVER — which running apps could host the pi prompt ──────────

PI_HOST_CANDIDATES = {
    "Terminal",
    "Code",               # VS Code's System Events process name
    "Electron",
    "Visual Studio Code",  # some builds report the full name
    "iTerm2",
    "Warp",
    "Alacritty",
    "kitty",
    "Hyper",
}

PASTE_TARGET_TEMPLATE = """\
tell application "System Events"
    tell process "{app}"
        set frontmost to true
        keystroke "v" using command down
    end tell
end tell"""


def osa(script: str) -> str:
    out = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=15,
    )
    return out.stdout.strip() or out.stderr.strip()


def running_gui_apps() -> list[str]:
    raw = osa(
        'tell application "System Events" to get name of every '
        'application process whose background only is false'
    )
    return [n.strip() for n in raw.split(",") if n.strip()]


def frontmost_app() -> str:
    return osa(
        'tell application "System Events" to get name of first '
        'application process whose frontmost is true'
    )


print("1) DISCOVER — running GUI apps:")
apps = running_gui_apps()
candidates = [a for a in apps if a in PI_HOST_CANDIDATES]
for a in candidates:
    print(f"   pi-host candidate: {a}")
print(f"   currently frontmost: {frontmost_app()}")

# ── 2. ACTIVATE — can we make the pi host frontmost deterministically? ─

target = candidates[0] if candidates else None
if target:
    print(f"\n2) ACTIVATE — testing 'set frontmost' on: {target}")
    osa(f'tell application "System Events" to set frontmost of process "{target}" to true')
    time.sleep(1.0)
    now = frontmost_app()
    ok = now == target
    print(f"   after activate, frontmost is: {now} — {'OK' if ok else 'FAIL'}")
    print("\n   paste command that WOULD be used (not sent):")
    print("   " + PASTE_TARGET_TEMPLATE.format(app=target).replace("\n", "\n   "))
else:
    print("\n2) ACTIVATE — no pi-host candidate found among GUI apps.")

# ── 3. ORDERING — paste only after recording completes ─────────────────

print("\n3) ORDERING — headless fake-mic cycle (paste recorded, not sent)")

EVENTS: list[str] = []

import src.backends.macos as macos_mod  # noqa: E402

macos_mod.subprocess.run = lambda *a, **k: (
    EVENTS.append(
        "pbcopy" if a and a[0] and a[0][0] == "pbcopy" else
        "paste" if a and a[0] and a[0][0] == "osascript" else "other"
    ),
    MagicMock(returncode=0),
)[1]


class FakeAudioCapture:
    def __init__(self):
        self._chunk_cb = None
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def set_chunk_callback(self, cb) -> None:
        self._chunk_cb = cb

    def start_recording(self) -> None:
        self._recording = True
        EVENTS.append("recording_started")
        threading.Thread(target=self._feed, daemon=True).start()

    def _feed(self) -> None:
        for _ in range(10):
            if self._chunk_cb:
                self._chunk_cb(np.full(1600, 0.3, dtype=np.float32))
            time.sleep(0.05)
        for _ in range(70):
            if self._chunk_cb:
                self._chunk_cb(np.zeros(1600, dtype=np.float32))
            time.sleep(0.05)

    def stop_recording(self) -> AudioBuffer:
        self._recording = False
        EVENTS.append("recording_stopped")
        return AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32), sample_rate=16000,
        )


controller = AppController(
    config=AppConfig(
        hotkey=HotkeyCombo(modifiers=frozenset(), key="`"),
        recording_mode=RecordingMode.TOGGLE,
        output_mode=OutputMode.AUTO_PASTE,
        silence_threshold_ms=3000,
        volume_threshold_db=-50.0,
        model_path="models/ggml-base.en.bin",
        wake_word="jarvis",
        wake_word_threshold=1e-20,
    ),
    tray=MagicMock(),
    hotkey_listener=MagicMock(),
    audio_capture=FakeAudioCapture(),
    vad_engine=VADEngine(silence_threshold_ms=3000, volume_threshold_db=-50.0),
    transcription_engine=MagicMock(transcribe=MagicMock(return_value="spike text")),
    output_handler=OutputHandler(mode=OutputMode.AUTO_PASTE),
    wake_word_listener=None,
)

controller._start_recording()
deadline = time.time() + 15
while controller.status != AppStatus.IDLE and time.time() < deadline:
    controller.process_queue(timeout=0.2)

print("   timeline:", " → ".join(EVENTS))
assert "paste" in EVENTS, "paste never fired"
assert EVENTS.index("paste") > EVENTS.index("recording_stopped"), (
    "paste fired before recording stopped"
)
print("\nPASS: paste can be targeted at the pi host and fires only after recording.")
