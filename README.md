# ARIA Nexus

Local, offline-first AI assistant for a Smart Home & Delivery Robot Hub.

- **Backend:** Flask + Flask-SocketIO (`backend/`)
- **Frontend:** vanilla-JS single-page app, no build step (`frontend/application/`)
- **Wake word:** local hot-word listener (`aarya_wakeword/`)
- **LLM:** Qwen2.5-3B-Instruct (text-only) via llama.cpp
- **STT:** whisper.cpp · **TTS:** Piper · **RAG:** ChromaDB
- **IoT:** Home Assistant + generic LAN (Tasmota/ESP) devices

## Quick start

```bash
cp .env.example .env        # then edit .env and fill in your secrets
set -a; source .env; set +a # load env vars into the shell
cd backend && bash run.bash # launches LLM + STT + TTS + Flask
```

Open the Flask host in a browser (default `http://<host>:5000`).

## Configuration & secrets

All secrets are read from the environment — nothing sensitive is stored in
source. Copy `.env.example` to `.env`, fill it in, and load it before launch.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `HA_TOKEN` | for IoT | _(empty)_ | Home Assistant long-lived access token |
| `HA_URL` | no | `http://127.0.0.1:8123` | Home Assistant base URL |
| `HA_TIMEOUT` | no | `10` | Home Assistant request timeout (seconds) |
| `FLASK_SECRET_KEY` | recommended | random per boot | Flask session signing key |
| `ALLOWED_ORIGINS` | no | localhost + detected LAN | CORS / Socket.IO allowlist (comma-separated origins). Never `*`. |

## Security notes

- `backend/config.py` and `.env` are git-ignored — do not commit real tokens.
- CORS / Socket.IO is restricted to localhost + detected LAN IPs by default;
  override with `ALLOWED_ORIGINS` (e.g. when serving over HTTPS on a fixed IP).
- If a token was ever committed to version control, **rotate it** (revoke it in
  Home Assistant and issue a new one) — removing it from source is not enough.

## Voice pipeline

The full-duplex voice stack was reworked for reliability and responsiveness:

- **Warm Piper TTS** (`backend/piper_tts.py`): each voice's ONNX model is loaded
  once and kept resident in RAM in a thread-safe pool. EN + AR are pre-warmed at
  startup, so only the *first* use of a voice is slow; switching EN ↔ AR reuses
  the already-warm model. Falls back to the legacy subprocess path if Piper is
  unavailable. Benchmark it: `cd backend && python bench_tts.py`.
- **Multilingual STT**: whisper.cpp now uses a multilingual model
  (`ggml-medium` by default) with per-utterance language auto-detection, tuned
  for Arabic (incl. Iraqi dialect) + English. Model + language are configurable
  (`NEXUS_WHISPER_MODEL`, `NEXUS_WHISPER_LANGUAGE`).
  > **TODO (next engineer): download a multilingual model.** The repo ships
  > with `ggml-small.bin`, which is multilingual but weak on Iraqi-dialect
  > Arabic. For stronger Arabic, download `ggml-medium.bin` (the default the
  > code expects) or `ggml-large-v3-turbo.bin` into `models/`, then point
  > `NEXUS_WHISPER_MODEL` at it. The `*.en` models are English-only — do NOT
  > use them.
  > ```bash
  > # from vendor/whisper.cpp (downloads into ./models, then copy/symlink):
  > bash ./models/download-ggml-model.sh medium       # -> ggml-medium.bin (~1.5 GB)
  > # or the faster turbo model:
  > bash ./models/download-ggml-model.sh large-v3-turbo
  > # place the .bin in <project>/models/ and select it:
  > export NEXUS_WHISPER_MODEL=ggml-medium.bin
  > export NEXUS_WHISPER_LANGUAGE=auto   # or "ar" to force Arabic
  > ```
- **Endpointing / VAD** (`frontend/.../js/mic.js`): ambient noise-floor
  calibration, pre-roll (recording starts before VAD arms so the first phoneme
  is never clipped), a minimum-speech gate and a silence hangover so utterances
  are never cut off mid-sentence. Tunable via `VAD_CONFIG` / `NEXUS_VAD_*`.
- **Wake word** (`backend/nexus_wakeword.py`): config-driven threshold (the old
  `0.1` caused constant false-accepts), plus a consecutive-frame debounce and a
  post-trigger cooldown. Tunable via `NEXUS_WAKE_*`.
- **Continuous conversation** (`frontend/.../js/pages/call.js`): press the
  phone/mic button to start a hands-free session; the mic auto re-arms after
  ARIA replies; **barge-in** (talking over ARIA stops playback and starts
  listening); and a **mute** button hard-stops capture with a clear visual
  state.

The frontend reads these tunables from the backend at boot via `GET /api/config`
(`window.NEXUS_VAD`), so there is a single source of truth in `config.py` / env.

## Tests

```bash
cd backend && python -m pytest -q     # or: python test_smoke.py  (no pytest needed)
cd backend && python bench_tts.py     # TTS warm-up latency benchmark
```

Includes a smoke test (`backend/test_smoke.py`) that builds the Flask app
factory and checks that `/api/launcher/health` responds.
