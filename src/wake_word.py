"""Wake word detection using CMU PocketSphinx.

Pure C extension with no external DLL dependencies — works reliably
in PyInstaller bundles unlike onnxruntime/torch.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WakeWordListener:
    """Continuous wake word detection using PocketSphinx keyword spotting.

    Runs a lightweight audio capture stream on a daemon thread.
    When the configured keyword is detected, the on_detected
    callback fires.
    """

    SAMPLE_RATE = 16000
    FRAME_SAMPLES = 1600  # 100ms at 16kHz

    def __init__(
        self,
        keyword: str = "alexa",
        threshold: float = 1e-20,
        device_index: Optional[int] = None,
    ):
        """
        Args:
            keyword: The wake word/phrase to detect.
            threshold: KWS threshold (lower = more selective).
                       Default 1e-20 works for normal speaking voice.
            device_index: sounddevice device index (None = system default).
        """
        self._keyword = keyword
        self._threshold = threshold
        self._device_index = device_index

        self._on_detected: Optional[Callable[[], None]] = None
        self._running = False
        self._paused = False
        self._cooldown_until: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._decoder: Optional[object] = None
        # Set while no InputStream is open. Cleared on open, set again on
        # close — pause() waits on it so the recording stream never opens
        # while the wake word stream still holds the mic.
        self._stream_closed = threading.Event()
        self._stream_closed.set()

    # ── Callback registration ──────────────────────────────────────────

    def set_on_detected(self, callback: Callable[[], None]) -> None:
        """Set callback invoked when the wake word is detected."""
        self._on_detected = callback

    # ── Lifecycle ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Start wake word detection on a daemon thread."""
        if self._running:
            return

        try:
            from pocketsphinx import Config, Decoder

            config = Config(
                keyphrase=self._keyword,
                kws_threshold=self._threshold,
            )
            self._decoder = Decoder(config)
        except Exception as e:
            logger.error("Failed to create PocketSphinx decoder: %s", e)
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            daemon=True,
            name="wake-word-listener",
        )
        self._thread.start()
        logger.info(
            "Wake word listener started: keyword='%s', threshold=%.0e",
            self._keyword,
            self._threshold,
        )

    def stop(self) -> None:
        """Stop wake word detection."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("Wake word listener stopped.")

    def pause(self) -> None:
        """Pause wake word detection AND close the audio stream.

        Blocks (bounded) until the stream is actually closed so the
        recording stream gets exclusive mic access. Two concurrent
        PortAudio input streams on macOS fail with PaErrorCode -9986
        and/or capture zero samples.
        """
        self._paused = True
        if not self._stream_closed.wait(timeout=2.0):
            logger.warning("Wake word stream did not close within 2s.")
        logger.debug("Wake word listener paused (stream closed).")

    def resume(self) -> None:
        """Resume wake word detection. Reopens the audio stream, resets
        decoder state and enforces a 3s cooldown so stale audio/echo
        doesn't cause false triggers."""
        import time
        self._paused = False
        self._stream_closed.clear()
        self._cooldown_until = time.monotonic() + 2.0
        if self._decoder is not None:
            try:
                self._decoder.end_utt()
                self._decoder.start_utt()
            except Exception as e:
                logger.warning("Failed to reset decoder on resume: %s", e)
        logger.debug("Wake word listener resumed (cooldown until %.1fs).", self._cooldown_until)

    # ── Audio loop ─────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Capture audio and run keyword spotting in a loop."""
        try:
            import sounddevice as sd
        except ImportError:
            logger.error("sounddevice not available — wake word disabled.")
            self._running = False
            return

        import numpy as np

        # Cooldown: ignore detections for 2s after each trigger
        cooldown_frames = 0
        COOLDOWN_DURATION_MS = 2000
        COOLDOWN_FRAMES = COOLDOWN_DURATION_MS // 100  # 100ms per frame

        # Require N consecutive frames with a hypothesis before firing.
        # Single-frame noise spikes won't trigger; real speech spans
        # multiple frames at 100ms/frame.
        consecutive_hits = 0
        CONSECUTIVE_REQUIRED = 1

        # Keep utterance open across frames so the decoder sees
        # enough audio to match multi-syllable keywords (~500ms).
        self._decoder.start_utt()
        frame_count = 0

        def audio_callback(indata, frames, time_info, status):
            nonlocal cooldown_frames, frame_count, consecutive_hits

            if not self._running:
                raise sd.CallbackStop

            if status:
                return

            # Post-resume cooldown — block detection for 3s after resume
            import time
            if time.monotonic() < self._cooldown_until:
                return

            # Reset utterance every 6s to prevent unbounded memory
            frame_count += 1
            if frame_count >= 60 and not self._paused:
                self._decoder.end_utt()
                self._decoder.start_utt()
                frame_count = 0

            # Skip decoding while paused — just consume frames
            if self._paused:
                return

            # Convert to int16 (PocketSphinx expects PCM16)
            if indata.ndim > 1:
                chunk = indata[:, 0]
            else:
                chunk = indata
            chunk_int16 = np.clip(chunk * 32767, -32768, 32767).astype(np.int16)

            # Feed to PocketSphinx (utterance stays open)
            self._decoder.process_raw(chunk_int16.tobytes(), False, False)

            hyp = self._decoder.hyp()

            # During cooldown, ignore everything and reset consecutive counter
            if cooldown_frames > 0:
                cooldown_frames -= 1
                return

            if hyp is not None:
                consecutive_hits += 1
                if consecutive_hits >= CONSECUTIVE_REQUIRED:
                    logger.info(
                        "Wake word detected: '%s' -> '%s'",
                        self._keyword,
                        hyp.hypstr,
                    )
                    cooldown_frames = COOLDOWN_FRAMES
                    consecutive_hits = 0
                    if self._on_detected:
                        try:
                            self._on_detected()
                        except Exception as e:
                            logger.warning("Wake word callback error: %s", e)
            else:
                consecutive_hits = 0

        while self._running:
            if self._paused:
                time.sleep(0.1)
                continue
            try:
                self._stream_closed.clear()
                with sd.InputStream(
                    samplerate=self.SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=audio_callback,
                    blocksize=self.FRAME_SAMPLES,
                    device=self._device_index,
                ):
                    while self._running and not self._paused:
                        sd.sleep(100)
            except Exception as e:
                logger.error("Wake word audio stream error: %s", e)
                self._running = False
            finally:
                self._stream_closed.set()
