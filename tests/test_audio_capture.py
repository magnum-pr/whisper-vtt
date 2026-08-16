"""Tests for AudioCapture."""

import numpy as np

from src.audio_capture import (
    SAMPLES_PER_CHUNK,
    AudioCapture,
    AudioCaptureError,
)
from src.models import AudioBuffer


class FakeStream:
    """Mock sounddevice stream with start/stop/close methods."""
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestAudioCaptureInit:
    def test_defaults(self):
        cap = AudioCapture()
        assert cap.sample_rate == 16000
        assert cap.channels == 1
        assert cap.chunk_samples == SAMPLES_PER_CHUNK
        assert cap.device_index is None
        assert not cap.is_recording

    def test_custom_params(self):
        cap = AudioCapture(sample_rate=44100, channels=2, chunk_samples=1024)
        assert cap.sample_rate == 44100
        assert cap.channels == 2
        assert cap.chunk_samples == 1024

    def test_device_index_stored(self):
        cap = AudioCapture(device_index=3)
        assert cap.device_index == 3

    def test_device_index_none_by_default(self):
        cap = AudioCapture()
        assert cap.device_index is None


class TestAudioCaptureCallbacks:
    def test_chunk_callback_set_get(self):
        cap = AudioCapture()
        received = []

        def cb(chunk):
            received.append(chunk)

        cap.set_chunk_callback(cb)
        assert cap._chunk_callback is not None


class TestAudioCaptureStopErrors:
    def test_stop_when_not_recording_raises(self):
        cap = AudioCapture()
        try:
            cap.stop_recording()
            assert False, "Should have raised"
        except AudioCaptureError as e:
            assert "Not currently recording" in str(e)


class TestAudioBufferReturn:
    def test_empty_recording_produces_empty_buffer(self):
        cap = AudioCapture()
        cap._is_recording = True
        cap._stream = FakeStream()
        cap._chunks = []

        buf = cap.stop_recording()
        assert isinstance(buf, AudioBuffer)
        assert len(buf.samples) == 0
        assert buf.sample_rate == 16000

    def test_chunks_concatenated(self):
        cap = AudioCapture()
        cap._is_recording = True
        cap._stream = FakeStream()
        cap._chunks = [
            np.array([0.1, 0.2], dtype=np.float32),
            np.array([0.3, 0.4], dtype=np.float32),
        ]

        buf = cap.stop_recording()
        assert len(buf.samples) == 4
        assert buf.samples[0] == 0.1
        assert buf.samples[3] == 0.4

    def test_stream_close_error_handled(self):
        """If closing the stream fails, we still get our buffer."""
        cap = AudioCapture()
        cap._is_recording = True

        class BrokenStream:
            def stop(self):
                pass
            def close(self):
                raise RuntimeError("boom")

        cap._stream = BrokenStream()
        cap._chunks = [np.array([1.0], dtype=np.float32)]

        buf = cap.stop_recording()
        assert len(buf.samples) == 1


class TestAudioCallback:
    def test_callback_appends_chunk(self):
        cap = AudioCapture()
        cap._is_recording = True
        cap._stream = FakeStream()

        indata = np.array([[0.5], [0.6]], dtype=np.float32)
        cap._audio_callback(indata, 2, None, None)

        assert len(cap._chunks) == 1
        assert cap._chunks[0][0] == 0.5
        assert cap._chunks[0][1] == 0.6

    def test_callback_multi_channel_extracts_first(self):
        cap = AudioCapture(channels=2)
        cap._is_recording = True
        cap._stream = FakeStream()

        indata = np.array([[0.1, 0.9], [0.2, 0.8]], dtype=np.float32)
        cap._audio_callback(indata, 2, None, None)

        assert cap._chunks[0][0] == 0.1
        assert cap._chunks[0][1] == 0.2

    def test_callback_calls_chunk_callback(self):
        cap = AudioCapture()
        cap._is_recording = True
        cap._stream = FakeStream()

        received = []
        cap.set_chunk_callback(lambda c: received.append(c))

        indata = np.array([[0.3]], dtype=np.float32)
        cap._audio_callback(indata, 1, None, None)

        assert len(received) == 1
        assert received[0][0] == 0.3

    def test_callback_chunk_callback_exception_handled(self):
        cap = AudioCapture()
        cap._is_recording = True
        cap._stream = FakeStream()

        def bad_callback(chunk):
            raise RuntimeError("boom")

        cap.set_chunk_callback(bad_callback)

        indata = np.array([[0.5]], dtype=np.float32)
        cap._audio_callback(indata, 1, None, None)  # should not raise

        assert len(cap._chunks) == 1  # chunk still appended


class TestAudioCaptureStartErrors:
    def test_start_without_sounddevice(self):
        """If sounddevice isn't installed, raises AudioCaptureError."""
        import builtins

        cap = AudioCapture()

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "sounddevice":
                raise ImportError("No module named 'sounddevice'")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            try:
                cap.start_recording()
                assert False, "Should have raised"
            except AudioCaptureError as e:
                assert "sounddevice" in str(e)
        finally:
            builtins.__import__ = original_import


class TestDeviceResolver:
    """device_resolver is consulted at every recording start."""

    def test_resolver_used_at_start(self):
        from unittest.mock import patch

        calls = []
        cap = AudioCapture(device_index=1, device_resolver=lambda: calls.append("r") or 9)

        with patch("sounddevice.InputStream") as mock_stream:
            mock_stream.return_value = FakeStream()
            cap.start_recording()

        mock_stream.assert_called_once()
        assert mock_stream.call_args.kwargs.get("device") == 9
        assert calls == ["r"]

    def test_resolver_none_falls_back_to_static_index(self):
        from unittest.mock import patch

        cap = AudioCapture(device_index=1)

        with patch("sounddevice.InputStream") as mock_stream:
            mock_stream.return_value = FakeStream()
            cap.start_recording()

        assert mock_stream.call_args.kwargs.get("device") == 1

    def test_resolver_not_called_without_one(self):
        from unittest.mock import patch

        cap = AudioCapture()

        with patch("sounddevice.InputStream") as mock_stream:
            mock_stream.return_value = FakeStream()
            cap.start_recording()

        assert mock_stream.call_args.kwargs.get("device") is None
