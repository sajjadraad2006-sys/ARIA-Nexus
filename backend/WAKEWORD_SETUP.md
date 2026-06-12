# Robot Face — Wake word (hands-free) setup

The **Robot Face** page can run fully hands-free: just say the wake word and
ARIA starts listening, thinks, and replies out loud (Whisper → LLM → Piper).
It is powered by **openWakeWord** running inside the Flask backend.

## 1. Install (run once, needs internet)

```bash
pip install openwakeword sounddevice numpy
# download the built-in pretrained wake words (hey_jarvis, alexa, etc.)
python -c "import openwakeword.utils as u; u.download_models()"
```

> On the Jetson you also need PortAudio for `sounddevice`:
> `sudo apt-get install -y libportaudio2`

## 2. (Optional) custom wake word

Drop your trained model files into:

```
<project_root>/models/wakeword/your_word.onnx
```

Any `.onnx` / `.tflite` files found there are loaded automatically.

## 3. Tuning (optional environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `NEXUS_WAKE_THRESHOLD` | `0.5` | Detection sensitivity (0–1, lower = easier to trigger) |
| `NEXUS_WAKE_MODELS` | _(built-in)_ | Comma-separated built-in names, e.g. `hey_jarvis,alexa` |

## 4. How it behaves

* Turn on **“Wake word (hands-free)”** on the Robot Face page.
* The backend opens the mic and listens continuously for the wake word.
* On detection it **frees the mic** so Whisper can record your request
  (a fixed ~6 s listening window), then replies with Piper and re-arms.
* If openWakeWord / sounddevice are missing, the toggle is disabled and the
  badge shows **“Wake word unavailable”** with the reason — everything else
  (tap-to-talk) keeps working.

No extra process/port is needed — the listener runs inside the main
Flask server (port 5000).
