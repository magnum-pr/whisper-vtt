"""Tests for the shared mic level meter."""

import time

import numpy as np

from src.level_meter import SILENCE_DB, LevelMeter


def loud_chunk(amplitude=0.3):
    return np.full(1600, amplitude, dtype=np.float32)


def test_loud_audio_sets_level_and_resets_silence():
    meter = LevelMeter()
    meter.update_from_samples(loud_chunk())
    assert meter.level_db() > SILENCE_DB
    assert meter.silent_for_seconds() == 0.0
    assert not meter.silent_too_long


def test_silence_accumulates_after_audible_audio():
    meter = LevelMeter(silent_alert_after=0.2)
    meter.update_from_samples(loud_chunk())
    assert not meter.silent_too_long
    meter.update_from_samples(np.zeros(1600, dtype=np.float32))  # quiet chunk starts silence
    time.sleep(0.25)
    assert meter.silent_too_long
    assert meter.silent_for_seconds() >= 0.2


def test_digital_silence_is_minus_inf():
    meter = LevelMeter()
    meter.update_from_samples(np.zeros(1600, dtype=np.float32))
    assert meter.level_db() == float("-inf")
    assert meter.level_bar(meter.level_db()).startswith("▁")


def test_level_bar_scales():
    assert LevelMeter.level_bar(float("-inf")).startswith("▁")
    assert LevelMeter.level_bar(-60.0).startswith("▁")
    full = LevelMeter.level_bar(-10.0)
    assert full == "▄" * 10
    mid = LevelMeter.level_bar(-35.0)
    assert mid.count("▄") >= 4


def test_never_heard_anything_counts_as_not_silent_too_long():
    # fresh meter with no updates must not fire the alert immediately
    meter = LevelMeter(silent_alert_after=5.0)
    assert not meter.silent_too_long
