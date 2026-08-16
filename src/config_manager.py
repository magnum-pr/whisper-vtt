"""Configuration manager — load, validate, and persist TOML config."""

import logging
import tomllib
from pathlib import Path
from typing import Optional

from src.models import AppConfig, HotkeyCombo, OutputMode, RecordingMode
from src.paths import PathResolver

logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_HOTKEY_MODIFIERS: frozenset[str] = frozenset()
DEFAULT_HOTKEY_KEY = "`"
DEFAULT_RECORDING_MODE = RecordingMode.TOGGLE
DEFAULT_OUTPUT_MODE = OutputMode.CLIPBOARD
DEFAULT_SILENCE_THRESHOLD_MS = 3000
DEFAULT_VOLUME_THRESHOLD_DB = -50.0
DEFAULT_MODEL_PATH = "models/ggml-base.en.bin"
DEFAULT_WAKE_WORD = "jarvis"
DEFAULT_WAKE_WORD_THRESHOLD = 1e-20
DEFAULT_AUDIO_DEVICE_NAME: Optional[str] = None
DEFAULT_REFRESH_INTERVAL_S = 120.0
DEFAULT_CALIBRATION_MARGIN_DB = 8.0
DEFAULT_SESSION_TIMEOUT_S = 60.0

# Valid values
VALID_MODIFIERS = frozenset({"ctrl", "shift", "alt", "win"})
VALID_RECORDING_MODES = frozenset({"toggle", "push_to_talk", "wake_word"})
VALID_OUTPUT_MODES = frozenset(
    {"auto_paste", "auto_send", "protected", "clipboard"})


def _default_config() -> AppConfig:
    """Return the default AppConfig."""
    return AppConfig(
        hotkey=HotkeyCombo(
            modifiers=DEFAULT_HOTKEY_MODIFIERS,
            key=DEFAULT_HOTKEY_KEY,
        ),
        recording_mode=DEFAULT_RECORDING_MODE,
        output_mode=DEFAULT_OUTPUT_MODE,
        silence_threshold_ms=DEFAULT_SILENCE_THRESHOLD_MS,
        volume_threshold_db=DEFAULT_VOLUME_THRESHOLD_DB,
        model_path=Path(DEFAULT_MODEL_PATH),
        wake_word=DEFAULT_WAKE_WORD,
        wake_word_threshold=DEFAULT_WAKE_WORD_THRESHOLD,
    )


def _validate_modifiers(modifiers: list) -> frozenset[str]:
    """Validate and clean modifier list. Invalid entries are dropped with a warning."""
    if not isinstance(modifiers, list):
        logger.warning(
            "Invalid hotkey modifiers (expected list, got %s). Using default: empty.",
            type(modifiers).__name__,
        )
        return DEFAULT_HOTKEY_MODIFIERS

    valid = frozenset(m for m in modifiers if m in VALID_MODIFIERS)
    invalid = set(modifiers) - VALID_MODIFIERS
    if invalid:
        logger.warning(
            "Ignoring invalid hotkey modifiers: %s. Valid options: %s",
            invalid,
            sorted(VALID_MODIFIERS),
        )
    return valid if valid else DEFAULT_HOTKEY_MODIFIERS


def _validate_key(key) -> str:
    """Validate the hotkey key. Must be a non-empty string."""
    if not isinstance(key, str) or not key.strip():
        logger.warning(
            "Invalid hotkey key (expected non-empty string, got %r). Using default: '%s'.",
            key,
            DEFAULT_HOTKEY_KEY,
        )
        return DEFAULT_HOTKEY_KEY
    return key.strip()


def _validate_recording_mode(mode) -> RecordingMode:
    """Validate recording mode. Falls back to default on invalid."""
    if isinstance(mode, str) and mode in VALID_RECORDING_MODES:
        return RecordingMode(mode)
    logger.warning(
        "Invalid recording_mode %r (expected 'toggle' or 'push_to_talk'). Using default: '%s'.",
        mode,
        DEFAULT_RECORDING_MODE.value,
    )
    return DEFAULT_RECORDING_MODE


def _validate_output_mode(mode) -> OutputMode:
    """Validate output mode. Falls back to default on invalid."""
    if isinstance(mode, str) and mode in VALID_OUTPUT_MODES:
        return OutputMode(mode)
    logger.warning(
        "Invalid output_mode %r (expected 'auto_paste', 'auto_send', "
        "'protected', or 'clipboard'). Using default: '%s'.",
        mode,
        DEFAULT_OUTPUT_MODE.value,
    )
    return DEFAULT_OUTPUT_MODE


def _validate_silence_threshold(value) -> int:
    """Validate silence threshold. Must be positive int. Default: 5000ms."""
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    logger.warning(
        "Invalid silence_threshold_ms %r (expected positive number). Using default: %d.",
        value,
        DEFAULT_SILENCE_THRESHOLD_MS,
    )
    return DEFAULT_SILENCE_THRESHOLD_MS


def _validate_volume_threshold(value) -> float:
    """Validate volume threshold. Must be a number. Default: -15.0 dB."""
    if isinstance(value, (int, float)):
        return float(value)
    logger.warning(
        "Invalid volume_threshold_db %r (expected number). Using default: %.1f.",
        value,
        DEFAULT_VOLUME_THRESHOLD_DB,
    )
    return DEFAULT_VOLUME_THRESHOLD_DB


def _validate_audio_device_name(value) -> Optional[str]:
    """Validate audio device name. Empty string, None, "auto", or
    "system" mean output-paired input routing (mic follows what the
    user is hearing from; MacBook mic fallback). A real name pins that
    device."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in ("auto", "system"):
            return None
        return stripped
    logger.warning(
        "Invalid audio device name %r (expected a string). Using auto-paired input.",
        value,
    )
    return None


def _validate_refresh_interval(value) -> float:
    """Validate environment refresh interval. Must be a positive number."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    logger.warning(
        "Invalid refresh_interval_s %r (expected positive number). Using default: %.0f.",
        value,
        DEFAULT_REFRESH_INTERVAL_S,
    )
    return DEFAULT_REFRESH_INTERVAL_S


def _validate_calibration_margin(value) -> float:
    """Validate VAD calibration margin. Must be a number."""
    if isinstance(value, (int, float)):
        return float(value)
    logger.warning(
        "Invalid calibration_margin_db %r (expected number). Using default: %.1f.",
        value,
        DEFAULT_CALIBRATION_MARGIN_DB,
    )
    return DEFAULT_CALIBRATION_MARGIN_DB


def _validate_session_timeout(value) -> float:
    """Validate session idle timeout. Must be a positive number."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    logger.warning(
        "Invalid session_timeout_s %r (expected positive number). Using default: %.0f.",
        value,
        DEFAULT_SESSION_TIMEOUT_S,
    )
    return DEFAULT_SESSION_TIMEOUT_S


def _validate_paste_target(value) -> str:
    """Validate paste target. Any non-empty string; special values:
    'frontmost' (default) and 'pi' (auto-resolve the pi host app)."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    logger.warning(
        "Invalid paste_target %r (expected non-empty string). Using default: 'frontmost'.",
        value,
    )
    return "frontmost"


def _validate_model_path(value) -> Path:
    """Validate model path. Must be a non-empty string. Default: models/tiny.en.pt."""
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    logger.warning(
        "Invalid model path %r (expected non-empty string). Using default: '%s'.",
        value,
        DEFAULT_MODEL_PATH,
    )
    return Path(DEFAULT_MODEL_PATH)


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from a TOML file.

    If the file does not exist or is corrupt, returns the default config.
    Invalid individual fields are replaced with defaults (never crashes).
    """
    if config_path is None:
        config_path = PathResolver.config_path()

    if not config_path.exists():
        logger.info("Config file not found at %s. Using defaults.", config_path)
        return _default_config()

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read config file %s: %s. Using defaults.", config_path, e)
        return _default_config()

    try:
        data = tomllib.loads(raw)
    except Exception as e:
        logger.warning("Config file %s is corrupt: %s. Using defaults.", config_path, e)
        return _default_config()

    # Parse [hotkey] section
    hotkey_section = data.get("hotkey", {})
    if not isinstance(hotkey_section, dict):
        hotkey_section = {}

    modifiers = _validate_modifiers(hotkey_section.get("modifiers", []))
    key = _validate_key(hotkey_section.get("key", DEFAULT_HOTKEY_KEY))

    # Parse [recording] section
    recording_section = data.get("recording", {})
    if not isinstance(recording_section, dict):
        recording_section = {}
    recording_mode = _validate_recording_mode(
        recording_section.get("mode", DEFAULT_RECORDING_MODE.value)
    )

    # Parse [wake_word] section
    wake_word_section = data.get("wake_word", {})
    if not isinstance(wake_word_section, dict):
        wake_word_section = {}
    wake_word = wake_word_section.get("phrase", DEFAULT_WAKE_WORD)
    if not isinstance(wake_word, str) or not wake_word.strip():
        logger.warning(
            "Invalid wake word %r. Using default: '%s'.",
            wake_word, DEFAULT_WAKE_WORD,
        )
        wake_word = DEFAULT_WAKE_WORD
    wake_word_threshold = wake_word_section.get("threshold", DEFAULT_WAKE_WORD_THRESHOLD)
    if not isinstance(wake_word_threshold, (int, float)) or wake_word_threshold <= 0:
        logger.warning(
            "Invalid wake word threshold %r. Using default: %.2f.",
            wake_word_threshold, DEFAULT_WAKE_WORD_THRESHOLD,
        )
        wake_word_threshold = DEFAULT_WAKE_WORD_THRESHOLD

    # Parse [output] section
    output_section = data.get("output", {})
    if not isinstance(output_section, dict):
        output_section = {}
    output_mode = _validate_output_mode(
        output_section.get("mode", DEFAULT_OUTPUT_MODE.value)
    )
    paste_target = _validate_paste_target(
        output_section.get("paste_target", "frontmost")
    )

    # Parse [vad] section
    vad_section = data.get("vad", {})
    if not isinstance(vad_section, dict):
        vad_section = {}
    silence_threshold_ms = _validate_silence_threshold(
        vad_section.get("silence_threshold_ms", DEFAULT_SILENCE_THRESHOLD_MS)
    )
    volume_threshold_db = _validate_volume_threshold(
        vad_section.get("volume_threshold_db", DEFAULT_VOLUME_THRESHOLD_DB)
    )

    # Parse [model] section
    model_section = data.get("model", {})
    if not isinstance(model_section, dict):
        model_section = {}
    model_path = _validate_model_path(
        model_section.get("path", DEFAULT_MODEL_PATH)
    )

    # Parse [audio] section
    audio_section = data.get("audio", {})
    if not isinstance(audio_section, dict):
        audio_section = {}
    audio_device_name = _validate_audio_device_name(
        audio_section.get("device_name", None)
    )

    # Parse [environment] section
    environment_section = data.get("environment", {})
    if not isinstance(environment_section, dict):
        environment_section = {}
    refresh_interval_s = _validate_refresh_interval(
        environment_section.get("refresh_interval_s", DEFAULT_REFRESH_INTERVAL_S)
    )
    calibration_margin_db = _validate_calibration_margin(
        environment_section.get("calibration_margin_db", DEFAULT_CALIBRATION_MARGIN_DB)
    )

    # Parse [session] section
    session_section = data.get("session", {})
    if not isinstance(session_section, dict):
        session_section = {}
    session_timeout_s = _validate_session_timeout(
        session_section.get("timeout_s", DEFAULT_SESSION_TIMEOUT_S)
    )

    return AppConfig(
        hotkey=HotkeyCombo(modifiers=modifiers, key=key),
        recording_mode=recording_mode,
        output_mode=output_mode,
        silence_threshold_ms=silence_threshold_ms,
        volume_threshold_db=volume_threshold_db,
        model_path=model_path,
        wake_word=wake_word,
        wake_word_threshold=wake_word_threshold,
        audio_device_name=audio_device_name,
        paste_target=paste_target,
        refresh_interval_s=refresh_interval_s,
        calibration_margin_db=calibration_margin_db,
        session_timeout_s=session_timeout_s,
    )


def config_to_toml(config: AppConfig) -> str:
    """Serialize an AppConfig to a TOML string."""
    modifiers = sorted(config.hotkey.modifiers)
    return f"""\
[hotkey]
modifiers = {modifiers}
key = "{config.hotkey.key}"

[recording]
mode = "{config.recording_mode.value}"

[output]
mode = "{config.output_mode.value}"
paste_target = "{config.paste_target}"

[vad]
silence_threshold_ms = {config.silence_threshold_ms}
volume_threshold_db = {config.volume_threshold_db}

[wake_word]
phrase = "{config.wake_word}"
threshold = {config.wake_word_threshold:.0e}

[model]
path = "{config.model_path.as_posix()}"

[audio]
device_name = "{config.audio_device_name or ''}"

[environment]
refresh_interval_s = {config.refresh_interval_s:.0f}
calibration_margin_db = {config.calibration_margin_db:.1f}

[session]
timeout_s = {config.session_timeout_s:.0f}
"""


def write_default_config(config_path: Optional[Path] = None) -> Path:
    """Write the default config file. Returns the path written."""
    if config_path is None:
        config_path = PathResolver.config_path()
    toml_str = config_to_toml(_default_config())
    config_path.write_text(toml_str, encoding="utf-8")
    logger.info("Wrote default config to %s", config_path)
    return config_path
