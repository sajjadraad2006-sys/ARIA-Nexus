# =====================================================================
#  nexus_wakeword.py
#  Hands-free wake-word listener for ARIA NEXUS, powered by openWakeWord.
#
#  TWO fully-offline ways to hear the wake word — both run the SAME
#  openWakeWord model locally on the Jetson, so no internet is ever
#  required once the model files are present:
#
#    1) LOCAL MIC (24/7) — a background thread opens the Jetson's own
#       microphone (sounddevice) and feeds 80 ms / 1280-sample frames at
#       16 kHz to the model. The input device is selectable (set_device)
#       because the default device is often wrong on headless Jetsons
#       ("احتمال مايلقط مايك لان ماضايفنه").
#
#    2) STREAMED MIC (feed) — ANY device that opens the web app streams
#       its microphone audio (PCM16 16 kHz mono) to /api/wake/feed; the
#       Jetson runs the model on it. This needs sounddevice NOT at all,
#       only openwakeword + numpy, so a laptop on the same LAN can act as
#       a microphone for the Jetson with the internet completely off.
#
#  When the score crosses the threshold we flag "detected". For the local
#  mic we auto-pause so the mic is freed for Whisper STT; the frontend
#  records the request, gets an LLM reply, speaks it, then re-arms.
#
#  Everything degrades gracefully: if openwakeword / sounddevice / numpy
#  are not installed, available()/available_feed() report why.
#
#  Install on the device (network needed once):
#      pip install openwakeword sounddevice numpy
#      python -c "import openwakeword.utils as u; u.download_models()"
#  Custom wake words: drop *.onnx / *.tflite in <root>/models/wakeword/.
#  Env overrides: NEXUS_WAKE_THRESHOLD, NEXUS_WAKE_MODELS, NEXUS_WAKE_DEVICE
# =====================================================================
import os
import threading
import time

try:
    from nexus_debug import dlog
except Exception:
    def dlog(*a, **kw): pass

try:
    import numpy as np
except Exception:
    np = None

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import nexus_settings as SETTINGS
except Exception:
    SETTINGS = None

try:
    import config as _CFG
except Exception:
    _CFG = None

_OWW_MODEL = None
_OWW_ERR = ""
try:
    from openwakeword.model import Model as _OWW_MODEL
except Exception as _exc:  # pragma: no cover - import guard
    _OWW_MODEL = None
    _OWW_ERR = str(_exc)

SAMPLE_RATE = 16000
FRAME = 1280            # 80 ms @ 16 kHz, the chunk size openWakeWord expects


def _project_root():
    try:
        import config as _cfg
        root = getattr(_cfg, "_PROJECT_ROOT", None)
        if root:
            return root
    except Exception:
        pass
    return os.getcwd()


class WakeWordListener:
    """Singleton-style background wake-word listener (local mic + streamed feed)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._stream = None
        self._running = False
        self._detected = False
        self._phrase = None
        self._score = 0.0
        self._model = None
        self._threshold = self._read_threshold()
        # Reliability tuning (see config.py WAKE_* / NEXUS_WAKE_* env vars):
        # require N consecutive over-threshold frames, then ignore further
        # detections for `cooldown` seconds. This is what kills both the
        # false-accepts (single noisy frame) and the rapid double-fires.
        self._trigger_frames = self._read_trigger_frames()
        self._cooldown = self._read_cooldown()
        self._consec = 0            # consecutive over-threshold frames so far
        self._last_trigger = 0.0    # monotonic-ish wall time of last trigger
        self._device = self._read_device()
        self._model_paths = self._discover_models()
        self._builtin = self._read_builtin_names()
        self._last_error = ""
        # streamed-feed state
        self._feed_buf = b""
        self._last_feed_ts = 0.0

    # ---- configuration helpers ----
    def _settings_wake(self):
        if SETTINGS is None:
            return {}
        try:
            return SETTINGS.get_wake() or {}
        except Exception:
            return {}

    def _read_threshold(self):
        # priority: explicit env override > saved settings > sensible default
        env = os.environ.get("NEXUS_WAKE_THRESHOLD")
        if env:
            try:
                return float(env)
            except Exception:
                pass
        default_thr = float(getattr(_CFG, "WAKE_THRESHOLD", 0.5)) if _CFG else 0.5
        try:
            return float(self._settings_wake().get("threshold", default_thr))
        except Exception:
            return default_thr

    def _read_trigger_frames(self):
        env = os.environ.get("NEXUS_WAKE_TRIGGER_FRAMES")
        if env:
            try:
                return max(1, int(env))
            except Exception:
                pass
        try:
            return max(1, int(getattr(_CFG, "WAKE_TRIGGER_FRAMES", 2)))
        except Exception:
            return 2

    def _read_cooldown(self):
        env = os.environ.get("NEXUS_WAKE_COOLDOWN")
        if env:
            try:
                return max(0.0, float(env))
            except Exception:
                pass
        try:
            return max(0.0, float(getattr(_CFG, "WAKE_COOLDOWN", 1.5)))
        except Exception:
            return 1.5

    def _eval_frame(self, preds):
        """Apply threshold + consecutive-frame debounce + cooldown to ONE
        frame's predictions. Returns (triggered, phrase, best_score).

        A trigger requires `_trigger_frames` consecutive frames at/above the
        threshold AND that we are past the post-trigger cooldown window.
        """
        best, over_name = 0.0, None
        for name, score in preds.items():
            s = float(score)
            if s > best:
                best = s
            if s >= self._threshold:
                over_name = name
        if over_name is not None:
            self._consec += 1
        else:
            self._consec = 0
        if over_name is not None and self._consec >= self._trigger_frames:
            now = time.time()
            if (now - self._last_trigger) >= self._cooldown:
                self._last_trigger = now
                self._consec = 0
                return True, over_name, best
        return False, None, best

    def _read_device(self):
        env = os.environ.get("NEXUS_WAKE_DEVICE")
        if env not in (None, ""):
            try:
                return int(env)
            except Exception:
                return env
        dev = self._settings_wake().get("device", None)
        return dev

    def _read_builtin_names(self):
        raw = os.environ.get("NEXUS_WAKE_MODELS", "").strip()
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()]

    def _discover_models(self):
        paths = []
        base = os.path.join(_project_root(), "models", "wakeword")
        if os.path.isdir(base):
            for f in sorted(os.listdir(base)):
                if f.endswith(".onnx") or f.endswith(".tflite"):
                    paths.append(os.path.join(base, f))
        aarya_dir = os.path.join(_project_root(), "aarya_wakeword")
        if os.path.isdir(aarya_dir):
            for f in sorted(os.listdir(aarya_dir)):
                if f.endswith(".onnx") or f.endswith(".tflite"):
                    candidate = os.path.join(aarya_dir, f)
                    if candidate not in paths:
                        paths.append(candidate)
        return paths

    # ---- availability ----
    def available(self):
        """Local-mic path needs sounddevice too."""
        return _OWW_MODEL is not None and sd is not None and np is not None

    def available_feed(self):
        """Streamed path only needs the model + numpy (no local mic)."""
        return _OWW_MODEL is not None and np is not None

    def reason(self):
        if _OWW_MODEL is None:
            return "openwakeword not installed (pip install openwakeword). " + _OWW_ERR
        if np is None:
            return "numpy not installed (pip install numpy)"
        if sd is None:
            return "sounddevice not installed (pip install sounddevice) — streamed mic still works"
        return ""

    def _ensure_model(self):
        if self._model is not None:
            return
        paths = self._model_paths or self._builtin or []
        try:
            # openwakeword >= 0.5 uses 'wakeword_models'; 0.4.x uses 'wakeword_model_paths'.
            # Try the newer kwarg first, fall back to the older one.
            import inspect as _insp
            sig = _insp.signature(_OWW_MODEL.__init__)
            if "wakeword_models" in sig.parameters:
                kw = "wakeword_models"
            else:
                kw = "wakeword_model_paths"
            kwargs = {kw: paths} if paths else {}
            self._model = _OWW_MODEL(**kwargs)
        except Exception as exc:
            self._last_error = str(exc)
            self._model = None

    def _reset_model(self):
        try:
            if self._model is not None and hasattr(self._model, "reset"):
                self._model.reset()
        except Exception:
            pass

    # ---- live tuning ----
    def set_threshold(self, value):
        try:
            self._threshold = max(0.0, min(1.0, float(value)))
        except Exception:
            pass
        return self._threshold

    def set_device(self, device):
        """Select the local-mic input device (sounddevice index or name).
        Takes effect on the next start(); restarts if already listening."""
        if device in ("", "default", "null", "none"):
            device = None
        elif device is not None:
            try:
                device = int(device)
            except Exception:
                pass  # allow a device-name string
        was_running = self._running
        self._device = device
        if was_running:
            self.stop()
            time.sleep(0.15)
            self.start()
        return self._device

    def list_devices(self):
        """Enumerate local input devices for the Settings mic picker."""
        out = []
        if sd is None:
            return out
        try:
            for idx, dev in enumerate(sd.query_devices()):
                if int(dev.get("max_input_channels", 0)) > 0:
                    out.append({
                        "index": idx,
                        "name": dev.get("name", "device %d" % idx),
                        "channels": int(dev.get("max_input_channels", 0)),
                        "default_samplerate": dev.get("default_samplerate"),
                        "selected": (idx == self._device),
                    })
        except Exception as exc:
            self._last_error = "device query failed: %s" % exc
        return out

    # ---- local-mic lifecycle ----
    def start(self):
        with self._lock:
            if not self.available():
                return False, self.reason()
            if self._running:
                return True, ""
            try:
                self._ensure_model()
            except Exception as exc:
                self._last_error = "model load failed: %s" % exc
                return False, self._last_error
            self._detected = False
            self._phrase = None
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True, ""

    def stop(self):
        with self._lock:
            self._running = False
        return True

    def _loop(self):
        try:
            kwargs = dict(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME)
            if self._device is not None:
                kwargs["device"] = self._device
            self._stream = sd.InputStream(**kwargs)
            self._stream.start()
        except Exception as exc:
            self._last_error = "microphone open failed: %s" % exc
            self._running = False
            self._stream = None
            return

        self._reset_model()

        while self._running:
            try:
                data, _overflow = self._stream.read(FRAME)
                audio = np.asarray(data, dtype=np.int16)
                if audio.ndim > 1:
                    audio = audio[:, 0]
                preds = self._model.predict(audio)
                triggered, phrase, best = self._eval_frame(preds)
                self._score = best
                if triggered:
                    self._detected = True
                    self._phrase = phrase
                    self._running = False   # auto-pause: free the mic for Whisper
                    break
            except Exception:
                time.sleep(0.03)

        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    # ---- streamed-feed path (browser microphone over the LAN) ----
    def feed(self, pcm_bytes):
        """Run the model on externally-captured PCM16 mono @ 16 kHz.

        Accepts raw little-endian int16 bytes (any length). Buffers across
        calls so we always predict on whole 1280-sample frames. Returns
        {available, detected, score, phrase, threshold}.
        """
        if not self.available_feed():
            return {"available": False, "detected": False, "score": 0.0,
                    "phrase": None, "threshold": self._threshold,
                    "reason": self.reason()}
        try:
            self._ensure_model()
        except Exception as exc:
            self._last_error = "model load failed: %s" % exc
            return {"available": False, "detected": False, "score": 0.0,
                    "phrase": None, "threshold": self._threshold,
                    "reason": self._last_error}

        self._last_feed_ts = time.time()
        if not isinstance(pcm_bytes, (bytes, bytearray)):
            try:
                pcm_bytes = bytes(pcm_bytes)
            except Exception:
                pcm_bytes = b""
        self._feed_buf += bytes(pcm_bytes)

        frame_bytes = FRAME * 2  # int16 => 2 bytes/sample
        detected, phrase, best = False, None, 0.0
        while len(self._feed_buf) >= frame_bytes:
            chunk = self._feed_buf[:frame_bytes]
            self._feed_buf = self._feed_buf[frame_bytes:]
            try:
                audio = np.frombuffer(chunk, dtype=np.int16)
                preds = self._model.predict(audio)
                f_trig, f_phrase, f_best = self._eval_frame(preds)
                if f_best > best:
                    best = f_best
                if f_trig:
                    detected = True
                    phrase = f_phrase
            except Exception:
                continue

        # keep the buffer from growing without bound on partial frames
        if len(self._feed_buf) > frame_bytes * 4:
            self._feed_buf = self._feed_buf[-frame_bytes * 4:]

        if detected:
            self._score = best
            dlog("WAKE", "model.DETECTED", score=round(best, 4),
                 phrase=phrase, threshold=self._threshold)
            # reset so the next utterance starts clean after a trigger
            self._feed_buf = b""
            self._reset_model()
        return {"available": True, "detected": detected, "score": round(best, 4),
                "phrase": phrase, "threshold": self._threshold}

    def reset_feed(self):
        self._feed_buf = b""
        self._consec = 0
        self._reset_model()

    # ---- polling ----
    def status(self):
        detected = self._detected
        phrase = self._phrase
        score = self._score
        if detected:
            self._detected = False   # consume the event on read
            self._phrase = None
        models = [os.path.basename(p) for p in self._model_paths] or self._builtin or ["(built-in defaults)"]
        feeding = (time.time() - self._last_feed_ts) < 3.0
        return {
            "available": self.available(),
            "available_feed": self.available_feed(),
            "reason": self.reason(),
            "listening": self._running,
            "feeding": feeding,
            "detected": detected,
            "phrase": phrase if detected else None,
            "score": round(score, 4),
            "models": models,
            "threshold": self._threshold,
            "trigger_frames": self._trigger_frames,
            "cooldown": self._cooldown,
            "device": self._device,
            "error": self._last_error or None,
        }


_LISTENER = WakeWordListener()


def get_listener():
    return _LISTENER
