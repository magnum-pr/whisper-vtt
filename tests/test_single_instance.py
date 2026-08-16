"""Tests for the single-instance guard (src/single_instance.py)."""

import os
from unittest.mock import patch

import pytest

from src.single_instance import (
    acquire_single_instance,
    release_single_instance,
)


@pytest.fixture(autouse=True)
def _fake_pid(monkeypatch):
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    return 4242


def test_acquire_writes_own_pid(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    assert acquire_single_instance(pidfile) is True
    assert pidfile.read_text() == "4242"


def test_acquire_stale_dead_pid_overwritten(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    pidfile.write_text("9999")
    with patch("src.single_instance._pid_alive", return_value=False):
        assert acquire_single_instance(pidfile) is True
    assert pidfile.read_text() == "4242"


def test_acquire_live_whisper_is_terminated(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    pidfile.write_text("7777")
    alive = [True]

    def _fake_alive(pid):
        return alive[0]

    with patch("src.single_instance._pid_alive", side_effect=_fake_alive), \
         patch("src.single_instance._looks_like_whisper", return_value=True), \
         patch("src.single_instance.os.kill") as mock_kill:
        # Old instance dies after SIGTERM — polling sees it exit.
        def _kill(pid, sig):
            alive[0] = False
        mock_kill.side_effect = _kill
        assert acquire_single_instance(pidfile) is True

    mock_kill.assert_called_once_with(7777, 15)  # SIGTERM
    assert pidfile.read_text() == "4242"


def test_acquire_alive_but_not_whisper_not_killed(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    pidfile.write_text("8888")  # recycled pid, now some other app
    with patch("src.single_instance._pid_alive", return_value=True), \
         patch("src.single_instance._looks_like_whisper", return_value=False), \
         patch("src.single_instance.os.kill") as mock_kill:
        assert acquire_single_instance(pidfile) is True
    mock_kill.assert_not_called()
    assert pidfile.read_text() == "4242"


def test_acquire_corrupt_pidfile_recovered(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    pidfile.write_text("not-a-pid")
    assert acquire_single_instance(pidfile) is True
    assert pidfile.read_text() == "4242"


def test_release_removes_own_pid(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    acquire_single_instance(pidfile)
    release_single_instance(pidfile)
    assert not pidfile.exists()


def test_release_keeps_foreign_pid(tmp_path):
    pidfile = tmp_path / "whisper.pid"
    pidfile.write_text("1234")  # newer instance took over
    release_single_instance(pidfile)
    assert pidfile.read_text() == "1234"


def test_looks_like_whisper_source_run():
    from src.single_instance import _looks_like_whisper

    with patch("src.single_instance.subprocess.run") as mock_run:
        mock_run.return_value.stdout = (
            "/Users/x/projects/whisper-vtt/.venv/bin/python -m src\n")
        assert _looks_like_whisper(123) is True


def test_looks_like_whisper_rejects_other_process():
    from src.single_instance import _looks_like_whisper

    with patch("src.single_instance.subprocess.run") as mock_run:
        mock_run.return_value.stdout = "/System/Applications/Safari.app/Contents/MacOS/Safari\n"
        assert _looks_like_whisper(123) is False
