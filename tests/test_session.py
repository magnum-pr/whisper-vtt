"""Tests for dictation-session phrase parsing (src/session.py)."""

from src.session import is_scratch, is_session_end, parse_session_start


class TestParseSessionStart:
    def test_with_topic(self):
        assert parse_session_start(
            "start a new session for AlignMe website") == "AlignMe website"

    def test_with_about(self):
        assert parse_session_start(
            "start a session about the header spacing") == "the header spacing"

    def test_with_jarvis_prefix(self):
        assert parse_session_start(
            "jarvis, start a new session for alignme") == "alignme"

    def test_no_topic_returns_empty(self):
        assert parse_session_start("start a new session") == ""

    def test_short_form(self):
        assert parse_session_start("start session for pricing") == "pricing"

    def test_not_a_session_trigger(self):
        assert parse_session_start("start the build please") is None
        assert parse_session_start("open a new session for me") is None
        assert parse_session_start("session notes are in the doc") is None
        assert parse_session_start("") is None

    def test_trailing_punctuation_ignored(self):
        assert parse_session_start(
            "start a new session for the nav bar.") == "the nav bar"


class TestSessionEnd:
    def test_standalone_end_phrases(self):
        for phrase in (
            "that's all", "that is all", "that'll be all",
            "done", "end session", "finish session", "close the session",
        ):
            assert is_session_end(phrase), phrase

    def test_end_must_be_standalone(self):
        assert is_session_end("add the hero image that's all") is False
        assert is_session_end("") is False

    def test_punctuation_tolerated(self):
        assert is_session_end("that's all.") is True


class TestScratch:
    def test_scratch_phrases(self):
        for phrase in ("scratch that", "remove that", "delete that"):
            assert is_scratch(phrase), phrase

    def test_scratch_must_be_standalone(self):
        assert is_scratch("scratch that and fix the header") is False
