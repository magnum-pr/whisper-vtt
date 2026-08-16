"""macOS backend implementations.

Real implementations using:
- Quartz event tap for global hotkey capture + swallow
- pbcopy / osascript for clipboard and paste
- rumps for menu bar app (system tray replacement)
"""

import logging
import re
import subprocess
import threading
import time
from typing import Optional

from PIL import Image, ImageDraw

from src.models import (
    AppStatus,
    HotkeyCombo,
    HotkeyEvent,
    OutputMode,
    SEND_NO_HOST,
    SEND_SKIPPED,
    SEND_SUPPRESSED,
)
from src.output_trigger import extract_no_send_intent, extract_send_intent
from src.pi_state import pi_state_fresh, read_pi_state

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
    """Delivers transcribed text via pbcopy and optional Cmd+V paste.

    paste_target controls where the paste lands:
    - "frontmost" (default): paste into whatever app is focused
    - "pi": auto-resolve the running pi host (VS Code "Code" or
      "Terminal") and activate it first; if pi is already frontmost,
      paste directly without stealing focus
    - an explicit process name (e.g. "Code", "Terminal"): activate that
      process first
    Falls back to a plain frontmost paste when the target can't be
    resolved — the text is always on the clipboard either way.
    """

    def __init__(self, mode=OutputMode.AUTO_PASTE, paste_target: str = "frontmost"):
        self._mode = mode
        self._paste_target = paste_target

    @property
    def mode(self) -> OutputMode:
        return self._mode

    @mode.setter
    def mode(self, value: OutputMode) -> None:
        self._mode = value

    @property
    def paste_target(self) -> str:
        return self._paste_target

    @paste_target.setter
    def paste_target(self, value: str) -> None:
        self._paste_target = value

    def deliver(self, text: str) -> None:
        if not text:
            return

        # Per-dictation override: spoken "without sending" phrases
        # suppress the Enter for this one dictation, in every mode.
        text, suppress_send = extract_no_send_intent(text)
        if not text:
            return  # override phrase alone — nothing to paste

        # protected guard-rail: Enter fires only when the dictation ends
        # with the spoken word 'Enter' (stripped from the text).
        should_send = False
        if self._mode == OutputMode.PROTECTED:
            text, should_send = extract_send_intent(text)
            if not text:
                return  # trigger alone — nothing to paste or send
            if should_send:
                logger.info("Send trigger detected — pressing Enter after paste.")

        self._set_clipboard(text)
        delivered_to = None
        if self._mode in (
            OutputMode.AUTO_PASTE, OutputMode.AUTO_SEND, OutputMode.PROTECTED
        ):
            delivered_to = self._simulate_paste(self._resolve_target())

        if suppress_send:
            # Override wins over every send path — trigger and on-mode alike.
            logger.info("Override: send suppressed for this dictation.")
            return SEND_SUPPRESSED
        if self._mode == OutputMode.AUTO_SEND:
            # on-mode safety net: never fire Enter into a random app when
            # no pi host is running at all (no Code, no pi terminal, no
            # fresh handshake state). With a host present, behavior is
            # unchanged — Enter follows the paste destination.
            if not _pi_host_present():
                logger.warning(
                    "Enter withheld: no pi host running — "
                    "text pasted, not sent.")
                return SEND_NO_HOST
            self._simulate_enter(delivered_to)
            return None
        if should_send:
            # protected Enter guard: only send when pi's window is
            # positively frontmost right now. The title is re-read AFTER
            # the paste so a failed targeted paste (or a focus flip)
            # can't make the Enter land in the wrong app.
            if _is_pi_window(_frontmost_window_title()):
                self._simulate_enter(delivered_to)
            else:
                logger.warning(
                    "Enter withheld: pi's window is not frontmost — "
                    "text pasted, not sent.")
                return SEND_SKIPPED
        return None

    def _set_clipboard(self, text: str) -> None:
        try:
            subprocess.run(
                ["pbcopy"], input=text, text=True,
                check=True, capture_output=True)
            logger.info("Clipboard set via pbcopy: %r", text[:50])
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            raise OutputError(f"Could not set clipboard: {e}") from e

    def _resolve_target(self):
        """Resolve paste_target to a process name to activate.

        Returns None when the paste should go to the frontmost app
        directly (default mode, pi already front, or target missing).
        """
        target = self._paste_target
        if target == "frontmost":
            return None
        front = _frontmost_process_name()
        if target == "pi":
            # Handshake first: a fresh pi-state file with a matching
            # window gives POSITIVE evidence of where pi lives — better
            # than any heuristic below.
            host = _pi_process_from_state()
            if host is not None:
                if front == host and _is_pi_window(
                        _frontmost_window_title()):
                    return None  # pi already front — no focus yank
                return host
            # Legacy heuristics (kept as fallback for stale handshakes):
            # only skip the focus yank on POSITIVE evidence that pi's
            # window is already frontmost. Process names are too coarse:
            # the frontmost Terminal is often whisper's own, not pi's
            # ("whisper" even contains "pi" as a substring — word
            # boundary required).
            if front in PI_HOST_CANDIDATES and _is_pi_window(
                    _frontmost_window_title()):
                return None  # pi already front — no focus yank
            gui = _gui_process_names()
            if "Code" in gui:
                return "Code"
            # Terminal is only a safe target when its pi window is
            # positively identified (handled above). Whisper's own
            # terminal is always in the GUI list, so falling back to
            # "Terminal" here would paste into it.
            return None  # no pi host running — plain paste
        # Explicit process name
        if front == target:
            return None
        gui = _gui_process_names()
        return target if target in gui else None

    def _simulate_paste(self, target: Optional[str]) -> Optional[str]:
        """Paste into the resolved target; falls back to frontmost.

        Returns the process that actually received the paste: the
        target when the targeted script succeeded, None when the
        paste went to the frontmost app (no target, or the targeted
        script failed). Enter must follow this — not the resolved
        target — so a failed targeted paste never yanks focus.
        """
        if target is not None:
            script = (
                'tell application "System Events"\n'
                f'tell process "{target}"\n'
                'set frontmost to true\n'
                'keystroke "v" using command down\n'
                'end tell\n'
                'end tell'
            )
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    check=True, capture_output=True, timeout=8)
                logger.info("Activated %s and simulated Cmd+V paste.", target)
                return target
            except subprocess.TimeoutExpired:
                logger.warning("Targeted paste timed out — falling back to plain paste.")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.warning("Targeted paste failed (%s) — falling back to plain paste.", e)

        # Plain frontmost paste (default + fallback path)
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
        return None

    def _simulate_enter(self, target: Optional[str]) -> None:
        """Press Return where the text was pasted.

        Targets the same process the paste landed in (when known) so
        the send can't land in a different app than the text.
        """
        if target is not None:
            script = (
                'tell application "System Events"\n'
                f'tell process "{target}"\n'
                'set frontmost to true\n'
                'keystroke return\n'
                'end tell\n'
                'end tell'
            )
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    check=True, capture_output=True, timeout=8)
                logger.info("Simulated Return key in %s.", target)
                return
            except subprocess.TimeoutExpired:
                logger.warning("Targeted Enter timed out — falling back to frontmost.")
            except (subprocess.SubprocessError, FileNotFoundError) as e:
                logger.warning("Targeted Enter failed (%s) — falling back to frontmost.", e)

        try:
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" '
                 'to keystroke return'],
                check=True, capture_output=True, timeout=8)
            logger.info("Simulated Return key.")
        except subprocess.TimeoutExpired:
            logger.warning("Enter simulation timed out.")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.warning("Enter simulation failed: %s", e)


ICON_SIZE = 64
STATUS_COLORS = {
    AppStatus.IDLE: (0, 180, 0),
    AppStatus.RECORDING: (220, 30, 30),
    AppStatus.TRANSCRIBING: (255, 165, 0),
    AppStatus.ERROR: (128, 128, 128),
}


# Pi host apps, in preference order (VS Code reports as "Code").
PI_HOST_CANDIDATES = ("Code", "Terminal")

# Word-boundary match so "whisper" (contains "pi") is not mistaken for pi.
PI_TITLE_RE = re.compile(r"\bpi\b", re.IGNORECASE)


def _is_pi_window(title: str) -> bool:
    """True when a window title positively identifies pi's window."""
    return bool(title) and bool(PI_TITLE_RE.search(title))


def _window_titles(process: str) -> list[str]:
    """Window titles of a GUI process, or [] on failure."""
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every '
             f'window of process "{process}"'],
            capture_output=True, text=True, timeout=8)
        return [t.strip() for t in out.stdout.split(",") if t.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def _pi_process_from_state() -> Optional[str]:
    """Resolve pi's host process from the handshake state file.

    Returns the process name when a fresh handshake exists AND its
    recorded window title fragment matches an open window of a known
    pi host app. Returns None when the handshake is stale, missing, or
    its window can't be found — callers fall back to legacy heuristics.
    """
    state = read_pi_state()
    if not state or not pi_state_fresh(state):
        return None
    fragment = (state.get("window_title_fragment") or "").strip()
    host = (state.get("host_app") or "").strip()
    candidates = [host] if host else ["Code", "Terminal", "iTerm2"]
    for process in candidates:
        titles = _window_titles(process)
        if not fragment:
            # No title recorded — weak positive: the app named in the
            # handshake has at least one window open.
            if titles:
                return process
            continue
        if any(fragment.lower() in title.lower() for title in titles):
            return process
    return None


def _pi_host_present() -> bool:
    """True when a pi host plausibly exists on this machine.

    Positive evidence, strongest first:
    1. A fresh handshake state file (pi wrote it recently).
    2. VS Code is running — pi's usual home.
    3. A terminal window with a pi-identifying title is open.

    Used by the on-mode safety net to withhold Enter when NO pi host
    exists, so auto_send never fires Enter into a random app.
    """
    if pi_state_fresh():
        return True
    gui = _gui_process_names()
    if "Code" in gui:
        return True
    for process in ("Terminal", "iTerm2"):
        if process in gui and any(
            _is_pi_window(title) for title in _window_titles(process)
        ):
            return True
    return False


def _frontmost_window_title() -> str:
    """Title of the frontmost GUI window, or '' on failure."""
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" '
             'to get name of front window of first application process '
             'whose frontmost is true'],
            capture_output=True, text=True, timeout=8)
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _frontmost_process_name() -> str:
    """Name of the frontmost GUI process, or '' on failure."""
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first '
             'application process whose frontmost is true'],
            capture_output=True, text=True, timeout=8)
        return out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return ""


def _gui_process_names() -> list[str]:
    """Names of all GUI (non-background) processes, or [] on failure."""
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of every '
             'application process whose background only is false'],
            capture_output=True, text=True, timeout=8)
        return [n.strip() for n in out.stdout.split(",") if n.strip()]
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


class MacSystemTray:
    """Menu bar app via rumps."""

    def __init__(self, title: str = "Whisper VTT"):
        self._title = title
        self._status = AppStatus.IDLE
        self._session_text: Optional[str] = ""
        self._on_exit = None
        self._app = None
        # Mic-level menu item + silent-mic watchdog state (wired in start()).
        self._mic_item = None
        self._silent_alerted = False

    @property
    def status(self) -> AppStatus:
        return self._status

    def set_on_exit(self, callback) -> None:
        self._on_exit = callback

    def set_status(self, status: AppStatus) -> None:
        self._status = status
        if self._app is not None:
            self._update_icon()

    def set_session_indicator(self, text: Optional[str]) -> None:
        """Show session state in the menu bar (item count or armed dot),
        or '' to clear. rumps renders app.title next to the icon."""
        self._session_text = text or ""
        if self._app is not None:
            self._app.title = self._session_text

    def show_notification(
        self,
        title: str,
        message: str,
        *,
        play_sound: bool = True,
        sound: Optional[str] = None,
        notify: bool = True,
    ) -> None:
        if notify:
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
                path = sound or "/System/Library/Sounds/Glass.aiff"
                subprocess.run(
                    ["afplay", path],
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

        # Mic-level menu item (updated by the meter timer below) + Exit.
        self._mic_item = rumps.MenuItem("Mic: —")
        exit_item = rumps.MenuItem(
            "Exit",
            callback=lambda _: (
                tray_ref._on_exit() if tray_ref._on_exit else None,
                rumps.quit_application(),
            ),
        )

        self._app = WhisperVTTApp(
            name=self._title,
            title="",
            icon=icon_path,
            menu=[self._mic_item, None, exit_item],
            quit_button=None,
        )
        self._meter_timer = rumps.Timer(self._update_meter, 1.0)
        self._meter_timer.start()
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

    def _update_meter(self, _) -> None:
        """Refresh the mic-level menu item + fire the silent-mic alert.

        Reads the shared LevelMeter published by whichever stream owns
        the mic (wake word listener while idle, recorder while dictating)
        — no extra audio streams, no device contention.
        """
        from src.level_meter import GLOBAL_METER, LevelMeter

        if self._mic_item is not None:
            db = GLOBAL_METER.level_db()
            if db == float("-inf"):
                self._mic_item.title = "Mic: no signal"
            else:
                self._mic_item.title = (
                    f"Mic: {LevelMeter.level_bar(db)} ({db:.0f} dB)"
                )

        if GLOBAL_METER.silent_too_long and not self._silent_alerted:
            self._silent_alerted = True
            self.show_notification(
                "Whisper VTT",
                "Microphone appears silent — check "
                "System Settings → Sound → Input.",
                play_sound=False,
            )
        elif not GLOBAL_METER.silent_too_long:
            self._silent_alerted = False

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
