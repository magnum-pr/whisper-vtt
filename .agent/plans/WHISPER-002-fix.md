# Fix Plan — WHISPER-002 (macOS wake word never starts)

## Problem
Observed: "Wake word mode: 'jarvis'" was logged, but the listener never
ran — no "Wake word listener started", no detections, no errors.
Expected: saying "jarvis" starts recording.

## Root cause
`MacSystemTray.start()` runs the rumps NSApplication loop synchronously
(blocks forever). `AppController.start()` called `self._tray.start()`
BEFORE the wake word block — so on macOS the wake word code was
unreachable. The tray icon worked (rumps ran on the main thread) which
masked the bug. The transcription queue worker in `__main__.py` was also
after the blocked call, so it never ran either.

Evidence: dictation.log shows "AppController starting." then nothing
until hotkey events — missing both "Wake word listener started" and
"Wake word mode active".

## TDD plan
1. RED: `TestWakeWordStartOrdering` — assert `wake.start()` is called
   before `tray.start()` in `AppController.start()` (mock call order).
   GREEN: reorder `AppController.start()` — hotkey → wake word → tray.
2. GREEN (defensive): re-entry guard in `MacSystemTray.start()`
   (`if self._app is not None: return`).
3. GREEN (supporting): `__main__.py` starts the macOS queue worker
   BEFORE `controller.start()` (which now blocks on rumps), and no
   longer double-calls `tray.start()`.

## Acceptance criteria
- [x] Ordering tests pass (2/2 new)
- [x] Pre-existing suite failures unchanged (25)
- [x] Log shows "Wake word listener started" + "Wake word mode active"
      in a real run
- [ ] User confirms: saying "jarvis" starts recording (needs human voice test)

## Follow-up if voice test fails
PocketSphinx keyword tuning: threshold is 1e-20 (permissive). If the
acoustic model still misses "jarvis", try a different keyphrase string
(e.g. "jar vis", "jarvis please") or threshold sweep 1e-20 → 1e-5.
