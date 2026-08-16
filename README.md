# Whisper VTT

> A portable, fully offline, system-wide dictation utility — built to talk
> to [pi](https://github.com/earendil-works/pi-coding-agent) (and anything
> else that accepts text). Say a wake word, speak, and your words appear
> as text, transcribed locally. No audio ever leaves the machine.

---

## What it is

Whisper VTT listens system-wide for a **wake word** ("jarvis") or a
**hotkey**, records your voice, transcribes it locally with
**whisper.cpp (GGML)** on CPU, and delivers the text where you want it —
pasted into pi, sent as a command, compiled into a task list, or filed
into your notes. It lives in the menu bar with a live mic meter, a
calibrated noise floor, and a whole dictation language on top.

```
say "jarvis" ──▶ record ──▶ transcribe (local, offline)
                          ├─▶ paste + send into pi (modes: clipboard / auto_paste / auto_send / protected)
                          ├─▶ drop box journal (every dictation)
                          ├─▶ sessions: compile a titled task list from many items
                          └─▶ sticky mode: stay armed for follow-ups — no wake word between commands
```

---

## Highlights

| Capability | What it does |
|---|---|
| **100% offline** | whisper.cpp GGML inference on CPU — no network, no API keys, no GPU |
| **Wake word or hotkey** | Say "jarvis" or press `` ` `` (configurable) from any app |
| **Output modes** | `clipboard`, `auto_paste`, `auto_send` (always Enter), `protected` (spoken "enter" trigger + window guard) — switchable **by voice**, no restart |
| **Dictation sessions** | *"Jarvis, start a new session for AlignMe website"* → narrate item after item (no wake word between them) → *"that's all"* commits a titled task list |
| **Sticky follow-ups** | After any command, whisper stays armed — follow-ups flow naturally; the lapse gate re-arms the wake word after ~20s of silence |
| **Pi drop box** | Every dictation is journaled locally; pi's `whisper-vtt` skill routes `task:` / `lesson:` / `journal:` / `status:` / `note:` prefixes into your project files |
| **Output-paired mic routing** | The mic follows what you're *hearing* from: AirPods out → AirPods mic, MacBook speakers → MacBook mic — resolved fresh at every recording |
| **Self-calibrating VAD** | A rolling ambient noise floor (fan, AC, room) recalibrates the silence threshold continuously — no more recording that runs long because of background noise |
| **Config hot-reload** | `config.toml` changes apply on the next dictation — no restart |
| **Single-instance guard** | Launching whisper ends any previous instance — two mics fighting over one stream is a thing of the past |
| **Pi handshake** | pi registers its window in a state file; whisper targets it positively instead of AppleScript-guessing |
| **Menu bar telemetry** | Live mic level, silent-mic watchdog, session item count, status colors |

---

## Setup

### macOS (primary target)

```bash
# 1. Clone
git clone https://github.com/magnum-pr/whisper-vtt.git
cd whisper-vtt

# 2. Install (venv recommended)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Download the default model (~141MB)
python scripts/download_model.py base.en

# 4. Run
python -m src
```

Two one-time permissions, then relaunch:

1. **Microphone** — System Settings → Privacy & Security → Microphone →
   enable your terminal app. Without it, macOS hands over a silent stream.
2. **Accessibility** — System Settings → Privacy & Security →
   Accessibility → add your terminal app. Required for the global hotkey
   (Quartz event tap) and auto-paste.

### Windows

```bash
pip install -r requirements.txt
python scripts/download_model.py base.en
python -m src
```

(Windows uses pystray + pywin32; the full suite includes Windows-only
tests that are skipped on macOS.)

### Portable distribution

```bash
python scripts/build.py   # → dist/Whisper-VTT/ — run from a folder, no install
```

---

## The dictation language

### Output modes

| Mode | Behavior |
|---|---|
| `clipboard` | Text lands on the clipboard — you paste manually |
| `auto_paste` *(auto-send off)* | Copies + pastes into the target app; never presses Enter |
| `auto_send` *(auto-send on)* | Pastes + **always presses Enter** — every dictation is a message. A safety net withholds the Enter when **no pi host is running at all**, so a random app never receives a stray send |
| `protected` | Pastes; presses Enter **only** when you end with the spoken word *"enter"* **and** pi's window is positively frontmost (handshake or title evidence) |

**Change modes by voice:** *"change auto_send to protected"* — pi runs
`scripts/set_mode.py`, `config.toml` updates atomically, and the change
applies on your next dictation (hot-reload). **No restart.**

**One-time override:** *"…without sending"*, *"don't send"*, *"just paste"*
anywhere in a dictation suppresses the Enter for that one message — in
every mode — and the phrase is stripped from the text.

### Sessions — one Jarvis, many items

For reviewing a site or reading a doc while noting things down:

```
"Jarvis, start a new session for AlignMe website"
  → chime + "Session started: AlignMe website — listening…"
"reorder the hero section"     ← just speak; no wake word
"fix the pricing table"        ← each item gets a tick + menu bar count
"scratch that"                 ← drops the last item
"that's all"                   ← commit
  → compiled into TASKS.md as "## AlignMe website (2026-08-16)" with - [ ] items
```

Speech onset (calibrated silence line + 6 dB) starts each recording; the
commit hands the list to pi automatically. 60s of silence auto-commits —
work is never lost.

### Sticky follow-ups — the default

After *any* dictation, whisper stays armed for follow-ups. Fast cadence
needs no wake word:

```
"jarvis, show me the tasks"   → delivered
"now open the homepage file"  → delivered (no jarvis needed)
"and check the build"         → delivered
"that's all"                  → disarms back to wake word mode
```

The **lapse gate**: ~20s of silence and the next utterance needs
"jarvis" again — a podcast or a phone call can't hijack the mic.
(`[session] lapse_s`, `[session] sticky = false` to turn the feature off.)

### Pi drop box prefixes

Every dictation is journaled to `~/.local/whisper-vtt/inbox/`. In pi,
say **"process my dictations"** and the `whisper-vtt` skill files them:

| You say | pi does |
|---|---|
| "Jarvis, **task:** fix the deploy timeout" | files it in `TASKS.md` |
| "Jarvis, **lesson:** never close an audio stream in its callback" | files it for the gardening pipeline |
| "Jarvis, **journal:** Sharon confirmed Dance $65" | saves it as project context |
| "Jarvis, **status:** merged testimonials, starting the mic meter" | timestamps a line into `PROGRESS.md` |
| "Jarvis, **note:** pick up milk" | shows it to you, unfiled |
| "Jarvis, fix the bug on the homepage, **Enter**" | treats it as a message to pi and sends it |

(Requires the `whisper-vtt` pi skill — see its `references/jarvis-guide.md`
for the full command reference.)

---

## Configuration

`config.toml` is auto-created on first run with sensible defaults and is
**hot-reloaded** — edits apply on the next dictation, no restart. Invalid
values fall back to defaults with a logged warning; a bad config never
crashes the app. Location: project root (source runs) or
`~/Library/Application Support/Whisper-VTT/config.toml` (packaged macOS).

```toml
[hotkey]
modifiers = []        # any of: "ctrl", "shift", "alt", "win" ("win" = Cmd)
key = "`"             # a–z, 0–9, f1–f12, backtick, space, tab, enter, escape…

[recording]
mode = "wake_word"    # "toggle" | "push_to_talk" | "wake_word"

[output]
mode = "auto_send"    # "clipboard" | "auto_paste" | "auto_send" | "protected"
paste_target = "pi"   # "frontmost" | "pi" | a process name (macOS)

[vad]
silence_threshold_ms = 3000   # fallback when the noise floor hasn't calibrated yet
volume_threshold_db = -50.0   # static fallback threshold (dB)

[wake_word]
phrase = "jarvis"     # the spoken trigger phrase
threshold = 1e-20     # detection sensitivity — lower = stricter

[model]
path = "models/ggml-base.en.bin"   # any whisper.cpp GGML model

[audio]
device_name = "auto"  # "auto"/"" = mic paired with the current OUTPUT;
                      # a device name pins that mic

[environment]
refresh_interval_s = 120      # device-change + calibration tick cadence
calibration_margin_db = 8.0   # silence line = ambient floor + this margin

[session]
timeout_s = 60       # idle auto-commit for compile sessions
sticky = true        # stay armed for follow-ups after every dictation
lapse_s = 20         # sticky: silence after which "jarvis" is required again
```

### `[audio] device_name` — output-paired routing

In auto mode whisper uses the mic that belongs to what you're currently
**hearing** from:

1. Exact name match with the default output device (AirPods out → AirPods mic)
2. Stem match ("MacBook Pro Speakers" ↔ "MacBook Pro Microphone")
3. MacBook microphone fallback
4. OS default input as a last resort

Menu-bar output switches and plug/unplug apply on the next dictation;
a periodic tick restarts the wake word stream when the paired device
changes mid-run. Set a device name to pin one permanently.

### `[vad]` — self-calibrating silence detection

While idle, the wake word stream feeds a rolling ambient floor (20th
percentile of the last 120s). At every recording start the silence
threshold becomes **floor + `calibration_margin_db`**, clamped to
[-60, -28] dB. A bedroom fan, AC, or a new room just works — the
configured `volume_threshold_db` only covers the first seconds after
launch, before the floor has data.

---

## Project structure

```
whisper-vtt/
├── src/
│   ├── __main__.py              # Entry point, wiring, single-instance lock
│   ├── app_controller.py        # State machine + dictation sessions + sticky mode
│   ├── audio_capture.py         # 16kHz mono capture, per-start device resolution
│   ├── vad_engine.py            # RMS silence detection (threshold pushed per recording)
│   ├── speech_onset.py          # Session-mode onset: voice above the silence line
│   ├── session.py               # Session phrases ("start a new session…", "that's all")
│   ├── environment.py           # Noise floor + output-paired device resolution + refresh ticks
│   ├── single_instance.py       # pidfile lock — one whisper, ever
│   ├── pi_state.py              # Pi handshake state file (~/.local/whisper-vtt/pi-state.json)
│   ├── output_trigger.py        # "enter" trigger + "without sending" override parsing
│   ├── dropbox.py               # Dictation journal (pi's inbox)
│   ├── level_meter.py           # Live mic level + silent-mic watchdog
│   ├── wake_word.py             # PocketSphinx KWS + onset feed
│   ├── transcription_engine.py  # whisper.cpp GGML wrapper
│   ├── config_manager.py        # TOML load/validate/serialize
│   ├── models.py                # Enums, dataclasses, deliver-result constants
│   ├── paths.py                 # Source vs PyInstaller path resolution
│   └── backends/                # macOS (Quartz/rumps/pbcopy) · Windows (pywin32/pystray)
├── scripts/
│   ├── set_mode.py              # Voice bridge: validate + rewrite [output] mode atomically
│   ├── pi_handshake.py          # Run by pi: registers its window (stdlib only)
│   ├── download_model.py        # Model downloader
│   ├── build.py                 # PyInstaller portable build
│   ├── diag_mic.py              # Microphone diagnostics
│   └── runtime_hook.py
├── models/                      # GGML model storage
├── tests/                       # 320+ tests across all subsystems
└── config.toml                  # Your settings (gitignored)
```

---

## Development

```bash
pip install -e ".[dev]"
pytest -v          # 320+ passed, Windows-only tests skipped on macOS
```

---

## Author

**Kasim Alam**

---

## License

MIT
