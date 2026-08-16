"""macOS backend implementations.

Real implementations using:
- Quartz event tap for global hotkey capture + swallow
- pbcopy / osascript for clipboard and paste
- rumps for menu bar app (system tray replacement)
"""

import logging
import subprocess
import threading
import time
from typing import Callable, Optional

from PIL import Image, ImageDraw

from src.models import AppStatus, HotkeyCombo, HotkeyEvent, OutputMode

logger = logging.getLogger(__name__)


MAC_KEYCODE_MAP = {
    **{chr(c).lower(): c - ord("a") for c in range(ord("A"), ord("Z") + 1)},
    **{str(i): 29 + i for i in range(10)},
    "backtick": 50,
    "`": 50, "~": 50,
    "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42,
    ";": 41, "'": 39, ",": 43, ".": 47, "/": 44,
    "space": 49, "tab": 48, "enter": 36, "backspace": 51,
    "escape": 53, "delete": 117, "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}

MAC_MODIFIER_FLAGS = {
    "shift": 0x20000, "ctrl": 0x40000,
    "alt": 0x80000, "cmd": 0x100000,
}

KEY_NAME_TO_VK = MAC_KEYCODE_MAP


class MacHotkeyListener:
    """Global hotkey listener via Quartz event tap."""

    def __init__(self, hotkey: HotkeyCombo):
        self._hotkey = hotkey
        self._on_activated = None
        self._on_released = None
        self._running = False
        self._key_down = False
        self._thread = None
        self._tap = None
        key_name = hotkey.key.lower()
        if key_name not in MAC_KEYCODE_MAP:
            raise ValueError(f"Unknown macOS key: {hotkey.key}")
        self._keycode = MAC_KEYCODE_MAP[key_name]

    def set_on_activated(self, callback):
        self._on_activated = callback

    def set_on_released(self, callback):
        self._on_released = callback

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_event_tap, daemon=True, name="hotkey-tap")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._tap is not None:
            try:
                import Quartz
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass

    def _run_event_tap(self) -> None:
        import Quartz
        import ApplicationServices
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(
            {ApplicationServices.kAXTrustedCheckOptionPrompt: True})
        if not trusted:
            logger.error(
                "Accessibility permission not granted. "
                "Go to System Preferences -> Security & Privacy -> "
                "Privacy -> Accessibility and add this app, then relaunch.")
            self._running = False
            return
        mask = (Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) |
                Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp))
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault, mask, self._tap_callback, None)
        if self._tap is None:
            logger.error("CGEventTapCreate returned NULL.")
            self._running = False
            return
        rls = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), rls, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        logger.info("Tap enabled for keycode=%d", self._keycode)
        try:
            Quartz.CFRunLoopRun()
        except Exception as e:
            logger.error("Event tap error: %s", e)
        finally:
            if self._tap is not None:
                Quartz.CGEventTapEnable(self._tap, False)
            self._running = False

    def _tap_callback(self, proxy, event_type, event, refcon):
        import Quartz
        if event_type == Quartz.kCGEventTapDisabledByTimeout:
            logger.warning("Tap disabled by timeout, re-enabling.")
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        if event_type == Quartz.kCGEventTapDisabledByUserInput:
            logger.warning("Tap disabled by user input, re-enabling.")
            Quartz.CGEventTapEnable(self._tap, True)
            return event
        keycode = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGKeyboardEventKeycode)
        if keycode != self._keycode:
            return event
        if event_type == Quartz.kCGEventKeyDown:
            return self._handle_key_down(event)
        elif event_type == Quartz.kCGEventKeyUp:
            return self._handle_key_up(event)
        return event

    def _handle_key_down(self, event):
        import Quartz
        flags = Quartz.CGEventGetFlags(event)
        if not self._modifiers_match(flags):
            return event
        if self._key_down:
            return None
        self._key_down = True
        if self._on_activated:
            self._dispatch(self._on_activated, self._build_event(pressed=True))
        return None

    def _handle_key_up(self, event):
        if not self._key_down:
            return event
        self._key_down = False
        if self._on_released:
            self._dispatch(self._on_released, self._build_event(pressed=False))
        return None

    def _dispatch(self, callback, event: HotkeyEvent) -> None:
        """Run a hotkey callback off the Quartz tap thread.

        The callback chain starts recording (opens audio streams, shows
        notifications) — too slow for a realtime event tap. macOS disables
        taps whose callbacks exceed the deadline ('Tap disabled by timeout'
        in the logs), so heavy work must never run inline here.
        """
        def _run():
            try:
                callback(event)
            except Exception as e:
                logger.warning("Hotkey callback error: %s", e)

        threading.Thread(
            target=_run, daemon=True, name="hotkey-dispatch").start()

    def _build_event(self, pressed: bool) -> HotkeyEvent:
        """Build a HotkeyEvent matching src.models.HotkeyEvent exactly.

        Regression seam: an earlier version passed outdated kwargs
        (hotkey=, no pressed=), crashing the tap thread on first press.
        """
        return HotkeyEvent(
            combo=self._hotkey,
            pressed=pressed,
            timestamp_ms=self._get_timestamp_ms(),
        )

    def _modifiers_match(self, flags: int) -> bool:
        required = set()
        for mod in self._hotkey.modifiers:
            m = mod.lower()
            if m in ("ctrl", "control"):
                required.add("ctrl")
            elif m in ("alt", "option"):
                required.add("alt")
            elif m in ("cmd", "command", "win"):
                required.add("cmd")
            elif m == "shift":
                required.add("shift")
        active = {n for n, f in MAC_MODIFIER_FLAGS.items() if flags & f}
        return required == active

    def _get_timestamp_ms(self) -> int:
        return int(time.time() * 1000)


class OutputError(Exception):
    """Raised when text delivery fails."""


class MacOutputHandler:
    """Delivers transcribed text via pbcopy and optional Cmd+V paste."""

    def __init__(self, mode=OutputMode.AUTO_PASTE):
        self._mode = mode

    @property
    def mode(self) -> OutputMode:
        return self._mode

    @mode.setter
    def mode(self, value: OutputMode) -> None:
        self._mode = value

    def deliver(self, text: str) -> None:
        if not text:
            return
        self._set_clipboard(text)
        if self._mode == OutputMode.AUTO_PASTE:
            self._simulate_paste()

    def _set_clipboard(self, text: str) -> None:
        try:
            subprocess.run(
                ["pbcopy"], input=text, text=True,
                check=True, capture_output=True)
            logger.info("Clipboard set via pbcopy: %r", text[:50])
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            raise OutputError(f"Could not set clipboard: {e}") from e

    def _simulate_paste(self) -> None:
        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" '
                 'to keystroke "v" using command down'],
                check=True, capture_output=True, timeout=8)
            logger.info("Simulated Cmd+V paste.")
        except subprocess.TimeoutExpired:
            logger.warning("Paste simulation timed out — text is on the clipboard (Cmd+V).")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.warning("Paste simulation failed: %s — text is on the clipboard (Cmd+V).", e)


ICON_SIZE = 64
STATUS_COLORS = {
    AppStatus.IDLE: (0, 180, 0),
    AppStatus.RECORDING: (220, 30, 30),
    AppStatus.TRANSCRIBING: (255, 165, 0),
    AppStatus.ERROR: (128, 128, 128),
}


class MacSystemTray:
    """Menu bar app via rumps."""

    def __init__(self, title: str = "Whisper VTT"):
        self._title = title
        self._status = AppStatus.IDLE
        self._on_exit = None
        self._app = None

    @property
    def status(self) -> AppStatus:
        return self._status

    def set_on_exit(self, callback) -> None:
        self._on_exit = callback

    def set_status(self, status: AppStatus) -> None:
        self._status = status
        if self._app is not None:
            self._update_icon()

    def show_notification(
        self, title: str, message: str, *, play_sound: bool = True
    ) -> None:
        try:
            esc_title = title.replace('"', '\\"')
            esc_msg = message.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{esc_msg}" '
                 f'with title "{esc_title}"'],
                capture_output=True, timeout=3)
        except Exception as e:
            logger.debug("Notification failed: %s", e)
        if play_sound:
            try:
                subprocess.run(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    capture_output=True, timeout=2)
            except Exception as e:
                logger.debug("Beep failed: %s", e)

    def start(self) -> None:
        # Re-entry guard: rumps NSApplication.run() blocks, and start() is
        # called from AppController.start() (and possibly again from the
        # caller's platform run loop). Never start a second app instance.
        if self._app is not None:
            return
        try:
            import rumps
        except ImportError:
            logger.error("rumps not installed. Menu bar unavailable.")
            return
        icon_path = self._write_icon(self._status)
        tray_ref = self

        class WhisperVTTApp(rumps.App):
            def __init__(app_self, **kwargs):
                super().__init__(**kwargs)
                app_self._tray_ref = tray_ref

            @rumps.clicked("Exit")
            def on_exit(app_self, _):
                if app_self._tray_ref._on_exit:
                    app_self._tray_ref._on_exit()
                rumps.quit_application()

        self._app = WhisperVTTApp(
            name=self._title, title="", icon=icon_path, quit_button=None)
        try:
            self._app.run()
        except Exception as e:
            logger.error("Menu bar error: %s", e)

    def stop(self) -> None:
        try:
            import rumps
            if self._app is not None:
                rumps.quit_application()
        except Exception:
            pass

    def _update_icon(self) -> None:
        if self._app is None:
            return
        path = self._write_icon(self._status)
        self._app.icon = path

    def _write_icon(self, status: AppStatus) -> str:
        import tempfile
        image = self._generate_icon(status)
        path = tempfile.gettempdir() + "/whisper_vtt_icon.png"
        image.save(path, "PNG")
        return path

    @staticmethod
    def _generate_icon(status: AppStatus) -> Image.Image:
        color = STATUS_COLORS.get(status, STATUS_COLORS[AppStatus.IDLE])
        image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        margin = 4
        draw.ellipse(
            [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
            fill=color)
        return image
