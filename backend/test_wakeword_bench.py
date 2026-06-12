#!/usr/bin/env python3
"""
test_wakeword_bench.py — Wake Word Model Inference Benchmark
=============================================================
Deep benchmark for the aarya.onnx wake word detection model:
  1. Model load time (cold)
  2. Single-frame inference latency (100 runs)
  3. Throughput (frames per second)
  4. openWakeWord full-pipeline latency
  5. Streamed feed() path latency
  6. False-positive rate with random noise

Run:
    cd backend && source venv/bin/activate
    python test_wakeword_bench.py
"""
import os
import sys
import time
import statistics

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(PROJECT_ROOT, "aarya_wakeword", "aarya.onnx")


def main():
    results = []
    print("🎤 Wake Word Model Inference Benchmark\n")

    if not os.path.exists(MODEL_PATH):
        print(f"❌ Model not found: {MODEL_PATH}")
        return

    size_kb = os.path.getsize(MODEL_PATH) / 1024
    results.append(("Model file", f"{size_kb:.1f} KB"))

    try:
        import numpy as np
    except ImportError:
        print("❌ numpy not installed")
        return

    # ── 1. ONNX Runtime Direct ──
    results.append(("─" * 50, ""))
    results.append(("ONNX RUNTIME DIRECT", ""))
    try:
        import onnxruntime as ort

        # Cold load
        t0 = time.perf_counter()
        sess = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        load_time = time.perf_counter() - t0
        results.append((f"  Model load (cold)", f"{load_time:.4f}s"))

        inp = sess.get_inputs()[0]
        out = sess.get_outputs()[0]
        results.append((f"  Input shape", str(inp.shape)))
        results.append((f"  Output shape", str(out.shape)))

        shape = [d if isinstance(d, int) else 1 for d in inp.shape]
        dummy = np.random.rand(*shape).astype(np.float32)

        # Warmup
        for _ in range(10):
            sess.run(None, {inp.name: dummy})

        # Inference benchmark (1000 runs)
        times = []
        for _ in range(1000):
            t0 = time.perf_counter()
            sess.run(None, {inp.name: dummy})
            times.append(time.perf_counter() - t0)

        avg = statistics.mean(times)
        med = statistics.median(times)
        mn = min(times)
        mx = max(times)
        p95 = sorted(times)[int(len(times) * 0.95)]
        fps = 1.0 / avg if avg > 0 else 0

        results.append((f"  Inference (1000 runs)", ""))
        results.append((f"    Average", f"{avg*1000:.3f}ms"))
        results.append((f"    Median", f"{med*1000:.3f}ms"))
        results.append((f"    Min", f"{mn*1000:.3f}ms"))
        results.append((f"    Max", f"{mx*1000:.3f}ms"))
        results.append((f"    P95", f"{p95*1000:.3f}ms"))
        results.append((f"    Throughput", f"{fps:.0f} frames/sec"))

        # Real-time check: 80ms frame @ 16kHz, inference must be < 80ms
        realtime_ok = avg * 1000 < 80
        results.append((f"    Real-time capable (<80ms)?",
                         "✅ YES" if realtime_ok else "❌ NO"))

    except Exception as e:
        results.append(("  ONNX Runtime test", f"❌ {e}"))

    # ── 2. openWakeWord Full Pipeline ──
    results.append(("─" * 50, ""))
    results.append(("openWakeWord PIPELINE", ""))
    try:
        from openwakeword.model import Model

        t0 = time.perf_counter()
        oww = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")
        load_time = time.perf_counter() - t0
        results.append((f"  Model load", f"{load_time:.4f}s"))
        results.append((f"  Keys", str(list(oww.models.keys()))))

        # Feed random noise (1280 samples = 80ms @ 16kHz)
        dummy_audio = (np.random.randn(1280) * 100).astype(np.int16)

        # Warmup
        for _ in range(10):
            oww.predict(dummy_audio)

        # Predict benchmark (500 runs)
        times = []
        scores = []
        for _ in range(500):
            t0 = time.perf_counter()
            pred = oww.predict(dummy_audio)
            times.append(time.perf_counter() - t0)
            for v in pred.values():
                scores.append(float(v))

        avg = statistics.mean(times)
        results.append((f"  predict() (500 runs)", ""))
        results.append((f"    Average", f"{avg*1000:.3f}ms"))
        results.append((f"    Min", f"{min(times)*1000:.3f}ms"))
        results.append((f"    Max", f"{max(times)*1000:.3f}ms"))
        results.append((f"    Throughput", f"{1.0/avg:.0f} frames/sec"))

        # False positive check with random noise
        false_positives = sum(1 for s in scores if s > 0.5)
        results.append((f"  False positives (noise, thr=0.5)",
                         f"{false_positives}/{len(scores)} ({false_positives/max(len(scores),1)*100:.1f}%)"))

    except Exception as e:
        results.append(("  openWakeWord test", f"❌ {e}"))

    # ── 3. nexus_wakeword feed() path ──
    results.append(("─" * 50, ""))
    results.append(("NEXUS WAKEWORD feed() PATH", ""))
    try:
        from nexus_wakeword import WakeWordListener

        listener = WakeWordListener()
        if listener.available_feed():
            dummy_bytes = (np.random.randn(1280) * 100).astype(np.int16).tobytes()

            # Warmup
            for _ in range(5):
                listener.feed(dummy_bytes)

            times = []
            for _ in range(200):
                listener.reset_feed()
                t0 = time.perf_counter()
                listener.feed(dummy_bytes)
                times.append(time.perf_counter() - t0)

            avg = statistics.mean(times)
            results.append((f"  feed() (200 calls)", ""))
            results.append((f"    Average", f"{avg*1000:.3f}ms"))
            results.append((f"    Min", f"{min(times)*1000:.3f}ms"))
            results.append((f"    Max", f"{max(times)*1000:.3f}ms"))
        else:
            results.append(("  feed() not available", listener.reason()[:60]))

    except Exception as e:
        results.append(("  nexus_wakeword test", f"❌ {e}"))

    _print_results(results)


def _print_results(results):
    print("\n" + "=" * 60)
    print("WAKE WORD BENCHMARK RESULTS")
    print("=" * 60)
    for label, value in results:
        print(f"  {label:<45} {value}")
    print()


if __name__ == "__main__":
    main()
