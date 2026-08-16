"""Tests for OutputHandler."""


import sys
import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

from unittest.mock import MagicMock, patch

import pytest

from src.models import OutputMode
from src.backends import OutputError, OutputHandler


class TestOutputHandlerInit:
    def test_default_mode(self):
        handler = OutputHandler()
        assert handler.mode == OutputMode.AUTO_PASTE

    def test_clipboard_mode(self):
        handler = OutputHandler(OutputMode.CLIPBOARD)
        assert handler.mode == OutputMode.CLIPBOARD

    def test_mode_setter(self):
        handler = OutputHandler()
        handler.mode = OutputMode.CLIPBOARD
        assert handler.mode == OutputMode.CLIPBOARD


class TestDeliver:
    def test_empty_text_noop(self):
        handler = OutputHandler()
        # Should not raise or do anything
        handler.deliver("")

    def test_deliver_sets_clipboard(self):
        handler = OutputHandler(OutputMode.CLIPBOARD)

        mock_clipboard = MagicMock()
        with patch.dict("sys.modules", {"win32clipboard": mock_clipboard}):
            handler.deliver("hello world")

        mock_clipboard.OpenClipboard.assert_called_once()
        mock_clipboard.EmptyClipboard.assert_called_once()
        mock_clipboard.SetClipboardText.assert_called_once_with("hello world")
        mock_clipboard.CloseClipboard.assert_called_once()

    def test_deliver_auto_paste_calls_paste(self):
        handler = OutputHandler(OutputMode.AUTO_PASTE)

        mock_clipboard = MagicMock()
        mock_shell = MagicMock()
        mock_win32com = MagicMock()
        mock_win32com.client.Dispatch.return_value = mock_shell

        modules = {
            "win32clipboard": mock_clipboard,
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
        }
        with patch.dict("sys.modules", modules):
            handler.deliver("hello")

        mock_shell.SendKeys.assert_called_once_with("^v")

    def test_deliver_win32clipboard_import_error_falls_back_to_clip_exe(self):
        handler = OutputHandler(OutputMode.CLIPBOARD)

        # Simulate win32clipboard not installed, but clip.exe exists
        with (
            patch.dict("sys.modules", {"win32clipboard": None}),
            patch("subprocess.run") as mock_run,
        ):
            handler.deliver("fallback text")

        mock_run.assert_called_once()
        assert mock_run.call_args[1]["input"] == "fallback text"
        assert mock_run.call_args[0][0] == ["clip.exe"]

    def test_deliver_both_fail(self):
        handler = OutputHandler(OutputMode.CLIPBOARD)

        with (
            patch.dict("sys.modules", {"win32clipboard": None}),
            patch("subprocess.run", side_effect=FileNotFoundError("clip.exe not found")),
        ):
            with pytest.raises(OutputError, match="Could not set clipboard"):
                handler.deliver("text")

    def test_deliver_win32clipboard_exception_falls_back(self):
        handler = OutputHandler(OutputMode.CLIPBOARD)

        mock_clipboard = MagicMock()
        mock_clipboard.OpenClipboard.side_effect = RuntimeError("clipboard busy")

        with patch.dict("sys.modules", {"win32clipboard": mock_clipboard}):
            with patch("subprocess.run") as mock_run:
                handler.deliver("fallback")

        mock_run.assert_called_once()

    def test_paste_blocked_silently_falls_back(self):
        """If SendInput is blocked, it should not raise — text is already on clipboard."""
        handler = OutputHandler(OutputMode.AUTO_PASTE)

        mock_clipboard = MagicMock()
        mock_shell = MagicMock()
        mock_shell.SendKeys.side_effect = RuntimeError("blocked")
        mock_win32com = MagicMock()
        mock_win32com.client.Dispatch.return_value = mock_shell

        modules = {
            "win32clipboard": mock_clipboard,
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
        }
        with patch.dict("sys.modules", modules):
            handler.deliver("hello")  # should not raise

        # Clipboard was still set
        mock_clipboard.SetClipboardText.assert_called_once_with("hello")
