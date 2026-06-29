# AGENTS.md — ARIA Nexus

> Instructions for AI coding agents (OpenCode, etc.) working in this repository.
> Read this fully before making any change.

## 1. Project context
ARIA Nexus is a **fully offline, local-first AI assistant** for a Smart Home & Delivery Robot Hub.
- **Target hardware:** NVIDIA Jetson Orin Nano (Kubuntu/Linux), ~8GB unified RAM/VRAM.
- **Hard rule:** Everything must work **100% offline** at runtime. Never add a feature that requires internet to function. No cloud APIs, no remote model calls.
- **Bilingual:** English (default) + Arabic, including Iraqi dialect.

## 2. Architecture (don't break the pipeline)
Voice pipeline: **Wake Word -> STT -> LLM -> TTS**
- **Wake word:** `openWakeWord` (wake word = "Aria") in `aarya_wakeword/`
- **STT:** `whisper.cpp` (GGML multilingual model) in `vendor/whisper.cpp`
- **LLM:** `Qwen2.5-Instruct` via `llama.cpp` (`vendor/llama.cpp`), text-only, speed-optimized
- **TTS:** `Piper` (warm resident pool) for EN + AR
- **RAG:** `ChromaDB` + `all-MiniLM-L6-v2` embeddings; docs live in `data_files/`, vectors in `chroma_db/`
- **Backend:** `Flask` + `Flask-SocketIO` (`backend/server.py`), orchestrated by `backend/run.bash`
- **Frontend:** Vanilla JS/HTML/CSS dashboard in `frontend/` (NO build step — keep it that way)

## 3. Critical constraints
- **Memory is tight (8GB).** LLM, STT, and TTS share RAM/VRAM. Don't load extra big models or keep duplicates in memory.
- **Flask runs CPU-only on purpose** so the GPU stays fully available for `llama-server`. Do not move Flask work onto the GPU.
- **Models are large** and live in `models/` (`.gguf`, `.bin`, `.onnx`, `.pt`). Never commit model weights. Never hardcode absolute model paths — use `backend/config.py`.
- **Secrets:** real values live in `.env` (gitignored). Never commit `.env` or print tokens (e.g. `HA_TOKEN`). Update `.env.example` when adding a new variable.

## 4. Project structure
```text
Jaston-project/
├── aarya_wakeword/   # Wake word listener scripts and models
├── backend/          # Core Python logic (Flask, RAG, IoT control, configs)
│   ├── run.bash      # Main launcher (spins up LLM, STT, TTS, Flask)
│   ├── config.py     # Centralized configuration (use this for paths/settings)
│   └── server.py     # Flask server entry point
├── chroma_db/        # Persistent vector DB (do not edit by hand)
├── data_files/       # Source documents for RAG indexing
├── frontend/         # Vanilla JS/CSS/HTML Nexus dashboard (no build step)
├── models/           # Downloaded weights (gitignored)
└── vendor/           # Submodules: llama.cpp, whisper.cpp, piper
```

## 5. How to run
```bash
cd backend
bash run.bash
# then open http://localhost:5000/nexus/
```
Setup (first time): `bash backend/setup.sh` then `bash backend/download_models.sh`.

## 6. Coding conventions
- **Python 3**, follow the style already in the codebase. Keep functions small and readable.
- Put all tunable values (paths, ports, model names, URLs) in `backend/config.py` — do not scatter constants.
- Keep the frontend dependency-free (plain JS/HTML/CSS).
- Add short comments for non-obvious logic; Arabic comments are fine where helpful.
- Prefer editing existing modules over adding new top-level files unless necessary.

## 7. Rules for the agent
- **Explore before editing.** Read the relevant files first; base changes on actual code, not assumptions.
- **Don't invent features** that aren't in the code or requested.
- **Don't break offline behavior, the voice pipeline, or memory limits.**
- For any large/structural change, **explain the plan first**, then implement.
- After changes, state clearly what you changed and how to test it.
- If something is ambiguous, ask or add a `TODO:` note instead of guessing silently.

## 8. Roadmap (current priorities)
- Upgrade Whisper to a larger model (`ggml-medium` or `ggml-large-v3-turbo`) for better Iraqi-dialect STT.
- Refine the autonomous navigation loop using YOLOv8 object detection + spatial memory.
