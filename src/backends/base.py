"""Protocol definitions for backend implementations.

Each backend (Windows, macOS) implements these interfaces.
The factory in __init__.py picks the right one at import time.
"""

from abc import ABC, abstractmethod
from typing import Callable

from src.models import AppStatus, HotkeyCombo, HotkeyEvent, OutputMode


class HotkeyBackend(ABC):
    """Global hotkey listener -- captures a key combo system-wide."""

    @abstractmethod
    def __init__(self, hotkey: HotkeyCombo): ...

    @abstractmethod
    def set_on_activated(self, callback: Callable[[HotkeyEvent], None]) -> None:
        """Register callback for hotkey press."""

    @abstractmethod
    def set_on_released(self, callback: Callable[[HotkeyEvent], None]) -> None:
        """Register callback for hotkey release."""

    @property
    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def start(self) -> None:
        """Start listening for the hotkey."""

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and clean up resources."""


class OutputBackend(ABC):
    """Delivers transcribed text to the user."""

    @abstractmethod
    def __init__(
        self,
        mode: OutputMode = OutputMode.AUTO_PASTE,
        paste_target: str = "frontmost",
    ): ...

    @property
    @abstractmethod
    def mode(self) -> OutputMode: ...

    @mode.setter
    @abstractmethod
    def mode(self, value: OutputMode) -> None: ...

    @abstractmethod
    def deliver(self, text: str) -> None:
        """Deliver text according to the configured mode."""


class TrayBackend(ABC):
    """System tray / menu bar icon with status indicator."""

    @abstractmethod
    def __init__(self, title: str = "Whisper VTT"): ...

    @property
    @abstractmethod
    def status(self) -> AppStatus: ...

    @abstractmethod
    def set_on_exit(self, callback: Callable[[], None]) -> None:
        """Register callback for exit action."""

    @abstractmethod
    def set_status(self, status: AppStatus) -> None:
        """Update the icon to reflect the new status."""

    @abstractmethod
    def show_notification(
        self, title: str, message: str, *, play_sound: bool = True
    ) -> None:
        """Show a notification with optional sound."""

    @abstractmethod
    def start(self) -> None:
        """Start the tray icon and its event loop."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the tray icon and clean up."""
