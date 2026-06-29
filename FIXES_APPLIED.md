# ARIA NEXUS — Fixes Applied (voice + IoT)

All changes are dependency-free and were syntax-checked (Python, JS, bash).

## 1) IoT: chatbot couldn't turn devices on/off  — `backend/config.py`
**Root cause:** nothing loaded `.env` from Python; only `run.bash` did, and it
died on `gnome-terminal: command not found`, so a manual `python3 server.py`
launch left `HA_TOKEN=""` → every Home Assistant call returned 401 → IoT failed
silently.
**Fix:** added a tiny dependency-free `.env` loader at the top of `config.py`.
It loads `backend/.env` and `<root>/.env`, and NEVER overrides vars already in
the environment (so run.bash exports still win). Works for manual launch,
systemd, and IDE.
> You still need: Home Assistant actually running + a valid `HA_TOKEN` in `.env`.

## 2) Launcher died on headless/minimal systems — `backend/run.bash`
**Fix:** `open_term()` now auto-detects gnome-terminal / konsole /
xfce4-terminal / xterm / x-terminal-emulator, and otherwise runs each service
in the background with a log file. No more hard dependency on gnome-terminal.

## 3) Wake word "aria" ran but never heard you — `backend/nexus_wakeword.py`
**Root cause:** if no custom model is in `models/wakeword/` or `aarya_wakeword/`,
openWakeWord loads its built-in words (alexa/hey jarvis/...) which don't include
"aria".
**Fix:**
- Loud startup WARNING when no custom model is found (instead of silent failure).
- When a custom model IS loaded, only accept the configured `WAKE_MODEL_NAME`
  (default "aarya") so stray built-in models can't false-trigger.
- Added `models/wakeword/README.md` explaining exactly what to drop in
  (`aarya.onnx`).
> Action required on device: place `aarya.onnx` in `models/wakeword/` and run
> `pip install openwakeword sounddevice numpy`.

## 4) Robot face went deaf after one turn — `frontend/.../pages/face.js` + `wake.js`
**Root cause:** the always-on listener and the per-turn recorder fought over the
mic (esp. on the Jetson's single mic), and if the turn promise never settled the
wake word stayed stuck "detected" forever.
**Fix:**
- `face.js runWakeTurn()` now `WakeManager.suspend()`s at the start and
  `resume()`s exactly once via a single `done()` path (no more mic contention).
- `wake.js onDetect()` re-arms exactly once and has a 90s watchdog so the
  listener can never get stuck after a single use.

## 5) Chatbot speech didn't stop when you stopped talking — `frontend/.../pages/chatbot.js`
**Root cause:** the chatbot mic used a raw MediaRecorder with NO VAD; it only
stopped when you tapped again.
**Fix:** switched to the shared `MicRecorder.capture({ vad: true })` (same engine
the face page uses). It auto-stops on silence, calls `stopSpeaking()` on start
(barge-in), and tapping again cuts it off early.

## 6) Misc accuracy — `backend/config.py`
- Fixed the Whisper model comment that said "defaults to ggml-medium" while the
  code actually defaults to `ggml-small.bin`.

---
### How to verify after copying onto the laptop
```bash
cd backend
python3 -c "import config; print('TOKEN len =', len(config.HA_TOKEN))"   # > 100, not 0
find .. -name '*.onnx' -o -name '*.tflite'                                # aarya.onnx present?
bash run.bash                                                            # should start even without gnome-terminal
```
