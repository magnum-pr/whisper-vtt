"""Spoken intent extraction — send trigger and per-dictation override.

Two spoken commands are recognized in transcriptions:

1. The send trigger: ending with the standalone word 'Enter' means
   "paste this and press Enter" (protected mode). The word is stripped.
2. The no-send override: a phrase like "paste this without sending"
   suppresses the Enter for this one dictation only, in every mode.
   The phrase is stripped from the text.
"""

import re

SEND_TRIGGER = "enter"

# Trigger must be a standalone final word: preceded by whitespace or
# common punctuation (so 'center' doesn't match), optionally followed
# by sentence-ending punctuation.
_TRIGGER_RE = re.compile(
    r"(?i)(^|[\s,;:]+)(" + SEND_TRIGGER + r")([.!?]*)$"
)

# Spoken override phrases that suppress the Enter for one dictation.
# Whisper omits punctuation and sometimes drops the apostrophe in
# "don't", so both spellings are accepted.
NO_SEND_PATTERNS = [
    r"\bpaste (?:this|it|that)?\s*without (?:sending|(?:pressing\s+)?enter)(?:\s+it)?\b",
    r"\bwithout (?:sending|(?:pressing\s+)?enter)(?:\s+it)?\b",
    r"\b(?:don'?t|do not|no)\s+send(?:\s+it)?\b",
    r"\bjust paste\b",
    r"\bpaste only\b",
]
_NO_SEND_RE = re.compile("(?i)(" + "|".join(NO_SEND_PATTERNS) + ")")


def extract_no_send_intent(text: str) -> tuple[str, bool]:
    """Return (cleaned_text, suppress_send).

    suppress_send is True when the transcription contains a spoken
    no-send phrase. The phrase is stripped from cleaned_text.
    """
    t = text.strip()
    if not _NO_SEND_RE.search(t):
        return t, False
    cleaned = _NO_SEND_RE.sub("", t)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .,;:!?-")
    return cleaned, True


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
