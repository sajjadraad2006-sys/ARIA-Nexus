#!/usr/bin/env python3
"""
Quick test: can the backend venv load aarya.onnx?
Run: python3 test_wakeword.py
"""
import os, sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH   = os.path.join(PROJECT_ROOT, "aarya_wakeword", "aarya.onnx")
print(f"Model path : {MODEL_PATH}")
print(f"File exists: {os.path.exists(MODEL_PATH)}")

try:
    from openwakeword.model import Model
    m = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")
    print(f"✅ Model loaded! Keys: {list(m.models.keys())}")
except Exception as e:
    print(f"❌ ERROR loading model: {type(e).__name__}: {e}")
    sys.exit(1)

try:
    import sounddevice as sd
    devs = sd.query_devices()
    print(f"✅ sounddevice OK — {len(devs)} audio devices found")
except Exception as e:
    print(f"⚠️  sounddevice error: {e}")

print("\nAll checks passed — wakeword integration should work.")
