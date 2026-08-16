"""Dictation session — phrase parsing and session state.

A session is started by a spoken trigger ("start a new session for X"),
kept open by speech-onset re-arming, and committed by a standalone
exit phrase ("that's all"). The trigger and control phrases are
commands, not dictation — they never get pasted or journaled.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

# "jarvis, start a new session for AlignMe website" / "start a session
# about the header" / "start a new session" (no topic).
_START_RE = re.compile(
    r"(?i)^\s*(?:jarvis[,\s!.]*)?"
    r"start\s+(?:a\s+)?(?:new\s+)?session"
    r"(?:\s+(?:for|about)\s+(.+?))?"
    r"\s*[.!?]*\s*$"
)

# Standalone exit phrases — the whole utterance must be one of these.
_END_PHRASES = frozenset(
    p.lower()
    for p in (
        "that's all",
        "that is all",
        "that'll be all",
        "that will be all",
        "done",
        "end session",
        "end the session",
        "finish session",
        "close session",
        "close the session",
    )
)

# Standalone correction phrases.
_SCRATCH_PHRASES = frozenset(
    p.lower()
    for p in (
        "scratch that",
        "remove that",
        "delete that",
        "forget that",
        "drop that",
    )
)


def parse_session_start(text: str) -> Optional[str]:
    """Topic from a session-start trigger, or None when not a trigger.

    Returns "" when no topic was given (caller picks a default title).
    """
    match = _START_RE.match(text.strip())
    if not match:
        return None
    topic = (match.group(1) or "").strip(" .!?")
    return topic


def is_session_end(text: str) -> bool:
    """True when the utterance is a standalone session-exit phrase."""
    return text.strip().strip(" .!?").lower() in _END_PHRASES


def is_scratch(text: str) -> bool:
    """True when the utterance is a standalone scratch-last-item phrase."""
    return text.strip().strip(" .!?").lower() in _SCRATCH_PHRASES


@dataclass
class SessionState:
    """An open dictation session.

    Compile sessions ("start a new session for X") accumulate items and
    commit a titled task list. Sticky sessions deliver every utterance
    live — they only relax the wake word requirement for follow-ups.
    """

    title: str
    items: list = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    sticky: bool = False

    def default_title(self) -> str:
        return f"Dictation session {time.strftime('%H:%M', time.localtime(self.started_at))}"
