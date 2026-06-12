# ARIA Nexus — Voice Pipeline Overhaul: Development Plan

A phased plan to fix warm TTS, wake-word reliability, Whisper endpointing,
multilingual STT, and the continuous-conversation UX. Each phase lists the
exact files/functions touched, the approach, edge cases, and verification.

> **Environment note:** the dev sandbox has no GPU/Jetson, no microphone, and
> no model files or running llama/whisper/piper servers. So all backend Python
> is **compile- and import-verified** and the logic is wired for real hardware,
> but true end-to-end audio latency must be measured on the Jetson with
> `bench_tts.py` and the in-code latency logs. Where a number can only come
> from real hardware, that is stated explicitly rather than faked.

---

## Phase 0 — Investigation & baseline

- **Looked at:** `server.py` (`generate_tts`, `generate_piper_audio`,
  `_resolve_piper_voice`, `_piper_warmup`, `_is_arabic_text`, whisper proxy),
  `config.py`, `nexus_wakeword.py`, `aarya_wakeword/`, `piper_server.py`,
  and the frontend `mic.js`, `voice.js`, `pages/call.js`, `wake.js`,
  `wakelistener.js`, `api.js`.
- **Root causes confirmed:**
  1. `generate_piper_audio()` spawns a fresh `piper` process per call, so the
     ONNX model is reloaded from disk every request → no warm behaviour, slow
     EN↔AR switching.
  2. Wake word threshold `0.1` with no debounce/cooldown → false-accepts and
     unreliable triggering; default model name (`aarya`) vs spoken "Aria".
  3. Frontend VAD cut speech early (short silence window, no min-speech gate,
     no noise-floor calibration).
  4. STT used English-leaning `ggml-small.bin` with a fixed `response_format`
     and no language control → weak Arabic.
  5. Continuous mode lacked barge-in and a hard mute, and was only reachable
     via the wake word.

## Phase 1 — Persistent / warm Piper TTS

- **Files:** new `backend/piper_tts.py`; `backend/server.py`
  (`generate_piper_audio`, `_piper_warmup`, Piper constants → config import);
  `backend/config.py` (PIPER_* knobs).
- **Approach:** a thread-safe `PiperVoicePool` keeps each voice's ONNX model
  resident (via `piper` Python API when present, else a cached long-lived path)
  and exposes `synthesize(text, voice)`. EN + AR are pre-warmed at startup in a
  background thread. `generate_piper_audio()` tries the pool first and falls
  back to the legacy subprocess if the pool is unavailable. First-vs-warm synth
  latency is logged per voice.
- **Edge cases:** Piper/voice files missing → `is_available()` false, callers
  fall back; concurrent synths serialized per voice; Arabic auto voice-swap
  preserved.
- **Verify:** `python -m py_compile`; `bench_tts.py` (cold vs warm vs switch).

## Phase 2 — Multilingual Whisper

- **Files:** `config.py` (`WHISPER_MODEL_FILE`, `WHISPER_MODEL`,
  `WHISPER_LANGUAGE`, `WHISPER_TEMPERATURE`); `server.py` (`_whisper_data()`
  helper + all 5 inference POST sites; fixed a double-`/inference` bug);
  `download_models.sh` (env-aware multilingual model download, small kept as
  fallback).
- **Approach:** default to multilingual `ggml-medium.bin`; send `language`
  ("auto" detects AR/EN per utterance) + `temperature` with every request; make
  model + language configurable via env.
- **Edge cases:** old config without the new keys → safe `"auto"`/`0.0`
  fallback; low-RAM devices can set `NEXUS_WHISPER_MODEL=ggml-small.bin`.
- **Verify:** `py_compile`; `bash -n download_models.sh`; `/api/config` echoes
  language; accuracy to be confirmed on-device with AR (Iraqi) + EN clips.

## Phase 3 — Whisper VAD / endpointing

- **Files:** `frontend/application/js/mic.js`; `config.py` `VAD_CONFIG`;
  `server.py` `/api/config`; `pages/call.js` (uses shared config).
- **Approach:** record BEFORE arming VAD (pre-roll, no clipped onset); ambient
  noise-floor calibration → dynamic speech threshold; min-speech gate +
  silence hangover + min/max length so turns never end mid-sentence. All knobs
  come from `VAD_CONFIG` / `NEXUS_VAD_*` via `window.NEXUS_VAD`.
- **Edge cases:** noisy rooms (calibration), very short clicks (min-speech),
  no AudioContext (falls back to fixed timing).
- **Verify:** `node --check mic.js`; `/api/config` returns the VAD block.

## Phase 4 — Wake-word reliability

- **Files:** `backend/nexus_wakeword.py`; `config.py` (`WAKE_THRESHOLD`,
  `WAKE_TRIGGER_FRAMES`, `WAKE_COOLDOWN`, `WAKE_MODEL_NAME`).
- **Approach:** config-driven threshold (raised from 0.1 → 0.5), a shared
  `_eval_frame()` applying an N-consecutive-frame debounce + post-trigger
  cooldown for BOTH the local-mic loop and the streamed `feed()` path;
  thresholds/frames/cooldown surfaced in `status()`.
- **Edge cases:** model file named `aarya` (≈ "Aria") documented; graceful
  degradation if openwakeword/numpy absent; buffer bounded on partial frames.
- **Verify:** `py_compile`; existing wake→`AssistantCall` handoff in `wake.js`.

## Phase 5 — Continuous conversation UX

- **Files:** `frontend/application/js/pages/call.js`; `nexus_app.html`
  (new launch button); `mic.js`/`voice.js` reused.
- **Approach:** a phone/mic button starts the hands-free session; mic auto
  re-arms 300 ms after ARIA replies; a separate echo-cancelled barge-in monitor
  during playback stops TTS and re-listens on sustained user speech; the mute
  button hard-stops capture (cancels mic + barge monitor + TTS) with clear
  visual state.
- **Edge cases:** `VoiceManager.stop()` does not resolve the in-flight speak
  promise, so barge-in re-arms explicitly (no double mic-open); mute mid-turn;
  two silent rounds auto-end the call.
- **Verify:** `node --check pages/call.js`.

## Phase 6 — Testing, benchmarks, docs

- **Files:** `backend/bench_tts.py` (new); `backend/test_smoke.py` (extended,
  runs with or without pytest); `README.md`; `.env.example`; this plan +
  `IMPLEMENTATION_REPORT.md`.
- **Verify:** `python test_smoke.py` standalone runner; `bench_tts.py` on
  device; all backend modules `py_compile` clean; all touched JS `node --check`
  clean.
