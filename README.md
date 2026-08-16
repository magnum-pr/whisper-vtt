# Whisper VTT

> A portable, fully offline, system-wide dictation utility for Windows and macOS. Press a hotkey or say a wake word, speak, and your words appear as text — transcribed locally. No audio ever leaves the machine.

---

## What it does

1. Listens for a **global hotkey** (default: backtick) or **wake word** from any application
2. Captures microphone audio at 16kHz mono with voice activity detection
3. Transcribes locally via **whisper.cpp (GGML)** on CPU — no GPU, no network, no API keys
4. Delivers transcribed text to the **clipboard**, **auto-pastes** it into the focused app, or **auto-sends** it (paste + Enter) depending on output mode
5. Lives in the **system tray / menu bar** with colored status indicators

---

## Why

Every dictation tool either phones home, needs an internet connection, requires admin install, or only works inside one app. Whisper VTT runs from a single folder — unzip, double-click, start dictating. Your voice data never leaves the machine.

---

## Features

| Feature | Detail |
|---|---|
| **100% offline** | whisper.cpp GGML inference on CPU — no network calls |
| **Portable** | Single folder distribution via PyInstaller — no installer, no admin rights |
| **System-wide hotkey** | Works in any application (IDEs, terminals, email, browsers) |
| **Wake word** | Optional voice activation — say a phrase to start recording |
| **VDI-compatible** | PortAudio via sounddevice for virtual desktop audio redirection |
| **VAD auto-stop** | RMS energy-based voice activity detection stops recording when you stop speaking |
| **Flexible output modes** | Clipboard-only, auto-paste, or auto-send with a spoken "Enter" guard-rail |
| **TOML config** | Power-user config for hotkey, model, VAD sensitivity, wake word, output mode |
| **Model selector** | Bundles `tiny.en` (~75MB); supports any whisper.cpp GGML model |
| **Zero-config start** | Sensible defaults — creates config on first run |

---

## Tech stack

| Component | Tech |
|---|---|
| Language | Python 3.11+ |
| Transcription | whisper.cpp via pywhispercpp (GGML, CPU-only) |
| Audio capture | sounddevice (PortAudio) |
| Hotkey | pywin32 global keyboard hook (Windows) · Quartz event tap (macOS) |
| System tray | pystray + Pillow (Windows) · rumps menu bar app (macOS) |
| Config | TOML (tomllib/tomli) |
| Packaging | PyInstaller `--onedir` |
| Testing | pytest + hypothesis |

---

## Project structure

```
whisper-vtt/
├── src/
│   ├── __main__.py              # Entry point
│   ├── app_controller.py        # State machine (Idle → Recording → Transcribing)
│   ├── audio_capture.py         # Microphone capture at 16kHz mono
│   ├── vad_engine.py            # Voice activity detection (RMS energy)
│   ├── transcription_engine.py  # whisper.cpp GGML wrapper
│   ├── output_handler.py        # Clipboard output via win32clipboard
│   ├── hotkey_listener.py       # Global keyboard hook
│   ├── wake_word.py             # Wake word detection
│   ├── system_tray.py           # Tray icon with colored circle indicators
│   ├── config_manager.py        # TOML config read/write
│   ├── models.py                # Data models
│   └── paths.py                 # Portable path resolution
├── scripts/
│   ├── build.py                 # PyInstaller build script
│   └── download_model.py        # Model downloader
├── models/                      # GGML model storage
├── tests/
├── pyproject.toml
└── requirements.txt
```

---

## Setup

```bash
# 1. Clone
git clone https://github.com/magnum-pr/whisper-vtt.git
cd whisper-vtt

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download a whisper.cpp GGML model (base.en is the default — ~141MB)
python scripts/download_model.py base.en

# 4. Run
./run.sh            # or: python -m src

# 5. Press backtick (`) from any application and start speaking
```

### macOS (primary target)

Two one-time permissions are required — grant both, then relaunch:

1. **Microphone** — System Settings → Privacy & Security → Microphone →
   enable your terminal app. Without it, macOS hands the app a silent
   audio stream.
2. **Accessibility** — System Settings → Privacy & Security →
   Accessibility → add your terminal app. Required for the global
   hotkey (Quartz event tap) and for auto-paste.

macOS extras:

- **Wake word** — set `[recording] mode = "wake_word"` to trigger by
  saying the phrase (`jarvis` by default).
- **Auto-paste into pi** — `paste_target = "pi"` activates VS Code or
  Terminal and pastes there (see [Configuration](#configuration)).
- **Mic selection** — the startup prompt lets you pick an input device
  and saves it to `[audio] device_name` (e.g. an audio interface with
  nothing plugged in reads as pure silence — pick the built-in mic).

> **Note on Rust-free setup:** this project needs no Rust toolchain or
> brew packages — plain `pip install -r requirements.txt` is enough on
> macOS and Windows.

---

## Packaging (portable distribution)

```bash
python scripts/build.py
# Output: dist/Whisper-VTT/ — portable folder, no install required
```

---

## Configuration

Whisper VTT reads `config.toml` at startup. The file is auto-created with
sensible defaults on first run — you never have to touch it. Invalid values
fall back to defaults with a logged warning; a bad config never crashes the
app. Config location: next to the app (source runs) or
`~/Library/Application Support/Whisper-VTT/config.toml` (packaged macOS).

### Full reference

```toml
[hotkey]
modifiers = []        # any of: "ctrl", "shift", "alt", "win" ("win" = Cmd on macOS)
key = "`"             # see Supported keys below

[recording]
mode = "wake_word"    # "toggle" | "push_to_talk" | "wake_word"

[output]
mode = "auto_send"    # "clipboard" | "auto_paste" | "auto_send"
paste_target = "pi"     # "frontmost" | "pi" | process name (macOS)

[vad]
silence_threshold_ms = 3000   # ms of continuous silence before auto-stop
volume_threshold_db = -50.0   # quieter-than-this counts as silence (dB)

[wake_word]
phrase = "jarvis"     # the spoken trigger phrase
threshold = 1e-20     # detection sensitivity — lower = stricter

[model]
path = "models/ggml-base.en.bin"   # any whisper.cpp GGML (.bin) model

[audio]
device_name = "MacBook Pro Microphone"  # exact device name; "" = system default
```

### [hotkey] — the manual trigger

| Key | Default | Notes |
|---|---|---|
| `modifiers` | `[]` | Any combination of `"ctrl"`, `"shift"`, `"alt"`, `"win"` (Cmd on macOS) |
| `key` | `` ` `` | Letters `a`–`z`, digits `0`–`9`, `f1`–`f12`, or names: `` ` `` / `"backtick"`, `"space"`, `"tab"`, `"enter"` / `"return"`, `"escape"` / `"esc"`, `"backspace"`, `"delete"`, `"insert"`, `"home"`, `"end"`, `"pageup"`, `"pagedown"`, `"up"` / `"down"` / `"left"` / `"right"`, `"capslock"`, `"numlock"`, `"scrolllock"`, `"printscreen"`, `"pause"` |

### [recording] — how recording starts

| Mode | Behavior |
|---|---|
| `toggle` *(default)* | Press the hotkey to start recording, press again to stop |
| `push_to_talk` | Hold the hotkey to record, release to stop |
| `wake_word` | Say the wake phrase to start; silence auto-stop ends it. The hotkey still works as a toggle in this mode |

### [output] — where the transcribed text goes

| Mode | Behavior |
|---|---|
| `clipboard` *(default)* | Text lands on the clipboard — you paste manually (Cmd+V / Ctrl+V) |
| `auto_paste` | Copies to the clipboard **and** pastes into the target app (see `paste_target`); you press Enter yourself. Safe general-purpose mode |
| `auto_send` | Like `auto_paste`, plus an **Enter press — but only when you end your dictation with the spoken word "Enter"** (stripped from the text). It never sends unless you explicitly say the trigger |

**`paste_target` — which app receives the paste (macOS):**

| Value | Behavior |
|---|---|
| `"frontmost"` *(default)* | Paste into whatever app is focused (classic behavior) |
| `"pi"` | Auto-resolve the running pi host (VS Code `"Code"` or `"Terminal"`) and activate it first. If pi is already frontmost, pastes directly without stealing focus |
| a process name | e.g. `"Terminal"`, `"Code"` — activate that specific process first |

If the target can't be resolved (pi not running, app name not found), the
paste falls back to the frontmost app — the text is always on the
clipboard either way.

**The `auto_send` guard-rail:**

| You say | What happens |
|---|---|
| *"fix the bug on the homepage"* | Pastes the text — **no Enter** |
| *"fix the bug on the homepage enter"* | Pastes *"fix the bug on the homepage"* **and presses Enter** |

- Case-insensitive (`"Enter"`, `"enter"`, `"ENTER"` all work)
- Trailing punctuation tolerated (*"…enter!"* still sends)
- Word-boundary aware: *"center"* does **not** trigger
- **Window guard:** the Enter is only pressed when pi's window is
  positively frontmost at send time (window title says pi). If it
  isn't — pi prompt closed, focus elsewhere — the text is still
  pasted but the Enter is **withheld**, and a notification tells you
  so. The text stays on the clipboard either way.

⚠️ `auto_paste` / `auto_send` type into the resolved `paste_target` — keep
that in mind for windows you don't want text injected into. Even if a
paste misses, the text is always on the clipboard as a fallback.

### [vad] — silence auto-stop

| Key | Default | Notes |
|---|---|---|
| `silence_threshold_ms` | `3000` | Milliseconds of continuous silence before recording auto-stops. Lower = snappier stop, higher = more tolerance for pauses |
| `volume_threshold_db` | `-50.0` | Sounds quieter than this level count as silence. More negative = quieter threshold = auto-stop fires more readily |

### [wake_word] — voice activation

| Key | Default | Notes |
|---|---|---|
| `phrase` | `"jarvis"` | The spoken trigger phrase (pocketsphinx keyphrase) |
| `threshold` | `1e-20` | Detection sensitivity — lower is stricter (fewer false triggers). `1e-20` is intentionally permissive |

### [model] — the transcription model

| Key | Default | Notes |
|---|---|---|
| `path` | `models/ggml-base.en.bin` | Path (relative to the app or absolute) to any whisper.cpp GGML model. Size/speed tradeoffs: `ggml-tiny.en.bin` (~77MB), `ggml-base.en.bin` (~141MB), `ggml-small.en.bin` (~466MB). If the file is missing, the engine falls back to loading the model by name |

### [audio] — microphone selection

| Key | Default | Notes |
|---|---|---|
| `device_name` | `""` | Exact device name as shown in the startup list (e.g. `"MacBook Pro Microphone"`). Empty string = system default, chosen silently |

---

## Requirements

- Windows or macOS
- Microphone
- Python 3.11+ (for development)
- ~75MB disk for the bundled `tiny.en` model

---

## Talking to Jarvis (dictation → pi)

Every transcription lands in a local drop box that the pi coding agent's
`whisper-vtt` skill reads. A spoken prefix tells pi what to do with it —
the keywords are natural speech:

| You say | pi does |
|---|---|
| "Jarvis, **task:** fix the deploy timeout" | files it in `TASKS.md` |
| "Jarvis, **lesson:** never close an audio stream in its callback" | files it for the gardening pipeline |
| "Jarvis, **journal:** Sharon confirmed Dance $65" | saves it as session context |
| "Jarvis, **status:** merged testimonials, starting mic meter" | timestamps a line into `PROGRESS.md` |
| "Jarvis, **note:** pick up milk" | shows it to you, unfiled |
| "Jarvis, fix the bug on the homepage **Enter**" | treats it as a message to pi and sends it |

In pi, say **"process my dictations"** — it reads the drop box, files
every entry, and reports where each one went. (Requires the
`whisper-vtt` pi skill — see its `references/jarvis-guide.md` for the
full command reference.)

---

## Development

```bash
pip install -e ".[dev]"
pytest -v
```

---

## Author

**Kasim Alam**

---

## License

MIT
