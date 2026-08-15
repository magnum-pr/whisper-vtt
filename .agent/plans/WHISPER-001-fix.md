# Fix Plan — WHISPER-001 (macOS hotkey crash)

## Problem
Observed: pressing the backtick hotkey once crashes the event-tap thread;
all subsequent presses are dead until app restart. In wake-word mode the
backtick is the only non-voice trigger, so dictation was effectively
unusable.
Expected: backtick toggles recording; listener survives indefinitely.
Environment: macOS (M1 Pro), Accessibility granted ("Tap enabled for
keycode=50" in dictation.log).

## Root cause
`src/backends/macos.py` constructed `HotkeyEvent(hotkey=..., timestamp_ms=...)`
but `src.models.HotkeyEvent` requires `combo`, `pressed`, `timestamp_ms`.
First keypress → TypeError inside the Quartz tap callback → exception
escaped to `_run_event_tap`'s handler → `_running = False` → tap thread dead.
The Windows backend (`src/backends/windows.py:276`) built the event
correctly — macOS never got the update.

Evidence: dictation.log
`14:21:39 [ERROR] src.backends.macos: Event tap error:
HotkeyEvent.__init__() got an unexpected keyword argument 'hotkey'`

## TDD plan
1. RED: `tests/test_macos_backend.py` — assert `_build_event(pressed=...)`
   returns a HotkeyEvent with `combo`/`pressed`/`timestamp_ms` matching the model.
   GREEN: add `_build_event` seam in `MacHotkeyListener` + use it in
   `_handle_key_down`/`_handle_key_up` with correct kwargs.

## Acceptance criteria
- [x] New tests pass (2/2)
- [x] Full suite failures do not increase (27 → 25; remaining are
      pre-existing Windows-internals test mismatches)
- [x] No `HotkeyEvent.__init__` errors in dictation.log after a real
      keypress (user re-test)

## Note (pre-existing, deferred)
25 suite failures exist on the clean tree — tests poke Windows backend
internals (`_tray_icon`, `_on_exit_clicked`). Tracked separately; not part
of this defect.
