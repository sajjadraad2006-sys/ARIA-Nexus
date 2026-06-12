#!/usr/bin/env python3
# =====================================================================
#  piper_server.py  --  Real Piper TTS server for ARIA Nexus TTS Studio
#  Listens on 127.0.0.1:5002 and exposes EXACTLY the endpoints the Nexus
#  backend proxies to:
#      GET  /health       -> {"status": "ok", ...}
#      GET  /voices       -> {"voices": [...], "active": "<id>"}
#      POST /voice        -> {"voice_id": "..."}  (set active voice)
#      POST /synthesize   -> {"text": "...", "voice_id?": "..."} -> WAV bytes
#
#  Piper is fully OFFLINE and fast on Jetson Orin Nano (CPU, no GPU needed),
#  which frees the GPU for the LLM.
#
#  SETUP (run once on the Jetson, with internet):
#      pip install piper-tts
#      mkdir -p models/piper
#      # download a voice (.onnx + .onnx.json) into models/piper/, e.g.:
#      #   ar_JO-kareem-medium.onnx / .onnx.json   (Arabic)
#      #   en_US-amy-medium.onnx   / .onnx.json   (English)
#  Then run:  python3 piper_server.py
# =====================================================================
import io
import os
import glob
import json
import wave
import threading

from flask import Flask, jsonify, request, Response

# ---- locate the voices directory ------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))


def _voices_dir():
    try:
        import config as c
        d = getattr(c, "PIPER_VOICES_DIR", None)
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    # Try project root first (ARIA_NEXUS_FULL/models/piper_voices)
    project_root = os.path.dirname(_HERE)
    candidate = os.path.join(project_root, "models", "piper_voices")
    if os.path.isdir(candidate):
        return candidate
    # Final fallback
    return os.path.join(_HERE, "models", "piper_voices")


HOST = "0.0.0.0"
PORT = 5002
try:
    import config as _c
    PORT = int(getattr(_c, "TTS_PORT", 5002))
except Exception:
    pass

app = Flask(__name__)

_lock = threading.RLock()
_loaded = {}          # voice_id -> PiperVoice instance (lazy cache)
_active = {"id": None}


def _voice_files():
    """Return {voice_id: onnx_path} for every voice in the voices dir."""
    out = {}
    d = _voices_dir()
    if not os.path.isdir(d):
        return out
    for onnx in sorted(glob.glob(os.path.join(d, "*.onnx"))):
        vid = os.path.splitext(os.path.basename(onnx))[0]
        out[vid] = onnx
    return out


def _voice_meta(vid, onnx_path):
    """Read the sidecar .onnx.json for language / quality info."""
    meta = {
        "id": vid,
        "voice_id": vid,
        "name": vid,
        "language": "",
        "quality": "",
        "num_speakers": 1,
    }
    cfg_path = onnx_path + ".json"
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8") as f:
                j = json.load(f)
            lang = j.get("language") or {}
            if isinstance(lang, dict):
                meta["language"] = lang.get("name_native") or lang.get("code") or ""
            else:
                meta["language"] = str(lang)
            meta["quality"] = (j.get("audio") or {}).get("quality", "") or j.get("quality", "")
            meta["num_speakers"] = int(j.get("num_speakers", 1) or 1)
    except Exception:
        pass
    return meta


def _get_voice(vid):
    """Lazy-load and cache a PiperVoice."""
    with _lock:
        if vid in _loaded:
            return _loaded[vid]
        files = _voice_files()
        onnx = files.get(vid)
        if not onnx:
            return None
        from piper import PiperVoice
        voice = PiperVoice.load(onnx)
        _loaded[vid] = voice
        return voice


def _default_voice_id():
    if _active["id"]:
        return _active["id"]
    files = _voice_files()
    if files:
        first = sorted(files.keys())[0]
        _active["id"] = first
        return first
    return None


def _synth_wav_bytes(voice, text):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        if hasattr(voice, "synthesize_wav"):
            voice.synthesize_wav(text, wf)
        else:
            voice.synthesize(text, wf)
    return buf.getvalue()


@app.route("/", methods=["GET"])
def root():
    # Lightweight liveness route so health-check pings don't spam 404s.
    return jsonify({"status": "ok", "engine": "piper"})


@app.route("/health", methods=["GET"])
def health():
    files = _voice_files()
    return jsonify({
        "status": "ok",
        "engine": "piper",
        "voices_dir": _voices_dir(),
        "voice_count": len(files),
        "active": _default_voice_id(),
    })


@app.route("/voices", methods=["GET"])
def voices():
    files = _voice_files()
    voices_list = [_voice_meta(vid, path) for vid, path in files.items()]
    return jsonify({"voices": voices_list, "active": _default_voice_id()})


@app.route("/voice", methods=["POST"])
def set_voice():
    data = request.get_json(silent=True) or {}
    vid = data.get("voice_id") or data.get("voice") or data.get("id")
    if not vid:
        return jsonify({"ok": False, "error": "voice_id is required"}), 400
    if vid not in _voice_files():
        return jsonify({"ok": False, "error": "unknown voice: " + str(vid)}), 404
    _active["id"] = vid
    return jsonify({"ok": True, "active": vid})


@app.route("/synthesize", methods=["POST"])
def synthesize():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    vid = data.get("voice_id") or data.get("voice") or _default_voice_id()
    if not text:
        return jsonify({"error": "text is required"}), 400
    if not vid:
        return jsonify({"error": "no voices installed in " + _voices_dir()}), 503
    try:
        voice = _get_voice(vid)
        if voice is None:
            return jsonify({"error": "unknown voice: " + str(vid)}), 404
        audio = _synth_wav_bytes(voice, text)
        return Response(audio, mimetype="audio/wav")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    print("[piper] serving voices from: " + _voices_dir())
    print("[piper] listening on http://" + HOST + ":" + str(PORT))
    app.run(host=HOST, port=PORT, threaded=True)
