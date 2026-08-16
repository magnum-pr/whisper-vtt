"""Tests for scripts/set_mode.py — the voice-config bridge."""

import importlib.util
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_set_mode():
    spec = importlib.util.spec_from_file_location(
        "set_mode", SCRIPTS / "set_mode.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def set_mode_module():
    return _load_set_mode()


def _write_config(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


CONFIG = """\
# device-specific settings (gitignored)
[output]
mode = "auto_send"   # current setting
paste_target = "pi"

[vad]
silence_threshold_ms = 3000
"""


def test_valid_mode_updates_line(set_mode_module, tmp_path):
    cfg = tmp_path / "config.toml"
    _write_config(cfg, CONFIG)
    assert set_mode_module.set_mode(cfg, "protected") == 0
    out = cfg.read_text(encoding="utf-8")
    assert 'mode = "protected"' in out
    assert 'paste_target = "pi"' in out  # untouched
    assert "# device-specific settings" in out  # comments preserved
    assert 'silence_threshold_ms = 3000' in out


def test_all_valid_modes_accepted(set_mode_module, tmp_path):
    for mode in ("clipboard", "auto_paste", "auto_send", "protected"):
        cfg = tmp_path / "config.toml"
        _write_config(cfg, CONFIG)
        assert set_mode_module.set_mode(cfg, mode) == 0, mode


def test_invalid_mode_rejected_and_file_unchanged(set_mode_module, tmp_path):
    cfg = tmp_path / "config.toml"
    _write_config(cfg, CONFIG)
    before = cfg.read_text(encoding="utf-8")
    assert set_mode_module.set_mode(cfg, "explode") == 1
    assert cfg.read_text(encoding="utf-8") == before


def test_missing_output_section_errors(set_mode_module, tmp_path):
    cfg = tmp_path / "config.toml"
    _write_config(cfg, "[vad]\nsilence_threshold_ms = 3000\n")
    before = cfg.read_text(encoding="utf-8")
    assert set_mode_module.set_mode(cfg, "auto_send") == 2
    assert cfg.read_text(encoding="utf-8") == before


def test_missing_file_errors(set_mode_module, tmp_path):
    assert set_mode_module.set_mode(tmp_path / "nope.toml", "auto_send") == 2
