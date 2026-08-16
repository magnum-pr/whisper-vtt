"""Tests for SystemTray (icon generation and status logic)."""


import sys
import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

from src.models import AppStatus
from src.backends import STATUS_COLORS, SystemTray


class TestGenerateIcon:
    def test_idle_icon_is_green(self):
        icon = SystemTray._generate_icon(AppStatus.IDLE)
        assert icon.size == (64, 64)
        assert icon.mode == "RGBA"

        # Check center pixel is green
        r, g, b, a = icon.getpixel((32, 32))
        assert (r, g, b) == STATUS_COLORS[AppStatus.IDLE]
        assert a == 255

    def test_recording_icon_is_red(self):
        icon = SystemTray._generate_icon(AppStatus.RECORDING)
        r, g, b, a = icon.getpixel((32, 32))
        assert (r, g, b) == STATUS_COLORS[AppStatus.RECORDING]

    def test_transcribing_icon_is_orange(self):
        icon = SystemTray._generate_icon(AppStatus.TRANSCRIBING)
        r, g, b, a = icon.getpixel((32, 32))
        assert (r, g, b) == STATUS_COLORS[AppStatus.TRANSCRIBING]

    def test_error_icon_is_gray(self):
        icon = SystemTray._generate_icon(AppStatus.ERROR)
        r, g, b, a = icon.getpixel((32, 32))
        assert (r, g, b) == STATUS_COLORS[AppStatus.ERROR]

    def test_icon_corners_are_transparent(self):
        """Circle icon — corners should be transparent."""
        icon = SystemTray._generate_icon(AppStatus.IDLE)
        # Top-left corner
        assert icon.getpixel((0, 0))[3] == 0
        # Top-right corner
        assert icon.getpixel((63, 0))[3] == 0
        # Bottom-left corner
        assert icon.getpixel((0, 63))[3] == 0
        # Bottom-right corner
        assert icon.getpixel((63, 63))[3] == 0


class TestSystemTrayStatus:
    def test_initial_status_is_idle(self):
        tray = SystemTray()
        assert tray.status == AppStatus.IDLE

    def test_set_status_updates(self):
        tray = SystemTray()
        tray.set_status(AppStatus.RECORDING)
        assert tray.status == AppStatus.RECORDING

    def test_set_status_without_icon_running(self):
        """set_status should work even when tray icon isn't running yet."""
        tray = SystemTray()
        tray.set_status(AppStatus.ERROR)
        assert tray.status == AppStatus.ERROR
        assert tray._tray_icon is None  # didn't crash


class TestSystemTrayCallbacks:
    def test_on_exit_callback(self):
        tray = SystemTray()
        called = []

        tray.set_on_exit(lambda: called.append(True))
        tray._on_exit_clicked(None, None)
        assert len(called) == 1

    def test_on_exit_stops_icon(self):
        tray = SystemTray()
        called = []

        tray.set_on_exit(lambda: called.append(True))

        # Simulate icon object
        class FakeIcon:
            def __init__(self):
                self.stopped = False
            def stop(self):
                self.stopped = True

        fake_icon = FakeIcon()
        tray._tray_icon = fake_icon
        tray._on_exit_clicked(None, None)

        assert fake_icon.stopped
        assert len(called) == 1


class TestShowNotification:
    def test_notification_no_crash_without_icon(self):
        """show_notification should not crash when tray icon isn't running."""
        tray = SystemTray()
        # No tray_icon set — should be a no-op, not a crash
        tray.show_notification("Test", "Hello")

    def test_notification_no_sound_no_crash(self):
        """play_sound=False should not crash even without tray icon."""
        tray = SystemTray()
        tray.show_notification("Test", "Hello", play_sound=False)


class TestStatusColors:
    def test_all_statuses_have_colors(self):
        for status in AppStatus:
            assert status in STATUS_COLORS, f"Missing color for {status}"


class TestSessionIndicator:
    def test_indicator_stored_and_cleared(self):
        from src.backends.macos import MacSystemTray

        tray = MacSystemTray()
        tray.set_session_indicator("●")
        assert tray._session_text == "●"
        tray.set_session_indicator("3")
        assert tray._session_text == "3"
        tray.set_session_indicator("")
        assert tray._session_text == ""
