"""Application controller — orchestrates the dictation state machine.

State flow:
    Idle → Recording → Transcribing → Delivering → Idle
      ↑        │              │             │
      └────────┴──────────────┴─────────────┘  (any error → Idle)
"""

import logging
import threading

from src.audio_capture import AudioCapture, AudioCaptureError
from src.config_manager import AppConfig, RecordingMode
from src.backends import HotkeyListener, OutputHandler, SystemTray
from src.models import AppStatus, AudioBuffer, HotkeyEvent, OutputMode, SEND_SKIPPED
from src.dropbox import append_dictation
from src.output_trigger import extract_send_intent
from src.transcription_engine import TranscriptionEngine, TranscriptionError
from src.vad_engine import VADEngine

logger = logging.getLogger(__name__)


class AppController:
    """Central orchestrator implementing the dictation state machine.

    Wires together hotkey listener, audio capture, VAD,
    transcription, output, and system tray. Handles errors
    at every transition — never crashes, always returns to idle.
    """

    def __init__(
        self,
        config: AppConfig,
        tray: SystemTray,
        hotkey_listener: HotkeyListener,
        audio_capture: AudioCapture,
        vad_engine: VADEngine,
        transcription_engine: TranscriptionEngine,
        output_handler: OutputHandler,
        wake_word_listener: object = None,
    ):
        self._config = config
        self._tray = tray
        self._hotkey_listener = hotkey_listener
        self._audio_capture = audio_capture
        self._vad_engine = vad_engine
        self._transcription_engine = transcription_engine
        self._output_handler = output_handler
        self._wake_word_listener = wake_word_listener

        self._status: AppStatus = AppStatus.IDLE
        self._lock = threading.Lock()
        self._status_callback: object = None  # called on status changes
        # Guards against double-dispatching the auto-stop worker
        self._stop_dispatched = False

        # Transcription queue — processed synchronously on main thread
        self._pending_transcribe: list[AudioBuffer] = []
        self._transcribe_cond = threading.Condition(self._lock)

        # Wire callbacks
        self._hotkey_listener.set_on_activated(self._on_hotkey_activated)
        self._hotkey_listener.set_on_released(self._on_hotkey_released)
        self._audio_capture.set_chunk_callback(self._on_audio_chunk)

        if self._wake_word_listener:
            self._wake_word_listener.set_on_detected(self._on_wake_word)

        # Push-to-talk tracking
        self._push_to_talk_active: bool = False

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def status(self) -> AppStatus:
        return self._status

    def start(self) -> None:
        """Start the application — begin listening for hotkey or wake word."""
        logger.info("AppController starting.")
        self._set_status(AppStatus.IDLE)
        self._hotkey_listener.start()

        # In wake word mode, start continuous listening.
        # MUST run before tray.start(): on macOS the tray's rumps run loop
        # blocks the calling thread, so anything after it never executes.
        if (
            self._config.recording_mode == RecordingMode.WAKE_WORD
            and self._wake_word_listener
        ):
            self._wake_word_listener.start()
            logger.info(
                "Wake word mode active: '%s' (threshold %.2f)",
                self._config.wake_word,
                self._config.wake_word_threshold,
            )

        self._tray.start()

    def stop(self) -> None:
        """Stop the application gracefully."""
        logger.info("AppController stopping.")
        with self._lock:
            self._status = AppStatus.IDLE
            self._pending_transcribe.clear()
        self._hotkey_listener.stop()
        if self._wake_word_listener:
            self._wake_word_listener.stop()
        if self._audio_capture.is_recording:
            try:
                self._audio_capture.stop_recording()
            except Exception:
                pass
        self._tray.stop()

    def process_queue(self, timeout: float = 1.0) -> None:
        """Process pending transcription work on the main thread.

        Called from the main event loop. Blocks up to `timeout` seconds
        waiting for work, then processes one transcription if queued.
        """
        buffer = None
        with self._lock:
            if not self._pending_transcribe:
                self._transcribe_cond.wait(timeout=timeout)
            if self._pending_transcribe:
                buffer = self._pending_transcribe.pop(0)

        if buffer is not None:
            self._do_transcribe(buffer)

    # ── Status management ──────────────────────────────────────────────

    def set_status_callback(self, callback) -> None:
        """Register a callback for status changes: callback(AppStatus, detail)."""
        self._status_callback = callback

    def _set_status(self, status: AppStatus) -> None:
        with self._lock:
            self._status = status
        self._tray.set_status(status)
        if self._status_callback:
            self._status_callback(status)

    # ── Hotkey callbacks ───────────────────────────────────────────────

    def _on_hotkey_activated(self, event: HotkeyEvent) -> None:
        """Hotkey pressed — start recording or toggle stop."""
        mode = self._config.recording_mode

        if mode == RecordingMode.PUSH_TO_TALK:
            self._start_recording()
        elif mode in (RecordingMode.TOGGLE, RecordingMode.WAKE_WORD):
            if self._status == AppStatus.IDLE:
                self._start_recording()
            elif self._status == AppStatus.RECORDING:
                self._stop_recording()
            # Ignore if transcribing or error — let them finish/fail

    def _on_hotkey_released(self, event: HotkeyEvent) -> None:
        """Hotkey released — stop recording in push-to-talk mode."""
        if self._config.recording_mode == RecordingMode.PUSH_TO_TALK:
            if self._status == AppStatus.RECORDING:
                self._stop_recording()

    # ── Wake word callback ─────────────────────────────────────────────

    def _on_wake_word(self) -> None:
        """Wake word detected — start recording."""
        if self._status == AppStatus.IDLE:
            logger.info("Wake word triggered — starting recording.")
            self._start_recording()

    # ── Recording flow ─────────────────────────────────────────────────

    def _start_recording(self) -> None:
        """Begin recording from the microphone."""
        if self._status != AppStatus.IDLE:
            return

        # Pause the wake word listener FIRST: pause() blocks until its
        # PortAudio stream is closed, so the recording stream below gets
        # exclusive mic access. Opening both streams concurrently fails
        # with PaErrorCode -9986 and/or captures zero samples.
        if self._wake_word_listener:
            self._wake_word_listener.pause()

        self._vad_engine.reset()
        self._stop_dispatched = False

        try:
            self._audio_capture.start_recording()
        except AudioCaptureError as e:
            logger.error("Failed to start recording: %s", e)
            self._tray.show_notification("Whisper VTT", f"Microphone error: {e}")
            if self._wake_word_listener:
                self._wake_word_listener.resume()
            return

        self._set_status(AppStatus.RECORDING)
        logger.info("Recording started.")
        self._tray.show_notification("Whisper VTT", "Recording started")

    def _stop_recording(self) -> None:
        """Stop recording and begin transcription."""
        if self._status != AppStatus.RECORDING:
            return

        try:
            buffer = self._audio_capture.stop_recording()
        except AudioCaptureError as e:
            logger.error("Failed to stop recording: %s", e)
            self._set_status(AppStatus.IDLE)
            return

        # Discard very short recordings (< 0.1s)
        if buffer.duration_seconds < 0.1:
            logger.debug("Recording too short (%.2fs), discarding.", buffer.duration_seconds)
            self._set_status(AppStatus.IDLE)
            if self._wake_word_listener:
                self._wake_word_listener.resume()
            return

        self._set_status(AppStatus.TRANSCRIBING)
        self._tray.show_notification(
            "Whisper VTT", "Recording stopped — transcribing…"
        )
        with self._lock:
            self._pending_transcribe.append(buffer)
            self._transcribe_cond.notify()

    # ── Audio chunk callback (VAD) ─────────────────────────────────────

    def _on_audio_chunk(self, chunk) -> None:
        """Process each audio chunk through VAD.

        NOTE: this runs inside the recording stream's PortAudio callback.
        _stop_recording closes the stream — doing that from within the
        stream's own callback deadlocks PortAudio (the process freezes,
        mic stays wedged). So the stop is handed off to a worker thread
        and this callback returns immediately.
        """
        silence_detected = self._vad_engine.process_chunk(chunk)
        if (
            silence_detected
            and self._status == AppStatus.RECORDING
            and not self._stop_dispatched
        ):
            logger.info("Silence detected, auto-stopping recording.")
            logger.debug(
                "(peak %.1f dB, threshold %.1f dB)",
                self._vad_engine.peak_db,
                self._vad_engine.volume_threshold_db,
            )
            self._stop_dispatched = True
            threading.Thread(
                target=self._stop_recording,
                daemon=True,
                name="stop-recording",
            ).start()

    # ── Transcription (runs synchronously on main thread) ─────────────

    def _do_transcribe(self, buffer: AudioBuffer) -> None:
        """Run transcription and deliver the result."""
        logger.info(
            "Transcribing %.1fs of audio (%d samples)...",
            buffer.duration_seconds,
            len(buffer.samples),
        )

        try:
            text = self._transcription_engine.transcribe(
                buffer.samples,
                buffer.sample_rate,
            )
        except TranscriptionError as e:
            logger.error("Transcription failed: %s", e)
            self._tray.show_notification("Whisper VTT", f"Transcription error: {e}")
            self._set_status(AppStatus.IDLE)
            if self._wake_word_listener:
                self._wake_word_listener.resume()
            return

        if text:
            # Drop box side channel — every transcription is journaled for
            # pi's whisper-vtt skill (tasks, lessons, journal, status).
            # Never blocks or raises; the paste/send path is primary.
            # In auto_send mode the spoken 'Enter' trigger is a command,
            # not dictation — strip it so the skill never routes it.
            journal_text = text
            if self._output_handler.mode == OutputMode.AUTO_SEND:
                journal_text, _ = extract_send_intent(text)
            if journal_text:
                append_dictation(journal_text)
            self._deliver_text(text)

        self._set_status(AppStatus.IDLE)
        logger.info("Dictation cycle complete.")
        logger.info("─" * 50)

        if self._wake_word_listener:
            self._wake_word_listener.resume()

    def _deliver_text(self, text: str) -> None:
        preview = text if len(text) <= 50 else text[:50] + "..."
        try:
            result = self._output_handler.deliver(text)
        except Exception as e:
            logger.error("Failed to deliver text: %s", e)
            self._tray.show_notification(
                "Whisper VTT",
                f"Could not set clipboard: {e}",
            )
        else:
            self._tray.show_notification(
                "Whisper VTT",
                f"Transcribed: {preview}",
                play_sound=False,
            )
            if result == SEND_SKIPPED:
                self._tray.show_notification(
                    "Whisper VTT",
                    "Auto-send skipped: pi's window isn't frontmost — "
                    "text is on the clipboard.",
                    play_sound=True,
                )
