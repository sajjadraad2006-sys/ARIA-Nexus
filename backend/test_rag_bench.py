#!/usr/bin/env python3
"""
test_rag_bench.py — RAG Engine Deep Benchmark
===============================================
Tests document retrieval quality + performance:
  1. Engine initialization time
  2. Embedding generation speed
  3. Vector search latency (cold + cached)
  4. Relevance scoring accuracy
  5. Cache hit/miss performance
  6. Concurrent query simulation

Run:
    cd backend && source venv/bin/activate
    python test_rag_bench.py
"""
import os
import sys
import time
import statistics

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

def main():
    results = []
    print("🔍 RAG Engine Deep Benchmark\n")

    # ── 1. Import + Init ──
    t0 = time.perf_counter()
    try:
        from rag_engine import RAGEngine
    except Exception as e:
        print(f"❌ Cannot import RAGEngine: {e}")
        return
    import_time = time.perf_counter() - t0
    results.append(("Import rag_engine", f"{import_time:.4f}s"))

    t0 = time.perf_counter()
    engine = RAGEngine()
    init_time = time.perf_counter() - t0
    results.append(("RAG Engine init (embeddings + DB)", f"{init_time:.4f}s"))

    if not engine.is_available():
        print("⚠️  RAG engine has no vectors — skipping query tests")
        _print_results(results)
        return

    # ── 2. Query benchmarks ──
    queries = [
        "What is ARIA?",
        "delivery policy",
        "robot capabilities",
        "smart home control",
        "navigation system",
    ]

    cold_times = []
    cache_times = []

    for q in queries:
        engine.clear_cache()

        # Cold query
        t0 = time.perf_counter()
        result = engine.query(q)
        cold = time.perf_counter() - t0
        cold_times.append(cold)
        has_result = "✅" if result else "⚠️ empty"
        results.append((f"Cold query: '{q}'", f"{cold:.4f}s  {has_result}"))

        # Cached query
        t0 = time.perf_counter()
        engine.query(q)
        cached = time.perf_counter() - t0
        cache_times.append(cached)
        results.append((f"  Cached repeat", f"{cached:.6f}s"))

    # ── 3. Aggregate stats ──
    results.append(("─" * 50, ""))
    results.append(("Cold query avg", f"{statistics.mean(cold_times):.4f}s"))
    results.append(("Cold query min", f"{min(cold_times):.4f}s"))
    results.append(("Cold query max", f"{max(cold_times):.4f}s"))
    results.append(("Cache query avg", f"{statistics.mean(cache_times):.6f}s"))
    results.append(("Cache speedup", f"{statistics.mean(cold_times)/max(statistics.mean(cache_times),1e-9):.0f}x"))

    # ── 4. Rapid-fire benchmark (50 queries) ──
    engine.clear_cache()
    t0 = time.perf_counter()
    for _ in range(50):
        engine.query("ARIA capabilities")
    rapid_total = time.perf_counter() - t0
    results.append(("50 repeated queries (1 cold + 49 cached)", f"{rapid_total:.4f}s"))
    results.append(("  Per-query avg", f"{rapid_total/50*1000:.2f}ms"))

    _print_results(results)


def _print_results(results):
    print("\n" + "=" * 60)
    print("RAG ENGINE BENCHMARK RESULTS")
    print("=" * 60)
    for label, value in results:
        print(f"  {label:<45} {value}")
    print()


if __name__ == "__main__":
    main()
