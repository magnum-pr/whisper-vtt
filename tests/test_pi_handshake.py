"""Tests for scripts/pi_handshake.py — the handshake writer pi runs."""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_handshake():
    spec = importlib.util.spec_from_file_location(
        "pi_handshake", SCRIPTS / "pi_handshake.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def handshake_module(monkeypatch, tmp_path):
    module = _load_handshake()
    import src.pi_state as pi_state

    monkeypatch.setattr(pi_state, "PI_STATE_FILE", str(tmp_path / "pi-state.json"))
    monkeypatch.setattr(pi_state, "PI_STATE_DIR", str(tmp_path))
    return module


def test_write_requires_title(handshake_module, capsys):
    assert handshake_module.main([]) == 2
    assert "error" in capsys.readouterr().err


def test_write_then_check(handshake_module, capsys):
    assert handshake_module.main(
        ["--title", "PI Code — alignme", "--host", "Code", "--session", "alignme"]
    ) == 0
    out = capsys.readouterr().out
    assert "pi-state written" in out
    assert "PI Code" in out

    assert handshake_module.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "fresh" in out


def test_check_with_no_state(handshake_module, capsys):
    assert handshake_module.main(["--check"]) == 0
    assert "missing" in capsys.readouterr().out


def test_empty_host_falls_back_to_code(handshake_module, capsys):
    assert handshake_module.main(["--title", "X", "--host", "  "]) == 0
    from src.pi_state import read_pi_state

    assert read_pi_state()["host_app"] == "Code"
