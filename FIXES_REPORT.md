# ARIA Nexus — Fixes Report (2026-06-12)

Senior-engineer debugging pass on the 6 reported issues. All changes are
minimal/surgical, keep the existing architecture, load no extra heavy models
(RAM-safe), and read from `config.py` as the single source of truth.

## Critical architecture note
The live SPA (`frontend/application/`, served at `/nexus/`) uses the REST
endpoints in `nexus_routes_additions.py` + the `nexus_assistant.py` brain — NOT
the legacy SocketIO handlers in `server.py` (those belong to the old
`web_ui/templates` UI and are effectively dead for the SPA). All fixes target
the live path.

## Verification on this build
- `python -m py_compile` on every changed .py: PASS
- `node --check` on changed/related JS: PASS
- `backend/test_smoke.py`: 2 passed, 4 skipped (Flask not installed in dev box), 0 failed
- No new models loaded; RAM-neutral.

---

## Issue 5 — STT only English  (FIXED)
**Root cause:** `nexus_stt_inference_proxy` (`nexus_routes_additions.py`) forwarded
only `response_format` to whisper.cpp and never sent `language`; whisper.cpp's
server defaults `language` to `en`, forcing English decoding.
**Fix:** forward `language` (from `config.WHISPER_LANGUAGE`, default `auto`) +
`temperature` to `/inference`.
**Issue 5b:** exact multilingual-model download command added to `README.md`;
`config.py` already documents `NEXUS_WHISPER_MODEL` / `NEXUS_WHISPER_LANGUAGE`.

## Issue 6 — IoT control  (FIXED)
**Root cause (i):** `nexus_assistant.llm_chat` never injected the live HA entity
list, so the LLM guessed entity_ids that don't exist -> tags unusable.
**Root cause (ii):** `handle_command` returned the model's optimistic "done"
text even when `execute_tags` reported `ok:false`; pages ignore `executed`.
**Fix:** inject live `ha_states()` entities into the system prompt; rewrite the
spoken reply to reflect the ACTUAL execution result (full/partial/total failure),
in the user's language (AR/EN).
Note: set `HA_TOKEN` + `HA_URL` in config/.env — IoT is dead until they are set.

## Issue 1 — RAG knowledge management  (FIXED, needs one-time reindex)
**Root cause (retrieval, not persistence):** endpoints + persistence work; the
Chroma collections were created with the default squared-L2 space, so langchain
relevance = 1 - distance maps good matches below `RAG_MIN_RELEVANCE` (0.3) and
filters everything out. Also the shared `RAGEngine` cached empty results and
latched `_available=False` after booting on an empty DB.
**Fix:** create all Chroma collections with `hnsw:space=cosine`
(`rag_engine.py`, `nexus_rag_store.py`, `ingest.py`); clear the shared engine
cache + set `_available=True` on add, clear cache on delete.
**One-time action after deploy:** rebuild the vector DB so the cosine metric
takes effect:
```bash
cd backend && python -m ingest    # or the Knowledge "Reindex" button
```

## Issue 2 — Offline wake / local whisper  (FIXED + on-device deps)
**Root cause:** the offline stream path (mic -> /api/wake/feed -> openWakeWord)
and offline STT are wired correctly; they only run if `openwakeword`+`numpy`
(+`sounddevice` for local mic) are installed and the `aarya` model loads.
`wakelistener.js` swallowed the server's `available:false` flag, so offline wake
failed silently and users fell back to online speech mode. The Issue-5 language
bug also broke the wake-turn transcription.
**Fix:** `wakelistener.js` now surfaces `available:false` once (red dot +
actionable console message). Whisper half fixed by Issue 5.
**On-device:** `pip install openwakeword sounddevice numpy`; verify
`/api/wake/status` -> `available_feed: true`.

## Issue 4 — Continuous conversation on wake  (NO CODE CHANGE NEEDED)
`call.js` already implements the continuous loop (listen -> reply -> auto re-arm,
ends after 2 silent rounds) and is the default wake destination. It only
appeared broken because STT returned empty/English each turn — fixed by Issue 5.

## Issue 3 — Mic UX  (FIXED)
- Mic closed by default: already true (tap-to-talk on face; toggle on chatbot).
- Latency: VAD silence hangover was 1500 ms -> reduced to 800 ms
  (`config.py VAD_CONFIG.silenceMs`, tunable via `NEXUS_VAD_SILENCE_MS`).
- Barge-in: full talk-over already exists in `call.js` (the default wake UI);
  face/chatbot interrupt TTS on next action. Not rewritten (surgical scope).

---

## Files changed
- backend/nexus_routes_additions.py  (Issue 5)
- backend/nexus_assistant.py          (Issue 6)
- backend/nexus_rag_store.py          (Issue 1)
- backend/rag_engine.py               (Issue 1)
- backend/ingest.py                   (Issue 1)
- backend/config.py                   (Issue 3)
- frontend/application/js/wakelistener.js (Issue 2)
- README.md                           (Issue 5b)

## On-device checklist (Jetson Orin Nano)
1. `cd backend && python -m ingest`  (rebuild Chroma with cosine — Issue 1)
2. `pip install openwakeword sounddevice numpy`; check `/api/wake/status` (Issue 2/4)
3. Set `HA_TOKEN` + `HA_URL`; `curl /api/states` returns devices (Issue 6)
4. (optional) download `ggml-medium.bin`, set `NEXUS_WHISPER_MODEL` (Issue 5)
5. Internet OFF end-to-end: "Aria" -> Call opens -> speak Arabic -> correct AR
   transcript -> "turn on <real device>" actuates -> spoken confirmation matches
   reality -> auto re-arm.
