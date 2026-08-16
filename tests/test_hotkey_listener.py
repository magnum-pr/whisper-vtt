"""Tests for HotkeyListener (logic tests, no Windows hook)."""


import sys
import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)


from src.backends import KEY_NAME_TO_VK, HotkeyListener
from src.models import HotkeyCombo


class TestKeyNameToVk:
    def test_letters(self):
        assert KEY_NAME_TO_VK["a"] == 0x41
        assert KEY_NAME_TO_VK["z"] == 0x5A

    def test_numbers(self):
        assert KEY_NAME_TO_VK["0"] == 0x30
        assert KEY_NAME_TO_VK["9"] == 0x39

    def test_function_keys(self):
        assert KEY_NAME_TO_VK["f1"] == 0x70
        assert KEY_NAME_TO_VK["f12"] == 0x7B

    def test_special_keys(self):
        assert KEY_NAME_TO_VK["`"] == 0xC0
        assert KEY_NAME_TO_VK["space"] == 0x20
        assert KEY_NAME_TO_VK["escape"] == 0x1B


class TestHotkeyListenerInit:
    def test_valid_combo(self):
        combo = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="space")
        listener = HotkeyListener(combo)
        assert listener._target_vk == 0x20

    def test_unknown_key_raises(self):
        import pytest
        combo = HotkeyCombo(modifiers=frozenset(), key="nonexistent_key")
        with pytest.raises(ValueError, match="Unknown key"):
            HotkeyListener(combo)


class TestModifierTracking:
    def setup_method(self):
        self.combo = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="a")
        self.listener = HotkeyListener(self.combo)

    def test_modifiers_match_exact(self):
        self.listener._pressed_modifiers = {"ctrl"}
        assert self.listener._modifiers_match()

    def test_modifiers_match_extra(self):
        """Extra modifier held → no match (exact matching)."""
        self.listener._pressed_modifiers = {"ctrl", "shift"}
        assert not self.listener._modifiers_match()

    def test_modifiers_match_missing(self):
        self.listener._pressed_modifiers = set()
        assert not self.listener._modifiers_match()

    def test_no_modifiers_combo(self):
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        listener._pressed_modifiers = set()
        assert listener._modifiers_match()

    def test_no_modifiers_combo_with_extra(self):
        """No modifiers configured, but ctrl held → no match."""
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        listener._pressed_modifiers = {"ctrl"}
        assert not listener._modifiers_match()


class TestCallbackRegistration:
    def test_activated_callback(self):
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        called = []

        listener.set_on_activated(lambda e: called.append(e))
        assert listener._on_activated is not None

    def test_released_callback(self):
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        called = []

        listener.set_on_released(lambda e: called.append(e))
        assert listener._on_released is not None


class TestHandleKeyDown:
    def test_activated_callback_fires(self):
        combo = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="space")
        listener = HotkeyListener(combo)
        listener._pressed_modifiers = {"ctrl"}

        events = []
        listener.set_on_activated(lambda e: events.append(e))

        result = listener._handle_key_down(0, 0x0100, 0)
        assert result == 1  # suppressed
        assert len(events) == 1
        assert events[0].pressed is True
        assert events[0].combo == combo

    def test_activated_callback_error_handled(self):
        """If callback raises, it shouldn't crash the hook."""
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        listener._pressed_modifiers = set()

        def bad_callback(event):
            raise RuntimeError("boom")

        listener.set_on_activated(bad_callback)

        # Should not raise
        result = listener._handle_key_down(0, 0x0100, 0)
        assert result == 1  # still suppressed

    def test_mismatched_modifiers_pass_through(self):
        combo = HotkeyCombo(modifiers=frozenset({"ctrl"}), key="space")
        listener = HotkeyListener(combo)
        listener._pressed_modifiers = set()  # no ctrl held

        result = listener._handle_key_down(0, 0x0100, 0)
        assert result != 1  # should call CallNextHookEx (would be 0 with mock)


class TestHandleKeyUp:
    def test_released_callback_fires(self):
        combo = HotkeyCombo(modifiers=frozenset(), key="`")
        listener = HotkeyListener(combo)
        listener._hotkey_pressed = True
        listener._pressed_modifiers = set()

        events = []
        listener.set_on_released(lambda e: events.append(e))

        listener._handle_key_up(0, 0x0101, 0)
        assert len(events) == 1
        assert events[0].pressed is False
        assert events[0].combo == combo
