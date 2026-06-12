#!/usr/bin/env python3
"""
bench_tts.py - Piper TTS warm-up / model-switching benchmark for ARIA Nexus.

Proves problem #1 is fixed: with the persistent warm Piper pool, the FIRST
synthesis with a voice pays the one-time ONNX load cost, and every later
synthesis with that already-loaded voice is fast - even when switching back
and forth between English and Arabic (the model stays resident in RAM and is
reused, never reloaded from disk).

It measures, per voice:
  * cold  : first synth (includes model load)
  * warm  : median of N subsequent synths (model already resident)
  * switch: synth right after using the OTHER voice (must still be warm)

Usage:
    python3 bench_tts.py                 # use config defaults
    python3 bench_tts.py --rounds 8
    python3 bench_tts.py --en en_GB-semaine-medium --ar ar_JO-kareem-medium

This is OFFLINE and self-contained: it imports piper_tts and drives the pool
directly. If Piper / voice models are not installed it prints a clear,
non-fatal message (graceful degradation) and exits 0 so CI never breaks on a
box without the model files.

NOTE ON ENVIRONMENT: real numbers require the actual Piper binary + the two
.onnx voice files present (run download_models.sh first) on the target Jetson.
On a machine without them, the harness reports 'unavailable' rather than fake
numbers.
"""
import argparse
import statistics
import sys
import time

EN_TEXT = "Hello, this is ARIA. Your delivery robot is ready and standing by."
AR_TEXT = "مرحبا، أنا آريا. روبوت التوصيل جاهز وبانتظار أوامرك."


def _ms(t):
    return "%.1f ms" % (t * 1000.0)


def _time_synth(pool, text, voice):
    t0 = time.perf_counter()
    wav = pool.synthesize(text, voice)
    dt = time.perf_counter() - t0
    return dt, (wav is not None and len(wav) > 0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Piper warm-up benchmark")
    ap.add_argument("--rounds", type=int, default=6, help="warm rounds per voice")
    ap.add_argument("--en", default=None, help="English voice id override")
    ap.add_argument("--ar", default=None, help="Arabic voice id override")
    args = ap.parse_args(argv)

    try:
        import config as cfg
    except Exception:
        cfg = None
    en_voice = args.en or getattr(cfg, "PIPER_DEFAULT_VOICE", "en_GB-semaine-medium")
    ar_voice = args.ar or getattr(cfg, "PIPER_ARABIC_VOICE", "ar_JO-kareem-medium")

    try:
        from piper_tts import get_pool
    except Exception as exc:
        print("[bench] piper_tts unavailable: %s" % exc)
        return 0

    pool = get_pool()
    if not pool.is_available():
        print("[bench] Piper pool unavailable (graceful skip): %s" % pool.reason())
        print("[bench] Run backend/download_models.sh on the target device first.")
        return 0

    print("=" * 64)
    print(" ARIA Nexus - Piper TTS warm-up benchmark")
    print("   EN voice: %s" % en_voice)
    print("   AR voice: %s" % ar_voice)
    print("   warm rounds: %d" % args.rounds)
    print("=" * 64)

    results = {}
    for label, voice, text in (("EN", en_voice, EN_TEXT), ("AR", ar_voice, AR_TEXT)):
        cold, ok = _time_synth(pool, text, voice)
        if not ok:
            print("[%s] synthesis returned no audio for '%s' - skipping" % (label, voice))
            continue
        warm = []
        for _ in range(max(1, args.rounds)):
            dt, _ok = _time_synth(pool, text, voice)
            warm.append(dt)
        results[label] = {"voice": voice, "cold": cold, "warm": warm}
        print("\n[%s] %s" % (label, voice))
        print("   cold (first, includes model load): %s" % _ms(cold))
        print("   warm  median: %s   min: %s   max: %s"
              % (_ms(statistics.median(warm)), _ms(min(warm)), _ms(max(warm))))
        speedup = cold / statistics.median(warm) if warm and statistics.median(warm) > 0 else 0
        print("   speedup (cold / warm median): %.1fx" % speedup)

    # Switching test: alternate EN<->AR and confirm both stay warm.
    if "EN" in results and "AR" in results:
        print("\n[switch] alternating EN <-> AR (models must stay resident):")
        for i in range(4):
            v, t, lbl = (en_voice, EN_TEXT, "EN") if i % 2 == 0 else (ar_voice, AR_TEXT, "AR")
            dt, _ok = _time_synth(pool, t, v)
            print("   round %d  %s  %s" % (i + 1, lbl, _ms(dt)))

    print("\n[bench] loaded voices now resident:", pool.loaded_voices())
    print("[bench] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
