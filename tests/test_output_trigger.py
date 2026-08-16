"""Tests for the spoken send-trigger extraction.

Rule: in auto_send mode, a transcription ending with the standalone
word 'Enter' (case-insensitive, optional trailing punctuation) means
"paste this and press Enter" — the trigger word is stripped from the
text. Otherwise paste-only.
"""

from src.output_trigger import extract_send_intent


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
