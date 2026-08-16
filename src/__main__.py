"""Whisper VTT — Portable offline dictation utility.

Entry point. Loads config, wires components, and starts the app.
Survives any component init failure — tray + hotkey always start.
"""

import logging
import signal
import sys
import traceback
from pathlib import Path
from typing import Optional

from src.app_controller import AppController
from src.audio_capture import AudioCapture
from src.config_manager import load_config, RecordingMode
from src.backends import HotkeyListener
from src.models import AppStatus
from src.backends import OutputHandler
from src.paths import PathResolver
from src.backends import SystemTray
from src.transcription_engine import TranscriptionEngine
from src.vad_engine import VADEngine
from src.wake_word import WakeWordListener


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape codes for accurate string width measurement."""
    import re
    return re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', text)


class _Term:
    """ANSI terminal codes — colors, dividers, layout. Zero dependencies."""
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    RED    = "\033[31m"
    CYAN   = "\033[36m"
    GRAY   = "\033[90m"
    WHITE  = "\033[97m"
    ORANGE = "\033[93m"  # bright yellow — closest supported color to orange

    @staticmethod
    def divider(char: str = "─", width: int = 62) -> str:
        return _Term.D + char * width + _Term.R

    @staticmethod
    def header(
        title: str,
        left: list[tuple[str, str]],
        right: list[str],
        left_w: int = 48,
    ) -> str:
        """Two-column orange banner. Add 'center' as 3rd tuple element."""
        O = _Term.ORANGE
        R = _Term.R
        D = _Term.D

        # Build left column lines with optional centering
        left_lines = []
        for item in left:
            txt, clr = item[0], item[1]
            centered = len(item) > 2 and item[2] == "center"
            left_lines.append((f"{clr}{txt}{R}", centered))

        def _vis(s): return len(_strip_ansi(s))
        vis_left_w = max(_vis(l[0]) for l in left_lines) if left_lines else 0
        vis_right_w = max(_vis(r) for r in right) if right else 0
        total = vis_left_w + vis_right_w + 11

        title_colored = O + title + R
        top = O + "╭─── " + title_colored + " " + "─" * max(0, total - len(title) - 7) + "╮" + R
        bot = O + "╰" + "─" * max(0, total - 2) + "╯" + R

        rows = []
        for i in range(max(len(left_lines), len(right))):
            l_str, centered = left_lines[i] if i < len(left_lines) else ("", False)
            r = right[i] if i < len(right) else ""
            l_vis = _vis(l_str) if l_str else 0
            if centered:
                pad = (vis_left_w - l_vis) // 2
                l_padded = " " * pad + l_str + " " * (vis_left_w - l_vis - pad)
            else:
                l_padded = l_str + " " * max(0, vis_left_w - l_vis)
            r_vis = _vis(r) if r else 0
            r_padded = r + " " * max(0, vis_right_w - r_vis)
            rows.append(
                O + "│" + R + "  " + l_padded + "  "
                + O + "│" + R + "  " + r_padded + "  "
                + O + "│" + R
            )

        return "\n".join([top] + rows + [bot])


def _init_console() -> None:
    """Enable VT processing for ANSI scrolling region on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        ENABLE_VT = 0x0004
        for hid in (-11, -12):
            h = k.GetStdHandle(hid)
            if h:
                m = ctypes.c_uint32()
                if k.GetConsoleMode(h, ctypes.byref(m)):
                    k.SetConsoleMode(h, m.value | ENABLE_VT)
    except Exception:
        pass


class _StatusBar:
    """Persistent bottom bar using bottombar library."""
    _item = None

    @classmethod
    def show(cls, symbol: str, text: str) -> None:
        try:
            import bottombar as bb
            if cls._item is None:
                cls._item = bb.add(f" {symbol} {text}", label="status")
                cls._item.__enter__()
            else:
                cls._item.text = f" {symbol} {text}"
        except Exception:
            pass


class _ConsoleFilter(logging.Filter):
    """Show app state changes and transcription results on console."""
    SHOWN = {"src.app_controller", "src.transcription_engine"}

    HIDE_MSG = {
        "AppController starting.",
        "Wake word mode active",
        "Wake word triggered",
        "Silence detected",
        "Clipboard set",
        "Dictation cycle complete.",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name not in self.SHOWN:
            return False
        for h in self.HIDE_MSG:
            if h in record.getMessage():
                return False
        return True


class _CLIFormatter(logging.Formatter):
    """Clean formatter — strip prefixes, color transcription text."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        msg = msg.replace("app_controller ", "").replace("transcription_engine ", "")

        lvl = record.levelno
        if lvl >= logging.ERROR:
            sym, clr = "✕", _Term.RED
        elif lvl >= logging.WARNING:
            sym, clr = "△", _Term.YELLOW
        elif "Transcription:" in msg:
            sym, clr = "", _Term.CYAN
            msg = msg.replace("Transcription: ", "").strip().strip('"').strip("'")
        elif "Recording started" in msg:
            sym, clr = "◉", _Term.GREEN
        elif "Transcribing" in msg:
            sym, clr = "○", _Term.ORANGE
        else:
            sym, clr = "", ""

        return f"{clr}{sym} {msg}{_Term.R}".strip()


def setup_logging() -> None:
    """Configure logging to file (full) and console (filtered + styled)."""
    log_path = PathResolver.log_path()

    # File log: everything at DEBUG, full timestamps
    log_file = open(log_path, "a", encoding="utf-8", buffering=1)
    file_handler = logging.StreamHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    # Console: INFO+, filtered, styled
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.addFilter(_ConsoleFilter())
    console_handler.setFormatter(_CLIFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Suppress noisy third-party loggers on console
    for noisy in ("PIL", "pywhispercpp", "pystray"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _resolve_audio_device(configured_name: Optional[str]) -> Optional[int]:
    """Resolve audio input device.

    If `configured_name` is set and the device exists, return its index silently.
    Otherwise, enumerate input devices, prompt the user to pick one, save the
    choice to config.toml, and return the selected index (None = system default).
    """
    logger = logging.getLogger(__name__)

    try:
        import sounddevice as sd
    except ImportError:
        logger.warning("sounddevice not available, using system default.")
        return None

    try:
        devices = sd.query_devices()
    except Exception as e:
        logger.warning("Could not query audio devices: %s. Using system default.", e)
        return None

    # Filter to input-capable devices, de-duplicate by name (first occurrence wins)
    seen: set[str] = set()
    input_devices: list[dict] = []
    for d in devices:
        if d.get("max_input_channels", 0) > 0:
            name: str = d.get("name", "")
            if name not in seen:
                seen.add(name)
                input_devices.append(d)

    if not input_devices:
        logger.warning("No input devices found. Using system default.")
        return None

    # No configured device (or explicit system default) — use it silently
    if not configured_name:
        logger.info("No audio device configured — using system default.")
        return None

    # If a device name is configured, try exact match
    if configured_name:
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and d.get("name") == configured_name:
                logger.info("Using configured audio device: %s", configured_name)
                return idx
        # Not found — warn and fall through to prompt
        logger.warning(
            "Configured audio device '%s' not found. Prompting for new selection.",
            configured_name,
        )

    # ── Prompt ──────────────────────────────────────────────────────────
    print(file=sys.stderr)
    print(f"{_Term.ORANGE}Available audio input devices:{_Term.R}", file=sys.stderr)
    print(f"  {_Term.D}0{_Term.R}  System default", file=sys.stderr)
    for i, d in enumerate(input_devices):
        ch = d.get("max_input_channels", 0)
        sr = int(d.get("default_samplerate", 0))
        print(
            f"  {_Term.ORANGE}{i + 1}{_Term.R}  {d['name']}"
            f"{_Term.D} ({ch}ch, {sr}Hz){_Term.R}",
            file=sys.stderr,
        )
    print(file=sys.stderr)

    while True:
        try:
            choice = input(
                f"Select device number {_Term.D}(0-{len(input_devices)}){_Term.R}: "
            ).strip()
            if not choice:
                print(f"{_Term.YELLOW}△ Using system default.{_Term.R}", file=sys.stderr)
                return None
            idx = int(choice)
            if idx == 0:
                print(f"{_Term.YELLOW}△ Using system default.{_Term.R}", file=sys.stderr)
                return None
            if 1 <= idx <= len(input_devices):
                selected_name: str = input_devices[idx - 1]["name"]
                # Find actual device list index in full devices list
                actual_idx: Optional[int] = None
                for di, d in enumerate(devices):
                    if d.get("name") == selected_name:
                        actual_idx = di
                        break
                if actual_idx is None:
                    actual_idx = idx - 1  # fallback

                # Save to config
                _save_audio_device(selected_name)
                print(
                    f"{_Term.GREEN}● Selected: {selected_name}{_Term.R}",
                    file=sys.stderr,
                )
                return actual_idx
            else:
                print(
                    f"{_Term.RED}✕ Invalid selection: {idx}. "
                    f"Choose 0-{len(input_devices)}.{_Term.R}",
                    file=sys.stderr,
                )
        except ValueError:
            print(
                f"{_Term.RED}✕ Please enter a number.{_Term.R}",
                file=sys.stderr,
            )
        except (EOFError, KeyboardInterrupt):
            print(f"\n{_Term.YELLOW}△ Using system default.{_Term.R}", file=sys.stderr)
            return None


def _save_audio_device(device_name: str) -> None:
    """Persist the selected device name to config.toml.

    Uses dataclasses.replace() to mutate only the audio_device_name field
    — avoids silently dropping new fields if AppConfig grows later.
    """
    from dataclasses import replace
    from src.config_manager import load_config, config_to_toml

    config_path = PathResolver.config_path()
    try:
        config = load_config(config_path)
    except Exception:
        return

    updated = replace(config, audio_device_name=device_name)
    try:
        config_path.write_text(config_to_toml(updated), encoding="utf-8")
    except OSError:
        pass


def main() -> None:
    """Application entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Whisper VTT starting...")

    # ── Config ──────────────────────────────────────────────────────────
    try:
        config = load_config()
        logger.info(
            "Config loaded: hotkey=%s, mode=%s, model=%s",
            config.hotkey,
            config.recording_mode.value,
            config.model_path,
        )
    except Exception as e:
        logger.fatal("Failed to load config: %s\n%s", e, traceback.format_exc())
        # Can't continue without config — it has the hotkey definition
        input("Press Enter to exit...")
        sys.exit(1)

    # ── System tray (start first — user sees something) ─────────────────
    logger.info("Initializing system tray...")
    tray = SystemTray(title="Whisper VTT")

    # ── Hotkey listener ─────────────────────────────────────────────────
    logger.info("Initializing hotkey listener...")
    try:
        hotkey_listener = HotkeyListener(config.hotkey)
    except Exception as e:
        logger.fatal("Failed to create hotkey listener: %s\n%s", e, traceback.format_exc())
        tray.show_notification("Whisper VTT", f"Fatal: Could not register hotkey: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

    # ── Audio device selection ─────────────────────────────────────────
    logger.info("Resolving audio input device...")
    device_index = _resolve_audio_device(config.audio_device_name)

    # ── Audio capture ───────────────────────────────────────────────────
    logger.info("Initializing audio capture...")
    audio_capture = AudioCapture(device_index=device_index)

    # ── VAD engine ──────────────────────────────────────────────────────
    logger.info("Initializing VAD engine...")
    vad_engine = VADEngine(
        silence_threshold_ms=config.silence_threshold_ms,
        volume_threshold_db=config.volume_threshold_db,
    )

    # ── Output handler ──────────────────────────────────────────────────
    logger.info("Initializing output handler...")
    output_handler = OutputHandler(
        mode=config.output_mode,
        paste_target=config.paste_target,
    )

    # ── Transcription engine ─────────────────────────────────────────
    logger.info("Initializing transcription engine...")
    model_path = str(PathResolver.resolve(config.model_path))
    transcription_engine = TranscriptionEngine(model_path=model_path)

    # Preload model (whisper.cpp writes directly to stderr fd 2 — suppress it)
    logger.info("Loading whisper model (this may take a moment)...")
    try:
        import os
        with open(os.devnull, "w") as devnull:
            old_fd = os.dup(2)
            os.dup2(devnull.fileno(), 2)
            try:
                transcription_engine.load_model()
            finally:
                os.dup2(old_fd, 2)
                os.close(old_fd)
    except Exception as e:
        logger.error("Model load exception: %s\n%s", e, traceback.format_exc())

    if not transcription_engine.is_available:
        logger.warning(
            "Whisper model not available: %s. Dictation will be disabled.",
            transcription_engine.load_error or "unknown error",
        )
        tray.show_notification(
            "Whisper VTT",
            f"Model not loaded: {transcription_engine.load_error or 'unknown error'}\n"
            f"Dictation is disabled.",
        )
    else:
        logger.info("Whisper model loaded successfully.")

    # ── Controller ──────────────────────────────────────────────────────
    logger.info("Creating app controller...")

    # Wake word listener (only created for wake_word mode)
    wake_word_listener = None
    if config.recording_mode == RecordingMode.WAKE_WORD:
        wake_word_listener = WakeWordListener(
            keyword=config.wake_word,
            threshold=config.wake_word_threshold,
            device_index=device_index,
        )
        logger.info(
            "Wake word mode: '%s' (threshold %.0e)",
            config.wake_word,
            config.wake_word_threshold,
        )

    controller = AppController(
        config=config,
        tray=tray,
        hotkey_listener=hotkey_listener,
        audio_capture=audio_capture,
        vad_engine=vad_engine,
        transcription_engine=transcription_engine,
        output_handler=output_handler,
        wake_word_listener=wake_word_listener,
    )

    # ── Shutdown handler ────────────────────────────────────────────────
    def on_exit() -> None:
        logger.info("Shutting down...")
        try:
            controller.stop()
        except Exception as e:
            logger.error("Error during shutdown: %s", e)

    tray.set_on_exit(on_exit)
    signal.signal(signal.SIGINT, lambda sig, frame: on_exit())

    # ── Start ───────────────────────────────────────────────────────────
    # Print banner before starting — avoids startup messages appearing
    # before the banner in the console.
    model_name = config.model_path.name
    hotkey_str = config.hotkey.key.upper() if config.hotkey.key else "`"

    art = [
        "    ⢀⣀⣠⣀⣀⡀",
        "  ⣠⣾⣿⣿⣿⣿⣿⣿⣷⣦⡀",
        " ⢠⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣷⡀     ⣠⣶⣾⣷⣶⣄",
        " ⢸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧   ⢰⣿⠟⠉⠻⣿⣿⣷",
        " ⠈⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⠿⢷⣄⠘⠿    ⢸⣿⣿⡆",
        "  ⠈⠿⣿⣿⣿⣿⣿⣀⣸⣿⣷⣤⣴⠟     ⢀⣼⣿⣿⠁",
        "    ⠈⠙⣛⣿⣿⣿⣿⣿⣿⣿⣿⣦⣀⣀⣀⣴⣾⣿⣿⡟",
        " ⢀⣠⣴⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡿⠟⠋ ⣠⣤⣀",
        "⣴⣿⣿⣿⠿⠟⠛⠛⢛⣿⣿⣿⣿⣿⣿⣧⡈⠉⠁    ⠈⠉⢻⣿⣧",
        "⣼⣿⣿⠋    ⢠⣾⣿⣿⠟⠉⠻⣿⣿⣿⣦⣄    ⣸⣿⣿⠃",
        "⣿⣿⡇     ⣿⣿⡿⠃     ⠈⠛⢿⣿⣿⣿⣿⣶⣿⣿⣿⡿⠋",
        "⢿⣿⣧⡀ ⣶⣄⠘⣿⣿⡇  ⠠⠶⣿⣶⡄ ⠈⠙⠛⠻⠟⠛⠛⠁",
        "⠈⠻⣿⣿⣿⣿⠏ ⢻⣿⣿⣄    ⣸⣿⡇",
        "         ⠻⣿⣿⣿⣶⣾⣿⣿⠃",
        "           ⠈⠙⠛⠛⠛⠋",
    ]
    left = [
        ("Welcome to Whisper VTT", _Term.B + _Term.WHITE, "center"),
        ("Your local voice transcription assistant", _Term.D, "center"),
        ("", ""),
        *[(_Term.ORANGE + a + _Term.R, "") for a in art],
        ("", ""),
        (f"Model: {model_name}", _Term.CYAN),
        (f"Hotkey: {hotkey_str}  ·  Ctrl+V to paste", _Term.GRAY),
    ]

    right = [
        _Term.ORANGE + "Tips for getting started" + _Term.R,
        "",
        f"Say {_Term.GREEN}'jarvis'{_Term.R} or press {_Term.ORANGE}{hotkey_str}{_Term.R}",
        "to start recording",
        "",
        f"{_Term.D}────────────────────────{_Term.R}",
        "",
        "Transcription copied",
        "to clipboard automatically",
        "",
        "Right-click tray to exit",
    ]

    print(_Term.header("Whisper VTT", left, right), file=sys.stderr)

    # Wire status bar updates from app controller
    def _on_status(status, detail=""):
        sym_map = {
            AppStatus.IDLE:         (_Term.CYAN + "●", f"Idle — {detail or 'say \"jarvis\" to start'}"),
            AppStatus.RECORDING:    (_Term.GREEN + "◉", f"Recording — {detail or 'speak now...'}"),
            AppStatus.TRANSCRIBING: (_Term.ORANGE + "○", f"Transcribing — {detail or 'processing audio...'}"),
            AppStatus.ERROR:        (_Term.RED + "✕", f"Error — {detail or 'something went wrong'}"),
        }
        sym, text = sym_map.get(status, ("●", detail))
        _StatusBar.show(sym, text)

    controller.set_status_callback(_on_status)

    logger.info("Starting app (tray + hotkey)...")

    # On macOS the tray's rumps run loop owns the main thread from
    # controller.start() onward, so the transcription queue worker must
    # already be running before that blocking call.
    queue_worker = None
    if sys.platform == "darwin":
        import threading

        def _worker_loop():
            while getattr(_worker_loop, "running", True):
                controller.process_queue(timeout=1.0)

        _worker_loop.running = True
        queue_worker = threading.Thread(
            target=_worker_loop, daemon=True, name="queue-worker")
        queue_worker.start()

    logger.info("Whisper VTT running. Press %s to dictate.", config.hotkey)

    # Platform-specific run loop.
    # - Windows: tray/hotkey on daemon threads, main thread processes queue.
    # - macOS: tray owns the main thread (NSApplication run loop),
    #   so controller.start() blocks here until rumps quits.
    if sys.platform == "darwin":
        try:
            controller.start()  # blocks until rumps quits (Exit menu or Cmd+Q)
        except KeyboardInterrupt:
            pass
        finally:
            _worker_loop.running = False
            queue_worker.join(timeout=2)
            on_exit()
    else:
        # Windows: main thread runs queue, tray/hotkey on daemon threads
        controller.start()
        try:
            import time
            while True:
                controller.process_queue(timeout=1.0)
        except KeyboardInterrupt:
            pass
        finally:
            on_exit()


if __name__ == "__main__":
    main()
