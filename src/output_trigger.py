"""Spoken send-trigger extraction.

In auto_send mode a transcription ending with the standalone word
'Enter' (case-insensitive, optional trailing punctuation) means "paste
this text and press Enter" — the trigger word is stripped from the text.
Otherwise the text is pasted without pressing Enter.
"""

import re

SEND_TRIGGER = "enter"

# Trigger must be a standalone final word: preceded by whitespace or
# common punctuation (so 'center' doesn't match), optionally followed
# by sentence-ending punctuation.
_TRIGGER_RE = re.compile(
    r"(?i)(^|[\s,;:]+)(" + SEND_TRIGGER + r")([.!?]*)$"
)


def extract_send_intent(text: str) -> tuple[str, bool]:
    """Return (cleaned_text, should_send).

    should_send is True when the transcription ends with the spoken
    trigger word 'Enter' as its final word. The trigger (and any
    punctuation directly after it) is stripped from cleaned_text.
    """
    t = text.strip()
    match = _TRIGGER_RE.search(t)
    if not match:
        return t, False
    cleaned = t[: match.start()].rstrip()
    return cleaned, True
