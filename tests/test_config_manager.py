"""Tests for ConfigManager."""

import tempfile
from pathlib import Path

from src.config_manager import (
    DEFAULT_HOTKEY_KEY,
    DEFAULT_HOTKEY_MODIFIERS,
    DEFAULT_MODEL_PATH,
    DEFAULT_OUTPUT_MODE,
    DEFAULT_RECORDING_MODE,
    DEFAULT_SILENCE_THRESHOLD_MS,
    DEFAULT_VOLUME_THRESHOLD_DB,
    _validate_audio_device_name,
    _validate_key,
    _validate_model_path,
    _validate_modifiers,
    _validate_output_mode,
    _validate_recording_mode,
    _validate_silence_threshold,
    _validate_volume_threshold,
    config_to_toml,
    load_config,
    write_default_config,
)
from src.models import AppConfig, HotkeyCombo, OutputMode, RecordingMode


# ── Validation unit tests ──────────────────────────────────────────────


class TestValidateModifiers:
    def test_valid_modifiers(self):
        result = _validate_modifiers(["ctrl", "shift"])
        assert result == frozenset({"ctrl", "shift"})

    def test_invalid_modifiers_dropped(self):
        result = _validate_modifiers(["ctrl", "bogus", "alt"])
        assert result == frozenset({"ctrl", "alt"})

    def test_all_invalid_returns_default(self):
        result = _validate_modifiers(["invalid"])
        assert result == DEFAULT_HOTKEY_MODIFIERS

    def test_not_a_list_returns_default(self):
        result = _validate_modifiers("ctrl")
        assert result == DEFAULT_HOTKEY_MODIFIERS

    def test_empty_list_returns_empty(self):
        result = _validate_modifiers([])
        assert result == frozenset()


class TestValidateKey:
    def test_valid_key(self):
        assert _validate_key("space") == "space"
        assert _validate_key("`") == "`"

    def test_empty_string_returns_default(self):
        assert _validate_key("") == DEFAULT_HOTKEY_KEY

    def test_whitespace_only_returns_default(self):
        assert _validate_key("   ") == DEFAULT_HOTKEY_KEY

    def test_non_string_returns_default(self):
        assert _validate_key(123) == DEFAULT_HOTKEY_KEY

    def test_none_returns_default(self):
        assert _validate_key(None) == DEFAULT_HOTKEY_KEY


class TestValidateRecordingMode:
    def test_valid(self):
        assert _validate_recording_mode("toggle") == RecordingMode.TOGGLE
        assert _validate_recording_mode("push_to_talk") == RecordingMode.PUSH_TO_TALK

    def test_invalid_returns_default(self):
        assert _validate_recording_mode("hold") == DEFAULT_RECORDING_MODE

    def test_non_string_returns_default(self):
        assert _validate_recording_mode(42) == DEFAULT_RECORDING_MODE


class TestValidateOutputMode:
    def test_valid(self):
        assert _validate_output_mode("auto_paste") == OutputMode.AUTO_PASTE
        assert _validate_output_mode("clipboard") == OutputMode.CLIPBOARD

    def test_invalid_returns_default(self):
        assert _validate_output_mode("paste") == DEFAULT_OUTPUT_MODE


class TestValidateSilenceThreshold:
    def test_valid(self):
        assert _validate_silence_threshold(3000) == 3000
        assert _validate_silence_threshold(5000.0) == 5000

    def test_zero_returns_default(self):
        assert _validate_silence_threshold(0) == DEFAULT_SILENCE_THRESHOLD_MS

    def test_negative_returns_default(self):
        assert _validate_silence_threshold(-100) == DEFAULT_SILENCE_THRESHOLD_MS

    def test_non_number_returns_default(self):
        assert _validate_silence_threshold("abc") == DEFAULT_SILENCE_THRESHOLD_MS


class TestValidateVolumeThreshold:
    def test_valid(self):
        assert _validate_volume_threshold(-20.0) == -20.0
        assert _validate_volume_threshold(0) == 0.0

    def test_non_number_returns_default(self):
        assert _validate_volume_threshold("loud") == DEFAULT_VOLUME_THRESHOLD_DB


class TestValidateAudioDeviceName:
    def test_valid_name(self):
        assert _validate_audio_device_name("Microphone (Realtek)") == "Microphone (Realtek)"

    def test_none_returns_none(self):
        assert _validate_audio_device_name(None) is None

    def test_empty_string_returns_none(self):
        assert _validate_audio_device_name("") is None

    def test_whitespace_only_returns_none(self):
        assert _validate_audio_device_name("   ") is None

    def test_non_string_returns_none(self):
        assert _validate_audio_device_name(42) is None

    def test_strips_whitespace(self):
        assert _validate_audio_device_name("  Mic  ") == "Mic"


class TestValidateModelPath:
    def test_valid(self):
        assert _validate_model_path("models/ggml-base.en.bin") == Path("models/ggml-base.en.bin")

    def test_empty_returns_default(self):
        assert _validate_model_path("") == Path(DEFAULT_MODEL_PATH)

    def test_non_string_returns_default(self):
        assert _validate_model_path(None) == Path(DEFAULT_MODEL_PATH)


# ── Serialization tests ────────────────────────────────────────────────


class TestConfigToToml:
    def test_roundtrip(self):
        """Serializing and re-parsing should produce the same config."""
        config = AppConfig(
            hotkey=HotkeyCombo(modifiers=frozenset({"ctrl", "shift"}), key="f1"),
            recording_mode=RecordingMode.PUSH_TO_TALK,
            output_mode=OutputMode.CLIPBOARD,
            silence_threshold_ms=3000,
            volume_threshold_db=-10.0,
            model_path=Path("models/ggml-base.en.bin"),
            audio_device_name="Microphone (USB)",
        )
        toml_str = config_to_toml(config)

        # Write to temp file and load back
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_str)
            tmp_path = Path(f.name)

        try:
            loaded = load_config(tmp_path)
            assert loaded.hotkey == config.hotkey
            assert loaded.recording_mode == config.recording_mode
            assert loaded.output_mode == config.output_mode
            assert loaded.silence_threshold_ms == config.silence_threshold_ms
            assert loaded.volume_threshold_db == config.volume_threshold_db
            assert loaded.model_path == config.model_path
            assert loaded.audio_device_name == "Microphone (USB)"
        finally:
            tmp_path.unlink()

    def test_default_roundtrip(self):
        """Default config serializes and re-parses identically."""
        from src.config_manager import _default_config

        config = _default_config()
        toml_str = config_to_toml(config)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_str)
            tmp_path = Path(f.name)

        try:
            loaded = load_config(tmp_path)
            assert loaded == config
        finally:
            tmp_path.unlink()


# ── File loading tests ─────────────────────────────────────────────────


class TestLoadConfig:
    def test_missing_file_returns_defaults(self):
        config = load_config(Path("nonexistent_config.toml"))
        assert config.hotkey.key == DEFAULT_HOTKEY_KEY
        assert config.hotkey.modifiers == DEFAULT_HOTKEY_MODIFIERS
        assert config.recording_mode == DEFAULT_RECORDING_MODE
        assert config.output_mode == DEFAULT_OUTPUT_MODE
        assert config.silence_threshold_ms == DEFAULT_SILENCE_THRESHOLD_MS
        assert config.volume_threshold_db == DEFAULT_VOLUME_THRESHOLD_DB

    def test_corrupt_file_returns_defaults(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write("this is not valid toml {{{")
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            assert config.hotkey.key == DEFAULT_HOTKEY_KEY
        finally:
            tmp_path.unlink()

    def test_partial_invalid_fields_replaced_with_defaults(self):
        """When some fields are invalid, they fall back to defaults without crashing."""
        toml_content = """\
[hotkey]
modifiers = ["ctrl", "bogus", 123]
key = ""

[recording]
mode = "invalid_mode"

[output]
mode = "clipboard"

[vad]
silence_threshold_ms = -500
volume_threshold_db = "quiet"

[model]
path = ""
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            # Invalid modifiers: bogus and 123 dropped; ctrl kept
            assert config.hotkey.modifiers == frozenset({"ctrl"})
            # Invalid key → default
            assert config.hotkey.key == DEFAULT_HOTKEY_KEY
            # Invalid recording mode → default
            assert config.recording_mode == DEFAULT_RECORDING_MODE
            # Valid output mode → clipboard
            assert config.output_mode == OutputMode.CLIPBOARD
            # Invalid silence threshold → default
            assert config.silence_threshold_ms == DEFAULT_SILENCE_THRESHOLD_MS
            # Invalid volume threshold → default
            assert config.volume_threshold_db == DEFAULT_VOLUME_THRESHOLD_DB
            # Invalid model path → default
            assert config.model_path == Path(DEFAULT_MODEL_PATH)
        finally:
            tmp_path.unlink()

    def test_valid_full_config(self):
        toml_content = """\
[hotkey]
modifiers = ["ctrl", "shift"]
key = "f2"

[recording]
mode = "push_to_talk"

[output]
mode = "clipboard"

[vad]
silence_threshold_ms = 2000
volume_threshold_db = -20.0

[model]
path = "models/ggml-base.en.bin"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            assert config.hotkey.modifiers == frozenset({"ctrl", "shift"})
            assert config.hotkey.key == "f2"
            assert config.recording_mode == RecordingMode.PUSH_TO_TALK
            assert config.output_mode == OutputMode.CLIPBOARD
            assert config.silence_threshold_ms == 2000
            assert config.volume_threshold_db == -20.0
            assert config.model_path == Path("models/ggml-base.en.bin")
        finally:
            tmp_path.unlink()

    def test_config_with_only_hotkey_section(self):
        """When only partial sections exist, missing sections use defaults."""
        toml_content = """\
[hotkey]
modifiers = ["alt"]
key = "space"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            assert config.hotkey.key == "space"
            assert config.hotkey.modifiers == frozenset({"alt"})
            assert config.recording_mode == DEFAULT_RECORDING_MODE
            assert config.output_mode == DEFAULT_OUTPUT_MODE
            assert config.audio_device_name is None
        finally:
            tmp_path.unlink()

    def test_audio_device_config(self):
        """Audio device name is loaded from [audio] section."""
        toml_content = """\
[audio]
device_name = "Yeti Stereo Microphone"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)

        try:
            config = load_config(tmp_path)
            assert config.audio_device_name == "Yeti Stereo Microphone"
        finally:
            tmp_path.unlink()


# ── Write config tests ─────────────────────────────────────────────────


class TestWriteDefaultConfig:
    def test_writes_and_loads(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = Path(f.name)

        try:
            result = write_default_config(tmp_path)
            assert result == tmp_path
            assert tmp_path.exists()

            loaded = load_config(tmp_path)
            assert loaded.hotkey.key == DEFAULT_HOTKEY_KEY
            assert loaded.hotkey.modifiers == DEFAULT_HOTKEY_MODIFIERS
        finally:
            tmp_path.unlink()


class TestPasteTarget:
    def test_paste_target_parsed(self):
        toml_content = """\
[output]
mode = "auto_send"
paste_target = "pi"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)
        try:
            config = load_config(tmp_path)
            assert config.paste_target == "pi"
        finally:
            tmp_path.unlink()

    def test_paste_target_defaults_to_frontmost(self):
        toml_content = """\
[output]
mode = "clipboard"
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            f.write(toml_content)
            tmp_path = Path(f.name)
        try:
            config = load_config(tmp_path)
            assert config.paste_target == "frontmost"
        finally:
            tmp_path.unlink()

    def test_paste_target_roundtrips(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".toml", delete=False, encoding="utf-8"
        ) as f:
            tmp_path = Path(f.name)
        try:
            from src.config_manager import config_to_toml, write_default_config
            write_default_config(tmp_path)
            # roundtrip a custom value through the serializer
            config = load_config(tmp_path)
            from dataclasses import replace
            updated = replace(config, paste_target="Code")
            written = config_to_toml(updated)
            assert 'paste_target = "Code"' in written
        finally:
            tmp_path.unlink()
