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
