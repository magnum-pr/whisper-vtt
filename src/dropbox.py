"""Dictation drop box — the whisper → pi bridge.

Every successful transcription is appended here as a JSONL entry.
pi's `whisper-vtt` skill reads this file and routes entries (tasks,
lessons, journal, status) with the LLM doing the disambiguation —
whisper stays a dumb, reliable pair of ears.

Location: ~/.local/whisper-vtt/inbox/dictations.jsonl
"""

import json
import os
import time

DROPBOX_DIR = os.path.expanduser("~/.local/whisper-vtt/inbox")
DROPBOX_FILE = os.path.join(DROPBOX_DIR, "dictations.jsonl")


def append_dictation(text: str, timestamp: float | None = None) -> dict:
    """Append one transcription entry to the drop box.

    Never raises — the drop box is a side channel; a failure must not
    break the paste/send path.
    """
    entry = {
        "ts": timestamp if timestamp is not None else time.time(),
        "text": text,
    }
    try:
        os.makedirs(DROPBOX_DIR, exist_ok=True)
        with open(DROPBOX_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return entry


def read_dictations() -> list[dict]:
    """All drop box entries, oldest first. [] when missing/empty."""
    try:
        with open(DROPBOX_FILE, encoding="utf-8") as f:
            return [
                json.loads(line)
                for line in f
                if line.strip()
            ]
    except (OSError, ValueError):
        return []


def archive_dictations() -> int:
    """Move the inbox to a timestamped archive; returns entries moved."""
    entries = read_dictations()
    if not entries:
        return 0
    archive = os.path.join(
        DROPBOX_DIR,
        f"processed-{time.strftime('%Y%m%d-%H%M%S')}.jsonl",
    )
    try:
        os.replace(DROPBOX_FILE, archive)
    except OSError:
        return 0
    return len(entries)
