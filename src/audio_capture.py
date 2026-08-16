"""Microphone audio capture via sounddevice (PortAudio)."""

import logging
from typing import Callable, Optional

import numpy as np

from src.level_meter import GLOBAL_METER
from src.models import AudioBuffer

logger = logging.getLogger(__name__)

# Default audio settings (whisper's native format)
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION_MS = 100  # ~100ms chunks
SAMPLES_PER_CHUNK = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 1600 samples


class AudioCaptureError(Exception):
    """Raised when audio capture fails."""


class AudioCapture:
    """Records microphone input at 16kHz mono using PortAudio.

    Streams audio in ~100ms chunks via a callback. Each chunk is
    forwarded to an optional VAD callback and accumulated into an
    internal buffer. On stop, all chunks are concatenated into an
    AudioBuffer.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        chunk_samples: int = SAMPLES_PER_CHUNK,
        device_index: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_samples = chunk_samples
        self.device_index = device_index

        self._stream: Optional[object] = None
        self._chunks: list[np.ndarray] = []
        self._chunk_callback: Optional[Callable[[np.ndarray], None]] = None
        self._error_callback: Optional[Callable[[str], None]] = None
        self._is_recording: bool = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def set_chunk_callback(self, callback: Callable[[np.ndarray], None]) -> None:
        """Set callback for each audio chunk (e.g., VAD processing)."""
        self._chunk_callback = callback

    def set_error_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for capture errors."""
        self._error_callback = callback

    def start_recording(self) -> None:
        """Begin recording from the default microphone.

        Raises:
            AudioCaptureError: If microphone is unavailable or access denied.
        """
        if self._is_recording:
            return

        self._chunks = []

        try:
            import sounddevice as sd
        except ImportError as e:
            raise AudioCaptureError(
                "sounddevice library not available. "
                "Install with: pip install sounddevice"
            ) from e

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=self._audio_callback,
                blocksize=self.chunk_samples,
                device=self.device_index,
            )
            self._stream.start()
            self._is_recording = True
            logger.info(
                "Recording started: %d Hz, %d channel(s), %d samples/chunk",
                self.sample_rate,
                self.channels,
                self.chunk_samples,
            )
        except sd.PortAudioError as e:
            raise AudioCaptureError(
                f"Could not access microphone: {e}"
            ) from e
        except PermissionError as e:
            raise AudioCaptureError(
                f"Microphone access denied: {e}"
            ) from e
        except OSError as e:
            raise AudioCaptureError(
                f"Audio system error: {e}"
            ) from e

    def stop_recording(self) -> AudioBuffer:
        """Stop recording and return the accumulated audio buffer.

        Returns:
            AudioBuffer containing all recorded samples.

        Raises:
            AudioCaptureError: If not currently recording.
        """
        if not self._is_recording or self._stream is None:
            raise AudioCaptureError("Not currently recording.")

        try:
            self._stream.stop()
            self._stream.close()
        except Exception as e:
            logger.warning("Error closing audio stream: %s", e)
        finally:
            self._stream = None
            self._is_recording = False

        if not self._chunks:
            samples = np.array([], dtype=np.float32)
        else:
            samples = np.concatenate(self._chunks)

        logger.info(
            "Recording stopped: %.1f seconds, %d samples",
            len(samples) / self.sample_rate,
            len(samples),
        )

        return AudioBuffer(
            samples=samples,
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        """Internal PortAudio callback — called from a high-priority audio thread."""
        if status:
            msg = f"Audio capture status: {status}"
            logger.warning(msg)
            if self._error_callback:
                self._error_callback(msg)

        # Copy to avoid buffer reuse issues
        chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        self._chunks.append(chunk)

        # Publish the live mic level (cheap RMS) for the menu bar meter
        GLOBAL_METER.update_from_samples(chunk)

        if self._chunk_callback:
            try:
                self._chunk_callback(chunk)
            except Exception as e:
                logger.warning("Chunk callback error: %s", e)
