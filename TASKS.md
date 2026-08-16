# TASKS.md — Whisper VTT

## Phase 1: Foundation ✅

- [x] Create project skeleton
  Done when: `pyproject.toml`, `requirements.txt`, `src/__init__.py`, `src/__main__.py` (stub), `scripts/`, `models/`, and `tests/` directories exist with correct structure.

- [x] Implement data models (`src/models.py`)
  Done when: All enums (RecordingMode, OutputMode, AppStatus) and dataclasses (HotkeyCombo, AppConfig, HotkeyEvent, AudioBuffer, DeviceInfo, ClipboardContents) are defined, importable, and match the spec.

- [x] Implement PathResolver (`src/paths.py`)
  Done when: `PathResolver` correctly resolves base path whether running from source (`sys.frozen` is False) or bundled (`sys.frozen` is True). Tested with both conditions.

- [x] Implement ConfigManager (`src/config_manager.py`)
  Done when: Loads valid TOML, replaces invalid fields with defaults (never crashes), writes TOML, logs warnings for bad values. Tested with valid config, corrupt config, and missing config file.

- [x] Create default `config.toml`
  Done when: `config.toml` exists at project root with all defaults from the spec (hotkey=backtick, toggle mode, auto_paste, 5000ms silence, -15dB threshold, models/tiny.en.pt).

- [x] Unit tests for Phase 1
  Done when: `pytest tests/ -v` passes. Covers config round-trip serialization, invalid config graceful defaults, PathResolver source vs bundled paths.

## Phase 2: Recording Pipeline ✅

- [x] VAD Engine (`src/vad_engine.py`)
  Done when: RMS energy calculation with dB conversion, consecutive silence tracking, configurable threshold, reset between sessions. Tests cover all edge cases.

- [x] Audio Capture (`src/audio_capture.py`)
  Done when: sounddevice InputStream at 16kHz mono, chunk streaming via callback, buffer accumulation, graceful error handling for unavailable/denied mic.

- [x] Transcription Engine (`src/transcription_engine.py`)
  Done when: openai-whisper model load (file or name-based), CPU-only inference, float32 conversion, error handling for missing model.

- [x] Unit tests for Phase 2
  Done when: 39 new tests across VAD, audio capture, and transcription engine. All pass.

## Phase 3: User Interface ✅

- [x] Hotkey Listener (`src/hotkey_listener.py`)
  Done when: Windows low-level keyboard hook via ctypes, dedicated message pump thread, modifier tracking, push-to-talk and toggle mode support, key name to VK mapping.

- [x] Output Handler (`src/output_handler.py`)
  Done when: Clipboard operations via win32clipboard with clip.exe fallback, auto-paste via SendInput with silent fallback, error resilience.

- [x] System Tray (`src/system_tray.py`)
  Done when: pystray icon with Pillow-generated colored circles (green/red/orange/gray), status updates, notifications, exit menu.

- [x] Unit tests for Phase 3
  Done when: 38 new tests across hotkey listener, output handler, and system tray. All pass.

## Phase 4: Integration ✅

- [x] App Controller (`src/app_controller.py`)
  Done when: Full state machine (Idle→Recording→Transcribing→Delivering→Idle), ThreadPoolExecutor for transcription, VAD auto-stop, error handling at every transition, push-to-talk and toggle modes.

- [x] Entry Point (`src/__main__.py`)
  Done when: Wires all components, loads config, preloads whisper model, starts tray and hotkey listener, handles graceful shutdown.

- [x] Integration tests for Phase 4
  Done when: 18 tests covering state transitions, error paths, VAD auto-stop, short recording discard, both recording modes.

## Phase 5: Build & Distribution ✅

- [x] Model download script (`scripts/download_model.py`)
  Done when: Downloads whisper model via openai-whisper, copies cached .pt file to models/, reports size.

- [x] PyInstaller build script (`scripts/build.py`)
  Done when: Runs PyInstaller --onedir, bundles model, copies config, creates distributable zip.

## Phase 6: Windows Notifications ✅

- [x] System tray sound support (`src/system_tray.py`)
  Done when: `show_notification()` accepts optional `play_sound` parameter, plays `winsound.MessageBeep()` by default.

- [x] App controller notifications (`src/app_controller.py`)
  Done when: Toast + beep at recording start, toast + beep at recording stop, toast with text preview at transcription complete (no beep).

- [x] Build script config preservation (`scripts/build.py`)
  Done when: Rebuild skips copying `config.toml` if dist copy already exists, preserving user edits.

- [x] Tests for notifications
  Done when: New tests verify notification calls fire at start/stop/transcribe, preview truncation, build config preservation logic.

## Queued (2026-08-16) — voice loop improvements

- [x] Q-0 Pi presence handshake — `src/pi_state.py` state file (`~/.local/whisper-vtt/pi-state.json`) + `scripts/pi_handshake.py` writer; pi registers its window title + host at session start and per turn. Whisper resolves the pi target from fresh handshake state before falling back to AppleScript heuristics. Done when: pi writes state (fresh ≤30 min); `_resolve_target("pi")` returns the recorded host; stale/missing falls back to legacy detection.
- [x] Q-1 On-mode safety net — in `on`/auto_send mode, when no pi host is running (no Code/pi window, no fresh handshake), withhold Enter + notify instead of sending into frontmost app. Done when: tests cover pi-not-running in on-mode; Enter withheld; notification shown. → `SEND_NO_HOST`
- [x] Q-2 Config hot-reload — watch config.toml (mtime+size, ~1s poll in process_queue); mode changes apply on next dictation, no whisper restart. Done when: editing config.toml changes output mode without restart; tests pass. Propagates output_mode + paste_target live.
- [x] Q-3 Per-dictation mode override — spoken phrase ("paste this without sending" / "don't send" / "just paste"…) suppresses Enter for that one dictation only; phrase stripped from paste + journal. Done when: phrase detection skips Enter for a single dictation; next dictation behaves per config. → `SEND_SUPPRESSED`
