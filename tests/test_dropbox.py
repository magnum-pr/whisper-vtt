"""Tests for the dictation drop box."""

from unittest.mock import patch

import src.dropbox as dropbox


@patch("src.dropbox.DROPBOX_FILE", "/tmp/whisper-test-inbox/dictations.jsonl")
@patch("src.dropbox.DROPBOX_DIR", "/tmp/whisper-test-inbox")
def test_append_and_read_roundtrip():
    import os
    os.system("rm -rf /tmp/whisper-test-inbox")
    dropbox.append_dictation("task: fix the deploy", timestamp=1000.0)
    dropbox.append_dictation("status: merged the feature", timestamp=2000.0)

    entries = dropbox.read_dictations()
    assert len(entries) == 2
    assert entries[0]["text"] == "task: fix the deploy"
    assert entries[0]["ts"] == 1000.0
    assert entries[1]["text"] == "status: merged the feature"


@patch("src.dropbox.DROPBOX_FILE", "/tmp/whisper-test-inbox/dictations.jsonl")
@patch("src.dropbox.DROPBOX_DIR", "/tmp/whisper-test-inbox")
def test_archive_moves_and_clears():
    import os
    os.system("rm -rf /tmp/whisper-test-inbox")
    dropbox.append_dictation("lesson: never close a stream in its callback")

    moved = dropbox.archive_dictations()
    assert moved == 1
    assert dropbox.read_dictations() == []
    # archived file exists
    archive_files = [
        f for f in os.listdir("/tmp/whisper-test-inbox")
        if f.startswith("processed-")
    ]
    assert len(archive_files) == 1


@patch("src.dropbox.DROPBOX_FILE", "/tmp/whisper-test-inbox/missing.jsonl")
def test_read_missing_file_returns_empty():
    import os
    os.system("rm -rf /tmp/whisper-test-inbox")
    assert dropbox.read_dictations() == []


@patch("src.dropbox.DROPBOX_FILE", "/tmp/whisper-test-inbox/dictations.jsonl")
@patch("src.dropbox.DROPBOX_DIR", "/tmp/whisper-test-inbox")
def test_append_preserves_unicode():
    import os
    os.system("rm -rf /tmp/whisper-test-inbox")
    dropbox.append_dictation("journal: Sharon said “héaling” 🌿")
    assert dropbox.read_dictations()[0]["text"] == "journal: Sharon said “héaling” 🌿"


def test_session_entry_roundtrip():
    """Session commits carry kind/title/items through the drop box."""
    import json

    from src.dropbox import DROPBOX_FILE, append_dictation, read_dictations

    original = DROPBOX_FILE
    try:
        import src.dropbox as db
        db.DROPBOX_FILE = db.DROPBOX_FILE + ".session-test"
        append_dictation(
            "Session: alignme",
            kind="session",
            title="alignme",
            items=["item a", "item b"],
        )
        entries = read_dictations()
        assert len(entries) == 1
        assert entries[0]["kind"] == "session"
        assert entries[0]["title"] == "alignme"
        assert entries[0]["items"] == ["item a", "item b"]
    finally:
        import src.dropbox as db
        import os
        try:
            os.remove(db.DROPBOX_FILE)
        except OSError:
            pass
        db.DROPBOX_FILE = original
