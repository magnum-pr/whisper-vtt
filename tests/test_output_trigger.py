"""Tests for the spoken send-trigger extraction.

Rule: in auto_send mode, a transcription ending with the standalone
word 'Enter' (case-insensitive, optional trailing punctuation) means
"paste this and press Enter" — the trigger word is stripped from the
text. Otherwise paste-only.
"""

from src.output_trigger import extract_no_send_intent, extract_send_intent


def test_trigger_at_end_is_detected_and_stripped():
    text, send = extract_send_intent("fix the bug enter")
    assert text == "fix the bug"
    assert send is True


def test_trigger_with_trailing_punctuation():
    text, send = extract_send_intent("fix the bug. Enter")
    assert text == "fix the bug."
    assert send is True


def test_trigger_with_punctuation_after_trigger():
    text, send = extract_send_intent("fix the bug enter!")
    assert text == "fix the bug"
    assert send is True


def test_capitalized_trigger():
    text, send = extract_send_intent("Fix the bug ENTER")
    assert text == "Fix the bug"
    assert send is True


def test_word_ending_in_enter_is_not_a_trigger():
    text, send = extract_send_intent("look at the center")
    assert text == "look at the center"
    assert send is False


def test_trigger_must_be_final_word():
    text, send = extract_send_intent("please enter the room")
    assert text == "please enter the room"
    assert send is False


def test_plain_text_has_no_trigger():
    text, send = extract_send_intent("hello world")
    assert text == "hello world"
    assert send is False


def test_trigger_alone():
    text, send = extract_send_intent("Enter")
    assert text == ""
    assert send is True


# ── No-send override ────────────────────────────────────────────────


def test_override_phrase_at_end_detected_and_stripped():
    text, suppress = extract_no_send_intent("show me the tasks without sending")
    assert text == "show me the tasks"
    assert suppress is True


def test_override_phrase_at_start_detected_and_stripped():
    text, suppress = extract_no_send_intent("paste this without sending show me the tasks")
    assert text == "show me the tasks"
    assert suppress is True


def test_override_dont_send_variant():
    text, suppress = extract_no_send_intent("fix the bug don't send")
    assert text == "fix the bug"
    assert suppress is True


def test_override_dont_without_apostrophe():
    text, suppress = extract_no_send_intent("fix the bug dont send")
    assert text == "fix the bug"
    assert suppress is True


def test_override_without_enter_variant():
    text, suppress = extract_no_send_intent("deploy it without enter")
    assert text == "deploy it"
    assert suppress is True


def test_override_just_paste_variant():
    text, suppress = extract_no_send_intent("just paste the report")
    assert text == "the report"
    assert suppress is True


def test_override_phrase_only():
    text, suppress = extract_no_send_intent("paste this without sending")
    assert text == ""
    assert suppress is True


def test_override_absent():
    text, suppress = extract_no_send_intent("send the report to the team")
    assert text == "send the report to the team"
    assert suppress is False


def test_override_case_insensitive():
    text, suppress = extract_no_send_intent("Without Sending deploy")
    assert text == "deploy"
    assert suppress is True


def test_override_strips_trailing_punctuation_leftover():
    text, suppress = extract_no_send_intent("fix the bug, don't send")
    assert text == "fix the bug"
    assert suppress is True
