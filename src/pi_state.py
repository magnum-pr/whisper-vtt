"""Pi presence handshake — the state file whisper reads instead of guessing.

pi (the coding agent) writes ``~/.local/whisper-vtt/pi-state.json`` while
it is active — at session start and whenever it responds. Whisper reads it
to learn two facts it previously had to guess with AppleScript:

- **Is a pi session plausibly alive?**  The file's ``updated_at`` must be
  within ``PI_STATE_MAX_AGE_S``.  A stale or missing file does not prove
  pi is gone — whisper combines this with its own window detection — it
  just means the positive evidence expired.
- **Which window belongs to pi?**  ``window_title_fragment`` (e.g.
  "PI Code — alignme") and ``host_app`` (e.g. "Code") let whisper target
  the exact pi window instead of matching titles heuristically.

JSON shape::

    {
      "window_title_fragment": "PI Code — alignme",
      "host_app": "Code",
      "session": "alignme",
      "updated_at": 1786864000.0
    }

This module is pure file IO (no AppleScript, no platform branches) so it
is importable and testable everywhere.  The writer lives in
``scripts/pi_handshake.py`` — run by pi, never by whisper.
"""

import json
import os
import time
from typing import Optional

PI_STATE_DIR = os.path.expanduser("~/.local/whisper-vtt")
PI_STATE_FILE = os.path.join(PI_STATE_DIR, "pi-state.json")
PI_STATE_MAX_AGE_S = 1800.0  # 30 minutes


def write_pi_state(
    window_title_fragment: Optional[str] = None,
    host_app: str = "Code",
    session: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> dict:
    """Atomically write the handshake state file. Returns the state dict."""
    state = {
        "window_title_fragment": window_title_fragment or "",
        "host_app": host_app,
        "session": session or "",
        "updated_at": timestamp if timestamp is not None else time.time(),
    }
    try:
        os.makedirs(PI_STATE_DIR, exist_ok=True)
        tmp = PI_STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, PI_STATE_FILE)
    except OSError:
        # Handshake is a side channel — never let it break the writer.
        pass
    return state


def read_pi_state() -> Optional[dict]:
    """Read the handshake state, or None when missing/corrupt."""
    try:
        with open(PI_STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def pi_state_fresh(
    state: Optional[dict] = None,
    max_age_s: float = PI_STATE_MAX_AGE_S,
    now: Optional[float] = None,
) -> bool:
    """True when the handshake file is newer than max_age_s."""
    if state is None:
        state = read_pi_state()
    if not state:
        return False
    updated = state.get("updated_at")
    if not isinstance(updated, (int, float)):
        return False
    return (now if now is not None else time.time()) - float(updated) < max_age_s
