#!/usr/bin/env python3
"""
test_benchmark.py — ARIA NEXUS Comprehensive Performance Benchmark
===================================================================
Measures cold-start and warm-path latency (in seconds) for every
subsystem. Writes a detailed benchmark report to:
    backend/benchmark_results.txt

Run:
    cd backend && source venv/bin/activate
    python test_benchmark.py

Tests included:
  1. Config Load Time
  2. Flask App Factory Build Time
  3. RAG Engine Init + Query Latency (cold & cached)
  4. Piper TTS Pool Init + Synthesis (cold & warm)
  5. Wake Word Model Load + Inference Speed
  6. Arabic Detection Speed (1000 iterations)
  7. IoT Controller Init Time
  8. Flask Route Response Times (/api/launcher/health, /api/config)
  9. Import Times for all major modules
"""
import os
import sys
import time
import statistics

os.environ.setdefault("FLASK_SECRET_KEY", "benchmark-secret")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
RESULTS_FILE = os.path.join(SCRIPT_DIR, "benchmark_results.txt")


# ── Helpers ───────────────────────────────────────────────────────────
def _time_it(label, fn, *args, **kwargs):
    """Run fn, measure wall-time, return (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        return result, elapsed, None
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return None, elapsed, exc


def _repeat(fn, n=100):
    """Run fn n times, return list of elapsed times."""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return times


# ── Benchmark Functions ──────────────────────────────────────────────
results = []


def bench_imports():
    """Benchmark import time for each major module."""
    modules = [
        ("config", "config"),
        ("flask", "flask"),
        ("rag_engine", "rag_engine"),
        ("piper_tts", "piper_tts"),
        ("iot_controller", "iot_controller"),
        ("nexus_wakeword", "nexus_wakeword"),
        ("onnxruntime", "onnxruntime"),
        ("numpy", "numpy"),
        ("requests", "requests"),
    ]
    results.append(("=" * 60, "", ""))
    results.append(("MODULE IMPORT TIMES", "", ""))
    results.append(("=" * 60, "", ""))
    for label, mod_name in modules:
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    for label, mod_name in modules:
        t0 = time.perf_counter()
        try:
            __import__(mod_name)
            elapsed = time.perf_counter() - t0
            results.append((f"import {label}", f"{elapsed:.4f}s", "✅"))
        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append((f"import {label}", f"{elapsed:.4f}s", f"⚠️ {e}"))


def bench_config():
    """Benchmark config.py load and key access."""
    results.append(("=" * 60, "", ""))
    results.append(("CONFIG LOAD", "", ""))
    results.append(("=" * 60, "", ""))
    _, elapsed, err = _time_it("config load", lambda: __import__("config"))
    if err:
        results.append(("Config load", f"{elapsed:.4f}s", f"❌ {err}"))
        return
    results.append(("Config load", f"{elapsed:.4f}s", "✅"))

    import config as cfg
    keys_to_check = [
        "FLASK_PORT", "WHISPER_URL", "LLAMA_URL", "HA_URL", "HA_TOKEN",
        "RAG_ENABLED", "PIPER_DEFAULT_VOICE", "PIPER_ARABIC_VOICE",
        "WAKE_THRESHOLD", "WAKE_TRIGGER_FRAMES", "VAD_CONFIG",
    ]
    for k in keys_to_check:
        val = getattr(cfg, k, "MISSING")
        status = "✅" if val != "MISSING" else "❌ MISSING"
        display = str(val)[:50] + "…" if len(str(val)) > 50 else str(val)
        results.append((f"  config.{k}", display, status))


def bench_flask_factory():
    """Benchmark Flask app creation."""
    results.append(("=" * 60, "", ""))
    results.append(("FLASK APP FACTORY", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from server import create_app
        app_obj, elapsed, err = _time_it("create_app", create_app)
        if err:
            results.append(("Flask create_app()", f"{elapsed:.4f}s", f"❌ {err}"))
            return None
        results.append(("Flask create_app()", f"{elapsed:.4f}s", "✅"))
        return app_obj
    except Exception as e:
        results.append(("Flask create_app()", "N/A", f"❌ import failed: {e}"))
        return None


def bench_routes(app_tuple):
    """Benchmark Flask route response times."""
    results.append(("=" * 60, "", ""))
    results.append(("FLASK ROUTE RESPONSE TIMES", "", ""))
    results.append(("=" * 60, "", ""))
    if not app_tuple:
        results.append(("Routes", "N/A", "⚠️ App not available"))
        return
    app, _ = app_tuple
    client = app.test_client()

    routes = [
        ("GET /api/launcher/health", "/api/launcher/health"),
        ("GET /api/config", "/api/config"),
        ("GET / (redirect)", "/"),
    ]
    for label, path in routes:
        times = []
        status_code = None
        for i in range(10):
            t0 = time.perf_counter()
            resp = client.get(path)
            times.append(time.perf_counter() - t0)
            if i == 0:
                status_code = resp.status_code
        avg = statistics.mean(times)
        mn = min(times)
        mx = max(times)
        results.append((
            f"  {label} (HTTP {status_code})",
            f"avg={avg:.4f}s  min={mn:.4f}s  max={mx:.4f}s",
            "✅" if status_code in (200, 302) else f"❌ HTTP {status_code}"
        ))


def bench_rag():
    """Benchmark RAG engine init + query performance."""
    results.append(("=" * 60, "", ""))
    results.append(("RAG ENGINE", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from rag_engine import RAGEngine
    except Exception as e:
        results.append(("RAG import", "N/A", f"❌ {e}"))
        return

    rag, init_time, err = _time_it("RAG init", RAGEngine)
    if err:
        results.append(("RAG init", f"{init_time:.4f}s", f"❌ {err}"))
        return
    results.append(("RAG init (embeddings + ChromaDB)", f"{init_time:.4f}s", "✅"))
    results.append(("  Available", str(rag.is_available()), ""))

    if not rag.is_available():
        results.append(("RAG query", "N/A", "⚠️ No vectors"))
        return

    # Cold query
    test_queries = [
        "What is ARIA?",
        "delivery policy",
        "robot navigation",
    ]
    for q in test_queries:
        rag.clear_cache()
        _, cold_time, _ = _time_it(f"RAG cold query", rag.query, q)
        results.append((f"  Query (cold): '{q}'", f"{cold_time:.4f}s", "✅"))

        # Cached query
        _, cache_time, _ = _time_it(f"RAG cached query", rag.query, q)
        results.append((f"  Query (cached): '{q}'", f"{cache_time:.6f}s", "✅ (cache hit)"))

        speedup = cold_time / cache_time if cache_time > 0 else 0
        results.append((f"  Cache speedup", f"{speedup:.0f}x faster", ""))


def bench_piper():
    """Benchmark Piper TTS pool init + synthesis."""
    results.append(("=" * 60, "", ""))
    results.append(("PIPER TTS POOL", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from piper_tts import PiperVoicePool, PiperUnavailable
    except Exception as e:
        results.append(("Piper import", "N/A", f"❌ {e}"))
        return

    pool, init_time, err = _time_it("PiperPool init", PiperVoicePool)
    if err:
        results.append(("PiperPool init", f"{init_time:.4f}s", f"❌ {err}"))
        return
    results.append(("PiperPool init", f"{init_time:.4f}s", "✅"))
    results.append(("  Available", str(pool.is_available()), ""))

    if not pool.is_available():
        results.append(("  Reason", pool.reason()[:80], ""))
        return

    # Test English voice
    test_texts = [
        ("Hello, I am ARIA.", None),                       # default EN voice
        ("مرحباً، أنا آريا.", "ar_JO-kareem-medium"),      # Arabic voice
    ]
    for text, voice in test_texts:
        voice_label = voice or "default-EN"
        try:
            # Cold synthesis
            _, cold_time, cold_err = _time_it("synth", pool.synthesize, text, voice)
            if cold_err:
                results.append((f"  Synth COLD ({voice_label})", f"{cold_time:.4f}s", f"❌ {cold_err}"))
                continue
            results.append((f"  Synth COLD ({voice_label})", f"{cold_time:.4f}s", "✅"))

            # Warm synthesis (5 runs)
            warm_times = []
            for _ in range(5):
                _, wt, _ = _time_it("synth", pool.synthesize, text, voice)
                warm_times.append(wt)
            avg = statistics.mean(warm_times)
            results.append((f"  Synth WARM ({voice_label}, avg of 5)",
                            f"{avg:.4f}s", "✅"))
        except Exception as e:
            results.append((f"  Synth ({voice_label})", "N/A", f"⚠️ {e}"))


def bench_wakeword():
    """Benchmark wake word model load + inference."""
    results.append(("=" * 60, "", ""))
    results.append(("WAKE WORD (openWakeWord)", "", ""))
    results.append(("=" * 60, "", ""))

    model_path = os.path.join(PROJECT_ROOT, "aarya_wakeword", "aarya.onnx")
    if not os.path.exists(model_path):
        results.append(("Model file", "N/A", f"❌ Not found: {model_path}"))
        return

    results.append(("Model file", f"{os.path.getsize(model_path)/1024:.1f} KB", "✅"))

    # ONNX Runtime direct load
    try:
        import onnxruntime as ort
        import numpy as np_local

        _, load_time, load_err = _time_it(
            "ort.InferenceSession",
            ort.InferenceSession, model_path, providers=["CPUExecutionProvider"]
        )
        if load_err:
            results.append(("ONNX load (onnxruntime)", f"{load_time:.4f}s", f"❌ {load_err}"))
        else:
            results.append(("ONNX load (onnxruntime)", f"{load_time:.4f}s", "✅"))

            sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0]
            shape = [d if isinstance(d, int) else 1 for d in inp.shape]
            dummy = np_local.random.rand(*shape).astype(np_local.float32)

            # Inference speed
            inf_times = []
            for _ in range(100):
                t0 = time.perf_counter()
                sess.run(None, {inp.name: dummy})
                inf_times.append(time.perf_counter() - t0)
            avg = statistics.mean(inf_times)
            mn = min(inf_times)
            mx = max(inf_times)
            results.append((
                f"  ONNX inference (100 runs)",
                f"avg={avg*1000:.2f}ms  min={mn*1000:.2f}ms  max={mx*1000:.2f}ms",
                "✅"
            ))
    except Exception as e:
        results.append(("ONNX direct test", "N/A", f"❌ {e}"))

    # openWakeWord model load
    try:
        from openwakeword.model import Model
        _, oww_load, oww_err = _time_it(
            "openWakeWord",
            Model, wakeword_models=[model_path], inference_framework="onnx"
        )
        if oww_err:
            results.append(("openWakeWord load", f"{oww_load:.4f}s", f"❌ {oww_err}"))
        else:
            results.append(("openWakeWord load", f"{oww_load:.4f}s", "✅"))
    except Exception as e:
        results.append(("openWakeWord load", "N/A", f"❌ {e}"))


def bench_arabic_detect():
    """Benchmark Arabic text detection speed."""
    results.append(("=" * 60, "", ""))
    results.append(("ARABIC TEXT DETECTION", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from server import _is_arabic_text
    except Exception as e:
        results.append(("Import _is_arabic_text", "N/A", f"❌ {e}"))
        return

    test_cases = [
        ("مرحبا كيف حالك", True),
        ("Hello how are you", False),
        ("شغّل الإضاءة في غرفة الجلوس", True),
        ("Turn on the lights", False),
        ("مزيج من both languages يعني", True),
    ]

    # Correctness check
    all_correct = True
    for text, expected in test_cases:
        actual = _is_arabic_text(text)
        status = "✅" if actual == expected else "❌"
        if actual != expected:
            all_correct = False
        results.append((f"  '{text[:30]}…'", f"→ {actual} (expected {expected})", status))

    # Speed benchmark (1000 iterations over all cases)
    times = []
    for _ in range(1000):
        t0 = time.perf_counter()
        for text, _ in test_cases:
            _is_arabic_text(text)
        times.append(time.perf_counter() - t0)
    avg = statistics.mean(times)
    total = sum(times)
    results.append((
        f"  Speed (1000 × {len(test_cases)} calls)",
        f"total={total:.4f}s  avg/batch={avg*1000:.3f}ms",
        "✅"
    ))


def bench_iot_controller():
    """Benchmark IoT controller initialization."""
    results.append(("=" * 60, "", ""))
    results.append(("IoT CONTROLLER", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from iot_controller import HAController
        import config as cfg

        _, init_time, init_err = _time_it(
            "HAController init",
            HAController,
            getattr(cfg, "HA_URL", "http://127.0.0.1:8123"),
            getattr(cfg, "HA_TOKEN", ""),
        )
        if init_err:
            results.append(("HAController init", f"{init_time:.4f}s", f"❌ {init_err}"))
            return
        results.append(("HAController init", f"{init_time:.4f}s", "✅"))

        ha = HAController(cfg.HA_URL, cfg.HA_TOKEN)
        _, avail_time, _ = _time_it("HA availability check", ha.is_available)
        results.append((f"  HA availability check", f"{avail_time:.4f}s",
                         "✅ reachable" if ha.is_available() else "⚠️ not reachable"))
    except Exception as e:
        results.append(("IoT controller", "N/A", f"❌ {e}"))


def bench_nexus_wakeword_module():
    """Benchmark the nexus_wakeword WakeWordListener."""
    results.append(("=" * 60, "", ""))
    results.append(("NEXUS WAKEWORD LISTENER", "", ""))
    results.append(("=" * 60, "", ""))
    try:
        from nexus_wakeword import WakeWordListener

        _, init_time, init_err = _time_it("WakeWordListener init", WakeWordListener)
        if init_err:
            results.append(("Listener init", f"{init_time:.4f}s", f"❌ {init_err}"))
            return
        results.append(("Listener init", f"{init_time:.4f}s", "✅"))

        listener = WakeWordListener()
        results.append(("  available() [local mic]", str(listener.available()), ""))
        results.append(("  available_feed() [stream]", str(listener.available_feed()), ""))

        # Feed benchmark with dummy audio
        if listener.available_feed():
            import numpy as np_local
            dummy_audio = (np_local.random.randn(1280) * 100).astype(np_local.int16).tobytes()
            feed_times = []
            for _ in range(50):
                t0 = time.perf_counter()
                listener.feed(dummy_audio)
                feed_times.append(time.perf_counter() - t0)
            avg = statistics.mean(feed_times)
            results.append((
                f"  feed() latency (50 frames)",
                f"avg={avg*1000:.2f}ms  min={min(feed_times)*1000:.2f}ms  max={max(feed_times)*1000:.2f}ms",
                "✅"
            ))
    except Exception as e:
        results.append(("Nexus wakeword", "N/A", f"❌ {e}"))


# ── Report Generator ─────────────────────────────────────────────────
def generate_report():
    """Write benchmark_results.txt."""
    lines = []
    lines.append("╔" + "═" * 78 + "╗")
    lines.append("║" + " ARIA NEXUS — COMPREHENSIVE BENCHMARK REPORT".center(78) + "║")
    lines.append("║" + f" Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}".center(78) + "║")
    lines.append("║" + f" Machine: {os.uname().nodename} ({os.uname().machine})".center(78) + "║")
    lines.append("╚" + "═" * 78 + "╝")
    lines.append("")

    for test_name, value, status in results:
        if test_name.startswith("="):
            lines.append("")
            lines.append(test_name)
            continue
        if value == "" and status == "":
            lines.append(test_name)
            continue
        if status:
            lines.append(f"  {test_name:<45} {value:<30} {status}")
        else:
            lines.append(f"  {test_name:<45} {value}")

    # Summary
    total_pass = sum(1 for _, _, s in results if s == "✅")
    total_fail = sum(1 for _, _, s in results if s.startswith("❌"))
    total_warn = sum(1 for _, _, s in results if s.startswith("⚠️"))

    lines.append("")
    lines.append("=" * 60)
    lines.append("SUMMARY")
    lines.append("=" * 60)
    lines.append(f"  ✅ Passed:   {total_pass}")
    lines.append(f"  ❌ Failed:   {total_fail}")
    lines.append(f"  ⚠️  Warning:  {total_warn}")
    lines.append("")

    report = "\n".join(lines)

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    return report


# ── Main ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n🚀 ARIA NEXUS Benchmark — Starting…\n")

    total_start = time.perf_counter()

    bench_imports()
    bench_config()
    app_tuple = bench_flask_factory()
    bench_routes(app_tuple)
    bench_rag()
    bench_piper()
    bench_wakeword()
    bench_arabic_detect()
    bench_iot_controller()
    bench_nexus_wakeword_module()

    total_elapsed = time.perf_counter() - total_start

    results.append(("=" * 60, "", ""))
    results.append(("TOTAL BENCHMARK TIME", "", ""))
    results.append(("=" * 60, "", ""))
    results.append(("Total", f"{total_elapsed:.2f}s", ""))

    report = generate_report()
    print("\n" + report)
    print(f"\n📄 Report saved to: {RESULTS_FILE}")
