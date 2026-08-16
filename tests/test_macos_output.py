"""Tests for MacOutputHandler delivery modes (pbcopy + osascript).

Verifies the mode matrix on macOS:
- CLIPBOARD  → copies only, no paste, no enter
- AUTO_PASTE → copies + pastes, no enter
- AUTO_SEND  → copies + pastes + presses Enter
"""

from unittest.mock import patch

from src.backends.macos import MacOutputHandler
from src.models import OutputMode


def _osascript_scripts(mock_run):
    """Extract the AppleScript text of every osascript invocation."""
    return [
        call_args.args[0][-1]
        for call_args in mock_run.call_args_list
        if call_args.args and call_args.args[0][0] == "osascript"
    ]


@patch("src.backends.macos.subprocess.run")
def test_clipboard_mode_copies_only(mock_run):
    handler = MacOutputHandler(mode=OutputMode.CLIPBOARD)
    handler.deliver("hello")
    assert not _osascript_scripts(mock_run)


@patch("src.backends.macos.subprocess.run")
def test_auto_paste_pastes_without_enter(mock_run):
    handler = MacOutputHandler(mode=OutputMode.AUTO_PASTE)
    handler.deliver("hello")
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 1
    assert "keystroke" in scripts[0]
    assert "return" not in scripts[0]


@patch("src.backends.macos.subprocess.run")
def test_auto_send_pastes_then_enters_on_trigger(mock_run):
    handler = MacOutputHandler(mode=OutputMode.AUTO_SEND)
    handler.deliver("hello enter")
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2
    assert "keystroke" in scripts[0]
    assert "return" in scripts[1]
    # clipboard received the STRIPPED text (trigger removed)
    pbcopy = [
        call_args for call_args in mock_run.call_args_list
        if call_args.args and call_args.args[0][0] == "pbcopy"
    ][0]
    assert pbcopy.kwargs.get("input") == "hello"


@patch("src.backends.macos.subprocess.run")
def test_auto_send_without_trigger_pastes_only(mock_run):
    handler = MacOutputHandler(mode=OutputMode.AUTO_SEND)
    handler.deliver("hello world")
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 1
    assert "keystroke" in scripts[0]
    assert "return" not in scripts[0]
