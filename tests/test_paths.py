import pytest
"""Tests for PathResolver."""

import sys
from pathlib import Path
from unittest.mock import patch

from src.paths import PathResolver


class TestPathResolver:
    def test_base_path_source(self):
        """When running from source, base path is parent of src/."""
        base = PathResolver.base_path()
        # case-insensitive: the repo may be cloned as whisper-vtt or Whisper-VTT
        assert base.name.lower() == "whisper-vtt"
        assert (base / "src" / "__init__.py").exists()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows path test")
    def test_base_path_frozen(self):
        """When running from PyInstaller bundle, base path is exe directory."""
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "C:\\app\\whisper-vtt.exe"):
                base = PathResolver.base_path()
                assert base == Path("C:\\app")

    def test_resolve(self):
        result = PathResolver.resolve("config.toml")
        assert result.name == "config.toml"
        assert result.parent == PathResolver.base_path()

    def test_config_path_default(self):
        result = PathResolver.config_path()
        assert result.name == "config.toml"

    def test_config_path_custom(self):
        result = PathResolver.config_path("custom.toml")
        assert result.name == "custom.toml"

    def test_model_path_default(self):
        result = PathResolver.model_path()
        assert result == PathResolver.base_path() / "models" / "ggml-base.en.bin"

    def test_model_path_custom(self):
        result = PathResolver.model_path("models/ggml-small.en.bin")
        assert result == PathResolver.base_path() / "models" / "ggml-small.en.bin"

    def test_log_path_default(self):
        result = PathResolver.log_path()
        assert result.name == "dictation.log"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows path test")
    def test_frozen_resolve_ignores_src_structure(self):
        """When frozen, resolve uses exe directory, not src/ parent."""
        with patch.object(sys, "frozen", True, create=True):
            with patch.object(sys, "executable", "C:\\dist\\whisper-vtt\\whisper-vtt.exe"):
                result = PathResolver.resolve("config.toml")
                assert result == Path("C:\\dist\\whisper-vtt\\config.toml")
