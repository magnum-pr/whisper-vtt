"""Regression tests for the macOS hotkey backend's event construction.

The live Quartz event tap can't run in unit tests, so the event-building
seam is tested directly. Guards the exact bug where HotkeyEvent was built
with outdated kwargs (hotkey=, no pressed=), which crashed the tap thread
on the first physical keypress and killed the hotkey listener.
"""

from src.backends.macos import MacHotkeyListener
from src.models import HotkeyCombo, HotkeyEvent


def _make_listener(key="`"):
    return MacHotkeyListener(HotkeyCombo(modifiers=frozenset(), key=key))


def test_build_event_activated_shape():
    listener = _make_listener()
    event = listener._build_event(pressed=True)
    assert isinstance(event, HotkeyEvent)
    assert event.combo == listener._hotkey
    assert event.pressed is True
    assert isinstance(event.timestamp_ms, int) and event.timestamp_ms > 0


def test_build_event_released_shape():
    listener = _make_listener()
    event = listener._build_event(pressed=False)
    assert isinstance(event, HotkeyEvent)
    assert event.combo == listener._hotkey
    assert event.pressed is False
    assert isinstance(event.timestamp_ms, int)
