## 2026-08-16 19:15 — Cleanup pass (pushed `4bd494a`)

- Fixed: macos tray missing notify= param (item ticks raised TypeError);
  mic-level menu item + silent-mic watchdog rewired (were dead + broken).
- Removed: backends/base.py, DeviceInfo, set_error_callback, dead flag,
  unused imports; simplified wake word consecutive-hit machinery.
- 318 passed / 43 skipped / 0 failures. Restart whisper to pick up.
## 2026-08-16 18:45 — Sticky follow-up mode + README refresh (pushed `d87ee15`)

**Sticky sessions (default on).** After any plain dictation, whisper stays armed
for follow-ups — no wake word between fast commands. Each follow-up is delivered
live (journaled + delivered like a normal dictation). "that's all" disarms with a
tick; `[session] sticky = false` opts out.

**Lapse gate.** `[session] lapse_s = 20` — silence past this disarms sticky and
the next utterance requires "jarvis" again. Podcasts/TV/calls can't hijack the
mic during thinking pauses. Sticky sessions never accumulate or commit; a
"start a new session for X" mid-sticky switches to a compile session; "scratch
that" is ignored (nothing accumulated).

**README rewritten from scratch** — dictation language (modes, overrides,
sessions, sticky), drop box prefixes, output-paired routing, self-calibrating
VAD, hot-reload, pi handshake, single-instance guard, full config reference,
current project structure. jarvis-guide updated with sticky section.

320 passed / 43 skipped / 0 failures. **User action:** restart whisper to load
sticky mode.
## 2026-08-16 18:00 — Dictation session mode (built + pushed `47faa12`)

**"Jarvis, start a new session for AlignMe website"** → chime + "listening" —
then narrate items back to back, no wake word between them. "that's all"
commits the compiled list as a titled task list into TASKS.md via pi.

- Trigger/topic parsing in src/session.py (start phrase, standalone end
  phrases, "scratch that")
- Speech-onset re-arming: the wake word stream doubles as the armed
  listener (silence line + 6dB, 300ms hits, cooldowns) — single mic
  stream at all times
- Items accumulate locally; per-item tick + menu bar count; 60s idle
  timeout auto-commits (no lost work); quit commits to the drop box
- Commit = structured drop box entry (kind/title/items) + auto-paste
  "process my dictations" → pi files `## <title> (<date>)` task list
- Skill + jarvis-guide updated for session entries
- 307 passed / 43 skipped / 0 failures

**User action:** restart whisper to load session mode.
## 2026-08-16 17:10 — Resource + environment pass (afternoon session)

Built and pushed (`a4bfc9e`). 272 passed / 42 skipped / 0 failures.

**Single-instance guard.** `src/single_instance.py` — pidfile in the app config dir
(`whisper.pid`, gitignored). A new launch SIGTERMs any live whisper instance, waits
up to 5s, takes over. A recycled pid belonging to a non-whisper process is never
killed (verified via `ps` cmdline match). Released on exit, only if still ours.

**Output-paired input routing (corrected spec).** NOT "follow the OS default input"
(the Scarlett was macOS's default input but the user hears MacBook speakers).
Whisper now routes the mic to the input paired with the current default OUTPUT:
exact name match (AirPods) -> stem match (MacBook Pro Speakers <-> MacBook Pro
Microphone) -> MacBook mic fallback -> OS default input as last resort. Pinned
`device_name` still works. Resolved fresh at EVERY stream open, so output switches
and plug/unplug apply on the next dictation. Verified live: default output MacBook
Speakers -> paired input MacBook Pro Microphone (Scarlett ignored).

**Environment refresher.** `src/environment.py` — daemon tick every
`refresh_interval_s` (120s): latches paired-input changes; the controller restarts
the wake word stream while idle (recorder already resolves per-start). Rolling
noise floor (20th percentile over 120s of IDLE wake-word chunks only — recording
chunks never pollute it) -> VAD silence threshold = floor + calibration_margin_db
(8dB), clamped [-60,-28], pushed at every recording start. Fixes the fan problem:
silence line tracks the ambient floor instead of a fixed -50dB.

**Config:** `[environment] refresh_interval_s / calibration_margin_db`; live config
set to `device_name = "auto"`.

The running whisper instance (restarted 17:02) is already on this code.
## 2026-08-16 02:40 — Voice loop improvements Q-0…Q-3 (overnight run)

Built while the user slept — the four queued improvement ideas:

**Q-0 Pi presence handshake (idea #1).** New `src/pi_state.py` + `scripts/pi_handshake.py`.
pi writes `~/.local/whisper-vtt/pi-state.json` (window title fragment, host app,
timestamp) at session start and per turn. Whisper's `_resolve_target("pi")` now
consults a FRESH (≤30 min) handshake before falling back to AppleScript heuristics —
positive evidence replaces guessing. Writer is stdlib-only (runs with plain python3).

**Q-1 On-mode safety net (idea #2).** In auto_send/on mode, Enter is now withheld
when NO pi host exists (no Code running, no pi terminal window, no fresh handshake).
Returns `SEND_NO_HOST` → tray notification "no pi host running — text pasted, not sent".
With a host present, on-mode behavior is unchanged.

**Q-2 Config hot-reload (idea #5).** `AppController` polls config.toml (mtime+size)
each queue tick (~1s). Changes to output_mode/paste_target apply on the next
dictation — no whisper restart. `set_mode.py` message updated accordingly.
Recording-mode/hotkey/model still require restart (documented).

**Q-3 Per-dictation override (idea #9).** `extract_no_send_intent` in
`src/output_trigger.py`: "paste this without sending", "without sending",
"don't/dont send", "do not send", "no send", "just paste", "paste only".
Suppresses Enter for that one dictation in every mode (beats even the spoken
Enter trigger in protected); phrase stripped from paste AND drop-box journal.
Returns `SEND_SUPPRESSED` → "Override: pasted without sending."

Also: `paste_target` setters on both backends; override parity in Windows backend.

**Verified:** 234 passed, 42 skipped (Windows-only), 0 failures — up from 192.
Handshake run live: state file fresh, pi registered as Code / "PI Code — alignme".
Skill (`whisper-vtt` SKILL.md + jarvis-guide.md) updated: handshake step,
no-restart config changes, override phrases.

# PROGRESS.md — Whisper VTT






<!-- session-in-progress:start=2026-07-09T01:37:52.182Z -->
## 2026-07-08 20:39 — **Changed:** `src/wake_word.py` — synced `WakeWordListener` default threshold fr... _(in progress)_
**Changed:** `src/wake_word.py` — synced `WakeWordListener` default threshold from `1e-30` to `1e-20` (matching `DEFAULT_WAKE_WORD_THRESHOLD`). Also `.gitignore` + `_save_audio_device` fix from earlier.
**Verified:** 177/177 passing
**Next:** Ready to commit. All device-selection changes (`src/`, `tests/`, `PLAN.md`, `PROGRESS.md`, `scripts/runtime_hook.py`) + the two portability fixes.
<!-- end-session-in-progress -->
## 2026-07-08 20:37 — Two concerns
Two concerns.

**1. `config.toml` is not in `.gitignore`.** If you commit, your machine's device name leaks into the repo. On another machine, `git pull` brings a stale device name that triggers a confusing "not found" warning + re-prompt on first launch. The code handles the missing-device case correctly, so it won't break — just bad first-run UX.

**2. `_save_audio_device` reconstructs `AppConfig` field-by-field.** If someone adds a field to `AppConfig` later, `_save_audio_device` silently ...
## 2026-07-08 13:24 — **Stop.** Project working tree is dirty — uncommitted changes from the device-se...
**Stop.** Project working tree is dirty — uncommitted changes from the device-selection work:

```
M  PLAN.md
M  PROGRESS.md
M  scripts/runtime_hook.py
M  src/__main__.py
M  src/audio_capture.py
M  src/config_manager.py
M  src/models.py
M  src/wake_word.py
M  tests/test_audio_capture.py
M  tests/test_config_manager.py
```

Gardening requires a clean git tree so `git checkout .` can undo anything. Commit or stash these before we proceed.
## 2026-07-08 12:55 — Audio input device selection at startup
Added device selection prompt on first run: enumerates input devices via sounddevice,
lets user pick by number, saves device name to config.toml for persistence across
restarts. Device is identified by name (not index) for stability across USB
plug/unplug. If saved device disappears, re-prompts. Passes resolved device index
to AudioCapture→sd.InputStream. All three phases (model+config, AudioCapture param,
prompt logic) green — 176/177 tests pass (1 pre-existing failure in wake word test).
## 2026-06-05 04:43 — Colors work (bottom bar is cyan), but RGB orange isn't supported
Colors work (bottom bar is cyan), but RGB orange isn't supported. Switching to bright yellow `\033[93m` which your terminal definitely supports:
## 2026-06-04 17:42 — Standalone whisper-cli.exe subprocess approach (WORKS)

Final fix: bundled pre-built whisper-cli.exe (whisper.cpp v1.8.6) + DLLs alongside
the Python app. Transcription writes audio to temp WAV, spawns whisper-cli.exe as
subprocess. Zero native Python library dependencies — no segfaults, no DLL init
failures. whisper.cpp crashes are isolated to the subprocess.

Bundle ~100MB (Python app + whisper-cli.exe + ggml-tiny.en.bin ~74MB).
167 tests pass. Starts cleanly in dist.

Replaced pywhispercpp (whisper.cpp GGML, C-level crash during transcription) with
faster-whisper (CTranslate2, 4x faster CPU inference, no PyTorch). Default model
changed to models/base.en (~145MB flat directory). Bundle ~550MB.

Model bundled as flat directory (snapshot_download with local_dir) — WhisperModel
loads directly, zero network, no HuggingFace cache dependency. Avoids the symlink/
blobs issue that broke the previous attempt. 169 tests pass.

Replaced pywhispercpp (whisper.cpp GGML, C-level crash during transcription) with
faster-whisper (CTranslate2, 4x faster CPU inference, no PyTorch). Default model
changed from ggml-tiny.en.bin → base.en (~140MB, good accuracy/speed balance).
Bundle ~500MB (vs 2GB for openai-whisper). 169 tests pass. Model pre-downloaded
and bundled into dist.

## 2026-06-04 16:50 — Reverted subprocess transcription + CLI-style logging

Subprocess transcription was broken in PyInstaller bundles: `sys.executable` points
to `Whisper-VTT.exe` (not a Python interpreter), so `subprocess.run()` launched a second
app instance that hung instead of transcribing. Reverted `_do_transcribe` to direct
`transcription_engine.transcribe()` call.

Logging reformatted: console output is now minimal CLI-style (`●`, `△`, `✕` symbols,
no timestamps); file log retains full timestamps at DEBUG level for diagnostics.

170 tests pass.

## 2026-06-04 14:41 — Subprocess transcription attempt (REVERTED — see 16:50)
to `Whisper-VTT.exe` (not a Python interpreter), so `subprocess.run()` launched a second
app instance that hung instead of transcribing. Reverted `_do_transcribe` to direct
`transcription_engine.transcribe()` call — the original approach that worked.

Logging reformatted: console output is now minimal CLI-style (`●`, `△`, `✕` symbols,
no timestamps); file log retains full timestamps at DEBUG level for diagnostics.

170 tests pass.

## 2026-06-04 14:41 — Subprocess transcription attempt (REVERTED)
## 2025-06-03 — Multiple wake words + faster silence detection

Wake word now supports multiple phrases via PocketSphinx native `/` delimiter: "okay now/hey dude". Silence threshold reduced 5000ms → 4000ms (20% faster auto-stop). No logic changes — both are PocketSphinx/VAD-native features. 167 tests pass, dist rebuilt.

Raised default threshold 1e-30 → 1e-15, added 2-frame consecutive-hit requirement before firing callback. Single-syllable words like "hey" no longer false-trigger from ambient noise. Dist rebuilt with config: wake_word="hey", threshold=1e-15. 167 tests passing.

Added `pause()`/`resume()` to `WakeWordListener`. Paused during recording (prevents self-triggering from own voice), resumed after transcription with clean decoder state (prevents stale matches). 164 tests passing (was 156), lint clean.

Added Windows toast notifications with system beep at recording start/stop, and a no-beep notification with transcribed text preview at completion. Notifications fire for all trigger types (hotkey toggle/push-to-talk, wake word, VAD auto-stop). Build script now preserves existing dist config on rebuild instead of overwriting user edits. 156 tests passing (was 151), lint clean.


## 2026-06-04 14:41 — Subprocess transcription attempt (REVERTED — see 16:50)
Done. Transcription now runs in a separate subprocess via the whisper CLI. No recording cap. If whisper.cpp crashes, the subprocess dies with an error code — the main app survives and shows "Transcription failed." 5-minute recordings? Go for it. Fire it up.
## 2025-06-03 — VAD threshold fixed, app fully operational

**VAD threshold calibrated:** Default changed from -15 dBFS → -30 → -45. The original -15 dB threshold was appropriate for loud signals but not speech through a typical webcam/laptop mic. User's speech peaks around -32 dBFS. Final threshold of -45 dB provides enough headroom while distinguishing speech from noise floor (-60 to -96 dB).

**Diagnostic logging added:** VAD now logs peak dB level vs threshold when silence triggers, making it easy to tune per-microphone.

**App status: FULLY OPERATIONAL**
- Startup: clean, model loads in ~120ms
- Hotkey: backtick toggle works, no ctypes errors
- Recording: 16kHz mono, 100ms chunks
- VAD: correctly tracks speech vs silence, auto-stops after 5s of real silence
- Transcription: whisper.cpp (GGML tiny.en), inference in ~1.5s for 33s of audio
- Output: clipboard set + auto-paste (Ctrl+V simulation)
- EXE: PyInstaller --onedir, portable, no PyTorch, no CUDA, no admin install

## 2025-06-02 — Switched to whisper.cpp + fixed hotkey & sounddevice

- Replaced openai-whisper (PyTorch) with pywhispercpp (whisper.cpp, GGML)
- Fixed CallNextHookEx ctypes overflow on x64 (declared argtypes)
- Fixed sounddevice missing from venv
- 151/151 tests pass, lint clean

## 2025-05-29 — Previous sessions
- All 5 phases implemented (Foundation, Recording, UI, Integration, Build)
- 151 tests across 10 test files
- PyInstaller build with model bundling
