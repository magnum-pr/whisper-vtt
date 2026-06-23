# Whisper VTT

> A portable, fully offline, system-wide dictation utility for Windows. Press a hotkey, speak, and your words appear as text — transcribed locally. No audio ever leaves the machine.

---

## What it does

1. Listens for a **global hotkey** (default: backtick) or **wake word** from any application
2. Captures microphone audio at 16kHz mono with voice activity detection
3. Transcribes locally via **whisper.cpp (GGML)** on CPU — no GPU, no network, no API keys
4. Places transcribed text on the **clipboard** for manual paste (Ctrl+V)
5. Lives in the **system tray** with colored status indicators

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
| **Clipboard output** | Text lands on clipboard — paste manually wherever your cursor is |
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
| Hotkey | pywin32 global keyboard hook |
| System tray | pystray + Pillow |
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
git clone https://github.com/LabidySabidy/whisper-vtt.git
cd whisper-vtt

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download a whisper.cpp GGML model (tiny.en recommended for speed)
python scripts/download_model.py tiny.en

# 4. Run
python -m src

# 5. Press backtick (`) from any application and start speaking
```

---

## Packaging (portable distribution)

```bash
python scripts/build.py
# Output: dist/Whisper-VTT/ — portable folder, no install required
```

---

## Configuration

On first run, a `config.toml` is created with sensible defaults:

```toml
[hotkey]
key = "backtick"
mode = "push_to_talk"    # or "toggle"

[audio]
sample_rate = 16000
channels = 1

[vad]
threshold = 0.02
silence_timeout_ms = 700

[transcription]
model = "tiny.en"

[wake_word]
enabled = false
phrase = "hey whisper"

[output]
mode = "clipboard"       # "clipboard" or "auto_paste"
```

---

## Requirements

- Windows (primary target)
- Microphone
- Python 3.11+ (for development)
- ~75MB disk for bundled `tiny.en` model

---

## CLI (optional)

```bash
python -m src --help
python -m src --model base.en --hotkey f9 --wake-word "computer"
```

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
