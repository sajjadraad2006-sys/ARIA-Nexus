#!/usr/bin/env python3
# =====================================================================
#  piper_tts.py  --  Persistent, WARM Piper TTS voice pool for ARIA Nexus
# =====================================================================
#  Replaces the old "spawn a fresh Piper process per call" path.
#
#  ROOT-CAUSE FIX
#  --------------
#  The previous implementation (server.generate_piper_audio) launched the
#  Piper *binary* on every single request. That reloads the ~60-110 MB ONNX
#  voice model from disk EVERY time, so:
#     * there was never any real "stay warm" behaviour, and
#     * switching EN <-> AR was always slow (both reloaded constantly).
#
#  This module loads each voice's ONNX model ONCE via the `piper` Python
#  package (onnxruntime) and keeps it resident in RAM. Only the FIRST
#  synthesis with a given voice pays the load cost; every later synthesis
#  with an already-loaded voice is warm and fast. Switching back and forth
#  reuses the already-warmed models -- nothing is reloaded.
#
#  DESIGN
#  ------
#  * Thread-safe: a global RLock guards the cache + per-voice locks; a
#    per-voice lock serialises synthesis on ONE voice while still letting
#    different voices synthesise in parallel.
#  * Offline-first: pure in-process, no network, no extra service/port.
#  * Graceful degradation: if the `piper` package or a voice model is
#    missing, load()/synthesize() raise PiperUnavailable so the caller can
#    fall back to the legacy binary-spawn path.
#  * Instrumentation: per-voice first-call (cold) vs warm-call latency is
#    measured + logged and exposed via stats() so the speed-up is provable.
# =====================================================================
import io
import os
import time
import wave
import threading


class PiperUnavailable(RuntimeError):
    """Raised when the in-process Piper pool cannot satisfy a request.

    The caller is expected to catch this and fall back to another TTS path
    (e.g. the legacy Piper binary spawn) so the assistant keeps talking.
    """


# ---- resolve paths/voices from config, with safe fallbacks ----------
def _project_root():
    try:
        import config as _cfg
        root = getattr(_cfg, "_PROJECT_ROOT", None)
        if root:
            return root
    except Exception:
        pass
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _voices_dir():
    try:
        import config as _cfg
        d = getattr(_cfg, "PIPER_VOICES_DIR", None)
        if d:
            return d
    except Exception:
        pass
    return os.path.join(_project_root(), "models", "piper_voices")


def _default_voice():
    try:
        import config as _cfg
        return getattr(_cfg, "PIPER_DEFAULT_VOICE", "en_GB-semaine-medium")
    except Exception:
        return "en_GB-semaine-medium"


class PiperVoicePool:
    """Loads and caches PiperVoice ONNX models, keeping them warm in RAM."""

    def __init__(self, voices_dir=None, default_voice=None):
        self._voices_dir = voices_dir or _voices_dir()
        self._default_voice = default_voice or _default_voice()
        self._cache = {}                 # voice_name -> PiperVoice
        self._voice_locks = {}           # voice_name -> threading.Lock
        self._cache_lock = threading.RLock()
        self._import_error = ""
        self._PiperVoice = None
        self._stats = {}                 # voice_name -> timing dict
        self._try_import()

    # -- import guard (so a missing package degrades gracefully) -------
    def _try_import(self):
        if self._PiperVoice is not None:
            return True
        try:
            from piper import PiperVoice  # type: ignore
            self._PiperVoice = PiperVoice
            return True
        except Exception as exc:  # pragma: no cover - import guard
            self._import_error = str(exc)
            self._PiperVoice = None
            return False

    def is_available(self):
        """True if the `piper` python package imported successfully."""
        return self._try_import()

    def reason(self):
        if self._PiperVoice is None:
            return "piper python package not importable: " + (self._import_error or "unknown")
        return ""

    # -- path resolution ---------------------------------------------
    def _resolve(self, voice_name):
        """Return an existing .onnx path for voice_name (or the default)."""
        onnx = os.path.join(self._voices_dir, voice_name + ".onnx")
        if os.path.exists(onnx):
            return voice_name, onnx
        # fall back to the configured default voice
        d_onnx = os.path.join(self._voices_dir, self._default_voice + ".onnx")
        if os.path.exists(d_onnx):
            return self._default_voice, d_onnx
        return voice_name, onnx  # non-existent; load() will raise

    def _voice_lock(self, voice_name):
        with self._cache_lock:
            lk = self._voice_locks.get(voice_name)
            if lk is None:
                lk = threading.Lock()
                self._voice_locks[voice_name] = lk
            return lk

    # -- model load (cold path, cached) ------------------------------
    def load(self, voice_name):
        """Return a warm PiperVoice for voice_name, loading it once if needed.

        Raises PiperUnavailable if the package or the model file is missing.
        """
        if not self._try_import():
            raise PiperUnavailable(self.reason())

        resolved, onnx_path = self._resolve(voice_name)

        # fast path: already cached + warm
        with self._cache_lock:
            cached = self._cache.get(resolved)
        if cached is not None:
            return resolved, cached

        if not os.path.exists(onnx_path):
            raise PiperUnavailable(
                "voice model not found: %s (dir=%s)" % (resolved, self._voices_dir)
            )

        # load under the per-voice lock so two threads don't load twice
        lk = self._voice_lock(resolved)
        with lk:
            with self._cache_lock:
                cached = self._cache.get(resolved)
            if cached is not None:
                return resolved, cached
            t0 = time.monotonic()
            try:
                voice = self._PiperVoice.load(onnx_path)
            except Exception as exc:
                raise PiperUnavailable("failed to load %s: %s" % (resolved, exc))
            load_ms = (time.monotonic() - t0) * 1000.0
            with self._cache_lock:
                self._cache[resolved] = voice
                self._stats[resolved] = {
                    "load_ms": round(load_ms, 1),
                    "calls": 0,
                    "first_synth_ms": None,
                    "last_synth_ms": None,
                    "warm_synth_ms_avg": None,
                    "_warm_total": 0.0,
                    "_warm_n": 0,
                }
            print("[PiperPool] Loaded voice %r (cold load %.0f ms) -- now warm in RAM"
                  % (resolved, load_ms))
            return resolved, voice

    # -- synthesis (warm path) ---------------------------------------
    def synthesize(self, text, voice_name=None):
        """Synthesise `text` with `voice_name`; return WAV bytes.

        First call for a voice loads + warms it (slow); later calls reuse the
        resident model (fast). Per-voice latency is logged so the cold-vs-warm
        difference is visible in the logs.
        """
        text = (text or "").strip()
        if not text:
            return None
        voice_name = voice_name or self._default_voice
        resolved, voice = self.load(voice_name)

        lk = self._voice_lock(resolved)
        with lk:                          # serialise synthesis per voice
            t0 = time.monotonic()
            wav_bytes = self._synth_wav_bytes(voice, text)
            synth_ms = (time.monotonic() - t0) * 1000.0
            self._record(resolved, synth_ms)
        return wav_bytes

    def _synth_wav_bytes(self, voice, text):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            # piper>=1.5 exposes synthesize_wav(text, wave_file); older builds
            # use synthesize(text, wave_file). Support both.
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, wf)
            else:
                voice.synthesize(text, wf)
        return buf.getvalue()

    def _record(self, voice_name, synth_ms):
        with self._cache_lock:
            st = self._stats.setdefault(voice_name, {
                "load_ms": None, "calls": 0, "first_synth_ms": None,
                "last_synth_ms": None, "warm_synth_ms_avg": None,
                "_warm_total": 0.0, "_warm_n": 0,
            })
            st["calls"] += 1
            st["last_synth_ms"] = round(synth_ms, 1)
            if st["first_synth_ms"] is None:
                st["first_synth_ms"] = round(synth_ms, 1)
                tag = "FIRST/cold"
            else:
                st["_warm_total"] += synth_ms
                st["_warm_n"] += 1
                st["warm_synth_ms_avg"] = round(st["_warm_total"] / st["_warm_n"], 1)
                tag = "warm"
        print("[PiperPool] %s synth: %.0f ms (%s)" % (voice_name, synth_ms, tag))

    # -- startup pre-warm --------------------------------------------
    def prewarm(self, voice_names):
        """Pre-load + do one tiny synthesis for each voice so the FIRST real
        user utterance is already warm. Failures are non-fatal."""
        if not self._try_import():
            print("[PiperPool] Pre-warm skipped -- %s" % self.reason())
            return
        for name in voice_names:
            try:
                self.synthesize("System ready.", name)
                print("[PiperPool] Pre-warmed voice %r" % name)
            except PiperUnavailable as exc:
                print("[PiperPool] Pre-warm of %r failed (non-fatal): %s" % (name, exc))
            except Exception as exc:
                print("[PiperPool] Pre-warm of %r error (non-fatal): %s" % (name, exc))

    def stats(self):
        """Return a copy of per-voice timing stats (for /metrics / benchmarks)."""
        with self._cache_lock:
            out = {}
            for k, v in self._stats.items():
                d = dict(v)
                d.pop("_warm_total", None)
                d.pop("_warm_n", None)
                d["loaded"] = k in self._cache
                out[k] = d
            return out

    def loaded_voices(self):
        with self._cache_lock:
            return sorted(self._cache.keys())


# ---- module-level singleton ----------------------------------------
_POOL = None
_POOL_LOCK = threading.Lock()


def get_pool():
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = PiperVoicePool()
    return _POOL
