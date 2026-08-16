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


# ── Paste-target resolution ────────────────────────────────────────────


def _handler(target):
    return MacOutputHandler(mode=OutputMode.AUTO_PASTE, paste_target=target)


@patch("src.backends.macos._frontmost_process_name", return_value="")
@patch("src.backends.macos._gui_process_names", return_value=[])
def test_frontmost_target_resolves_to_none(mock_gui, mock_front):
    assert _handler("frontmost")._resolve_target() is None


@patch("src.backends.macos._frontmost_process_name", return_value="Code")
def test_pi_target_no_activation_when_pi_already_front(mock_front):
    # pi is frontmost — paste directly, no focus yank
    assert _handler("pi")._resolve_target() is None


@patch("src.backends.macos._frontmost_process_name", return_value="Slack")
@patch("src.backends.macos._gui_process_names", return_value=["Code", "Slack", "Finder"])
def test_pi_target_resolves_to_code(mock_gui, mock_front):
    assert _handler("pi")._resolve_target() == "Code"


@patch("src.backends.macos._frontmost_process_name", return_value="Slack")
@patch("src.backends.macos._gui_process_names", return_value=["Slack", "Finder"])
def test_pi_target_falls_back_when_no_host(mock_gui, mock_front):
    assert _handler("pi")._resolve_target() is None


@patch("src.backends.macos._frontmost_process_name", return_value="Slack")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Slack"])
def test_explicit_target_resolves_when_running(mock_gui, mock_front):
    assert _handler("Terminal")._resolve_target() == "Terminal"


@patch("src.backends.macos._frontmost_process_name", return_value="Slack")
@patch("src.backends.macos._gui_process_names", return_value=["Slack"])
def test_explicit_target_missing_returns_none(mock_gui, mock_front):
    assert _handler("Terminal")._resolve_target() is None


@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
def test_explicit_target_already_front_returns_none(mock_front):
    assert _handler("Terminal")._resolve_target() is None


@patch("src.backends.macos.MacOutputHandler._resolve_target", return_value="Code")
@patch("src.backends.macos.subprocess.run")
def test_deliver_pastes_into_resolved_target(mock_run, mock_resolve):
    handler = _handler("pi")
    handler.deliver("hello")
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 1
    assert 'process "Code"' in scripts[0]
    assert "set frontmost to true" in scripts[0]
    assert 'keystroke "v" using command down' in scripts[0]
