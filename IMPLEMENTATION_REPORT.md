# ARIA Nexus — Voice Pipeline Overhaul: Implementation Report

This report records what changed per phase and how it was verified.

> **Honesty about latency numbers.** This work was done in a sandbox with **no
> GPU/Jetson, no microphone, and no model files or running
> llama/whisper/piper servers**. Therefore:
> - All backend Python is **compile- and import-verified** and all touched
>   JavaScript is **`node --check`-verified**.
> - The TTS warm-up improvement is delivered as (a) the persistent warm pool,
>   (b) in-code first-vs-warm latency logging, and (c) `bench_tts.py`, a
>   reproducible harness. **Real cold/warm millisecond numbers must be produced
>   on the Jetson** by running `bench_tts.py` after `download_models.sh`. No
>   fabricated numbers are presented as if measured on hardware.
> - STT capture timing is governed by the browser VAD; the methodology and
>   tunables are documented, to be confirmed with on-device mic input.

---

## Phase 1 — Persistent / warm Piper TTS

**Changed**
- **New `backend/piper_tts.py`**: thread-safe `PiperVoicePool` keeping each
  voice's ONNX model resident; `synthesize()`, `prewarm()`, `loaded_voices()`,
  `is_available()`/`reason()`, singleton `get_pool()`. Logs cold-load ms and
  first-vs-warm synth ms per voice.
- **`server.py`**: Piper constants now imported from `config.py` (with literal
  fallbacks); guarded pool import (`_PIPER_POOL`); `generate_piper_audio()`
  tries the pool first, falls back to the legacy subprocess; `_piper_warmup()`
  pre-warms `PIPER_PREWARM_VOICES`. Fixed an undefined-globals bug
  (`PIPER_MODEL`/`PIPER_CONFIG` → `_piper_model`/`_piper_config`).
- **`config.py`**: `PIPER_VOICES_DIR`, `PIPER_EXE`, `PIPER_DEFAULT_VOICE`,
  `PIPER_ARABIC_VOICE`, `PIPER_PREWARM_VOICES`, `PIPER_USE_POOL`.

**Verified:** `python3 -m py_compile piper_tts.py config.py server.py` → OK.
Benchmark harness `bench_tts.py` added (run on device for numbers).

## Phase 2 — Multilingual Whisper

**Changed**
- **`config.py`**: `WHISPER_MODEL_FILE` (default `ggml-medium.bin`, env
  `NEXUS_WHISPER_MODEL`), `WHISPER_MODEL`, `WHISPER_LANGUAGE` (`"auto"`),
  `WHISPER_TEMPERATURE` (`0.0`).
- **`server.py`**: new `_whisper_data()` helper sending `language` +
  `temperature` on every whisper.cpp request; replaced all 5 inference POST
  sites; **fixed a double-`/inference`** bug in the STT proxy.
- **`download_models.sh`**: env-aware multilingual model download
  (`NEXUS_WHISPER_MODEL`), keeping `ggml-small.bin` as a low-RAM fallback.

**Verified:** `py_compile server.py config.py` → OK; `bash -n
download_models.sh` → OK; `/api/config` returns the language.

## Phase 3 — Whisper VAD / endpointing

**Changed**
- **`frontend/.../js/mic.js`** rewritten: pre-roll (record before VAD arms),
  ambient noise-floor calibration → dynamic speech threshold, min-speech gate,
  silence hangover, min/max length. All knobs read from `window.NEXUS_VAD`
  (backend `VAD_CONFIG`) with safe defaults.
- **`config.py`**: `VAD_CONFIG` dict (startThreshold, silenceMs, minMs,
  minSpeechMs, maxMs, preRollMs, bargeInThreshold, bargeInMs; each `NEXUS_VAD_*`
  overridable).
- **`server.py`**: new `GET /api/config` exposing `vad` + `wake`.
- **`api.js`**: hydrates `window.NEXUS_VAD` / `window.NEXUS_WAKE` at boot.

**Verified:** `node --check mic.js` → OK; `/api/config` smoke test added.

## Phase 4 — Wake-word reliability

**Changed**
- **`backend/nexus_wakeword.py`**: threshold default now from
  `config.WAKE_THRESHOLD` (raised 0.1 → 0.5); shared `_eval_frame()` adds an
  N-consecutive-frame debounce + post-trigger cooldown for both the local-mic
  loop and the streamed `feed()` path; `status()` reports `trigger_frames` and
  `cooldown`.
- **`config.py`**: `WAKE_THRESHOLD`, `WAKE_TRIGGER_FRAMES`, `WAKE_COOLDOWN`,
  `WAKE_MODEL_NAME`.
- **Note documented:** the model file is named `aarya` (≈ spoken "Aria"); the
  custom `aarya.onnx` is not bundled — drop it in `models/wakeword/` on device.

**Verified:** `python3 -m py_compile nexus_wakeword.py` → OK.

## Phase 5 — Continuous conversation UX

**Changed**
- **`frontend/.../js/pages/call.js`**: barge-in monitor (separate echo-cancelled
  mic stream during playback; sustained speech stops TTS and re-listens),
  config-driven VAD (no hard-coded capture timing), mute now hard-stops the
  barge monitor + TTS, and a chat-bar phone button opens/closes the hands-free
  session. Auto re-arm after each reply was retained.
- **`nexus_app.html`**: new `#chat-call-btn` launch button.

**Implementation subtlety:** `VoiceManager.stop()` intentionally does not
resolve the in-flight `speak()` promise, so the barge handler re-arms the mic
explicitly — guaranteeing exactly one listening turn (no double mic-open).

**Verified:** `node --check pages/call.js`, `voice.js` → OK.

## Phase 6 — Testing, benchmarks, docs

**Changed**
- **`backend/bench_tts.py`** (new): cold-vs-warm-vs-switch Piper benchmark;
  gracefully reports "unavailable" instead of faking numbers when models are
  absent.
- **`backend/test_smoke.py`** (extended): app factory, health, `/api/config`,
  config keys (multilingual + Piper + VAD/wake), Piper pool graceful
  degradation, Arabic detection. Runs under pytest **or** standalone
  (`python test_smoke.py`).
- **`README.md`**, **`.env.example`**: documented the new voice pipeline and all
  `NEXUS_*` env vars.
- **`DEVELOPMENT_PLAN.md`**, this report.

## How to get real numbers on the Jetson

```bash
cd backend
bash download_models.sh          # pulls ggml-medium + Piper EN/AR voices
set -a; source ../.env; set +a
python bench_tts.py --rounds 8   # prints cold vs warm vs EN<->AR switch ms
python test_smoke.py             # or: python -m pytest -q
```

The backend also logs `[piper] cold-load`, `FIRST/cold`, and `warm` synth ms
per voice at runtime, so production latency is observable in the server log.
