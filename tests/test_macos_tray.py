"""macOS-specific tray behavior: session indicator + icon colors."""

from src.backends.macos import MacSystemTray
from src.models import AppStatus


class TestSessionIndicator:
    def test_indicator_stored_and_cleared(self):
        tray = MacSystemTray()
        tray.set_session_indicator("●")
        assert tray._session_text == "●"
        tray.set_session_indicator("3")
        assert tray._session_text == "3"
        tray.set_session_indicator("")
        assert tray._session_text == ""


class TestSessionIconColor:
    def test_idle_color_when_not_armed(self):
        tray = MacSystemTray()
        tray._status = AppStatus.IDLE
        assert tray._current_icon_color() == (0, 180, 0)

    def test_blue_when_armed(self):
        tray = MacSystemTray()
        tray.set_session_indicator("●")
        assert tray._current_icon_color() == (0, 122, 255)

    def test_recording_color_preserved_when_not_armed(self):
        tray = MacSystemTray()
        tray._status = AppStatus.RECORDING
        assert tray._current_icon_color() == (220, 30, 30)


class TestArmedIcon:
    def test_session_icon_generated_blue(self):
        tray = MacSystemTray()
        tray.set_session_indicator("●")
        path = tray._write_icon(AppStatus.IDLE)
        from PIL import Image
        img = Image.open(path)
        px = img.getpixel((32, 32))
        # RGBA — blue center
        assert px[2] > 200 and px[0] < 100
