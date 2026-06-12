#!/usr/bin/env python3
"""
Aarya Wake Word Detector
========================
Real-time microphone detection of the wake word "AARYA" (AR-ee-ah)
using a custom-trained openWakeWord model (aarya.onnx).

Usage:
    python3 aarya_wakeword.py

Edit on_wakeword() to plug in your own action.
"""
import time
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from openwakeword.model import Model

# ===================== SETTINGS =====================
MODEL_PATH = "aarya.onnx"   # path to the trained model
THRESHOLD  = 0.1            # detection threshold 0..1 (lower = more sensitive)
COOLDOWN   = 1.5            # seconds to ignore after a detection (anti-repeat)
TARGET_SR  = 16000          # model expects 16 kHz (do not change)
# ====================================================


def on_wakeword(score):
    """Put whatever should happen when 'aarya' is detected here."""
    print(f"\n\U0001F7E2 Wake word 'aarya' detected!  (score={score:.3f})\n")
    # Examples:
    #   import os; os.system("your-command")
    #   play_sound(); start_assistant(); etc.


def main():
    # Detect the microphone's native sample rate (laptop mics are usually 44100/48000 Hz)
    dev = sd.query_devices(kind="input")
    native_sr = int(dev["default_samplerate"])
    block = int(round(native_sr * 0.08))   # 80 ms window

    oww = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")
    key = list(oww.models.keys())[0]

    print(f"\u2713 Model '{key}' loaded | mic {native_sr}Hz -> {TARGET_SR}Hz | threshold={THRESHOLD}")
    print("Listening... say 'AARYA'   (Ctrl+C to stop)\n")

    last_fire = 0.0
    try:
        with sd.InputStream(samplerate=native_sr, channels=1,
                            dtype="int16", blocksize=block) as stream:
            while True:
                data, _ = stream.read(block)
                x = np.frombuffer(data, dtype=np.int16).astype(np.float32).flatten()
                # resample any native rate down to exactly 1280 samples (16kHz * 0.08s)
                x16 = resample_poly(x, TARGET_SR, native_sr)
                x16 = np.clip(x16, -32768, 32767).astype(np.int16)

                score = oww.predict(x16)[key]
                bar = "#" * int(score * 40)
                print(f"\r{score:5.3f} |{bar:<40}|", end="")

                now = time.time()
                if score >= THRESHOLD and (now - last_fire) > COOLDOWN:
                    last_fire = now
                    on_wakeword(score)
    except KeyboardInterrupt:
        print("\n\nStopped. \U0001F44B")


if __name__ == "__main__":
    main()
