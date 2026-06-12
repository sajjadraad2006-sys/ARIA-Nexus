#!/usr/bin/env python3
"""
test_tts_bench.py — Piper TTS Performance Benchmark
=====================================================
Tests TTS synthesis speed for both English and Arabic voices:
  1. Voice pool initialization
  2. Cold synthesis (first utterance — includes model load)
  3. Warm synthesis (model already in RAM)
  4. Short text vs long text comparison
  5. Language switching overhead
  6. Output WAV size estimation

Run:
    cd backend && source venv/bin/activate
    python test_tts_bench.py
"""
import os
import time
import statistics

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")


def main():
    results = []
    print("🔊 Piper TTS Performance Benchmark\n")

    try:
        from piper_tts import PiperVoicePool, PiperUnavailable
    except Exception as e:
        print(f"❌ Cannot import PiperVoicePool: {e}")
        return

    # ── 1. Pool init ──
    t0 = time.perf_counter()
    pool = PiperVoicePool()
    init_time = time.perf_counter() - t0
    results.append(("PiperVoicePool init", f"{init_time:.4f}s"))
    results.append(("  Available", str(pool.is_available())))

    if not pool.is_available():
        results.append(("  Reason", pool.reason()[:80]))
        _print_results(results)
        return

    # ── 2. Cold + Warm synthesis for each voice ──
    voices = {
        "English (en_GB-semaine-medium)": None,  # default
        "Arabic (ar_JO-kareem-medium)": "ar_JO-kareem-medium",
    }

    test_texts = {
        "short": {
            None: "Hello, I am ARIA.",
            "ar_JO-kareem-medium": "مرحباً أنا آريا",
        },
        "medium": {
            None: "The delivery robot is currently navigating through the hallway toward the reception desk.",
            "ar_JO-kareem-medium": "الروبوت حالياً يتنقل في الممر باتجاه مكتب الاستقبال لتسليم الطلب.",
        },
        "long": {
            None: "Welcome to ARIA Nexus Command Center. I can help you control smart home devices, manage deliveries, and navigate autonomously using computer vision. How can I assist you today?",
            "ar_JO-kareem-medium": "أهلاً وسهلاً بكم في مركز قيادة آريا نيكسس. أقدر أساعدكم بالتحكم بأجهزة المنزل الذكي وإدارة التوصيلات والتنقل الذاتي باستخدام الرؤية الحاسوبية. كيف أقدر أساعدكم اليوم؟",
        },
    }

    for voice_label, voice_name in voices.items():
        results.append(("─" * 50, ""))
        results.append((f"Voice: {voice_label}", ""))

        for length, texts in test_texts.items():
            text = texts.get(voice_name, texts.get(None, "Test"))

            # Cold (first call for this voice+text combo — pool may already have the model)
            t0 = time.perf_counter()
            try:
                wav = pool.synthesize(text, voice_name)
                elapsed = time.perf_counter() - t0
                wav_kb = len(wav) / 1024 if wav else 0
                results.append((
                    f"  {length} text ({len(text)} chars)",
                    f"{elapsed:.4f}s  →  {wav_kb:.1f} KB WAV"
                ))
            except PiperUnavailable as e:
                results.append((f"  {length} text", f"❌ {e}"))
                continue

            # Warm — 5 runs
            warm_times = []
            for _ in range(5):
                t0 = time.perf_counter()
                pool.synthesize(text, voice_name)
                warm_times.append(time.perf_counter() - t0)

            avg = statistics.mean(warm_times)
            mn = min(warm_times)
            mx = max(warm_times)
            results.append((
                f"    warm (5 runs)",
                f"avg={avg:.4f}s  min={mn:.4f}s  max={mx:.4f}s"
            ))

    # ── 3. Language switching overhead ──
    results.append(("─" * 50, ""))
    results.append(("Language Switch Test (EN→AR→EN→AR, 10 cycles)", ""))

    switch_times = []
    for i in range(10):
        t0 = time.perf_counter()
        pool.synthesize("Hello world.", None)
        pool.synthesize("مرحبا بالعالم.", "ar_JO-kareem-medium")
        switch_times.append(time.perf_counter() - t0)

    avg = statistics.mean(switch_times)
    results.append((f"  Avg cycle (EN+AR)", f"{avg:.4f}s"))
    results.append((f"  Per-utterance avg", f"{avg/2:.4f}s"))

    # ── 4. Pool stats ──
    results.append(("─" * 50, ""))
    results.append(("Pool Stats", ""))
    stats = pool.stats()
    for vname, vstat in stats.items():
        results.append((f"  {vname}", ""))
        results.append((f"    Load time", f"{vstat.get('load_ms', 0):.0f}ms"))
        results.append((f"    Total calls", str(vstat.get('calls', 0))))
        results.append((f"    First synth", f"{vstat.get('first_synth_ms', 0):.0f}ms"))
        if vstat.get('warm_synth_ms_avg'):
            results.append((f"    Warm avg", f"{vstat['warm_synth_ms_avg']:.0f}ms"))

    _print_results(results)


def _print_results(results):
    print("\n" + "=" * 60)
    print("PIPER TTS BENCHMARK RESULTS")
    print("=" * 60)
    for label, value in results:
        print(f"  {label:<45} {value}")
    print()


if __name__ == "__main__":
    main()
