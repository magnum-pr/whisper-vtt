"""Application controller — orchestrates the dictation state machine.

State flow:
    Idle → Recording → Transcribing → Delivering → Idle
      ↑        │              │             │
      └────────┴──────────────┴─────────────┘  (any error → Idle)

Dictation sessions: "start a new session for X" opens a session; each
utterance appends an item (speech onset re-arms, no wake word needed);
"that's all" commits the compiled list to the drop box and hands it to
pi. Idle timeout auto-commits.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from src.audio_capture import AudioCapture, AudioCaptureError
from src.config_manager import AppConfig, RecordingMode, load_config
from src.backends import HotkeyListener, OutputHandler, SystemTray
from src.models import (
    AppStatus,
    AudioBuffer,
    HotkeyEvent,
    OutputMode,
    SEND_NO_HOST,
    SEND_SKIPPED,
    SEND_SUPPRESSED,
)
from src.dropbox import append_dictation
from src.environment import GLOBAL_ENV
from src.output_trigger import extract_no_send_intent, extract_send_intent
from src.paths import PathResolver
from src.session import SessionState, is_scratch, is_session_end, parse_session_start
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
        config_path: Optional[Path] = None,
    ):
        self._config = config
        self._config_path = config_path if config_path is not None else PathResolver.config_path()
        self._config_signature = self._config_file_signature()
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
            self._wake_word_listener.set_on_onset(self._on_speech_onset)

        # Dictation session ("start a new session for X")
        self._session: Optional[SessionState] = None
        self._session_last_activity: float = 0.0


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
        # Commit an open session to the drop box before exiting — work
        # is never lost; pi picks it up on the next 'process my dictations'.
        if self._session is not None and self._session.items:
            append_dictation(
                f"Session: {self._session.title}",
                kind="session",
                title=self._session.title,
                items=list(self._session.items),
            )
        self._session = None
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
        self._reload_config_if_changed()
        self._handle_device_change()
        self._check_session_timeout()
        buffer = None
        with self._lock:
            if not self._pending_transcribe:
                self._transcribe_cond.wait(timeout=timeout)
            if self._pending_transcribe:
                buffer = self._pending_transcribe.pop(0)

        if buffer is not None:
            self._do_transcribe(buffer)

    def _handle_device_change(self) -> None:
        """React to an OS default input device change (latched by the
        environment refresher). While idle, restart the wake word stream
        so it reopens on the new default; the recorder resolves fresh at
        every start anyway, so nothing else needs to move. While busy,
        leave the change latched for a later tick.
        """
        if self._wake_word_listener is None:
            GLOBAL_ENV.consume_device_change()
            return
        if GLOBAL_ENV.pending_device_change() is None:
            return
        if self._status != AppStatus.IDLE:
            return  # busy — handle on a later tick
        new_device = GLOBAL_ENV.consume_device_change()
        if new_device is None:
            return
        logger.info(
            "Restarting wake word listener on OS default device %r.",
            new_device,
        )
        self._wake_word_listener.stop()
        self._wake_word_listener.start()

    # ── Config hot-reload ───────────────────────────────────────────

    def _config_file_signature(self):
        """(mtime_ns, size) of config.toml, or None when unreadable."""
        try:
            st = self._config_path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _reload_config_if_changed(self) -> None:
        """Hot-reload config.toml when it changed on disk.

        Polled from process_queue (once per queue tick, ~1s), so a
        mode switch — e.g. via the voice bridge scripts/set_mode.py —
        applies on the next dictation with no whisper restart.

        Propagated live: output_mode and paste_target (the settings the
        voice bridge edits). Recording-mode, hotkey, and model changes
        still require a restart — swapping those mid-run risks a wedged
        mic or tap.
        """
        sig = self._config_file_signature()
        if sig == self._config_signature:
            return
        self._config_signature = sig
        if sig is None:
            return
        try:
            new_config = load_config(self._config_path)
        except Exception as e:
            logger.warning("Config hot-reload failed: %s", e)
            return
        self._config = new_config
        output_handler = self._output_handler
        if hasattr(output_handler, "mode"):
            output_handler.mode = new_config.output_mode
        if hasattr(output_handler, "paste_target"):
            output_handler.paste_target = new_config.paste_target
        logger.info(
            "Config hot-reloaded: output_mode=%s, paste_target=%s",
            new_config.output_mode.value,
            new_config.paste_target,
        )
        self._tray.show_notification(
            "Whisper VTT",
            f"Config reloaded — mode: {new_config.output_mode.value}",
            play_sound=False,
        )

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

    def _on_speech_onset(self) -> None:
        """Speech onset detected (session mode) — start recording."""
        if self._status == AppStatus.IDLE:
            logger.info("Speech onset triggered — starting recording.")
            self._start_recording()

    # ── Recording flow ─────────────────────────────────────────────────

    def _start_recording(self) -> None:
        """Begin recording from the microphone."""
        if self._status != AppStatus.IDLE:
            return

        # Calibrated silence threshold: ambient floor (fed by the idle
        # wake word stream) + margin, clamped. Falls back to the static
        # config threshold while the floor warms up (~3s of idle audio).
        calibrated = GLOBAL_ENV.silence_threshold_db(
            self._config.calibration_margin_db
        )
        if calibrated is not None:
            self._vad_engine.volume_threshold_db = calibrated
            logger.debug(
                "VAD silence threshold calibrated: %.1f dB (floor + %.1f)",
                calibrated,
                self._config.calibration_margin_db,
            )
        else:
            self._vad_engine.volume_threshold_db = self._config.volume_threshold_db

        # Pause the wake word listener FIRST: pause() blocks until its
        # PortAudio stream is closed, so the recording stream below gets
        # exclusive mic access. Opening both streams concurrently fails
        # with PaErrorCode -9986 and/or captures zero samples.
        if self._wake_word_listener:
            self._wake_word_listener.pause()

        self._vad_engine.reset()
        self._stop_dispatched = False

        # The mic opens FIRST — recording starts the instant the wake
        # word/onset fires. The notification (and its beep) comes after;
        # a pre-open chime waits on afplay, which hangs on some machines
        # (2s timeout), and dictation spoken right after "jarvis" was
        # lost to the delay. The beep leaking into the audio is a known,
        # accepted trade-off for now (chime fix deferred).
        try:
            self._audio_capture.start_recording()
        except AudioCaptureError as e:
            logger.error("Failed to start recording: %s", e)
            self._set_status(AppStatus.IDLE)
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
            self._finish_cycle()
            return

        if text:
            self._route_transcription(text)

        self._finish_cycle()

    def _finish_cycle(self) -> None:
        """Return to idle after a dictation cycle.

        Re-arms speech onset when a session is open, so the next
        utterance starts recording without a wake word; otherwise the
        listener resumes in plain wake word mode.
        """
        self._set_status(AppStatus.IDLE)
        logger.info("Dictation cycle complete.")
        logger.info("─" * 50)

        if self._wake_word_listener:
            if self._session is not None:
                threshold = GLOBAL_ENV.silence_threshold_db(
                    self._config.calibration_margin_db
                )
                self._wake_word_listener.set_onset_enabled(True, threshold)
            else:
                self._wake_word_listener.set_onset_enabled(False)
            self._wake_word_listener.resume()

    # ── Dictation session routing ──────────────────────────────────────

    def _route_transcription(self, text: str) -> None:
        """Route a transcription: session commands vs. plain dictation."""
        if self._session is None:
            topic = parse_session_start(text)
            if topic is not None:
                self._start_session(topic)
                return
            # Plain single dictation: journal + deliver as usual, then
            # stay armed for follow-ups (sticky mode) when enabled.
            self._journal_and_deliver(text)
            if self._config.sticky_sessions:
                self._start_sticky_session()
            return

        if self._session.sticky:
            self._route_sticky(text)
            return

        # Compile session — commands first.
        if is_session_end(text):
            self._commit_session(timed_out=False)
            return
        if is_scratch(text):
            self._scratch_item()
            return
        topic = parse_session_start(text)
        if topic is not None:
            # "start a new session for X" mid-session: commit the
            # current one, open a fresh one.
            self._commit_session(timed_out=False)
            self._start_session(topic)
            return

        item = text.strip()
        if item:
            self._session.items.append(item)
            self._session_last_activity = time.monotonic()
            self._tray.set_session_indicator(str(len(self._session.items)))
            logger.info(
                "Session '%s' item %d: %r",
                self._session.title,
                len(self._session.items),
                item[:80],
            )
            self._tray.show_notification(
                "Whisper VTT",
                f"Added ({len(self._session.items)}) to "
                f"'{self._session.title}'",
                play_sound=True,
                sound="/System/Library/Sounds/Tink.aiff",
                notify=False,
            )

    def _route_sticky(self, text: str) -> None:
        """Sticky follow-up mode: deliver live, no wake word, until
        'that's all' or the lapse gate disarms."""
        if is_session_end(text):
            self._close_sticky_session(spoken=True)
            return
        if is_scratch(text):
            # Nothing accumulates in sticky mode — ignore, but keep the
            # follow-up window open.
            self._session_last_activity = time.monotonic()
            return
        topic = parse_session_start(text)
        if topic is not None:
            # Switch to a compile session mid-follow-up.
            self._close_sticky_session(spoken=False)
            self._start_session(topic)
            return
        self._session_last_activity = time.monotonic()
        self._journal_and_deliver(text)

    def _journal_and_deliver(self, text: str) -> None:
        """Journal one dictation to the drop box and deliver it."""
        journal_text = text
        if self._output_handler.mode == OutputMode.PROTECTED:
            journal_text, _ = extract_send_intent(text)
        # The no-send override phrase is a command, not dictation —
        # strip it so the skill never routes it.
        journal_text, _ = extract_no_send_intent(journal_text)
        if journal_text:
            append_dictation(journal_text)
        self._deliver_text(text)

    def _start_sticky_session(self) -> None:
        """Arm follow-up listening after a plain dictation.

        Silent (menu bar dot only) — the user just dictated; a chime
        after every command would be noise.
        """
        self._session = SessionState(title="", sticky=True)
        self._session_last_activity = time.monotonic()
        self._tray.set_session_indicator("●")
        logger.info("Sticky follow-up armed.")

    def _close_sticky_session(self, spoken: bool) -> None:
        """Disarm follow-up listening."""
        self._session = None
        self._tray.set_session_indicator("")
        if spoken:
            self._tray.show_notification(
                "Whisper VTT",
                "Follow-up listening off.",
                play_sound=True,
                sound="/System/Library/Sounds/Tink.aiff",
            )
        logger.info("Sticky follow-up ended.")

    def _start_session(self, topic: str) -> None:
        """Open a dictation session."""
        self._session = SessionState(title=topic)
        if not self._session.title:
            self._session.title = self._session.default_title()
        self._session_last_activity = time.monotonic()
        self._tray.set_session_indicator("●")
        self._tray.show_notification(
            "Whisper VTT",
            f"Session started: {self._session.title} — listening…",
            play_sound=True,
        )
        logger.info("Session started: '%s'", self._session.title)

    def _scratch_item(self) -> None:
        """Drop the last session item ("scratch that")."""
        self._session_last_activity = time.monotonic()
        if self._session.items:
            removed = self._session.items.pop()
            self._tray.set_session_indicator(
                str(len(self._session.items)) if self._session.items else "●"
            )
            self._tray.show_notification(
                "Whisper VTT",
                f"Removed: {removed}",
                play_sound=True,
                sound="/System/Library/Sounds/Tink.aiff",
            )
            logger.info("Scratched session item: %r", removed)
        else:
            self._tray.show_notification(
                "Whisper VTT",
                "Nothing to scratch.",
                play_sound=True,
                sound="/System/Library/Sounds/Tink.aiff",
            )

    def _commit_session(self, timed_out: bool = False) -> None:
        """Close the session and hand the compiled list to pi.

        The list lands in the drop box as a structured session entry;
        pi's whisper-vtt skill files it under a titled task-list
        heading. A 'process my dictations' message is delivered so pi
        picks it up immediately (Enter depends on the output mode).
        """
        session = self._session
        self._session = None
        self._tray.set_session_indicator("")

        if session is None:
            return
        if session.sticky:
            # Defensive: sticky sessions never commit — nothing
            # accumulated to lose.
            logger.info("Sticky follow-up ended (commit path).")
            return
        items = [item for item in session.items if item.strip()]
        if not items:
            self._tray.show_notification(
                "Whisper VTT",
                "Session ended — nothing captured.",
                play_sound=True,
            )
            logger.info("Session '%s' ended empty.", session.title)
            return

        append_dictation(
            f"Session: {session.title}",
            kind="session",
            title=session.title,
            items=items,
        )
        # Hand off to pi immediately.
        self._deliver_text("process my dictations")

        message = (
            f"Session committed: {len(items)} item(s) → "
            f"'{session.title}' task list"
        )
        if timed_out:
            message = f"Session timed out — {message}"
        self._tray.show_notification(
            "Whisper VTT", message, play_sound=True,
        )
        logger.info(message)

    def _check_session_timeout(self) -> None:
        """Sticky sessions disarm on the lapse gate; compile sessions
        auto-commit after the idle timeout (no work lost)."""
        if self._session is None or self._status != AppStatus.IDLE:
            return
        elapsed = time.monotonic() - self._session_last_activity
        if self._session.sticky:
            if elapsed >= self._config.lapse_s:
                logger.info(
                    "Sticky lapse (%.0fs) — follow-up listening off.",
                    self._config.lapse_s,
                )
                self._close_sticky_session(spoken=False)
            return
        if elapsed >= self._config.session_timeout_s:
            logger.info(
                "Session '%s' idle timeout (%.0fs) — auto-committing.",
                self._session.title,
                self._config.session_timeout_s,
            )
            self._commit_session(timed_out=True)

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
            elif result == SEND_NO_HOST:
                self._tray.show_notification(
                    "Whisper VTT",
                    "Auto-send skipped: no pi host running — "
                    "text pasted, not sent.",
                    play_sound=True,
                )
            elif result == SEND_SUPPRESSED:
                self._tray.show_notification(
                    "Whisper VTT",
                    "Override: pasted without sending.",
                    play_sound=False,
                )
