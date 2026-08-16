"""Tests for the pi presence handshake state file (src/pi_state.py).

Pure file IO — no platform deps. Verifies the atomic write/read cycle
and the freshness window that whisper's on-mode safety net relies on.
"""

import json

import pytest

from src.pi_state import (
    PI_STATE_FILE,
    read_pi_state,
    pi_state_fresh,
    write_pi_state,
)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    import src.pi_state as mod

    state_file = tmp_path / "pi-state.json"
    monkeypatch.setattr(mod, "PI_STATE_FILE", str(state_file))
    monkeypatch.setattr(mod, "PI_STATE_DIR", str(tmp_path))
    return state_file


def test_write_then_read_roundtrip(_isolate_state):
    state = write_pi_state(
        window_title_fragment="PI Code — alignme",
        host_app="Code",
        session="alignme",
        timestamp=1000.0,
    )
    assert state["window_title_fragment"] == "PI Code — alignme"
    assert state["host_app"] == "Code"
    assert state["updated_at"] == 1000.0

    read = read_pi_state()
    assert read == state


def test_missing_state_reads_none(_isolate_state):
    assert read_pi_state() is None


def test_corrupt_state_reads_none(_isolate_state):
    _isolate_state.write_text("{not json", encoding="utf-8")
    assert read_pi_state() is None


def test_non_dict_state_reads_none(_isolate_state):
    _isolate_state.write_text("[1, 2, 3]", encoding="utf-8")
    assert read_pi_state() is None


def test_fresh_within_window(_isolate_state):
    write_pi_state(timestamp=500.0)
    assert pi_state_fresh(max_age_s=100.0, now=550.0) is True


def test_stale_beyond_window(_isolate_state):
    write_pi_state(timestamp=500.0)
    assert pi_state_fresh(max_age_s=100.0, now=700.0) is False


def test_boundary_is_stale_when_age_equals_max(_isolate_state):
    write_pi_state(timestamp=500.0)
    assert pi_state_fresh(max_age_s=100.0, now=600.0) is False


def test_fresh_with_no_file(_isolate_state):
    assert pi_state_fresh(max_age_s=100.0, now=0.0) is False


def test_fresh_rejects_missing_timestamp(_isolate_state):
    _isolate_state.write_text(
        json.dumps({"host_app": "Code"}), encoding="utf-8")
    assert pi_state_fresh(max_age_s=100.0, now=0.0) is False


def test_write_replaces_previous_state(_isolate_state):
    write_pi_state(window_title_fragment="old", timestamp=1.0)
    write_pi_state(window_title_fragment="new", timestamp=2.0)
    read = read_pi_state()
    assert read["window_title_fragment"] == "new"
    assert read["updated_at"] == 2.0
