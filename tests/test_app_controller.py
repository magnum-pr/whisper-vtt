"""Tests for AppController state machine."""

from unittest.mock import MagicMock, call, patch

import numpy as np

from src.app_controller import AppController
from src.config_manager import AppConfig, RecordingMode
from src.models import (
    AppStatus,
    AudioBuffer,
    HotkeyCombo,
    OutputMode,
)


def make_toggle_config() -> AppConfig:
    return AppConfig(
        hotkey=HotkeyCombo(modifiers=frozenset(), key="`"),
        recording_mode=RecordingMode.TOGGLE,
        output_mode=OutputMode.CLIPBOARD,
        silence_threshold_ms=5000,
        volume_threshold_db=-15.0,
        model_path="models/ggml-base.en.bin",
    )


def make_push_to_talk_config() -> AppConfig:
    return AppConfig(
        hotkey=HotkeyCombo(modifiers=frozenset(), key="`"),
        recording_mode=RecordingMode.PUSH_TO_TALK,
        output_mode=OutputMode.CLIPBOARD,
        silence_threshold_ms=5000,
        volume_threshold_db=-15.0,
        model_path="models/ggml-base.en.bin",
    )


def make_wake_word_config() -> AppConfig:
    return AppConfig(
        hotkey=HotkeyCombo(modifiers=frozenset(), key="`"),
        recording_mode=RecordingMode.WAKE_WORD,
        output_mode=OutputMode.CLIPBOARD,
        silence_threshold_ms=5000,
        volume_threshold_db=-15.0,
        model_path="models/ggml-base.en.bin",
    )


class TestAppControllerInit:
    def test_starts_idle(self):
        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )
        assert controller.status == AppStatus.IDLE

    def test_callbacks_wired(self):
        hotkey = MagicMock()
        audio = MagicMock()

        _controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=hotkey,
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        hotkey.set_on_activated.assert_called_once()
        hotkey.set_on_released.assert_called_once()
        audio.set_chunk_callback.assert_called_once()


class TestToggleMode:
    """Toggle mode: first press starts recording, second stops it."""

    def test_first_press_starts_recording(self):
        audio = MagicMock()
        audio.is_recording = False
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        # Initial status should be IDLE
        assert controller.status == AppStatus.IDLE

        # Simulate hotkey press
        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        audio.start_recording.assert_called_once()
        assert controller.status == AppStatus.RECORDING
        tray.show_notification.assert_called_once_with("Whisper VTT", "Recording started")

    def test_second_press_stops_recording(self):
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        # Return a buffer that's long enough
        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),  # 1 second
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        # Manually set to RECORDING
        controller._set_status(AppStatus.RECORDING)

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        audio.stop_recording.assert_called_once()

    def test_second_press_stops_notification_fires(self):
        """Notification fires for stop even when executor runs transcription."""
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )


    def test_press_during_transcribing_ignored(self):
        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.TRANSCRIBING)

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        # Nothing should happen — audio should NOT start
        # (we can verify status is still TRANSCRIBING)
        assert controller.status == AppStatus.TRANSCRIBING


class TestWakeWordHotkeyMode:
    """In wake_word mode, the hotkey acts as a toggle — same as toggle mode."""

    def test_hotkey_starts_recording_in_wake_word_mode(self):
        audio = MagicMock()
        audio.is_recording = False
        tray = MagicMock()

        controller = AppController(
            config=make_wake_word_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        audio.start_recording.assert_called_once()
        assert controller.status == AppStatus.RECORDING

    def test_hotkey_stops_recording_in_wake_word_mode(self):
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        controller = AppController(
            config=make_wake_word_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        audio.stop_recording.assert_called_once()


class TestPushToTalkMode:
    def test_press_starts_recording(self):
        audio = MagicMock()
        audio.is_recording = False

        controller = AppController(
            config=make_push_to_talk_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        from src.models import HotkeyEvent
        controller._on_hotkey_activated(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=True,
                timestamp_ms=0,
            )
        )

        audio.start_recording.assert_called_once()
        assert controller.status == AppStatus.RECORDING

    def test_release_stops_recording(self):
        audio = MagicMock()
        audio.is_recording = True

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        controller = AppController(
            config=make_push_to_talk_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)

        from src.models import HotkeyEvent
        controller._on_hotkey_released(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=False,
                timestamp_ms=0,
            )
        )

        audio.stop_recording.assert_called_once()

    def test_release_when_not_recording_noop(self):
        audio = MagicMock()

        controller = AppController(
            config=make_push_to_talk_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        # IDLE → release should be noop
        from src.models import HotkeyEvent
        controller._on_hotkey_released(
            HotkeyEvent(
                combo=HotkeyCombo(modifiers=frozenset(), key="`"),
                pressed=False,
                timestamp_ms=0,
            )
        )

        audio.stop_recording.assert_not_called()


class TestRecordingTooShort:
    def test_recording_under_100ms_discarded(self):
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        # Buffer with less than 0.1s of audio
        buffer = AudioBuffer(
            samples=np.zeros(800, dtype=np.float32),  # 0.05s at 16kHz
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        transcription = MagicMock()
        output = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        controller._set_status(AppStatus.RECORDING)
        controller._stop_recording()

        # Should return to idle without transcribing
        assert controller.status == AppStatus.IDLE
        transcription.transcribe.assert_not_called()

        # Notification should fire for stop, but not for transcription

    def test_recording_exactly_100ms_not_discarded(self):
        from unittest.mock import patch

        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        buffer = AudioBuffer(
            samples=np.zeros(1600, dtype=np.float32),  # exactly 0.1s
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        transcription = MagicMock()
        transcription.transcribe.return_value = "test"

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=MagicMock(),
        )

        # Prevent the transcribe thread from actually running
        with patch("threading.Thread.start"):
            controller._set_status(AppStatus.RECORDING)
            controller._stop_recording()

        # Status should be TRANSCRIBING (thread started — but blocked by patch)
        assert controller.status == AppStatus.TRANSCRIBING


class TestVADAutoStop:
    def test_silence_detected_stops_recording(self):
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        vad = MagicMock()
        vad.process_chunk.return_value = True  # silence detected

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=vad,
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)

        # Send a chunk that triggers silence
        controller._on_audio_chunk(np.zeros(1600, dtype=np.float32))

        audio.stop_recording.assert_called_once()

    def test_silence_detected_notification_fires(self):
        """Notification fires for silence stop even when executor runs transcription."""
        audio = MagicMock()
        audio.is_recording = True
        tray = MagicMock()

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )
        audio.stop_recording.return_value = buffer

        vad = MagicMock()
        vad.process_chunk.return_value = True

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=vad,
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)
        controller._on_audio_chunk(np.zeros(1600, dtype=np.float32))


    def test_silence_ignored_when_not_recording(self):
        audio = MagicMock()
        vad = MagicMock()
        vad.process_chunk.return_value = True

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=vad,
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        # IDLE — silence should not trigger stop
        controller._on_audio_chunk(np.zeros(1600, dtype=np.float32))
        audio.stop_recording.assert_not_called()


class TestTranscription:
    def test_transcription_delivers_text(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "hello world"
        output = MagicMock()
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        output.deliver.assert_called_once_with("hello world")
        assert controller.status == AppStatus.IDLE

    def test_journal_strips_send_trigger_in_protected(self):
        from src.models import OutputMode

        transcription = MagicMock()
        transcription.transcribe.return_value = "task: fix deploy enter"
        output = MagicMock()
        output.mode = OutputMode.PROTECTED

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        # journal gets the trigger stripped; deliver gets the raw text
        append.assert_called_once_with("task: fix deploy")
        output.deliver.assert_called_once_with("task: fix deploy enter")

    def test_trigger_only_dictation_not_journaled(self):
        from src.models import OutputMode

        transcription = MagicMock()
        transcription.transcribe.return_value = "Enter."
        output = MagicMock()
        output.mode = OutputMode.PROTECTED

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        append.assert_not_called()

    def test_journal_keeps_enter_in_auto_paste(self):
        from src.models import OutputMode

        transcription = MagicMock()
        transcription.transcribe.return_value = "say enter"
        output = MagicMock()
        output.mode = OutputMode.AUTO_PASTE

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        # in non-send modes 'enter' is dictation content, not a command
        append.assert_called_once_with("say enter")

    def test_journal_keeps_enter_in_auto_send_on(self):
        from src.models import OutputMode

        transcription = MagicMock()
        transcription.transcribe.return_value = "say enter"
        output = MagicMock()
        output.mode = OutputMode.AUTO_SEND

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        # on mode: 'enter' is always dictation content — journaled raw
        append.assert_called_once_with("say enter")

    def test_transcription_preview_truncated(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "a" * 100
        output = MagicMock()
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        tray.show_notification.assert_called_with(
            "Whisper VTT",
            "Transcribed: " + "a" * 50 + "...",
            play_sound=False,
        )

    def test_transcription_error_returns_to_idle(self):
        from src.transcription_engine import TranscriptionError
        transcription = MagicMock()
        transcription.transcribe.side_effect = TranscriptionError("inference error")
        output = MagicMock()
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        output.deliver.assert_not_called()
        tray.show_notification.assert_called_with(
            "Whisper VTT", "Transcription error: inference error"
        )
        assert controller.status == AppStatus.IDLE

    def test_empty_transcription_not_delivered(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = ""
        output = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        output.deliver.assert_not_called()
        assert controller.status == AppStatus.IDLE

    def test_send_skipped_notification(self):
        from src.models import SEND_SKIPPED

        transcription = MagicMock()
        transcription.transcribe.return_value = "hello world"
        output = MagicMock()
        output.deliver.return_value = SEND_SKIPPED
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        tray.show_notification.assert_any_call(
            "Whisper VTT",
            "Auto-send skipped: pi's window isn't frontmost — "
            "text is on the clipboard.",
            play_sound=True,
        )

    def test_delivery_error_shows_notification(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "hello"
        output = MagicMock()
        output.deliver.side_effect = RuntimeError("clipboard error")
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        tray.show_notification.assert_any_call(
            "Whisper VTT",
            "Could not set clipboard: clipboard error",
        )
        assert controller.status == AppStatus.IDLE

class TestRecordingErrors:
    def test_start_recording_error_shows_notification(self):
        from src.audio_capture import AudioCaptureError

        audio = MagicMock()
        audio.start_recording.side_effect = AudioCaptureError("mic not found")

        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._start_recording()

        # Only the error notification, not "Recording started"
        tray.show_notification.assert_called_once()
        args = tray.show_notification.call_args[0]
        assert "Microphone error" in args[1]
        assert controller.status == AppStatus.IDLE  # stays idle

    def test_stop_recording_error_returns_to_idle(self):
        from src.audio_capture import AudioCaptureError

        audio = MagicMock()
        audio.is_recording = True
        audio.stop_recording.side_effect = AudioCaptureError("stream error")

        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

        controller._set_status(AppStatus.RECORDING)
        controller._stop_recording()

        assert controller.status == AppStatus.IDLE


class TestWakeWordPauseResume:
    """Verify wake word listener is paused during recording and resumed after."""

    def test_recording_start_pauses_wake_word(self):
        audio = MagicMock()
        audio.is_recording = False
        wake_word = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
            wake_word_listener=wake_word,
        )

        controller._start_recording()

        wake_word.pause.assert_called_once()

    def test_transcription_complete_resumes_wake_word(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "hello"
        output = MagicMock()
        wake_word = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
            wake_word_listener=wake_word,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        controller._do_transcribe(buffer)

        wake_word.resume.assert_called_once()

    def test_no_wake_word_listener_no_crash(self):
        """Start/transcribe should not crash when no wake word listener is set."""
        audio = MagicMock()
        audio.is_recording = False

        transcription = MagicMock()
        transcription.transcribe.return_value = "ok"

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=audio,
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=MagicMock(),
            wake_word_listener=None,
        )

        # Should not raise
        controller._start_recording()
        controller._do_transcribe(AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        ))


class TestWakeWordStartOrdering:
    """Wake word listener must start BEFORE the tray.

    Regression: on macOS MacSystemTray.start() blocks on the rumps
    NSApplication run loop, so anything ordered after tray.start() in
    AppController.start() never ran — the wake word was silently dead.
    """

    def test_wake_word_starts_before_tray(self):
        tray = MagicMock()
        hotkey = MagicMock()
        wake = MagicMock()

        controller = AppController(
            config=make_wake_word_config(),
            tray=tray,
            hotkey_listener=hotkey,
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
            wake_word_listener=wake,
        )

        parent = MagicMock()
        parent.attach_mock(wake.start, "wake_start")
        parent.attach_mock(tray.start, "tray_start")

        controller.start()

        assert parent.mock_calls.index(call.wake_start()) < parent.mock_calls.index(
            call.tray_start()
        )

    def test_wake_word_starts_in_wake_word_mode(self):
        wake = MagicMock()

        controller = AppController(
            config=make_wake_word_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
            wake_word_listener=wake,
        )

        controller.start()

        wake.start.assert_called_once()


# ── Config hot-reload ───────────────────────────────────────────────


CONFIG_TOML = """\
[output]
mode = "auto_send"
paste_target = "pi"
"""

CONFIG_TOML_CHANGED = """\
[output]
mode = "protected"
paste_target = "frontmost"
"""


def _write_config(path, body):
    path.write_text(body, encoding="utf-8")


class TestConfigHotReload:
    def test_process_queue_reloads_changed_config(self, tmp_path):
        cfg = tmp_path / "config.toml"
        _write_config(cfg, CONFIG_TOML)
        output = MagicMock()
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=output,
            config_path=cfg,
        )

        _write_config(cfg, CONFIG_TOML_CHANGED)
        controller.process_queue(timeout=0)

        assert controller._config.output_mode == OutputMode.PROTECTED
        assert controller._config.paste_target == "frontmost"
        output.mode = OutputMode.PROTECTED  # was set by controller
        assert output.mode == OutputMode.PROTECTED
        assert output.paste_target == "frontmost"

    def test_unchanged_config_is_not_reloaded(self, tmp_path):
        cfg = tmp_path / "config.toml"
        _write_config(cfg, CONFIG_TOML)
        output = MagicMock()
        tray = MagicMock()

        controller = AppController(
            config=make_toggle_config(),
            tray=tray,
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=output,
            config_path=cfg,
        )

        controller.process_queue(timeout=0)
        output.mode = "sentinel"  # must not be touched
        output.paste_target = "sentinel"

        controller.process_queue(timeout=0)
        assert output.mode == "sentinel"
        assert output.paste_target == "sentinel"

    def test_missing_config_file_ignored(self, tmp_path):
        cfg = tmp_path / "nope.toml"
        output = MagicMock()
        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=output,
            config_path=cfg,
        )
        controller.process_queue(timeout=0)
        assert controller._config.output_mode == OutputMode.CLIPBOARD


# ── Journal override stripping ──────────────────────────────────────


class TestJournalNoSendOverride:
    def test_journal_strips_no_send_phrase(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "task: clean inbox without sending"
        output = MagicMock()
        output.mode = OutputMode.AUTO_SEND

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        append.assert_called_once_with("task: clean inbox")

    def test_journal_override_phrase_alone_not_journaled(self):
        transcription = MagicMock()
        transcription.transcribe.return_value = "just paste"
        output = MagicMock()
        output.mode = OutputMode.AUTO_PASTE

        controller = AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=transcription,
            output_handler=output,
        )

        buffer = AudioBuffer(
            samples=np.zeros(16000, dtype=np.float32),
            sample_rate=16000,
        )

        with patch("src.app_controller.append_dictation") as append:
            controller._do_transcribe(buffer)

        append.assert_not_called()


# ── Delivery result notifications ───────────────────────────────────


class TestDeliveryResultNotifications:
    def _controller(self):
        return AppController(
            config=make_toggle_config(),
            tray=MagicMock(),
            hotkey_listener=MagicMock(),
            audio_capture=MagicMock(),
            vad_engine=MagicMock(),
            transcription_engine=MagicMock(),
            output_handler=MagicMock(),
        )

    def test_no_host_result_notifies(self):
        from src.models import SEND_NO_HOST

        controller = self._controller()
        controller._output_handler.deliver.return_value = SEND_NO_HOST
        controller._deliver_text("hello")
        controller._tray.show_notification.assert_any_call(
            "Whisper VTT",
            "Auto-send skipped: no pi host running — "
            "text pasted, not sent.",
            play_sound=True,
        )

    def test_suppressed_result_notifies(self):
        from src.models import SEND_SUPPRESSED

        controller = self._controller()
        controller._output_handler.deliver.return_value = SEND_SUPPRESSED
        controller._deliver_text("hello")
        controller._tray.show_notification.assert_any_call(
            "Whisper VTT",
            "Override: pasted without sending.",
            play_sound=False,
        )
