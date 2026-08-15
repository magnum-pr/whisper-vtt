"""Diagnostic: reproduce the wake-word → recording mic contention.

Sequence mirroring the app: start wake word stream, pause it (waits for
the stream to close), open the recording stream, capture 3s, stop.
Prints whether samples actually flowed.
"""

import sys
import time

sys.path.insert(0, ".")

from src.wake_word import WakeWordListener
from src.audio_capture import AudioCapture

print("1) starting wake word listener...")
ww = WakeWordListener(keyword="jarvis", threshold=1e-20)
ww.start()
time.sleep(2.0)
print("   wake word running:", ww.is_running)

print("2) pausing wake word (blocks until stream closed)...")
t0 = time.time()
ww.pause()
print(f"   paused in {time.time()-t0:.2f}s")

print("3) starting recording...")
cap = AudioCapture()
try:
    cap.start_recording()
except Exception as e:
    print(f"   FAILED to start recording: {e}")
    ww.stop()
    sys.exit(1)

print("   recording started — capturing 3s...")
time.sleep(3.0)

print("4) stopping recording...")
buf = cap.stop_recording()
print(f"   samples captured: {len(buf.samples)} ({buf.duration_seconds:.2f}s)")

if len(buf.samples) > 0:
    import numpy as np
    peak = float(np.max(np.abs(buf.samples)))
    print(f"   peak amplitude: {peak:.4f}")
    print("   SUCCESS — mic captured audio")
else:
    print("   FAILURE — zero samples captured")

print("5) resuming wake word...")
ww.resume()
time.sleep(1.5)
print("   done. cleaning up...")
ww.stop()
