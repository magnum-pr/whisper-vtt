"""Windows backend implementations -- hotkey, output, system tray.

Consolidates the original Windows-only code from:
- src/hotkey_listener.py -> WindowsHotkeyListener
- src/output_handler.py   -> WindowsOutputHandler
- src/system_tray.py       -> WindowsSystemTray

Exports:
- WindowsHotkeyListener, KEY_NAME_TO_VK
- WindowsOutputHandler, OutputError
- WindowsSystemTray, STATUS_COLORS
"""

"""Global hotkey listener via Windows low-level keyboard hook."""

import ctypes
import logging
import threading
from ctypes import wintypes
from typing import Callable, Optional, Set

from src.models import HotkeyCombo, HotkeyEvent

logger = logging.getLogger(__name__)

# Windows API constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# Virtual key code lookup
KEY_NAME_TO_VK: dict[str, int] = {
    # Letters (lowercase)
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
    # Numbers
    **{str(i): 0x30 + i for i in range(10)},
    # Function keys
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
    # Special keys
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "space": 0x20,
    "tab": 0x09,
    "return": 0x0D,
    "enter": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "printscreen": 0x2C,
    "pause": 0x13,
}

# Modifier virtual key codes
MODIFIER_VK: dict[str, int] = {
    "ctrl": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
}

# Reverse lookup: VK → modifier name
VK_TO_MODIFIER: dict[int, str] = {v: k for k, v in MODIFIER_VK.items()}


class WindowsHotkeyListener:
    """Detects a global keyboard shortcut via Windows low-level hook.

    Installs WH_KEYBOARD_LL hook on a dedicated thread with its own
    message pump. Tracks modifier state and fires callbacks for
    hotkey activation/release.
    """

    def __init__(self, hotkey: HotkeyCombo):
        self._hotkey = hotkey
        self._target_vk = KEY_NAME_TO_VK.get(hotkey.key.lower())
        if self._target_vk is None:
            raise ValueError(f"Unknown key name: {hotkey.key}")

        self._pressed_modifiers: Set[str] = set()
        self._hotkey_pressed: bool = False

        self._on_activated: Optional[Callable[[HotkeyEvent], None]] = None
        self._on_released: Optional[Callable[[HotkeyEvent], None]] = None

        self._thread: Optional[threading.Thread] = None
        self._hook_id: Optional[int] = None
        self._running: bool = False
        self._lock = threading.Lock()

        # Keep references to prevent GC of callbacks
        self._hook_proc = None

        # Windows module handles for ctypes
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32

        # Declare CallNextHookEx argtypes — on x64, LPARAM/WPARAM are
        # 8-byte values that overflow ctypes' default c_int (4 bytes).
        self._user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.CallNextHookEx.restype = wintypes.LPARAM

    # ── Callback registration ──────────────────────────────────────────

    def set_on_activated(self, callback: Callable[[HotkeyEvent], None]) -> None:
        """Set callback for hotkey activation (key press matching combo)."""
        self._on_activated = callback

    def set_on_released(self, callback: Callable[[HotkeyEvent], None]) -> None:
        """Set callback for hotkey release (key release matching combo)."""
        self._on_released = callback

    # ── Thread management ──────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start the hotkey listener on a daemon thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._message_pump,
            daemon=True,
            name="hotkey-listener",
        )
        self._thread.start()
        logger.info("Hotkey listener started: %s", self._hotkey)

    def stop(self) -> None:
        """Stop the hotkey listener and unhook."""
        self._running = False

        # Unhook from the Windows hook chain
        with self._lock:
            if self._hook_id is not None:
                self._user32.UnhookWindowsHookEx(self._hook_id)
                self._hook_id = None

        # Post a quit message to wake up GetMessage
        if self._thread and self._thread.is_alive():
            self._user32.PostThreadMessageW(
                self._thread.ident, 0x0012, 0, 0  # WM_QUIT
            )

        logger.info("Hotkey listener stopped.")

    # ── Message pump (runs on dedicated thread) ────────────────────────

    def _message_pump(self) -> None:
        """Windows message pump for the hook thread."""
        # Define the hook callback type
        # Windows LRESULT is LONG_PTR (8 bytes on x64), not LONG (4 bytes).
        # Using ctypes.c_long on 64-bit causes stack corruption and
        # SetWindowsHookExW returns NULL.
        HOOKPROC = ctypes.WINFUNCTYPE(
            wintypes.LPARAM,  # LRESULT = LONG_PTR
            ctypes.c_int,     # nCode
            wintypes.WPARAM,  # wParam
            wintypes.LPARAM,  # lParam
        )

        # Store reference to prevent GC
        self._hook_proc = HOOKPROC(self._low_level_keyboard_proc)

        # Install the hook
        # WH_KEYBOARD_LL requires hMod = NULL (0), not a module handle.
        # Passing GetModuleHandleW(None) returns non-NULL in PyInstaller
        # bundles, causing SetWindowsHookExW to fail.
        with self._lock:
            self._hook_id = self._user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                self._hook_proc,
                0,  # hMod must be NULL for WH_KEYBOARD_LL
                0,  # dwThreadId = 0 for global hook
            )

        if not self._hook_id:
            logger.error("Failed to install keyboard hook.")
            self._running = False
            return

        # Message loop
        msg = wintypes.MSG()
        while self._running:
            ret = self._user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            )
            if ret in (0, -1):
                break
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

        # Cleanup
        with self._lock:
            if self._hook_id is not None:
                self._user32.UnhookWindowsHookEx(self._hook_id)
                self._hook_id = None

    # ── Low-level keyboard hook callback ───────────────────────────────

    def _low_level_keyboard_proc(
        self, n_code: int, w_param: int, l_param: int
    ) -> int:
        """Windows low-level keyboard hook callback.

        Called by the OS on every key event system-wide.
        Returns 1 to suppress the key, or calls CallNextHookEx.
        """
        if n_code < 0:
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        vk_code = ctypes.cast(l_param, ctypes.POINTER(ctypes.c_ulong))[0]

        is_key_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_key_up = w_param in (WM_KEYUP, WM_SYSKEYUP)

        # Track modifier state
        if vk_code in VK_TO_MODIFIER:
            mod_name = VK_TO_MODIFIER[vk_code]
            if is_key_down:
                self._pressed_modifiers.add(mod_name)
            elif is_key_up:
                self._pressed_modifiers.discard(mod_name)
            # Never suppress modifier keys
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        # Check if this is our target key
        if vk_code == self._target_vk:
            if is_key_down:
                return self._handle_key_down(n_code, w_param, l_param)
            elif is_key_up:
                return self._handle_key_up(n_code, w_param, l_param)

        # Not our key — pass through
        return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _handle_key_down(self, n_code: int, w_param: int, l_param: int) -> int:
        """Handle a key-down event for the target key."""
        if not self._modifiers_match():
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._hotkey_pressed = True

        event = HotkeyEvent(
            combo=self._hotkey,
            pressed=True,
            timestamp_ms=self._get_timestamp_ms(),
        )

        if self._on_activated:
            try:
                self._on_activated(event)
            except Exception as e:
                logger.warning("on_activated callback error: %s", e)

        # Suppress the keypress so it doesn't reach the focused app
        return 1

    def _handle_key_up(self, n_code: int, w_param: int, l_param: int) -> int:
        """Handle a key-up event for the target key."""
        if not self._hotkey_pressed:
            self._hotkey_pressed = False
            # Don't suppress key-up — OS needs it for correct key state
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._hotkey_pressed = False

        event = HotkeyEvent(
            combo=self._hotkey,
            pressed=False,
            timestamp_ms=self._get_timestamp_ms(),
        )

        if self._on_released:
            try:
                self._on_released(event)
            except Exception as e:
                logger.warning("on_released callback error: %s", e)

        # Key-up is NOT suppressed — OS tracks key state
        return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _modifiers_match(self) -> bool:
        """Check if currently held modifiers match the configured combo exactly."""
        return self._pressed_modifiers == set(self._hotkey.modifiers)

    def _get_timestamp_ms(self) -> int:
        """Get current time in milliseconds since epoch."""
        import time
        return int(time.time() * 1000)


"""Output handler — delivers transcribed text via clipboard."""

import logging
import subprocess

from src.models import OutputMode
from src.output_trigger import extract_send_intent

logger = logging.getLogger(__name__)


class OutputError(Exception):
    """Raised when text delivery fails."""


class WindowsOutputHandler:
    """Delivers transcribed text to the user.

    Two modes:
    - AUTO_PASTE: Sets clipboard, then tries to simulate Ctrl+V via
      SendInput (VDI environments often block this, so it falls back
      to clipboard-only).
    - CLIPBOARD: Sets clipboard text for manual paste by the user.
    """

    def __init__(
        self, mode: OutputMode = OutputMode.AUTO_PASTE, paste_target: str = "frontmost"
    ):
        self._mode = mode
        # paste_target is a macOS concept (app activation). On Windows the
        # paste always goes to the focused app; accept + ignore the value.
        self._paste_target = paste_target

    @property
    def mode(self) -> OutputMode:
        return self._mode

    @mode.setter
    def mode(self, value: OutputMode) -> None:
        self._mode = value

    def deliver(self, text: str) -> None:
        """Deliver transcribed text according to the configured mode.

        Args:
            text: The transcribed text to deliver.

        Raises:
            OutputError: If clipboard access fails and fallback also fails.
        """
        if not text:
            return

        # auto_send guard-rail: Enter fires only when the dictation ends
        # with the spoken word 'Enter' (stripped from the text).
        should_send = False
        if self._mode == OutputMode.AUTO_SEND:
            text, should_send = extract_send_intent(text)
            if not text:
                return  # trigger alone — nothing to paste or send
            if should_send:
                logger.info("Send trigger detected — pressing Enter after paste.")

        # Set clipboard — this always happens regardless of mode
        self._set_clipboard(text)

        if self._mode in (OutputMode.AUTO_PASTE, OutputMode.AUTO_SEND):
            self._simulate_paste()
        if should_send:
            self._simulate_enter()

    def _set_clipboard(self, text: str) -> None:
        """Set the Windows clipboard to the given text.

        Tries win32clipboard first, falls back to clip.exe subprocess.
        """
        # Strategy 1: win32clipboard
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text)
                logger.info("Clipboard set via win32clipboard: %r", text[:50])
                return
            finally:
                win32clipboard.CloseClipboard()
        except ImportError:
            logger.debug("pywin32 not available, trying clip.exe fallback.")
        except Exception as e:
            logger.warning("win32clipboard failed: %s. Trying clip.exe fallback.", e)

        # Strategy 2: clip.exe subprocess
        try:
            subprocess.run(
                ["clip.exe"],
                input=text,
                text=True,
                check=True,
                capture_output=True,
            )
            logger.info("Clipboard set via clip.exe: %r", text[:50])
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            raise OutputError(
                f"Could not set clipboard: {e}"
            ) from e

    def _simulate_paste(self) -> None:
        """Attempt to simulate Ctrl+V via SendInput.

        In many VDI environments, SendInput is blocked. If it fails,
        we silently fall back — the text is already on the clipboard.
        """
        try:
            import win32com.client

            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys("^v")
            logger.info("Simulated Ctrl+V paste.")
        except ImportError:
            logger.debug("win32com not available — paste simulation skipped.")
        except Exception as e:
            # VDI environments often block this — not an error
            logger.debug("SendInput paste blocked or unavailable: %s", e)

    def _simulate_enter(self) -> None:
        """Press Enter in the frontmost app (sends the message)."""
        try:
            import win32com.client

            shell = win32com.client.Dispatch("WScript.Shell")
            shell.SendKeys("{ENTER}")
            logger.info("Simulated Enter key.")
        except ImportError:
            logger.debug("win32com not available — enter simulation skipped.")
        except Exception as e:
            logger.debug("SendInput enter blocked or unavailable: %s", e)


"""System tray icon and notifications."""

import logging
import threading
from typing import Callable, Optional

from PIL import Image, ImageDraw

from src.models import AppStatus

logger = logging.getLogger(__name__)

# Icon sizes and colors
ICON_SIZE = 64
STATUS_COLORS = {
    AppStatus.IDLE: (0, 180, 0),         # Green
    AppStatus.RECORDING: (220, 30, 30),   # Red
    AppStatus.TRANSCRIBING: (255, 165, 0), # Orange
    AppStatus.ERROR: (128, 128, 128),     # Gray
}


class WindowsSystemTray:
    """System tray icon with status indicator and exit menu.

    Uses pystray with Pillow-generated colored circle icons.
    Runs on its own daemon thread.
    """

    def __init__(self, title: str = "Whisper VTT"):
        self._title = title
        self._status: AppStatus = AppStatus.IDLE
        self._tray_icon: Optional[object] = None
        self._on_exit: Optional[Callable[[], None]] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def status(self) -> AppStatus:
        return self._status

    def set_on_exit(self, callback: Callable[[], None]) -> None:
        """Set callback invoked when user clicks Exit."""
        self._on_exit = callback

    def set_status(self, status: AppStatus) -> None:
        """Update the tray icon to reflect the new status."""
        self._status = status
        if self._tray_icon is not None:
            self._tray_icon.icon = self._generate_icon(status)

    def show_notification(self, title: str, message: str, *, play_sound: bool = True) -> None:
        """Show a balloon notification with an optional system beep."""
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(message, title)
            except Exception as e:
                logger.warning("Failed to show notification: %s", e)
        if play_sound:
            try:
                import winsound
                winsound.MessageBeep()
            except Exception as e:
                logger.debug("System beep failed: %s", e)

    def start(self) -> None:
        """Start the system tray on a daemon thread."""

        self._thread = threading.Thread(
            target=self._run_tray,
            daemon=True,
            name="system-tray",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the system tray icon."""
        if self._tray_icon is not None:
            self._tray_icon.stop()

    def _run_tray(self) -> None:
        """Run the pystray event loop (blocking on this thread)."""
        import pystray

        icon = self._generate_icon(self._status)
        menu = pystray.Menu(
            pystray.MenuItem("Exit", self._on_exit_clicked),
        )

        self._tray_icon = pystray.Icon(
            name=self._title,
            title=self._title,
            icon=icon,
            menu=menu,
        )

        try:
            self._tray_icon.run()
        except Exception as e:
            logger.error("System tray error: %s", e)

    def _on_exit_clicked(self, icon, item) -> None:
        """Handle Exit menu click."""
        if self._on_exit:
            self._on_exit()
        if self._tray_icon:
            self._tray_icon.stop()

    @staticmethod
    def _generate_icon(status: AppStatus) -> Image.Image:
        """Generate a colored circle icon for the given status."""
        color = STATUS_COLORS.get(status, STATUS_COLORS[AppStatus.IDLE])
        image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Draw filled circle
        margin = 4
        draw.ellipse(
            [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
            fill=color,
        )

        return image
