"""Single-instance guard — one whisper process at a time.

Two whisper instances fight over the mic (dual PortAudio streams fail
with -9986 and/or capture silence), so a new launch must end any
surviving instance before it starts.

Mechanism: a pidfile in the app's config dir. On acquire:
- stale pid (dead process, or pid recycled by a non-whisper process)
  → overwrite, we own the lock
- live whisper instance → SIGTERM it, wait up to 5s for exit, take over

On release, the pidfile is removed only if it still contains OUR pid —
never a newer instance's file.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TERMINATE_WAIT_S = 5.0


def _pid_alive(pid: int) -> bool:
    """True when a process with this pid exists."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _looks_like_whisper(pid: int) -> bool:
    """Best-effort check that the pid actually is a whisper instance.

    Guards against the pidfile pointing at a recycled pid that now
    belongs to some unrelated process — we must never kill those.
    """
    if sys.platform == "win32":
        # No `ps` equivalent without extra deps; trust the pidfile on
        # Windows (the pidfile lives in whisper's own config dir).
        return True
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return True  # can't verify — trust the pidfile
    cmd = out.stdout.strip().lower()
    # Source run:  .../whisper-vtt/.venv/bin/python -m src
    # Bundled run: .../Whisper-VTT.app/...  or  Whisper-VTT
    return "whisper" in cmd or "-m src" in cmd


def _read_pid(pidfile: Path) -> Optional[int]:
    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _write_pid(pidfile: Path, pid: int) -> None:
    tmp = pidfile.with_suffix(".tmp")
    tmp.write_text(str(pid), encoding="utf-8")
    os.replace(tmp, pidfile)


def acquire_single_instance(pidfile: Path) -> bool:
    """Ensure this is the only whisper instance. Returns True when we own
    the lock (a previous instance was ended, or none existed)."""
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    old_pid = _read_pid(pidfile)

    if old_pid is not None and old_pid != os.getpid():
        if _pid_alive(old_pid) and _looks_like_whisper(old_pid):
            logger.warning(
                "Another whisper instance is running (pid %d) — ending it.",
                old_pid,
            )
            try:
                os.kill(old_pid, 15)  # SIGTERM
            except OSError as e:
                logger.warning("Could not terminate pid %d: %s", old_pid, e)
            deadline = time.monotonic() + TERMINATE_WAIT_S
            while time.monotonic() < deadline and _pid_alive(old_pid):
                time.sleep(0.1)
            if _pid_alive(old_pid):
                logger.warning(
                    "Previous instance (pid %d) did not exit — "
                    "continuing anyway.", old_pid)
        elif _pid_alive(old_pid):
            logger.warning(
                "Stale pidfile: pid %d is alive but is not whisper — "
                "overwriting.", old_pid)
        else:
            logger.info("Stale pidfile (pid %d is gone) — taking over.", old_pid)

    _write_pid(pidfile, os.getpid())
    return True


def release_single_instance(pidfile: Path) -> None:
    """Remove the pidfile — only if it still names our pid."""
    try:
        if _read_pid(pidfile) == os.getpid():
            pidfile.unlink(missing_ok=True)
    except OSError:
        pass
