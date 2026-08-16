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


@patch("src.backends.macos._frontmost_window_title", return_value="PI Code — alignme")
@patch("src.backends.macos.subprocess.run")
def test_protected_pastes_then_enters_on_trigger(mock_run, mock_title):
    handler = MacOutputHandler(mode=OutputMode.PROTECTED)
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


# ── auto_send: on / protected / off ───────────────────────────────────


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal"])
def test_on_mode_always_enters_without_trigger(mock_gui, mock_front, mock_title, mock_run):
    # on: no trigger word needed — paste + Enter every time
    handler = MacOutputHandler(mode=OutputMode.AUTO_SEND, paste_target="pi")
    assert handler.deliver("hello world") is None
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2
    assert "keystroke" in scripts[0]
    assert "return" in scripts[1]


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal"])
def test_on_mode_ignores_window_guard(mock_gui, mock_front, mock_title, mock_run):
    # on: pi's window not front → Enter still fires (follows the paste
    # destination). The guard is protected-mode behavior only.
    handler = MacOutputHandler(mode=OutputMode.AUTO_SEND, paste_target="pi")
    assert handler.deliver("hello world") is None
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2
    assert "return" in scripts[1]


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title", return_value="PI Code — alignme")
@patch("src.backends.macos._frontmost_process_name", return_value="Code")
@patch("src.backends.macos._gui_process_names", return_value=["Code"])
def test_on_mode_keeps_trigger_word_in_text(mock_gui, mock_front, mock_title, mock_run):
    # on: 'enter' is dictation content, not a command — never stripped
    handler = MacOutputHandler(mode=OutputMode.AUTO_SEND, paste_target="pi")
    handler.deliver("hello enter")
    pbcopy = [
        call_args for call_args in mock_run.call_args_list
        if call_args.args and call_args.args[0][0] == "pbcopy"
    ][0]
    assert pbcopy.kwargs.get("input") == "hello enter"
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2


# ── Send (Enter) targeting — protected mode (follows paste) ──────────


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title",
       side_effect=["whisper — zsh — 80×24", "PI Code — alignme"])
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Code"])
def test_protected_enter_targets_resolved_pi_window(mock_gui, mock_front, mock_title, mock_run):
    # whisper terminal front → paste resolves Code; after activation pi's
    # window is front → Enter lands in Code too
    handler = MacOutputHandler(mode=OutputMode.PROTECTED, paste_target="pi")
    assert handler.deliver("hello enter") is None
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2
    assert 'tell process "Code"' in scripts[0]
    assert 'keystroke "v"' in scripts[0]
    assert 'tell process "Code"' in scripts[1]
    assert "keystroke return" in scripts[1]


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal"])
def test_protected_withholds_enter_when_pi_window_not_front(mock_gui, mock_front, mock_title, mock_run):
    # no resolvable pi host and pi's window never front → paste only,
    # Enter withheld so the send can't land in the wrong app
    from src.models import SEND_SKIPPED

    handler = MacOutputHandler(mode=OutputMode.PROTECTED, paste_target="pi")
    assert handler.deliver("hello enter") == SEND_SKIPPED
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 1
    assert "return" not in scripts[0]


@patch("src.backends.macos.subprocess.run")
@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Code"])
def test_protected_withheld_when_targeted_paste_failed(mock_gui, mock_front, mock_title, mock_run):
    # targeted paste fails → plain paste; pi's window isn't front →
    # Enter withheld (no yank-to-Code send after a failed paste)
    import subprocess as sp

    from src.models import SEND_SKIPPED

    handler = MacOutputHandler(mode=OutputMode.PROTECTED, paste_target="pi")

    def _fake_run(args, **kwargs):
        script = args[-1] if isinstance(args[-1], str) else ""
        if "tell process" in script and 'keystroke "v"' in script:
            raise sp.CalledProcessError(1, args)
        return sp.CompletedProcess(args, 0)

    mock_run.side_effect = _fake_run
    assert handler.deliver("hello enter") == SEND_SKIPPED
    scripts = _osascript_scripts(mock_run)
    assert len(scripts) == 2  # targeted paste (failed) + plain paste, no Enter
    assert 'tell process' not in scripts[1]
    assert 'keystroke "v"' in scripts[1]


@patch("src.backends.macos.subprocess.run")
def test_protected_without_trigger_pastes_only(mock_run):
    handler = MacOutputHandler(mode=OutputMode.PROTECTED)
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


@patch("src.backends.macos._frontmost_window_title", return_value="PI Code — alignme")
@patch("src.backends.macos._frontmost_process_name", return_value="Code")
def test_pi_target_no_activation_when_pi_already_front(mock_front, mock_title):
    # pi's window is frontmost — paste directly, no focus yank
    assert _handler("pi")._resolve_target() is None


@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Code"])
def test_pi_target_terminal_front_non_pi_window_resolves_code(mock_gui, mock_front, mock_title):
    # whisper's own terminal is front — "whisper" contains "pi" as a
    # substring, but must NOT be treated as pi's window (word boundary)
    assert _handler("pi")._resolve_target() == "Code"


@patch("src.backends.macos._frontmost_window_title", return_value="pi — alignme — zsh")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Code"])
def test_pi_target_terminal_front_pi_window_no_yank(mock_gui, mock_front, mock_title):
    # genuine pi terminal is front — no focus yank
    assert _handler("pi")._resolve_target() is None


@patch("src.backends.macos._frontmost_window_title", return_value="whisper — zsh — 80×24")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal"])
def test_pi_target_terminal_front_non_pi_no_code_falls_back(mock_gui, mock_front, mock_title):
    # whisper terminal front, no Code running — plain frontmost paste fallback
    assert _handler("pi")._resolve_target() is None


@patch("src.backends.macos._frontmost_window_title", return_value="")
@patch("src.backends.macos._frontmost_process_name", return_value="Terminal")
@patch("src.backends.macos._gui_process_names", return_value=["Terminal", "Code"])
def test_pi_target_terminal_front_unknown_title_resolves_code(mock_gui, mock_front, mock_title):
    # title lookup failed — no evidence pi is front, prefer Code
    assert _handler("pi")._resolve_target() == "Code"


@patch("src.backends.macos._frontmost_window_title", return_value="README.md — alignme")
@patch("src.backends.macos._frontmost_process_name", return_value="Code")
@patch("src.backends.macos._gui_process_names", return_value=["Code"])
def test_pi_target_code_front_non_pi_window_still_targets_code(mock_gui, mock_front, mock_title):
    # Code is front but focused elsewhere — no better target than Code
    assert _handler("pi")._resolve_target() == "Code"


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
