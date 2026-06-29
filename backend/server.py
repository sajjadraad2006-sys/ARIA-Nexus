import os
import time

# ══ MUST be set BEFORE torch/transformers are imported ═════════════════
# Flask/RAG runs on CPU. All VRAM is reserved for llama-server.
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["CUDA_DEVICE_ORDER"]    = "PCI_BUS_ID"

_BACKEND_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)  # ARIA_NEXUS_FULL root
import re
import json
import base64
import tempfile
import socket
import subprocess
import requests
from collections import deque
from flask import Flask, render_template, request, redirect, jsonify
from flask_socketio import SocketIO, emit

# ==========================================
# IMPORT CONFIG (single source of truth)
# ==========================================
from config import (
    FLASK_HOST, FLASK_PORT,
    WHISPER_URL as WHISPER_BASE_URL,
    LLAMA_URL   as LLAMA_BASE_URL,
    FFMPEG_PATH,
    ROBOT_SYSTEM_PROMPT,
    TTS_URL     as TTS_BASE_URL,
    QWEN_TTS_TIMEOUT,
    WHISPER_TIMEOUT,
    LLAMA_TIMEOUT,
    RAG_ENABLED,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_REPEAT_PENALTY,
    LLM_MAX_TOKENS,
    LLM_HISTORY_TURNS,
    LLAMA_CTX,
    HA_URL,
    HA_TOKEN,
    HA_TIMEOUT,
    # YOLO + Autonomous Navigation
    YOLO_MODEL_PATH,
    YOLO_CONFIDENCE,
    YOLO_APPROACH_RATIO,
    YOLO_CENTER_THRESH,
    SPATIAL_MEMORY_COLLECTION,
    AUTO_NAV_CYCLE_INTERVAL,
    AUTO_NAV_YOLO_INTERVAL,
    AUTO_NAV_MAX_MISSION_TIME,
    AUTO_NAV_MEMORY_INTERVAL,
)

WHISPER_URL = WHISPER_BASE_URL + "/inference"

# Multilingual STT controls (configurable; defaults stay safe if config is old).
try:
    from config import WHISPER_LANGUAGE, WHISPER_TEMPERATURE
except Exception:
    WHISPER_LANGUAGE, WHISPER_TEMPERATURE = "auto", 0.0

def _whisper_data(extra: dict | None = None) -> dict:
    """Form fields sent with every whisper.cpp /inference POST.

    Sending `language` is what makes STT bilingual: "auto" lets whisper.cpp
    detect Arabic vs English per utterance; set NEXUS_WHISPER_LANGUAGE=ar|en to
    force one. `temperature` keeps decoding deterministic. Centralised here so
    every STT call site stays in sync.
    """
    data = {
        "response_format": "json",
        "language": WHISPER_LANGUAGE,
        "temperature": str(WHISPER_TEMPERATURE),
    }
    if extra:
        data.update(extra)
    return data
LLAMA_URL   = LLAMA_BASE_URL  + "/v1/chat/completions"
TTS_URL     = TTS_BASE_URL    + "/generate"   # Qwen3-TTS FastAPI endpoint

# ==========================================
# HTTP SESSION — connection pooling
# Reuses TCP + TLS across requests to the same backend (~50-100ms saved)
# ==========================================
_http = requests.Session()
_http.headers.update({"Connection": "keep-alive"})

# ==========================================
# RAG ENGINE  (Retrieval-Augmented Generation)
# ==========================================
rag_engine = None
if RAG_ENABLED:
    try:
        from rag_engine import RAGEngine
        rag_engine = RAGEngine()
        if rag_engine.is_available():
            print("[RAG] ✅ RAG engine loaded — document context will be injected")
        else:
            print("[RAG] Engine loaded but no documents found — run ingest first")
    except Exception as _rag_err:
        print(f"[RAG] Could not load RAG engine: {_rag_err}")
        rag_engine = None

# ==========================================
# YOLO OBJECT DETECTION  — DISABLED (text-only chatbot mode)
# ==========================================
_yolo_model = None
_HAS_YOLO = False
print("[YOLO] Skipped — text-only chatbot mode (saving RAM)")

# ==========================================
# SPATIAL MEMORY ENGINE  — DISABLED (text-only chatbot mode)
# ==========================================
spatial_engine = None
print("[SpatialMem] Skipped — text-only chatbot mode (saving RAM)")

# ==========================================
# IOT CONTROLLER  (Home Assistant Bridge)
# ==========================================
iot_controller = None
generic_device_mgr = None
try:
    from iot_controller import HAController, GenericDeviceManager
    iot_controller = HAController(
        ha_url=HA_URL,
        ha_token=HA_TOKEN,
        timeout=HA_TIMEOUT,
    )
    # Generic device manager — ONE canonical JSON store shared by the dashboard
    # routes (GENERIC_PATH) and the assistant brain (_get_generic_mgr). The path
    # is absolute (see config.NEXUS_GENERIC_DEVICES_PATH) so every component
    # reads/writes the exact same file regardless of the process CWD.
    from config import NEXUS_GENERIC_DEVICES_PATH as _GENERIC_DEVICES_PATH
    generic_device_mgr = GenericDeviceManager(_GENERIC_DEVICES_PATH)

    if iot_controller.is_available():
        print("[IoT] ✅ Home Assistant reachable — Smart Home enabled")
    else:
        print("[IoT] ⚠️  Home Assistant not reachable (will retry on demand)")
except Exception as _iot_err:
    print(f"[IoT] Could not load IoT controller: {_iot_err}")
    iot_controller = None
    generic_device_mgr = None

# --- Piper configuration (single source of truth is config.py; literals are
# kept only as a defensive fallback so server.py still runs if config is old) ---
try:
    from config import (
        PIPER_EXE, PIPER_VOICES_DIR, PIPER_DEFAULT_VOICE, PIPER_ARABIC_VOICE,
        PIPER_PREWARM_VOICES, PIPER_USE_POOL,
    )
except Exception:
    PIPER_EXE        = os.path.join(_PROJECT_ROOT, "vendor", "piper", "piper")
    PIPER_VOICES_DIR = os.path.join(_PROJECT_ROOT, "models", "piper_voices")
    PIPER_DEFAULT_VOICE = "en_GB-semaine-medium"   # original ARIA (English) voice
    PIPER_ARABIC_VOICE  = "ar_JO-kareem-medium"    # auto-selected for Arabic replies
    PIPER_PREWARM_VOICES = [PIPER_DEFAULT_VOICE, PIPER_ARABIC_VOICE]
    PIPER_USE_POOL = True

# Persistent, warm Piper voice pool (keeps each ONNX voice resident in RAM).
# Import is guarded so a missing dependency simply disables the pool and we
# fall back to the legacy spawn-per-call binary path.
try:
    from piper_tts import get_pool as _get_piper_pool, PiperUnavailable
    _PIPER_POOL = _get_piper_pool()
except Exception as _pool_err:   # pragma: no cover - import guard
    print(f"[Piper] Warm pool unavailable, using legacy spawn path: {_pool_err}")
    _PIPER_POOL = None
    class PiperUnavailable(RuntimeError):
        pass

def _resolve_piper_voice(voice_name: str) -> tuple[str, str]:
    """Return (model_path, config_path) for the given Piper voice name."""
    model  = os.path.join(PIPER_VOICES_DIR, f"{voice_name}.onnx")
    config = os.path.join(PIPER_VOICES_DIR, f"{voice_name}.onnx.json")
    if not os.path.exists(model):
        # Fallback to default
        print(f"[Piper] Voice '{voice_name}' not found — falling back to {PIPER_DEFAULT_VOICE}")
        model  = os.path.join(PIPER_VOICES_DIR, f"{PIPER_DEFAULT_VOICE}.onnx")
        config = os.path.join(PIPER_VOICES_DIR, f"{PIPER_DEFAULT_VOICE}.onnx.json")
    return model, config

def _is_arabic_text(text: str) -> bool:
    """Return True if the text is predominantly Arabic."""
    if not text:
        return False
    arabic_chars = sum(1 for ch in text if '\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u077F')
    return arabic_chars > len(text) * 0.3

# ==========================================
# FLASK + SOCKETIO
# ==========================================
from config import ALLOWED_ORIGINS


def _local_ipv4s():
    """Best-effort list of this machine's IPv4 addresses (all interfaces)."""
    import socket as _socket
    import subprocess as _subprocess
    ips = []
    try:
        out = _subprocess.run(["hostname", "-I"], capture_output=True,
                              text=True, timeout=3)
        for tok in out.stdout.split():
            tok = tok.strip()
            if tok and ":" not in tok and tok not in ips:  # skip IPv6
                ips.append(tok)
    except Exception:
        pass
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    return ips


def _resolve_allowed_origins():
    """Socket.IO CORS allowlist. Uses ALLOWED_ORIGINS from config/env when set;
    otherwise defaults to localhost + this machine's LAN IPs on the Flask port
    (both http and https). Never falls back to a '*' wildcard."""
    if ALLOWED_ORIGINS:
        return list(ALLOWED_ORIGINS)
    hosts = ["localhost", "127.0.0.1"] + _local_ipv4s()
    origins, seen = [], set()
    for h in hosts:
        for scheme in ("http", "https"):
            for candidate in (f"{scheme}://{h}:{FLASK_PORT}", f"{scheme}://{h}"):
                if candidate not in seen:
                    seen.add(candidate)
                    origins.append(candidate)
    return origins


# The Flask app + Socket.IO server are created at import time so the route and
# Socket.IO handlers defined below can bind to them. create_app() is a thin,
# importable factory (used by tests / external launchers) that returns the
# already-configured singletons.
app = Flask(__name__, template_folder='web_ui/templates', static_folder='web_ui/static')
from nexus_routes_additions import register_nexus
register_nexus(app, rag_engine=rag_engine)

# SECURITY: Flask secret + CORS allowlist come from the environment / config,
# never hard-coded. A missing FLASK_SECRET_KEY falls back to a random per-boot key.
app.config['SECRET_KEY'] = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())
socketio = SocketIO(app, cors_allowed_origins=_resolve_allowed_origins(),
                    async_mode='threading',
                    max_http_buffer_size=8 * 1024 * 1024)  # 8 MB — for custom face images


def create_app():
    """Return the configured (app, socketio) singletons.

    Routes and Socket.IO handlers are registered against the module-level
    ``app`` / ``socketio`` at import time, so this factory simply returns those
    fully-wired objects. It lets tests and external WSGI launchers obtain the
    app without executing the ``__main__`` block.
    """
    return app, socketio

# ==========================================
# CONVERSATION MEMORY  (rolling 10-turn window)
# ==========================================
MAX_HISTORY = 10
conversation_history: deque = deque(maxlen=MAX_HISTORY)

def add_to_history(role: str, content) -> None:
    conversation_history.append({"role": role, "content": content})

def get_history_messages() -> list:
    """Return the last N messages for the LLM context window.

    We keep MAX_HISTORY (10) in the deque for internal state, but only
    send LLM_HISTORY_TURNS (6) to the LLM to leave room for RAG context.
    """
    history = list(conversation_history)
    return history[-LLM_HISTORY_TURNS:]

# ==========================================
# LATEST VIDEO FRAME
# ==========================================
latest_video_frame: str | None = None

# ==========================================
# SYSTEM PROMPTS
# ==========================================
SYSTEM_PROMPT = ROBOT_SYSTEM_PROMPT

VISION_SYSTEM_PROMPT = """You are ARIA, a friendly smart delivery robot with a live camera.
Describe what you see in the image concisely and helpfully.
Keep responses under 3 sentences unless asked for detail."""

# Receptionist persona — used by /chatbot page (full ARIA identity with IoT)
RECEPTIONIST_PROMPT = ROBOT_SYSTEM_PROMPT

# ==========================================
# VISION GATEKEEPER — pre-compiled regex (single-pass match)
# ==========================================
VISION_TRIGGERS = [
    # English — "see"
    "what do you see", "can you see", "what can you see",
    "what are you seeing", "what do u see", "wat do you see",
    "you see", "tell me what you see", "what can u see",
    "what r you seeing", "what can you c",
    # English — "look"
    "look around", "look at that", "take a look", "have a look",
    "look at this", "what are you looking at",
    # English — camera / vision
    "show me what", "use the camera", "use your camera",
    "what's in front", "what is in front", "in front of you",
    "around you", "what's there", "what is there",
    "describe what", "describe the", "describe your surroundings",
    "what is that", "what's that", "who is that", "who's there",
    "read that sign", "scan the", "detect the", "identify that",
    "what do you notice", "what do you observe",
    "look and tell", "tell me what's around",
    "what do u c", "what can i see", "show me",
    "can you look", "can u see", "what's happening",
    # Arabic — MSA + Gulf + Iraqi
    "شاهد", "انظر", "كاميرا", "كامرا",
    "ما أمامك", "صف ما", "ماذا ترى", "ماذا تشاهد",
    "وش تشوف", "شو تشوف", "شوف", "وش قدامك", "ايش تشوف",
    "صف محيطك", "ايش امامك",
    # Iraqi Arabic
    "شنو تشوف", "شنو امامك", "شنو تشاهد", "شنو تريد",
    "تشوف شي", "ترى شي", "شوفلي", "قولي شنو تشوف",
    "شنو يگدر", "شنو ترا",
]

# Pre-compile into a single regex — one pass instead of 40 substring scans
_VISION_RE = re.compile(
    "|".join(re.escape(t) for t in VISION_TRIGGERS),
    re.IGNORECASE
)

def should_use_vision(text: str) -> bool:
    """Single-pass regex match — ~5× faster than iterating 40 substrings."""
    return bool(_VISION_RE.search(text.strip()))

def build_user_content(text: str) -> tuple:
    """Return (content, vision_used).  Content is str or multimodal list."""
    vision_requested = should_use_vision(text)
    if vision_requested:
        print(f"[Vision] TRIGGERED by: '{text}'")
        if latest_video_frame:
            print(f"[Vision] Frame available — sending multimodal request")
            return (
                [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{latest_video_frame}"}},
                ],
                True,
            )
        else:
            print(f"[Vision] WARNING — vision triggered but NO frame available yet (camera not streaming?)")
            return text, True
    print(f"[Vision] TEXT ONLY: '{text}'")
    return text, False

# ==========================================
# NETWORK UTILITY
# ==========================================
def get_local_ip() -> str:
    """Get local LAN IP without needing internet access."""
    for target in [("192.168.1.1", 80), ("10.0.0.1", 80), ("172.16.0.1", 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass
    try:
        hostname = socket.gethostname()
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for res in results:
            ip = res[4][0]
            if not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"

# ==========================================
# PIPER TTS — reliable spawn-per-call, WAV file output
# ==========================================
# Root cause of glitches with the old persistent-process approach:
#   • The reader thread blocks stdout between calls, causing the next call's
#     PCM to be partially swallowed or mixed with leftover data.
#   • IDLE_SECS heuristic fires too early on slow CPUs, truncating audio.
#   • stdout corruption kills the process silently; the lock is never released.
#
# Solution: spawn a fresh Piper process per call, write WAV to a temp file.
#   Piper exits cleanly when done → we read the complete, unambiguous WAV file.
#   Slightly slower first-call (~0.3 s extra) but 100% clean audio every time.
#   A semaphore limits concurrency to 1 so the GPU/CPU isn't overloaded.
# ==========================================
import threading as _threading
import io as _io
import wave as _wave

_piper_sem = _threading.Semaphore(1)   # one synthesis at a time

def _piper_warmup():
    """Pre-load AND warm EVERY configured voice (EN + AR) at startup so the
    user's FIRST utterance in either language is already fast.

    With the warm pool this loads each ONNX voice into RAM once and keeps it
    resident; switching EN<->AR afterwards reuses the cached model instead of
    reloading from disk. Falls back to a single dummy synthesis on the legacy
    spawn path when the pool is unavailable.
    """
    try:
        if _PIPER_POOL is not None and _PIPER_POOL.is_available():
            print(f"[Piper] Pre-warming voices in RAM: {PIPER_PREWARM_VOICES}")
            _PIPER_POOL.prewarm(PIPER_PREWARM_VOICES)
            print(f"[Piper] \u2705 Warm pool ready \u2014 loaded: {_PIPER_POOL.loaded_voices()}")
            return
        # Legacy fallback: at least warm the ONNX runtime via one synthesis.
        print("[Piper] Warm pool unavailable \u2014 warming legacy spawn path...")
        result = generate_piper_audio("System ready.")
        if result:
            print("[Piper] \u2705 Legacy warm-up complete")
        else:
            print("[Piper] \u26a0\ufe0f  Warm-up produced no audio (non-fatal)")
    except Exception as exc:
        print(f"[Piper] Warm-up error (non-fatal): {exc}")


def _llm_warmup():
    """Send one tiny request so the LLM does its slow FIRST inference at
    startup instead of on the user's first real message.

    The model is already resident in the llama-server process; the lag the user
    notices is the one-off cold inference (kernel/graph setup). We trigger it
    here with a 1-token probe. Retries because llama-server may still be booting.
    """
    try:
        print("[LLM] Warming up model (first inference is slow)...")
        payload = {
            "messages": [
                {"role": "system", "content": "warmup"},
                {"role": "user", "content": "ping"},
            ],
            "max_tokens": 1,
            "temperature": 0,
        }
        for _ in range(30):
            try:
                res = _http.post(LLAMA_URL, json=payload, timeout=120)
                if res.ok:
                    print("[LLM] \u2705 Warm-up complete \u2014 model is hot")
                    return
            except Exception:
                pass
            time.sleep(3)
        print("[LLM] \u26a0\ufe0f  Warm-up could not reach llama-server (non-fatal)")
    except Exception as exc:
        print(f"[LLM] Warm-up error (non-fatal): {exc}")


def _whisper_warmup():
    """Push 0.5s of silence through Whisper so its model + GPU kernels are ready
    before the first real speech request. Retries while whisper-server boots."""
    try:
        print("[Whisper] Warming up model...")
        buf = _io.BytesIO()
        with _wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 8000)   # 0.5s silence @ 16kHz mono
        wav_bytes = buf.getvalue()
        for _ in range(30):
            try:
                res = _http.post(
                    WHISPER_URL,
                    files={"file": ("warmup.wav", wav_bytes, "audio/wav")},
                    data=_whisper_data(),
                    timeout=120,
                )
                if res.ok:
                    print("[Whisper] \u2705 Warm-up complete \u2014 model is hot")
                    return
            except Exception:
                pass
            time.sleep(3)
        print("[Whisper] \u26a0\ufe0f  Warm-up could not reach whisper-server (non-fatal)")
    except Exception as exc:
        print(f"[Whisper] Warm-up error (non-fatal): {exc}")


def _models_warmup():
    """Warm the heavy models SEQUENTIALLY (LLM then Whisper).

    RAM on the Jetson is tight, so we deliberately avoid running both cold
    inferences at the same time — staggering them keeps the peak memory lower
    while still getting both models hot before the user interacts.
    """
    _llm_warmup()
    _whisper_warmup()
    # Tell the nexus routes that Whisper is already warm so any browser-triggered
    # /api/stt/warmup call returns immediately (skipped=True) instead of sending
    # a duplicate silent-WAV request that could collide with a real user recording.
    try:
        import nexus_routes_additions as _nra
        _nra._stt_warmed = True
    except Exception:
        pass


def generate_piper_audio(text: str) -> str | None:
    """
    Synthesise speech by spawning Piper once per call.

    Piper is invoked with -f <tempfile.wav> so it writes a complete, valid WAV
    and exits.  We read the file after the process exits — no guesswork about
    when the PCM stream ends, no reader-thread race conditions.

    Returns base64-encoded WAV on success, None on failure.
    """
    _voice_name = voice_state.get("piper_voice", PIPER_DEFAULT_VOICE)

    # --- Preferred path: persistent WARM voice pool (model stays in RAM) -----
    # First use of a voice is slow (one-time load); every later call is fast.
    if PIPER_USE_POOL and _PIPER_POOL is not None:
        try:
            wav_bytes = _PIPER_POOL.synthesize(text, _voice_name)
            if wav_bytes:
                return base64.b64encode(wav_bytes).decode()
        except PiperUnavailable as exc:
            print(f"[Piper] Warm pool unavailable ({exc}); falling back to binary spawn")
        except Exception as exc:
            print(f"[Piper] Warm pool synth error ({exc}); falling back to binary spawn")

    # --- Fallback path: legacy spawn-per-call Piper binary -------------------
    out_wav = None
    with _piper_sem:          # serialise concurrent TTS requests
        try:
            # Create temp file path (delete=False so Piper can write to it)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                out_wav = tmp.name

            # Resolve active voice from voice_state
            _piper_model, _piper_config = _resolve_piper_voice(_voice_name)

            cmd = [
                PIPER_EXE,
                "--model",  _piper_model,
                "--config", _piper_config,
                "--output_file", out_wav,   # Piper ≥ 1.2 flag
            ]
            # Feed text via stdin; Piper reads one line and writes the WAV file
            result = subprocess.run(
                cmd,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,       # capture stderr for diagnostics
                timeout=30,
            )

            if result.returncode != 0:
                stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
                # Some Piper builds use -f instead of --output_file — retry
                if "--output_file" in stderr_msg or "unrecognized" in stderr_msg.lower():
                    cmd2 = [
                        PIPER_EXE,
                        "-m", _piper_model,
                        "-c", _piper_config,
                        "-f", out_wav,
                    ]
                    result = subprocess.run(
                        cmd2,
                        input=text.encode("utf-8"),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=30,
                    )
                    if result.returncode != 0:
                        print(f"[Piper] Both flag styles failed (rc={result.returncode})")
                        return None
                else:
                    print(f"[Piper] returncode={result.returncode}: {stderr_msg[:200]}")
                    return None

            # Verify output file is a valid WAV (> 44 byte header)
            if not os.path.exists(out_wav) or os.path.getsize(out_wav) <= 44:
                print("[Piper] Output WAV missing or empty")
                return None

            with open(out_wav, "rb") as f:
                wav_bytes = f.read()

            kb  = len(wav_bytes) // 1024
            # Read duration from WAV header for logging
            try:
                with _wave.open(_io.BytesIO(wav_bytes)) as wf:
                    dur = wf.getnframes() / wf.getframerate()
            except Exception:
                dur = 0.0

            print(f"[Piper] ✅ {kb} KB WAV | ~{dur:.1f}s | spawn-per-call")
            return base64.b64encode(wav_bytes).decode()

        except subprocess.TimeoutExpired:
            print("[Piper] Synthesis timed out after 30 s")
            return None
        except Exception as exc:
            print(f"[Piper] Unexpected error: {exc}")
            return None
        finally:
            # Always clean up the temp file
            if out_wav:
                try:
                    os.remove(out_wav)
                except OSError:
                    pass

# ==========================================
# VOICE STATE  — dual-mode TTS selector
# ==========================================
# mode         : "piper" (default) | "qwen" (voice clone)
# piper_voice  : name of the active Piper voice (e.g. "en_US-lessac-medium")
# ref_audio_b64: base64 WAV of the reference speaker (None when mode=piper)
# ref_text     : transcript of what the speaker says in the reference audio
voice_state: dict = {
    "mode":          "piper",
    "piper_voice":   PIPER_DEFAULT_VOICE,
    "ref_audio_b64": None,
    "ref_text":      "",
}

# ==========================================
# QWEN3-TTS CALL  — posts to tts_server.py
# ==========================================
def generate_qwen_audio(text: str) -> str | None:
    """
    Send text + voice reference to the Qwen3-TTS FastAPI server (port 5002).
    Returns base64-encoded WAV string, or None if the call fails for any reason.
    Uses the shared HTTP session for connection reuse.
    """
    ref_b64  = voice_state.get("ref_audio_b64") or ""
    ref_text = voice_state.get("ref_text")       or ""

    if not ref_b64:
        print("[QwenTTS] No reference audio set — cannot clone voice")
        return None

    try:
        payload = {
            "text":          text,
            "ref_audio_b64": ref_b64,
            "ref_text":      ref_text,
        }
        resp = requests.post(TTS_URL, json=payload, timeout=QWEN_TTS_TIMEOUT)
        if resp.ok:
            audio_b64 = resp.json().get("audio_base64")
            if audio_b64:
                print(f"[QwenTTS] ✅ Cloned audio for: {text[:50]!r}")
                return audio_b64
            print("[QwenTTS] Response OK but no audio_base64 in body")
        else:
            print(f"[QwenTTS] HTTP {resp.status_code}: {resp.text[:200]}")
    except requests.exceptions.ConnectionError:
        print("[QwenTTS] Connection refused — tts_server.py not running?")
    except requests.exceptions.Timeout:
        print(f"[QwenTTS] Request timed out after {QWEN_TTS_TIMEOUT}s")
    except Exception as exc:
        print(f"[QwenTTS] Unexpected error: {exc}")

    return None


# ── Emoji / special-char stripper for TTS ──────────────────────
# Piper reads emoji codepoints as garbage syllables. Strip them before synthesis.
import unicodedata as _unicodedata

def _strip_for_tts(text: str) -> str:
    """Remove emojis, control chars, and IOT/GENERIC tags before TTS."""
    # Remove [IOT:...] and [GENERIC:...] tags
    text = _IOT_TAG_RE.sub('', text)
    text = _GENERIC_TAG_RE.sub('', text)
    # Remove emojis and symbols via Unicode category filtering
    # Keep: letters (L*), marks (M*), numbers (N*), punctuation (P*),
    #       separators/spaces (Z*). Remove: symbols (S*) which includes emoji.
    cleaned = []
    for ch in text:
        cat = _unicodedata.category(ch)
        # Allow normal text categories; block So (Symbol Other = emoji)
        if cat.startswith('So'):
            continue
        cleaned.append(ch)
    result = ''.join(cleaned)
    # Collapse multiple spaces
    result = re.sub(r'  +', ' ', result).strip()
    return result

def generate_tts(text: str) -> str | None:
    """
    Master TTS dispatcher.
    • mode == "qwen"  → try Qwen voice clone → fallback to Piper on any failure
    • mode == "piper" → Piper directly (Qwen server never contacted)
    • Arabic auto-detect: if response is Arabic, temporarily switch to ar_JO-kareem
    • Emojis are stripped so Piper doesn't try to read them
    """
    # Strip emojis before any TTS path
    tts_text = _strip_for_tts(text)
    if not tts_text:
        return None

    if voice_state["mode"] == "qwen":
        print(f"[TTS] Mode=qwen — attempting voice clone")
        result = generate_qwen_audio(tts_text)
        if result:
            return result
        print("[TTS] Qwen failed — falling back to Piper")

    # Arabic auto-detection: temporarily use Arabic voice if text is Arabic
    if _is_arabic_text(tts_text):
        original_voice = voice_state.get("piper_voice", PIPER_DEFAULT_VOICE)
        voice_state["piper_voice"] = PIPER_ARABIC_VOICE
        print(f"[TTS] Arabic text detected — using {PIPER_ARABIC_VOICE}")
        result = generate_piper_audio(tts_text)
        voice_state["piper_voice"] = original_voice  # restore
        return result

    # Default / fallback path
    return generate_piper_audio(tts_text)

# ==========================================
# LLM CALL  (shared, with rolling history)
# Uses tuned generation params from config
# ==========================================
def call_llm(user_content, system_prompt: str, vision_used: bool = False) -> str:
    """Send to Llama with rolling history. Returns clean text string.

    When vision_used is True, we do NOT include conversation_history
    so that llama-server sees only: [system] + [user multimodal] — this ensures
    the mmproj vision projector is correctly triggered.

    RAG: For text-only requests, relevant document context is retrieved from the
    vector store and appended to the system prompt.
    """
    # ── RAG context injection (text-only, non-vision) ──
    # Skip RAG for IoT commands (short device-control phrases). RAG
    # injects up to 3000 chars of documents, which wastes precious
    # context tokens when the user just wants to toggle a device.
    effective_prompt = system_prompt
    _IOT_KEYWORDS = {'turn', 'toggle', 'switch', 'light', 'led', 'fan',
                     'dimmer', 'lamp', 'relay', 'on', 'off', 'power'}
    query_text = user_content if isinstance(user_content, str) else ""
    is_iot_command = (len(query_text.split()) <= 8
                      and any(w in query_text.lower().split()
                              for w in _IOT_KEYWORDS))
    if is_iot_command:
        print("[RAG] Skipped — looks like an IoT command")

    if not vision_used and rag_engine and rag_engine.is_available():
        if query_text and not is_iot_command:
            rag_context = rag_engine.query(query_text)
            if rag_context:
                effective_prompt = (
                    system_prompt
                    + "\n\n--- Relevant Documents ---\n"
                    + rag_context
                    + "\n--- End of Documents ---"
                )
                print(f"[RAG] Injected {len(rag_context)} chars of context")

    # ── IoT device context injection (text-only, non-vision) ──
    # Only inject TOGGLEABLE devices (switches/lights) — skip sensors
    # to keep the context window small enough for reliable responses.
    if not vision_used and iot_controller:
        try:
            devices = iot_controller.get_filtered_devices()
            if devices:
                toggle_devs = [d for d in devices if d.get('is_toggle')]
                if toggle_devs:
                    lines = []
                    for d in toggle_devs:
                        lines.append(
                            f"  - {d['name']} ({d['entity_id']}) = {d['state']}"
                        )
                    device_block = "\n".join(lines)
                    effective_prompt += (
                        "\n\n--- HA Devices (toggleable) ---\n"
                        + device_block
                        + "\n--- End ---"
                    )
                    print(f"[IoT] Injected {len(toggle_devs)} toggleable "
                          f"devices (skipped {len(devices) - len(toggle_devs)} sensors)")
        except Exception as e:
            print(f"[IoT] Failed to inject device context: {e}")

    # ── Generic IP device context injection (text-only, non-vision) ──
    if not vision_used and generic_device_mgr:
        try:
            gen_devices = generic_device_mgr.list_devices()
            if gen_devices:
                gen_lines = []
                for gd in gen_devices:
                    dtype = gd.get('device_type', 'switch')
                    room = gd.get('room', '')
                    prefix = f"{room}: " if room else ""
                    dev_target = gd['id']

                    if dtype == 'multi_channel':
                        channels = gd.get('channels', [])
                        ch_states = gd.get('state', {})
                        for i, ch_name in enumerate(channels, 1):
                            ch_st = ch_states.get(str(i), 'unknown') \
                                if isinstance(ch_states, dict) else 'unknown'
                            gen_lines.append(
                                f"  - {prefix}{ch_name} (Channel {i}) = {ch_st} [Target: {dev_target}|{i}]"
                            )
                    elif dtype == 'dimmer':
                        state_str = str(gd['state'])
                        gen_lines.append(
                            f"  - {prefix}{gd['name']} = {state_str}   [Target: {dev_target} -> use for dimmer 0-100]"
                        )
                    elif dtype == 'fan':
                        state_str = str(gd['state'])
                        gen_lines.append(
                            f"  - {prefix}{gd['name']} = {state_str}   [Target: {dev_target} -> use for fan 1-3]"
                        )
                    else:
                        # Normalize boolean states for virtual devices
                        state_raw = gd.get('state', 'unknown')
                        if isinstance(state_raw, bool):
                            state_str = 'on' if state_raw else 'off'
                        else:
                            state_str = str(state_raw)
                        gen_lines.append(
                            f"  - {prefix}{gd['name']} = {state_str}   [Target: {dev_target}]"
                        )

                gen_block = "\n".join(gen_lines)
                effective_prompt += (
                    "\n\n--- Generic IP Devices ---\n"
                    + gen_block
                    + "\n--- End ---"
                )
                print(f"[GenDev] Injected {len(gen_devices)} generic "
                      f"device(s) into LLM context")
        except Exception as e:
            print(f"[GenDev] Failed to inject device context: {e}")

    messages = [{"role": "system", "content": effective_prompt}]

    if not vision_used:
        # Normal text request — include trimmed rolling history
        hist = get_history_messages()
        # Smart context trimming: estimate token count and drop oldest
        # history entries if we're getting too close to the context limit.
        # Reserve 300 tokens for output + safety margin.
        prompt_est = len(effective_prompt) // 4
        user_est = len(user_content) // 4 if isinstance(user_content, str) else 50
        safe_limit = LLAMA_CTX - LLM_MAX_TOKENS - 100  # leave room for output
        hist_budget = safe_limit - prompt_est - user_est
        # Trim history from the oldest if it exceeds budget
        while hist and sum(len(str(m.get('content', ''))) // 4 for m in hist) > hist_budget:
            hist.pop(0)
        messages += hist

    messages.append({"role": "user", "content": user_content})

    # ── Chat model requires strictly alternating user/assistant roles ──
    # Remove consecutive messages with the same role (keep the last one)
    sanitized = [messages[0]]  # always keep system prompt
    for msg in messages[1:]:
        if sanitized and msg["role"] == sanitized[-1]["role"]:
            sanitized[-1] = msg  # replace with newer message
        else:
            sanitized.append(msg)
    # Ensure first non-system message is "user" (chat-model requirement)
    if len(sanitized) > 1 and sanitized[1]["role"] != "user":
        sanitized.insert(1, {"role": "user", "content": "hello"})
    messages = sanitized

    payload = {
        "messages":       messages,
        "temperature":    LLM_TEMPERATURE,
        "max_tokens":     LLM_MAX_TOKENS,
        "top_p":          LLM_TOP_P,
        "repeat_penalty": LLM_REPEAT_PENALTY,
    }

    try:
        res = _http.post(LLAMA_URL, json=payload, timeout=LLAMA_TIMEOUT)
        if res.ok:
            raw = res.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"[Llama HTTP {res.status_code}] {res.text[:300]}")
            raw = "Sorry, I couldn't process that."
    except requests.exceptions.ConnectionError as e:
        print(f"[Llama ConnectionError] {e}")
        raw = "Cannot connect to the AI brain."
    except requests.exceptions.Timeout:
        print(f"[Llama Timeout] Request timed out after {LLAMA_TIMEOUT}s")
        raw = "The AI brain is taking too long."
    except Exception as e:
        print(f"[Llama Exception] {type(e).__name__}: {e}")
        raw = "Cannot connect to the AI brain."

    return raw

# ==========================================
# IOT TAG PARSER — intercepts [IOT:action|entity_id]
#                   AND [GENERIC:action|dev_id] or [GENERIC:action|dev_id|value]
# ==========================================
_IOT_TAG_RE     = re.compile(r'\[IOT:(\w+)\|([^\]]+)\]')
# Match GENERIC tags with optional third segment:
#   [GENERIC:toggle|generic.led]       → 2 segments (no value)
#   [GENERIC:toggle|generic.led|]      → 3 segments (empty value)
#   [GENERIC:toggle|generic.switch|2]  → 3 segments (channel 2)
_GENERIC_TAG_RE = re.compile(r'\[GENERIC:(\w+)\|([^|\]]+)(?:\|([^\]]*))?\]')

def _exec_generic_action(action: str, dev_id: str, value_str: str) -> bool:
    """Execute one generic-device action. Broadcasts result. Returns True on success."""
    if not generic_device_mgr:
        return False
    ok = False
    result = ""
    try:
        if action == "toggle":
            channel = int(value_str) if value_str else None
            ok, result = generic_device_mgr.toggle_device(dev_id, channel=channel)
            if ok:
                socketio.emit('iot_generic_device_toggled',
                              {'ok': True, 'id': dev_id, 'state': result, 'channel': channel})
        elif action in ("turn_on", "on"):
            channel = int(value_str) if value_str else None
            ok, result = generic_device_mgr.set_device_state(dev_id, "on", channel=channel)
            if ok:
                socketio.emit('iot_generic_device_toggled',
                              {'ok': True, 'id': dev_id, 'state': result, 'channel': channel})
        elif action in ("turn_off", "off"):
            channel = int(value_str) if value_str else None
            ok, result = generic_device_mgr.set_device_state(dev_id, "off", channel=channel)
            if ok:
                socketio.emit('iot_generic_device_toggled',
                              {'ok': True, 'id': dev_id, 'state': result, 'channel': channel})
        elif action in ("dimmer", "fan"):
            val = int(value_str) if value_str else 0
            ok, result = generic_device_mgr.send_command(dev_id, action, val)
            if ok:
                socketio.emit('iot_generic_command_result',
                              {'ok': True, 'id': dev_id, 'command': action, 'value': val})
        else:
            print(f"[GenDev-LLM] Unknown action: {action}")
            return False
        if ok:
            print(f"[GenDev-LLM] ✅ {action}({dev_id}|{value_str!r}) = {result}")
        else:
            print(f"[GenDev-LLM] ⚠️ {action}({dev_id}) failed: {result}")
    except Exception as e:
        print(f"[GenDev-LLM] Error {action}({dev_id}): {e}")
    return ok


def process_iot_tags(ai_text: str, user_text: str = "") -> tuple[str, bool]:
    """Parse [IOT:action|entity_id] and [GENERIC:action|dev_id|value] tags.

    Steps per tag:
      1. Execute the action via the appropriate controller
      2. Broadcast state change to all UI clients
      3. Strip tag from the response text

    Also handles bulk fallback: if user said 'all'/'every' and the LLM
    only emitted tags for SOME channels of a multi-channel device,
    the server fires the remaining channels automatically.

    Returns (cleaned_text, tags_found).
    """
    # ── Process HA [IOT:] tags ──
    if iot_controller:
        for action, entity_id in _IOT_TAG_RE.findall(ai_text):
            action = action.lower().strip()
            entity_id = entity_id.strip()
            domain = entity_id.split('.')[0] if '.' in entity_id else ''
            print(f"[IoT-LLM] Executing: {action} → {entity_id}")
            try:
                ok = iot_controller.call_service(domain, action, entity_id)
                if ok:
                    print(f"[IoT-LLM] ✅ {action}({entity_id}) succeeded")
                    new_state = iot_controller.get_entity_state(entity_id)
                    if new_state:
                        attrs = new_state.get('attributes', {})
                        socketio.emit('iot_state_changed', {
                            'entity_id':  entity_id,
                            'state':      new_state.get('state', 'unknown'),
                            'name':       attrs.get('friendly_name', entity_id),
                            'attributes': attrs,
                        })
                else:
                    print(f"[IoT-LLM] ⚠️ {action}({entity_id}) failed")
            except Exception as e:
                print(f"[IoT-LLM] Error executing {action}({entity_id}): {e}")

    # ── Process Generic [GENERIC:] tags ──
    if generic_device_mgr:
        g_matches = _GENERIC_TAG_RE.findall(ai_text)
        # Track emitted (dev_id, channel_str) pairs to avoid duplicates
        emitted: set[tuple[str, str]] = set()
        # Keep the last action used per device for the bulk fill-in
        last_action_per_dev: dict[str, str] = {}

        for match in g_matches:
            action    = match[0].lower().strip()
            dev_id    = match[1].strip()
            value_str = (match[2] or "").strip() if len(match) > 2 else ""
            key = (dev_id, value_str)
            if key not in emitted:
                emitted.add(key)
                last_action_per_dev[dev_id] = action
                _exec_generic_action(action, dev_id, value_str)

        # ── Bulk all-channels fallback ─────────────────────────────
        # When user says "all"/"every"/"everything" and at least one tag
        # was emitted for a multi-channel device, fire missing channels.
        _BULK_WORDS = {'all', 'every', 'everything', 'each', 'entire'}
        if _BULK_WORDS & set(user_text.lower().split()) and emitted:
            try:
                dev_map = {d['id']: d for d in generic_device_mgr.list_devices()}
                for dev_id, action in last_action_per_dev.items():
                    dev = dev_map.get(dev_id)
                    if not dev or dev.get('device_type') != 'multi_channel':
                        continue
                    n_ch = len(dev.get('channels', []))
                    for ch in range(1, n_ch + 1):
                        ch_str = str(ch)
                        if (dev_id, ch_str) not in emitted:
                            print(f"[GenDev-LLM] Bulk-filling ch{ch} for {dev_id}")
                            _exec_generic_action(action, dev_id, ch_str)
                            emitted.add((dev_id, ch_str))
            except Exception as e:
                print(f"[GenDev-LLM] Bulk-fill error: {e}")

    # Strip ALL tags so TTS never reads them
    cleaned = _IOT_TAG_RE.sub('', ai_text)
    cleaned = _GENERIC_TAG_RE.sub('', cleaned)
    cleaned = re.sub(r'  +', ' ', cleaned).strip()
    tags_found = (cleaned != ai_text.strip())
    return cleaned, tags_found


# ==========================================
# WHISPER BLANK TRANSCRIPT FILTER
# Whisper outputs these markers for silence / no speech.
# Without filtering, they get sent to the LLM as real questions.
# ==========================================
_BLANK_PATTERNS = re.compile(
    r'^\s*$'
    r'|^\[BLANK_AUDIO\]$'
    r'|^\(blank audio\)$'
    r'|^\[ Silence \]$'
    r'|^\[no speech\]$'
    r'|^\[no speech detected\]$'
    r'|^\( no audio \)$'
    r'|^\(no audio\)$'
    r'|^\[Music\]$'
    r'|^\( music \)$'
    r'|^\[music\]$'
    r'|^you$'
    r'|^\.$'
    r'|^\.+$'
    r'|^,+$'
    r'|^!+$'
    r'|^\s*\.\.\.\s*$'
    r'|^Thank you\.?$'
    r'|^Thanks for watching\.?$'
    r'|^Bye\.?$'
    r'|^السلام عليكم\.?$'
    r'|^تمام\.?$',
    re.IGNORECASE
)

# Minimum WAV file size to be worth transcribing.
# 16kHz × 1 channel × 2 bytes × 0.5 second + 44-byte header ≈ 16044 bytes
# Lowered from 32000 — let Whisper decide what's too short, not a hard gate.
_MIN_WAV_BYTES = 16000

def _is_blank_transcript(text: str) -> bool:
    """Return True if Whisper's output is a known blank/noise marker."""
    return bool(_BLANK_PATTERNS.match(text.strip()))


# ==========================================
# STT PROXY — forward audio from HTTPS browser to Whisper HTTP server
# Needed to avoid HTTPS mixed-content errors (browser → Flask → Whisper)
# ==========================================
@app.route("/api/stt/inference", methods=["POST"])
def stt_inference_proxy():
    """
    Accepts a multipart audio file from the browser (WebM), converts it to 
    16kHz mono WAV via FFmpeg, and forwards it to the Whisper server.
    Returns the Whisper JSON response { text: "...", ...} to the browser.
    """
    import requests as _req
    import tempfile
    import subprocess
    import os
    try:
        f = request.files.get("file")
        if not f:
            return jsonify({"error": "No audio file"}), 400
        
        audio_bytes = f.read()
        
        # Convert WebM to 16kHz Mono WAV (required by whisper.cpp)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
            tmp_in.write(audio_bytes)
            in_file = tmp_in.name
            
        out_file = in_file + ".wav"
        try:
            # -y = overwrite, -ar 16000 = sample rate, -ac 1 = mono
            subprocess.run(
                ["ffmpeg", "-y", "-i", in_file, "-ar", "16000", "-ac", "1", out_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            with open(out_file, "rb") as wf:
                wav_bytes = wf.read()
        except subprocess.CalledProcessError:
            return jsonify({"error": "Failed to convert audio via ffmpeg"}), 500
        finally:
            if os.path.exists(in_file): os.remove(in_file)
            if os.path.exists(out_file): os.remove(out_file)
            
        resp = _req.post(
            WHISPER_URL,
            files={"file": ("recording.wav", wav_bytes, "audio/wav")},
            data=_whisper_data(),
            timeout=WHISPER_TIMEOUT,
        )
        return (resp.content, resp.status_code, {"Content-Type": "application/json"})
    except _req.exceptions.ConnectionError:
        return jsonify({"error": "Whisper server not running on port 8081"}), 503
    except Exception as _e:
        return jsonify({"error": str(_e)}), 500

@app.route("/api/stt/start", methods=["POST"])
def stt_start():
    return jsonify({"ok": True, "status": "use /api/stt/inference for direct audio"})

@app.route("/api/stt/stop", methods=["POST"])
def stt_stop():
    return jsonify({"ok": True, "text": ""})

@app.route("/api/config", methods=["GET"])
def client_config():
    """Expose front-end-tunable knobs (VAD endpointing + wake word) so the
    browser SPA reads them from config.py / env instead of hard-coding.
    The frontend hydrates window.NEXUS_VAD from `vad`."""
    try:
        from config import VAD_CONFIG as _VAD
    except Exception:
        _VAD = {}
    try:
        _wake = {
            "threshold": float(globals().get("WAKE_THRESHOLD", 0.5)),
            "trigger_frames": int(globals().get("WAKE_TRIGGER_FRAMES", 2)),
            "cooldown": float(globals().get("WAKE_COOLDOWN", 1.5)),
        }
    except Exception:
        _wake = {}
    return jsonify({"ok": True, "vad": dict(_VAD or {}), "wake": _wake})

# ==========================================
# ROUTES
# ==========================================
@app.route("/robot")

def robot_face():
    return render_template("robot_face.html")

@app.route("/")
def root_redirect():
    return redirect("/nexus/")

@app.route("/mock")
def mock_home():
    return render_template("mock_home.html")

@app.route("/network")
def network_scanner():
    return render_template("network_scanner.html")


@app.route("/chatbot")
def chatbot_page():
    return render_template("chatbot.html")

# ── Serve local MP3 files for games ──────────────────────
import mimetypes as _mimetypes
from flask import send_file as _send_file

MUSIC_DIR = os.path.join(_PROJECT_ROOT, "Music")

@app.route("/music/<path:filename>")
def serve_music(filename):
    """Stream local Music/ files to browser (game background music)."""
    try:
        filepath = os.path.normpath(os.path.join(MUSIC_DIR, filename))
        if not filepath.startswith(os.path.normpath(MUSIC_DIR)):
            return "Forbidden", 403
        if not os.path.isfile(filepath):
            return "Not found", 404
        mime, _ = _mimetypes.guess_type(filepath)
        return _send_file(filepath, mimetype=mime or "audio/mpeg", conditional=True)
    except Exception as e:
        print(f"[Music] Error: {e}")
        return "Error", 500

# ── Minigame routes ───────────────────────────────────────
@app.route("/game/flappy")
def game_flappy():
    return render_template("game_flappy.html")

@app.route("/game/tetris")
def game_tetris():
    return render_template("game_tetris.html")

@app.route("/game/pacman")
def game_pacman():
    return render_template("game_pacman.html")

# ==========================================
# SOCKET EVENTS
# ==========================================
@socketio.on("connect")
def on_connect():
    print(f"[+] Client connected: {request.sid}")

@socketio.on("disconnect")
def on_disconnect():
    print(f"[-] Client disconnected: {request.sid}")
    emit("robot_disconnected", {}, broadcast=True)

@socketio.on("video_frame")
def handle_video_frame(data):
    global latest_video_frame
    latest_video_frame = data.get("frame")
    emit("video_update", data, broadcast=True, include_self=False)

@socketio.on("audio_data")
def handle_audio_data(data):
    emit("status_update", {"status": "thinking"}, broadcast=True)

    audio_b64 = data.get("audio")
    if not audio_b64:
        return

    audio_bytes = base64.b64decode(audio_b64)
    raw_tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav",  delete=False)
    raw_path, wav_path = raw_tmp.name, wav_tmp.name
    raw_tmp.close(); wav_tmp.close()

    try:
        with open(raw_path, "wb") as f:
            f.write(audio_bytes)

        subprocess.run(
            [FFMPEG_PATH, "-y", "-i", raw_path,
             "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-f", "wav", wav_path],
            capture_output=True, timeout=15,
        )

        # ── WAV size gate — skip Whisper for clips < 1 second ──
        wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
        if wav_size < _MIN_WAV_BYTES:
            print(f"[STT] WAV too small ({wav_size} B) — skipping Whisper")
            emit("ai_response", {
                "user_text": "",
                "ai_text":   "Recording too short — hold the mic button longer.",
                "stt_failed": True,
            }, broadcast=True)
            emit("status_update", {"status": "idle"}, broadcast=True)
            return

        transcript = ""
        with open(wav_path, "rb") as f:
            wr = _http.post(
                WHISPER_URL,
                files={"file": ("audio.wav", f, "audio/wav")},
                data=_whisper_data(),
                timeout=WHISPER_TIMEOUT,
            )
        if wr.ok:
            transcript = wr.json().get("text", "").strip()

        # ── Filter Whisper blank/noise markers ──
        if not transcript or _is_blank_transcript(transcript):
            print(f"[STT] Blank transcript filtered: {transcript!r}")
            emit("ai_response", {
                "user_text": "",
                "ai_text":   "Sorry, I didn't catch that. Try speaking louder.",
                "stt_failed": True,
            }, broadcast=True)
            emit("status_update", {"status": "idle"}, broadcast=True)
            return

        emit("user_message", {"text": transcript}, broadcast=True)

        user_content, vision_used = build_user_content(transcript)
        add_to_history("user", user_content if isinstance(user_content, str) else transcript)

        sp = VISION_SYSTEM_PROMPT if vision_used else SYSTEM_PROMPT
        ai_text = call_llm(user_content, sp, vision_used=vision_used)

        # ── Phase 4: IoT tag interception ��─
        ai_text, had_iot_tags = process_iot_tags(ai_text, user_text=transcript)

        # Don't pollute history with IoT exchanges — they're simple
        # confirmations that waste context tokens on future calls.
        if not had_iot_tags:
            add_to_history("assistant", ai_text)
        else:
            # Also remove the user's IoT command from history
            if conversation_history and conversation_history[-1].get('role') == 'user':
                conversation_history.pop()

        print(f"[ARIA] Text={ai_text}")
        audio_b64_out = generate_tts(ai_text)

        emit("ai_response", {
            "user_text":    transcript,
            "ai_text":      ai_text,
            "audio_base64": audio_b64_out,
            "voice_mode":   voice_state["mode"],
        }, broadcast=True)

    except Exception as e:
        print(f"[Error] handle_audio_data: {e}")
        emit("ai_response", {
            "user_text": "[Error]",
            "ai_text":   "A processing error occurred.",
        }, broadcast=True)
    finally:
        emit("status_update", {"status": "idle"}, broadcast=True)
        for p in (raw_path, wav_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass  # Windows file-lock safety

@socketio.on("text_message")
def handle_text_message(data):
    text = data.get("text", "").strip()
    if not text:
        return

    emit("status_update", {"status": "thinking"}, broadcast=True)
    # Send to everyone except sender — control station adds the bubble locally in sendText()
    emit("user_message", {"text": text}, broadcast=True, include_self=False)

    try:
        user_content, vision_used = build_user_content(text)
        add_to_history("user", user_content if isinstance(user_content, str) else text)

        sp = VISION_SYSTEM_PROMPT if vision_used else SYSTEM_PROMPT
        ai_text = call_llm(user_content, sp, vision_used=vision_used)

        # ── Phase 4: IoT tag interception ──
        ai_text, had_iot_tags = process_iot_tags(ai_text, user_text=text)

        # Don't pollute history with IoT exchanges
        if not had_iot_tags:
            add_to_history("assistant", ai_text)
        else:
            if conversation_history and conversation_history[-1].get('role') == 'user':
                conversation_history.pop()

        print(f"[ARIA] Text={ai_text}")
        audio_b64 = generate_tts(ai_text)

        # Send ai_response FIRST, then set idle — robot face needs the audio
        emit("ai_response", {
            "user_text":    text,
            "ai_text":      ai_text,
            "audio_base64": audio_b64,
            "voice_mode":   voice_state["mode"],
        }, broadcast=True)
    except Exception as e:
        print(f"[Error] handle_text_message: {e}")
        emit("ai_response", {
            "user_text": text,
            "ai_text":   "A processing error occurred.",
        }, broadcast=True)
    finally:
        emit("status_update", {"status": "idle"}, broadcast=True)

# ==========================================
# CHATBOT RECEPTIONIST — separate handler + history
# Uses RECEPTIONIST_PROMPT, independent from the robot ARIA conversation.
# ==========================================
_chatbot_history: deque = deque(maxlen=10)

# ── Build a live-enriched system prompt for chatbot handlers ──────────
def _build_chatbot_system_prompt() -> str:
    """Inject live HA devices + generic devices into RECEPTIONIST_PROMPT."""
    prompt = RECEPTIONIST_PROMPT
    try:
        from nexus_assistant import ha_states as _ha_states, _entity_friendly
        _devs = _ha_states()
        if _devs:
            ctrl = ("light", "switch", "fan", "input_boolean",
                    "climate", "cover", "media_player", "lock")
            lines = []
            for s in _devs:
                eid = s.get("entity_id", "")
                if eid.split(".")[0] in ctrl:
                    fname = _entity_friendly(s)
                    state = s.get("state", "unknown")
                    lines.append(f"- {eid} ({fname}) = {state}")
            if lines:
                prompt = (prompt
                          + "\n\nLIVE Home Assistant devices you can control. "
                          + "Use the EXACT entity_id in any [IOT:action|entity_id] tag:\n"
                          + "\n".join(lines[:40]))
    except Exception as _exc:
        print(f"[Chatbot] HA device injection failed: {_exc}")
    try:
        if generic_device_mgr:
            gen_devs = generic_device_mgr.list_devices()
            if gen_devs:
                gen_lines = []
                for gd in gen_devs:
                    dtype = gd.get('device_type', 'switch')
                    room = gd.get('room', '')
                    prefix = (room + ": ") if room else ""
                    dev_target = gd['id']
                    if dtype == 'multi_channel':
                        ch_states = gd.get('state', {})
                        for i, ch in enumerate(gd.get('channels', []), 1):
                            ch_st = ch_states.get(str(i), 'unknown') \
                                if isinstance(ch_states, dict) else 'unknown'
                            gen_lines.append(
                                f"  - {prefix}{ch} (ch{i}) = {ch_st} [Target: {dev_target}|{i}]")
                    else:
                        state_raw = gd.get('state', 'unknown')
                        if isinstance(state_raw, bool):
                            state_str = 'on' if state_raw else 'off'
                        else:
                            state_str = str(state_raw)
                        gen_lines.append(
                            f"  - {prefix}{gd['name']} = {state_str} [Target: {dev_target}]")
                if gen_lines:
                    prompt = (prompt
                              + "\n\n--- Generic IP Devices (use [GENERIC:action|target] tags) ---\n"
                              + "\n".join(gen_lines)
                              + "\n--- End ---")
    except Exception as _exc:
        print(f"[Chatbot] Generic device injection failed: {_exc}")
    return prompt


@socketio.on("chatbot_message")
def handle_chatbot_message(data):
    """Chatbot handler — full ARIA persona with live HA device list injected."""
    text = data.get("text", "").strip()
    if not text:
        return

    # Only notify THIS client's room (SID) + broadcast status
    emit("status_update", {"status": "thinking"}, to=request.sid)

    try:
        # Build history for this chatbot session
        hist = list(_chatbot_history)[-LLM_HISTORY_TURNS:]
        sys_prompt = _build_chatbot_system_prompt()   # includes live HA devices
        messages = [{"role": "system", "content": sys_prompt}]
        messages += hist
        messages.append({"role": "user", "content": text})

        # Sanitize: the chat model needs strictly alternating roles
        sanitized = [messages[0]]
        for msg in messages[1:]:
            if sanitized and msg["role"] == sanitized[-1]["role"]:
                sanitized[-1] = msg
            else:
                sanitized.append(msg)
        if len(sanitized) > 1 and sanitized[1]["role"] != "user":
            sanitized.insert(1, {"role": "user", "content": "hello"})

        payload = {
            "messages":       sanitized,
            "temperature":    LLM_TEMPERATURE,
            "max_tokens":     200,           # enough for a sentence + IoT tag(s)
            "top_p":          LLM_TOP_P,
            "repeat_penalty": LLM_REPEAT_PENALTY,
        }

        try:
            res = _http.post(LLAMA_URL, json=payload, timeout=LLAMA_TIMEOUT)
            if res.ok:
                ai_text = res.json()["choices"][0]["message"]["content"].strip()
            else:
                ai_text = "Sorry, I couldn't process that."
        except requests.exceptions.ConnectionError:
            ai_text = "Cannot connect to the AI brain right now."
        except requests.exceptions.Timeout:
            ai_text = "The AI is taking too long — please try again."

        # Store in chatbot-specific history
        _chatbot_history.append({"role": "user", "content": text})
        _chatbot_history.append({"role": "assistant", "content": ai_text})

        print(f"[Chatbot] Q: {text[:60]!r}  A: {ai_text[:80]!r}")

        # ── IoT tag interception — execute any [IOT:] / [GENERIC:] tags ──
        ai_text, had_iot_tags = process_iot_tags(ai_text, user_text=text)

        # Generate TTS audio (tags already stripped from ai_text)
        audio_b64 = generate_tts(ai_text)

        emit("ai_response", {
            "user_text":    text,
            "ai_text":      ai_text,
            "audio_base64": audio_b64,
            "voice_mode":   voice_state["mode"],
        }, to=request.sid)

    except Exception as e:
        print(f"[Error] handle_chatbot_message: {e}")
        emit("ai_response", {
            "user_text": text,
            "ai_text":   "A processing error occurred.",
        }, to=request.sid)
    finally:
        emit("status_update", {"status": "idle"}, to=request.sid)

@socketio.on("chatbot_clear_history")
def handle_chatbot_clear():
    """Clear the chatbot receptionist conversation history."""
    _chatbot_history.clear()
    print("[Chatbot] History cleared")

@socketio.on("chatbot_voice")
def handle_chatbot_voice(data):
    """Receptionist chatbot — voice input via microphone.
    Payload: { "audio": "<base64 webm/ogg>" }
    Flow: mic audio → ffmpeg → Whisper STT → LLM → Piper TTS → client
    """
    audio_b64 = data.get("audio")
    if not audio_b64:
        return

    emit("status_update", {"status": "listening"}, to=request.sid)

    raw_tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    raw_path, wav_path = raw_tmp.name, wav_tmp.name
    raw_tmp.close(); wav_tmp.close()

    try:
        # Decode and write raw audio
        audio_bytes = base64.b64decode(audio_b64)
        with open(raw_path, "wb") as f:
            f.write(audio_bytes)

        # Convert to 16kHz mono WAV for Whisper
        subprocess.run(
            [FFMPEG_PATH, "-y", "-i", raw_path,
             "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-f", "wav", wav_path],
            capture_output=True, timeout=15,
        )

        # ── WAV size gate — skip Whisper for clips < 1 second ──
        wav_size = os.path.getsize(wav_path) if os.path.exists(wav_path) else 0
        if wav_size < _MIN_WAV_BYTES:
            print(f"[Chatbot-Mic] WAV too small ({wav_size} B) — skipping Whisper")
            emit("ai_response", {
                "user_text": "",
                "ai_text":   "التسجيل قصير — اضغط مطول على زر المايك\nRecording too short — hold the mic button longer.",
                "stt_failed": True,
            }, to=request.sid)
            emit("status_update", {"status": "idle"}, to=request.sid)
            return

        # Transcribe via Whisper
        emit("status_update", {"status": "thinking"}, to=request.sid)
        transcript = ""
        with open(wav_path, "rb") as f:
            wr = _http.post(
                WHISPER_URL,
                files={"file": ("audio.wav", f, "audio/wav")},
                data=_whisper_data(),
                timeout=WHISPER_TIMEOUT,
            )
        if wr.ok:
            transcript = wr.json().get("text", "").strip()

        # ── Filter Whisper blank/noise markers ──
        if not transcript or _is_blank_transcript(transcript):
            print(f"[Chatbot-Mic] Blank transcript filtered: {transcript!r}")
            emit("ai_response", {
                "user_text": "",
                "ai_text":   "لم أسمعك — حاول تتكلم بصوت أعلى\nSorry, I didn't catch that. Try speaking louder.",
                "stt_failed": True,
            }, to=request.sid)
            emit("status_update", {"status": "idle"}, to=request.sid)
            return

        print(f"[Chatbot-Mic] Heard: {transcript!r}")

        # Send transcribed text back so client shows it as user bubble
        emit("chatbot_transcript", {"text": transcript}, to=request.sid)

        # Build LLM messages (reuse chatbot logic)
        hist = list(_chatbot_history)[-LLM_HISTORY_TURNS:]
        sys_prompt = _build_chatbot_system_prompt()   # includes live HA devices
        messages = [{"role": "system", "content": sys_prompt}]
        messages += hist
        messages.append({"role": "user", "content": transcript})

        # Sanitize roles for the chat model
        sanitized = [messages[0]]
        for msg in messages[1:]:
            if sanitized and msg["role"] == sanitized[-1]["role"]:
                sanitized[-1] = msg
            else:
                sanitized.append(msg)
        if len(sanitized) > 1 and sanitized[1]["role"] != "user":
            sanitized.insert(1, {"role": "user", "content": "hello"})

        payload = {
            "messages":       sanitized,
            "temperature":    LLM_TEMPERATURE,
            "max_tokens":     200,           # enough for a sentence + IoT tag(s)
            "top_p":          LLM_TOP_P,
            "repeat_penalty": LLM_REPEAT_PENALTY,
        }

        try:
            res = _http.post(LLAMA_URL, json=payload, timeout=LLAMA_TIMEOUT)
            if res.ok:
                ai_text = res.json()["choices"][0]["message"]["content"].strip()
            else:
                ai_text = "Sorry, I couldn't process that."
        except requests.exceptions.ConnectionError:
            ai_text = "Cannot connect to the AI brain right now."
        except requests.exceptions.Timeout:
            ai_text = "The AI is taking too long — please try again."

        # Store in chatbot history
        _chatbot_history.append({"role": "user", "content": transcript})
        _chatbot_history.append({"role": "assistant", "content": ai_text})

        print(f"[Chatbot-Mic] Q: {transcript[:60]!r}  A: {ai_text[:80]!r}")

        # ── IoT tag interception — execute any [IOT:] / [GENERIC:] tags ──
        ai_text, had_iot_tags = process_iot_tags(ai_text, user_text=transcript)

        # Generate Piper TTS audio (tags already stripped from ai_text)
        audio_b64_out = generate_tts(ai_text)

        emit("ai_response", {
            "user_text":    transcript,
            "ai_text":      ai_text,
            "audio_base64": audio_b64_out,
            "voice_mode":   voice_state["mode"],
        }, to=request.sid)

    except Exception as e:
        print(f"[Error] handle_chatbot_voice: {e}")
        emit("ai_response", {
            "user_text": "",
            "ai_text":   "A processing error occurred.",
        }, to=request.sid)
    finally:
        for p in (raw_path, wav_path):
            try:
                os.remove(p)
            except OSError:
                pass
        emit("status_update", {"status": "idle"}, to=request.sid)

@socketio.on("set_persona")
def handle_set_persona(data):
    persona = data.get("persona", "default")
    print(f"[Persona] → {persona}")
    emit("set_persona", {"persona": persona}, broadcast=True, include_self=False)

# Global session for ESP32 to prevent socket exhaustion and speed up requests
_esp32_session = requests.Session()

@socketio.on("move_command")
def handle_move_command(data):
    """Forward movement direction to socket clients and ESP32 chassis."""
    direction = data.get("direction", "stop")
    print(f"[Move] dir={direction}")
    emit("move_command", {"direction": direction}, broadcast=True, include_self=False)
    
    # Forward to ESP32 asynchronously to avoid blocking the SocketIO thread
    def _forward():
        try:
            _esp32_session.get(f"http://aria-esp32.local/move?dir={direction}", timeout=0.5)
        except Exception:
            pass
    _threading.Thread(target=_forward, daemon=True).start()

@socketio.on("set_speed")
def handle_set_speed(data):
    """Forward speed change to ESP32 and broadcast to all clients.
    Payload: { "speed": 0-255 }
    """
    speed = data.get("speed", 200)
    speed = max(0, min(255, int(speed)))
    print(f"[Speed] → {speed}")
    emit("speed_updated", {"speed": speed}, broadcast=True, include_self=False)

    # Forward to ESP32
    def _fwd_speed():
        try:
            _esp32_session.get(f"http://aria-esp32.local/speed?val={speed}", timeout=0.5)
        except Exception:
            pass
    _threading.Thread(target=_fwd_speed, daemon=True).start()

@socketio.on("clear_history")
def handle_clear_history():
    conversation_history.clear()
    if rag_engine:
        rag_engine.clear_cache()
    print("[History] Cleared by client (RAG cache also flushed)")

@socketio.on("update_voice")
def handle_update_voice(data):
    """
    Update the active TTS voice mode.

    Payload from client:
      { "mode": "piper" }
        — switch back to default Piper voice, clears any stored reference.

      { "mode": "qwen", "ref_audio_b64": "<base64 WAV>", "ref_text": "..." }
        — enable Qwen voice cloning with the given reference audio.

    Broadcasts "voice_updated" to all clients so the UI can reflect the
    current mode everywhere (e.g. robot face badge).
    """
    mode = data.get("mode", "piper")

    if mode == "qwen":
        ref_b64  = data.get("ref_audio_b64", "")
        ref_text = data.get("ref_text", "")
        if not ref_b64:
            emit("voice_update_error", {"error": "ref_audio_b64 is required for Qwen mode"})
            return
        voice_state["mode"]          = "qwen"
        voice_state["ref_audio_b64"] = ref_b64
        voice_state["ref_text"]      = ref_text
        print(f"[Voice] Mode → qwen  |  ref_text={ref_text[:60]!r}")
    else:
        # Piper (default) — clear any stored reference data
        voice_state["mode"]          = "piper"
        voice_state["ref_audio_b64"] = None
        voice_state["ref_text"]      = ""
        print("[Voice] Mode → piper (default)")

    # Broadcast so every connected client (robot face, other tabs) stays in sync
    emit("voice_updated", {"mode": voice_state["mode"]}, broadcast=True)

@socketio.on("set_tts_engine")
def handle_set_tts_engine(data):
    """
    Switch TTS engine mode from the Voice Studio panel.
    Payload: { "engine": "piper" | "qwen" }
    When switching to piper, the active piper_voice is preserved.
    When switching to qwen, ref_audio must already be set (via test_voice_clone).
    """
    engine = data.get("engine", "piper")
    if engine == "qwen":
        if voice_state.get("ref_audio_b64"):
            voice_state["mode"] = "qwen"
            print("[Voice] Engine switched → qwen (voice clone)")
        else:
            print("[Voice] Cannot switch to qwen — no reference audio set")
            emit("voice_update_error", {"error": "Record or upload a voice sample first"})
            return
    else:
        voice_state["mode"] = "piper"
        print(f"[Voice] Engine switched → piper (voice: {voice_state.get('piper_voice')})")
    emit("voice_updated", {
        "mode": voice_state["mode"],
        "piper_voice": voice_state.get("piper_voice", PIPER_DEFAULT_VOICE),
    }, broadcast=True)

@socketio.on("test_voice_clone")
def handle_test_voice_clone(data):
    """
    Apply Qwen voice cloning — sets the AI voice for ALL future responses.
    Payload: { "audio_data": "<base64>", "text": "..." }
    Stores the reference audio in voice_state, switches to qwen mode,
    and generates a preview so the user can hear the result.
    """
    audio_data = data.get("audio_data", "")
    text = data.get("text", "").strip()

    if not audio_data:
        emit("voice_clone_result", {"ok": False, "error": "No audio data provided"})
        return

    # Store reference and switch to qwen for ALL future AI responses
    voice_state["mode"] = "qwen"
    voice_state["ref_audio_b64"] = audio_data
    voice_state["ref_text"] = ""  # auto-transcribed by tts_server via Whisper

    print(f"[VoiceClone] ✅ Voice cloned & SET as active AI voice")
    emit("voice_updated", {"mode": "qwen"}, broadcast=True)
    emit("voice_clone_result", {"ok": True})

@socketio.on("set_piper_voice")
def handle_set_piper_voice(data):
    """
    Set the active Piper voice for ALL future AI responses.
    Payload: { "voice": "en_US-lessac-medium" }
    Switches mode to piper and sets the voice.
    Generates a preview so the user can hear it.
    """
    voice_name = data.get("voice", PIPER_DEFAULT_VOICE)
    model_path, _ = _resolve_piper_voice(voice_name)

    if not os.path.exists(model_path):
        emit("piper_voice_result", {"ok": False, "error": f"Voice '{voice_name}' not installed"})
        return

    # Set as active voice for ALL future responses
    voice_state["mode"] = "piper"
    voice_state["piper_voice"] = voice_name
    print(f"[Piper] ✅ Voice SET to '{voice_name}' for all AI responses")
    emit("voice_updated", {
        "mode": "piper",
        "piper_voice": voice_name,
    }, broadcast=True)

    # Generate a preview
    text = "Hello, I am ARIA, your intelligent delivery robot assistant."
    result = generate_piper_audio(text)
    if result:
        emit("piper_voice_result", {"ok": True, "audio_base64": result, "voice": voice_name})
        emit("ai_audio", {"audio": result}, broadcast=True)
    else:
        emit("piper_voice_result", {"ok": False, "error": "Voice set but preview failed"})

# ==========================================
# IOT SOCKET EVENTS  (Smart Home / Home Assistant)
# ==========================================
@socketio.on("iot_get_devices")
def handle_iot_get_devices():
    """Client requests the list of IoT devices for the dashboard."""
    if not iot_controller:
        emit("iot_devices", {"ok": False, "error": "IoT controller not loaded",
                             "devices": []})
        return
    try:
        devices = iot_controller.get_filtered_devices()
        available = iot_controller.is_available()
        emit("iot_devices", {"ok": True, "devices": devices,
                             "ha_connected": available})
        print(f"[IoT] Sent {len(devices)} devices to client")
    except Exception as e:
        print(f"[IoT] Error fetching devices: {e}")
        emit("iot_devices", {"ok": False, "error": str(e), "devices": []})

@socketio.on("iot_toggle_device")
def handle_iot_toggle(data):
    """Toggle a switch / light / input_boolean.
    Payload: { entity_id: "switch.irrigation" }
    """
    eid = data.get("entity_id", "")
    if not eid or not iot_controller:
        emit("iot_error", {"error": "Invalid entity or IoT not loaded"})
        return
    try:
        ok = iot_controller.toggle(eid)
        if ok:
            # Fetch updated state and broadcast to all clients
            new_state = iot_controller.get_entity_state(eid)
            if new_state:
                attrs = new_state.get("attributes", {})
                emit("iot_state_changed", {
                    "entity_id": eid,
                    "state":     new_state.get("state", "unknown"),
                    "name":      attrs.get("friendly_name", eid),
                    "attributes": attrs,
                }, broadcast=True)
            print(f"[IoT] Toggled {eid}")
        else:
            emit("iot_error", {"error": f"Failed to toggle {eid}"})
    except Exception as e:
        print(f"[IoT] Toggle error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_call_service")
def handle_iot_call_service(data):
    """Generic HA service call.
    Payload: { domain, service, entity_id, data: {} }
    """
    domain   = data.get("domain", "")
    service  = data.get("service", "")
    eid      = data.get("entity_id")
    svc_data = data.get("data")
    if not domain or not service or not iot_controller:
        emit("iot_error", {"error": "Missing domain/service or IoT not loaded"})
        return
    try:
        ok = iot_controller.call_service(domain, service, eid, svc_data)
        if ok and eid:
            new_state = iot_controller.get_entity_state(eid)
            if new_state:
                attrs = new_state.get("attributes", {})
                emit("iot_state_changed", {
                    "entity_id": eid,
                    "state":     new_state.get("state", "unknown"),
                    "name":      attrs.get("friendly_name", eid),
                    "attributes": attrs,
                }, broadcast=True)
        if not ok:
            emit("iot_error", {"error": f"Service {domain}.{service} failed"})
    except Exception as e:
        print(f"[IoT] Service call error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_add_device")
def handle_iot_add_device(data):
    """Create a new virtual Input Boolean device in Home Assistant.

    Payload: { "name": "Garden Sprinkler", "room": "Living Room" }

    The optional 'room' field is appended to the friendly name as
    "[Room]" so the UI can group devices by room.

    On success, broadcasts the updated device list to ALL connected
    clients so the new device appears immediately.  Because call_llm()
    fetches the device list dynamically for every request, the LLM
    will automatically see the new device in its system prompt context.
    """
    name = (data.get("name") or "").strip()
    room = (data.get("room") or "").strip()
    if not name:
        emit("iot_error", {"error": "Device name cannot be empty"})
        return
    if not iot_controller:
        emit("iot_error", {"error": "IoT controller not loaded"})
        return

    # Build display name with optional room suffix
    display_name = f"{name} [{room}]" if room else name

    try:
        ok, result = iot_controller.create_input_boolean(display_name)
        if ok:
            print(f"[IoT] ✅ Virtual device created: {result}"
                  + (f" (room={room})" if room else ""))
            # Fetch the full updated device list and broadcast to everyone
            devices = iot_controller.get_filtered_devices()
            available = iot_controller.is_available()
            emit("iot_devices", {
                "ok": True,
                "devices": devices,
                "ha_connected": available,
            }, broadcast=True)
            # Also send a success notification to the requesting client
            emit("iot_device_added", {
                "ok": True,
                "entity_id": result,
                "name": display_name,
            })
        else:
            print(f"[IoT] ⚠️ Failed to create device: {result}")
            emit("iot_error", {"error": f"Failed to create device: {result}"})
    except Exception as e:
        print(f"[IoT] Device creation error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_delete_device")
def handle_iot_delete_device(data):
    """Delete a virtual input_boolean device from Home Assistant.

    Payload: { "entity_id": "input_boolean.garden_sprinkler" }

    On success, broadcasts the updated device list to all clients.
    Only input_boolean (virtual) devices can be deleted.
    """
    eid = (data.get("entity_id") or "").strip()
    if not eid:
        emit("iot_error", {"error": "Entity ID cannot be empty"})
        return
    if not iot_controller:
        emit("iot_error", {"error": "IoT controller not loaded"})
        return

    try:
        ok, msg = iot_controller.delete_device(eid)
        if ok:
            print(f"[IoT] 🗑️ Device deleted: {eid}")
            # Small delay to let HA process the deletion
            import time; time.sleep(0.5)
            # Broadcast updated device list
            devices = iot_controller.get_filtered_devices()
            available = iot_controller.is_available()
            emit("iot_devices", {
                "ok": True,
                "devices": devices,
                "ha_connected": available,
            }, broadcast=True)
            emit("iot_device_deleted", {
                "ok": True,
                "entity_id": eid,
                "message": msg,
            })
        else:
            print(f"[IoT] ⚠️ Failed to delete device: {msg}")
            emit("iot_error", {"error": msg})
    except Exception as e:
        print(f"[IoT] Delete error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_update_device")
def handle_iot_update_device(data):
    """Update the friendly_name of an entity.

    Payload: { "entity_id": "input_boolean.garden", "friendly_name": "New Name" }

    Broadcasts state change to all clients on success.
    """
    eid  = (data.get("entity_id") or "").strip()
    name = (data.get("friendly_name") or "").strip()
    if not eid or not name:
        emit("iot_error", {"error": "entity_id and friendly_name are required"})
        return
    if not iot_controller:
        emit("iot_error", {"error": "IoT controller not loaded"})
        return

    try:
        ok, result = iot_controller.update_friendly_name(eid, name)
        if ok:
            print(f"[IoT] ✏️ Device renamed: {eid} → {name}")
            new_state = iot_controller.get_entity_state(eid)
            if new_state:
                attrs = new_state.get("attributes", {})
                emit("iot_state_changed", {
                    "entity_id": eid,
                    "state":     new_state.get("state", "unknown"),
                    "name":      name,
                    "attributes": attrs,
                }, broadcast=True)
            emit("iot_device_updated", {
                "ok": True,
                "entity_id": eid,
                "friendly_name": name,
            })
        else:
            emit("iot_error", {"error": f"Rename failed: {result}"})
    except Exception as e:
        print(f"[IoT] Rename error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_get_device_info")
def handle_iot_get_device_info(data):
    """Fetch detailed info for a single entity — used by the settings modal.

    Payload: { "entity_id": "switch.irrigation" }
    Response: { ok: true, info: { entity_id, friendly_name, domain, ... } }
    """
    eid = (data.get("entity_id") or "").strip()
    if not eid:
        emit("iot_error", {"error": "entity_id is required"})
        return
    if not iot_controller:
        emit("iot_error", {"error": "IoT controller not loaded"})
        return

    try:
        info = iot_controller.get_entity_attributes(eid)
        if info:
            emit("iot_device_info", {"ok": True, "info": info})
        else:
            emit("iot_device_info", {"ok": False, "error": f"Entity {eid} not found"})
    except Exception as e:
        print(f"[IoT] Device info error: {e}")
        emit("iot_device_info", {"ok": False, "error": str(e)})

# ==========================================
# IOT AUTO-DETECT POLLING
# ==========================================
_auto_detect_active = False
_auto_detect_thread = None
_auto_detect_snapshot: set = set()  # entity_ids from last poll

def _auto_detect_loop():
    """Background loop: poll HA every 3s and emit new device events."""
    global _auto_detect_active, _auto_detect_snapshot
    print("[AutoDetect] Polling started")
    while _auto_detect_active:
        try:
            if iot_controller and iot_controller.is_available():
                devices = iot_controller.get_filtered_devices()
                current_ids = {d["entity_id"] for d in devices}
                new_ids = current_ids - _auto_detect_snapshot
                if _auto_detect_snapshot and new_ids:
                    # Find the full device objects for new entities
                    new_devs = [d for d in devices if d["entity_id"] in new_ids]
                    for nd in new_devs:
                        print(f"[AutoDetect] ✨ New device: {nd['name']} "
                              f"({nd['entity_id']})")
                    socketio.emit("iot_new_devices_detected", {
                        "devices": new_devs,
                    })
                    # Also broadcast the full updated list
                    socketio.emit("iot_devices", {
                        "ok": True,
                        "devices": devices,
                        "ha_connected": True,
                    })
                _auto_detect_snapshot = current_ids
        except Exception as e:
            print(f"[AutoDetect] Poll error: {e}")
        time.sleep(3)
    print("[AutoDetect] Polling stopped")

@socketio.on("iot_auto_detect")
def handle_iot_auto_detect(data):
    """Toggle auto-detect polling.
    Payload: { "enabled": true/false }
    """
    global _auto_detect_active, _auto_detect_thread, _auto_detect_snapshot
    enabled = data.get("enabled", False)

    if enabled and not _auto_detect_active:
        _auto_detect_active = True
        # Take initial snapshot so we don't flag existing devices as new
        if iot_controller:
            try:
                devices = iot_controller.get_filtered_devices()
                _auto_detect_snapshot = {d["entity_id"] for d in devices}
            except Exception:
                _auto_detect_snapshot = set()
        _auto_detect_thread = _threading.Thread(
            target=_auto_detect_loop, daemon=True
        )
        _auto_detect_thread.start()
        emit("iot_auto_detect_status", {"active": True})
        print("[AutoDetect] Enabled by client")
    elif not enabled and _auto_detect_active:
        _auto_detect_active = False
        emit("iot_auto_detect_status", {"active": False})
        print("[AutoDetect] Disabled by client")
    else:
        emit("iot_auto_detect_status", {"active": _auto_detect_active})

# ==========================================
# GENERIC DEVICE SOCKET EVENTS (Tasmota/ESP)
# ==========================================
@socketio.on("iot_get_generic_devices")
def handle_get_generic_devices():
    """Return the list of generic network devices."""
    if not generic_device_mgr:
        emit("iot_generic_devices", {"ok": False, "devices": [],
                                      "error": "Generic device manager not loaded"})
        return
    devices = generic_device_mgr.list_devices()
    emit("iot_generic_devices", {"ok": True, "devices": devices})

@socketio.on("iot_test_generic_device")
def handle_test_generic_device(data):
    """Test connectivity to a generic device IP.
    Payload: { "ip": "192.168.1.50" }
    Response: { ok: bool, ip: str, reachable: bool, tasmota: bool, state: str, error: str }
    """
    ip = (data.get("ip") or "").strip()
    if not ip:
        emit("iot_test_result", {"ok": False, "error": "IP is required"})
        return

    result = {"ok": True, "ip": ip, "reachable": False,
              "tasmota": False, "state": ""}

    # ── Step 1: Ping test ──
    try:
        ping = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True, timeout=4,
        )
        result["reachable"] = (ping.returncode == 0)
    except Exception:
        result["reachable"] = False

    if not result["reachable"]:
        result["error"] = f"Device at {ip} is not reachable (ping failed)"
        emit("iot_test_result", result)
        return

    # ── Step 2: Tasmota API test ──
    try:
        r = requests.get(f"http://{ip}/cm?cmnd=Power",
                         timeout=3)
        if r.ok:
            body = r.json()
            power = body.get("POWER", body.get("POWER1", ""))
            if power:
                result["tasmota"] = True
                result["state"] = power
            else:
                result["error"] = ("Device responded but not in Tasmota format. "
                                   "Expected JSON with POWER key.")
        else:
            result["error"] = f"Device responded with HTTP {r.status_code}"
    except requests.exceptions.ConnectionError:
        result["error"] = (f"Device at {ip} is online (ping OK) but "
                           f"no HTTP server on port 80")
    except Exception as exc:
        result["error"] = f"HTTP test failed: {exc}"

    emit("iot_test_result", result)
    print(f"[GenDev] Test {ip}: reachable={result['reachable']} "
          f"tasmota={result['tasmota']} state={result.get('state', '?')}")


@socketio.on("iot_add_generic_device")
def handle_add_generic_device(data):
    """Add a generic network device.
    Payload: { "name": "ESP Relay", "ip": "192.168.1.50",
               "room": "Living Room", "device_type": "switch",
               "channels": ["Ch1", "Ch2"] }

    Performs a quick connectivity check before adding.
    """
    name = (data.get("name") or "").strip()
    ip = (data.get("ip") or "").strip()
    room = (data.get("room") or "").strip()
    device_type = (data.get("device_type") or "switch").strip()
    channels = data.get("channels") or []
    if not name or not ip:
        emit("iot_error", {"error": "Name and IP address are required"})
        return
    if not generic_device_mgr:
        emit("iot_error", {"error": "Generic device manager not loaded"})
        return

    # ── Quick connectivity test ──
    warning = ""
    try:
        ping = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            capture_output=True, timeout=4,
        )
        if ping.returncode != 0:
            warning = f"⚠️ Device at {ip} is not reachable (ping failed). Adding anyway."
            print(f"[GenDev] Warning: {ip} not reachable during add")
    except Exception:
        warning = f"⚠️ Could not test {ip} connectivity. Adding anyway."

    try:
        ok, result = generic_device_mgr.add_device(
            name, ip, room=room, device_type=device_type, channels=channels)
        if ok:
            # Try to get initial state from device
            try:
                r = requests.get(f"http://{ip}/cm?cmnd=Power", timeout=2)
                if r.ok:
                    body = r.json()
                    power = body.get("POWER", body.get("POWER1", ""))
                    if power:
                        result["state"] = power.lower()
                        generic_device_mgr._save()
            except Exception:
                pass

            emit("iot_generic_device_added", {
                "ok": True, "device": result, "warning": warning,
            })
            # Broadcast updated list
            emit("iot_generic_devices", {
                "ok": True, "devices": generic_device_mgr.list_devices()
            }, broadcast=True)
        else:
            emit("iot_error", {"error": result})
    except Exception as e:
        print(f"[GenDev] Add error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_toggle_generic_device")
def handle_toggle_generic_device(data):
    """Toggle a generic Tasmota device.
    Payload: { "id": "generic.esp_relay", "channel": 2 }
    """
    dev_id = (data.get("id") or "").strip()
    channel = data.get("channel")
    if channel is not None:
        try:
            channel = int(channel)
        except (ValueError, TypeError):
            channel = None
    if not dev_id or not generic_device_mgr:
        emit("iot_error", {"error": "Invalid device or manager not loaded"})
        return
    try:
        ok, result = generic_device_mgr.toggle_device(dev_id, channel=channel)
        if ok:
            emit("iot_generic_device_toggled", {
                "ok": True, "id": dev_id, "state": result,
                "channel": channel,
            }, broadcast=True)
        else:
            emit("iot_error", {"error": result})
    except Exception as e:
        print(f"[GenDev] Toggle error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_send_generic_command")
def handle_send_generic_command(data):
    """Send a command (dimmer/fan) to a generic device.
    Payload: { "id": "generic.dimmer", "command": "dimmer", "value": 75 }
    """
    dev_id = (data.get("id") or "").strip()
    command = (data.get("command") or "").strip()
    value = data.get("value", 0)
    if not dev_id or not command or not generic_device_mgr:
        emit("iot_error", {"error": "Invalid device/command or manager not loaded"})
        return
    try:
        value = int(value)
        ok, result = generic_device_mgr.send_command(dev_id, command, value)
        if ok:
            emit("iot_generic_command_result", {
                "ok": True, "id": dev_id,
                "command": command, "value": value,
            }, broadcast=True)
        else:
            emit("iot_error", {"error": result})
    except Exception as e:
        print(f"[GenDev] Command error: {e}")
        emit("iot_error", {"error": str(e)})

@socketio.on("iot_delete_generic_device")
def handle_delete_generic_device(data):
    """Delete a generic device.
    Payload: { "id": "generic.esp_relay" }
    """
    dev_id = (data.get("id") or "").strip()
    if not dev_id or not generic_device_mgr:
        emit("iot_error", {"error": "Invalid device or manager not loaded"})
        return
    try:
        ok, msg = generic_device_mgr.delete_device(dev_id)
        if ok:
            emit("iot_generic_device_deleted", {"ok": True, "id": dev_id})
            emit("iot_generic_devices", {
                "ok": True, "devices": generic_device_mgr.list_devices()
            }, broadcast=True)
        else:
            emit("iot_error", {"error": msg})
    except Exception as e:
        print(f"[GenDev] Delete error: {e}")
        emit("iot_error", {"error": str(e)})

import concurrent.futures as _futures


def _discover_mdns_names() -> dict:
    """Discover all mDNS hostnames on the local network in one shot.

    Uses ``avahi-browse -arpt`` to get all advertised services with their
    resolved IP addresses, then builds a {ip: hostname} mapping.

    This is MUCH faster than calling ``avahi-resolve --address <ip>``
    per-IP, which often hangs/times out on consumer networks.

    Returns a dict mapping IP addresses to mDNS hostnames.
    """
    mdns_map = {}
    try:
        r = subprocess.run(
            ["avahi-browse", "-arpt"],
            capture_output=True, text=True, timeout=6,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                # Format: +;eth0;IPv4;hostname;_http._tcp;local;host.local;192.168.1.50;80;""
                # We want the IP (field 7) and hostname (field 6)
                parts = line.split(";")
                if len(parts) >= 8 and parts[0] == "=":
                    ip = parts[7].strip()
                    hostname = parts[6].strip().rstrip(".")
                    if ip and hostname:
                        mdns_map[ip] = hostname
    except FileNotFoundError:
        pass  # avahi-browse not installed
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        print(f"[NetScan] avahi-browse error: {e}")
    return mdns_map


def _resolve_hostname_fast(ip_addr: str, mdns_cache: dict) -> str:
    """Fast hostname resolution using pre-built mDNS cache + DNS + NetBIOS.

    Unlike the slow per-IP avahi-resolve, this uses the pre-cached mDNS
    results from _discover_mdns_names(), falling back to DNS and NetBIOS.
    """
    # ── Strategy 1: mDNS cache (instant) ──
    if ip_addr in mdns_cache:
        return mdns_cache[ip_addr]

    # ── Strategy 2: Reverse DNS ──
    try:
        name = socket.gethostbyaddr(ip_addr)[0]
        if name:
            return name
    except Exception:
        pass

    # ── Strategy 3: HTTP probe for Tasmota/ESP32 devices ──
    try:
        r = requests.get(f"http://{ip_addr}/status",
                         timeout=1.5)
        if r.ok:
            body = r.json()
            hostname = body.get("hostname", "")
            if hostname:
                return hostname + ".local"
    except Exception:
        pass

    # ── Strategy 4: NetBIOS via nmblookup ──
    try:
        r = subprocess.run(
            ["nmblookup", "-A", ip_addr],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if "<00>" in line and "UNIQUE" in line.upper():
                    name = line.split("<00>")[0].strip()
                    if name and name != "*":
                        return name
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception:
        pass

    return ""


def _ping_sweep(subnet_prefix: str) -> None:
    """Fast parallel ping sweep to populate the ARP cache.

    Pings all 254 IPs in a /24 subnet concurrently using 50 threads.
    Each ping has a 1-second timeout so the whole sweep finishes in ~6s.
    """
    def _ping_one(ip):
        try:
            subprocess.run(
                ["ping", "-c", "1", "-W", "1", ip],
                capture_output=True, timeout=2,
            )
        except Exception:
            pass

    ips = [f"{subnet_prefix}.{i}" for i in range(1, 255)]
    with _futures.ThreadPoolExecutor(max_workers=50) as pool:
        list(pool.map(_ping_one, ips))


@socketio.on("iot_scan_lan")
def handle_scan_lan():
    """Scan local network for active devices.

    Pipeline:
      1. Determine local subnet
      2. Populate ARP cache via nmap -sn (fast) or ping sweep (fallback)
      3. Read ARP cache via 'ip neigh' or 'arp -a'
      4. Resolve hostnames concurrently (DNS → mDNS → NetBIOS)
      5. Return sorted list to the client

    Returns a list of { ip, mac, hostname, state } dicts.
    """
    hosts = []
    local_ip = get_local_ip()
    if not local_ip or local_ip == "127.0.0.1":
        emit("iot_scan_result", {
            "ok": False, "error": "Cannot determine local IP", "hosts": []
        })
        return

    subnet_prefix = local_ip.rsplit(".", 1)[0]
    subnet_cidr = subnet_prefix + ".0/24"

    # ── Step 1: Populate ARP cache ──
    arp_populated = False
    # Try nmap first (fast SYN-based discovery)
    try:
        nmap_result = subprocess.run(
            ["nmap", "-sn", "-T4", "--min-parallelism", "50", subnet_cidr],
            capture_output=True, text=True, timeout=20,
        )
        if nmap_result.returncode == 0:
            arp_populated = True
            print(f"[NetScan] ARP cache populated via nmap")
    except FileNotFoundError:
        print("[NetScan] nmap not installed — using ping sweep fallback")
    except subprocess.TimeoutExpired:
        print("[NetScan] nmap timed out — using ping sweep fallback")
    except Exception as e:
        print(f"[NetScan] nmap error: {e}")

    # Fallback: parallel ping sweep
    if not arp_populated:
        try:
            print(f"[NetScan] Running parallel ping sweep on {subnet_cidr}...")
            _ping_sweep(subnet_prefix)
            print("[NetScan] Ping sweep complete")
        except Exception as e:
            print(f"[NetScan] Ping sweep error: {e}")

    # ── Step 2: Read ARP cache ──
    raw_hosts = []   # list of (ip, mac, state)
    try:
        result = subprocess.run(
            ["ip", "neigh"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if len(parts) >= 5 and "lladdr" in parts:
                    lladdr_idx = parts.index("lladdr")
                    if lladdr_idx + 1 < len(parts):
                        ip_addr = parts[0]
                        mac = parts[lladdr_idx + 1]
                        state = parts[-1] if parts[-1] in \
                            ("REACHABLE", "STALE", "DELAY", "PROBE") else ""

                        # Skip Docker bridge, localhost, and self
                        if ip_addr == local_ip:
                            continue
                        if ip_addr.startswith("172.17.") or \
                           ip_addr.startswith("172.18.") or \
                           ip_addr.startswith("172.19."):
                            continue

                        raw_hosts.append((ip_addr, mac, state))
        else:
            # Fallback: arp -a
            result = subprocess.run(
                ["arp", "-a"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    m = re.match(
                        r'^([^\s]+)\s*\(([\d.]+)\)\s+at\s+([0-9a-fA-F:-]+)',
                        line,
                    )
                    if m:
                        ip_addr = m.group(2)
                        if ip_addr == local_ip:
                            continue
                        if ip_addr.startswith("172.17.") or \
                           ip_addr.startswith("172.18.") or \
                           ip_addr.startswith("172.19."):
                            continue
                        mac = m.group(3).replace("-", ":")
                        arp_name = m.group(1) if m.group(1) != "?" else ""
                        raw_hosts.append((ip_addr, mac, arp_name))

    except Exception as e:
        print(f"[NetScan] ARP read error: {e}")
        emit("iot_scan_result", {
            "ok": False, "error": f"Failed to read ARP cache: {e}",
            "hosts": [],
        })
        return

    if not raw_hosts:
        print("[NetScan] No hosts found in ARP cache")
        emit("iot_scan_result", {"ok": True, "hosts": []})
        return

    # ── Step 3: Resolve hostnames ──
    # Phase A: Discover ALL mDNS names in one shot (fast, ~3-5s)
    mdns_cache = _discover_mdns_names()
    if mdns_cache:
        print(f"[NetScan] mDNS discovered {len(mdns_cache)} name(s): "
              f"{list(mdns_cache.values())}")

    # Phase B: Resolve remaining IPs concurrently (DNS + HTTP probe + NetBIOS)
    ip_list = [h[0] for h in raw_hosts]
    hostname_map = {}
    try:
        with _futures.ThreadPoolExecutor(max_workers=10) as pool:
            future_map = {pool.submit(_resolve_hostname_fast, ip, mdns_cache): ip
                          for ip in ip_list}
            for future in _futures.as_completed(future_map, timeout=20):
                ip = future_map[future]
                try:
                    hostname_map[ip] = future.result()
                except Exception:
                    hostname_map[ip] = ""
    except Exception as e:
        print(f"[NetScan] Hostname resolution error: {e}")

    # ── Step 4: Build result ──
    for ip_addr, mac, state in raw_hosts:
        hostname = hostname_map.get(ip_addr, "")
        hosts.append({
            "ip": ip_addr,
            "mac": mac,
            "hostname": hostname,
            "state": state if state in
                ("REACHABLE", "STALE", "DELAY", "PROBE") else "",
        })

    # Sort by IP octet
    hosts.sort(key=lambda h: tuple(int(p) for p in h["ip"].split(".")))
    print(f"[NetScan] Found {len(hosts)} host(s) on LAN")
    emit("iot_scan_result", {"ok": True, "hosts": hosts})

# ==========================================
# NETWORK STATUS
# ==========================================
@socketio.on("iot_network_status")
def handle_network_status():
    """Return local network health info."""
    ha_ok = False
    if iot_controller:
        try:
            ha_ok = iot_controller.is_available()
        except Exception:
            pass

    # Check WAN connectivity (non-blocking, fast)
    wan_ok = False
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _s.settimeout(2)
        _s.connect(("8.8.8.8", 53))
        _s.close()
        wan_ok = True
    except Exception:
        pass

    local_ip = get_local_ip()
    emit("iot_network_status", {
        "ha_reachable": ha_ok,
        "wan_available": wan_ok,
        "local_ip": local_ip,
        "ha_url": HA_URL,
        "mode": "local" if ha_ok and not wan_ok else ("full" if ha_ok and wan_ok else "degraded"),
    })

# ==========================================
# CAMERA ROTATION
# ==========================================
@socketio.on("camera_rotate")
def handle_camera_rotate(data):
    """Relay camera rotation command to all clients.
    Payload: { "angle": 0|90|180|270 }
    """
    angle = data.get("angle", 0)
    print(f"[Camera] Rotation → {angle}°")
    emit("camera_rotate", {"angle": angle}, broadcast=True, include_self=False)


# ==========================================
# AUTONOMOUS NAVIGATION  (Vision + LLM + YOLO + Spatial Memory)
# ==========================================
_auto_nav_active = False
_auto_nav_thread = None
_auto_nav_lock = _threading.Lock()

# ── Mission State ─────────────────────────────────────────
_mission_state = {
    "type": "explore",       # explore | find_object | move_direction | go_to_remembered | search_by_landmarks
    "target": None,          # object name for find_object
    "started_at": 0,
    "status": "idle",        # idle | active | found | failed
    "memory_context": "",    # recalled spatial memory text
    "direction": None,       # for move_direction
    "duration": 3,           # seconds for move_direction
}

def _set_mission(mission_type, **kwargs):
    """Update mission state and broadcast to clients."""
    _mission_state["type"] = mission_type
    _mission_state["started_at"] = time.time()
    _mission_state["status"] = "active"
    _mission_state["target"] = kwargs.get("target")
    _mission_state["memory_context"] = kwargs.get("memory_context", "")
    _mission_state["direction"] = kwargs.get("direction")
    _mission_state["duration"] = kwargs.get("duration", 3)
    socketio.emit("autonomous_mission", {
        "type": mission_type,
        "target": _mission_state["target"],
        "status": "active",
    })

def _clear_mission():
    _mission_state["type"] = "explore"
    _mission_state["target"] = None
    _mission_state["status"] = "idle"
    _mission_state["memory_context"] = ""
    socketio.emit("autonomous_mission", {"type": "explore", "target": None, "status": "idle"})

# ── YOLO Detection Helper ─────────────────────���───────────
def _yolo_detect_in_frame(frame_b64, target_name):
    """Run YOLO on a base64 JPEG frame. Returns (found, x_center_ratio, area_ratio, class_name) or (False,0,0,'')."""
    if not _yolo_model or not _HAS_YOLO:
        return False, 0, 0, ""
    try:
        img_bytes = base64.b64decode(frame_b64)
        np_arr = _np.frombuffer(img_bytes, _np.uint8)
        img = _cv2.imdecode(np_arr, _cv2.IMREAD_COLOR)
        if img is None:
            return False, 0, 0, ""

        results = _yolo_model(img, conf=YOLO_CONFIDENCE, verbose=False)
        frame_h, frame_w = img.shape[:2]
        frame_area = frame_h * frame_w
        target_lower = target_name.lower()

        best_match = None
        best_area = 0
        for r in results:
            for box in r.boxes:
                cls_name = r.names[int(box.cls)].lower()
                if target_lower in cls_name or cls_name in target_lower:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    box_area = (x2 - x1) * (y2 - y1)
                    if box_area > best_area:
                        best_area = box_area
                        x_center = (x1 + x2) / 2 / frame_w
                        best_match = (True, x_center, box_area / frame_area, cls_name)
        return best_match or (False, 0, 0, "")
    except Exception as exc:
        print(f"[YOLO] Detection error: {exc}")
        return False, 0, 0, ""

# ── ESP32 Move Helper ─────────────────────────────────────
def _send_esp32_move(direction):
    """Send move command to ESP32 (non-blocking)."""
    def _fwd():
        try:
            _esp32_session.get(f"http://aria-esp32.local/move?dir={direction}", timeout=0.5)
        except Exception:
            pass
    _threading.Thread(target=_fwd, daemon=True).start()
    socketio.emit("move_command", {"direction": direction})

# ── Build Goal-Oriented Prompt ────────────────────────────
def _build_goal_prompt():
    """Build the LLM system prompt based on current mission."""
    mission = _mission_state["type"]
    target = _mission_state.get("target", "")

    base = """You are the autonomous navigation AI for ARIA, a delivery robot with a live camera.

Analyze this camera image and decide the NEXT movement action.
You MUST respond with ONLY a valid JSON object — no markdown, no extra text.

Valid actions: "forward", "backward", "left", "right", "stop"
Valid status: "exploring", "searching", "found", "navigating", "blocked"

Decision rules:
- Path clear ahead → "forward"
- Obstacle on left → "right"
- Obstacle on right → "left"
- Path blocked → "backward"
- Wall very close → "stop"
- Person detected → "stop" (safety)
- Dark/unclear image → "stop"

IMPORTANT: Always provide a scene_description with notable objects, furniture, doors, and spatial relationships. Identify the most prominent visual landmark as primary_landmark.
Keep reason under 10 words.

"""

    if mission == "find_object" and target:
        base += f"""CURRENT MISSION: Find "{target}"
You are actively searching for: {target}
If you see {target} or something similar, set status to "found" and action to "stop".
Otherwise, keep exploring systematically — try different directions.

"""
    elif mission == "search_by_landmarks":
        mem_ctx = _mission_state.get("memory_context", "")
        base += f"""CURRENT MISSION: Navigate to a remembered location.
Use these spatial memories to guide navigation:
{mem_ctx}

Compare what you see NOW to the memories above. If the scene matches, set status to "found".
Otherwise, keep exploring toward matching landmarks.

"""
    elif mission == "explore":
        base += """CURRENT MISSION: Explore the environment
Map the area systematically. Prefer unexplored directions. Describe everything you see.

"""

    base += """Respond with this exact JSON format:
{"action": "forward", "reason": "path is clear", "status": "exploring", "scene_description": "A hallway with white walls and a wooden door on the left", "primary_landmark": "wooden door"}"""

    return base

# ── Main Navigation Loop ──────────────────────────────────
def _auto_nav_loop():
    """Goal-oriented navigation loop with YOLO fast-track and spatial memory."""
    global _auto_nav_active
    print("[AutoNav] ✅ Autonomous navigation STARTED")
    _emit_auto_log("🟢 Navigation engine started", "ok")

    cycle = 0
    consecutive_errors = 0
    MAX_ERRORS = 5

    while _auto_nav_active:
        cycle += 1
        mission = _mission_state["type"]

        # ─�� Mission timeout check ──
        if _mission_state["started_at"] > 0:
            elapsed = time.time() - _mission_state["started_at"]
            if elapsed > AUTO_NAV_MAX_MISSION_TIME:
                _emit_auto_log(f"⏱ Mission timeout ({int(elapsed)}s) — returning to explore", "warn")
                _clear_mission()

        try:
            # ════════════════════════════════════════════
            # MOVE_DIRECTION — Simple timed movement
            # ════════════════════════════════════════════
            if mission == "move_direction":
                direction = _mission_state.get("direction") or "forward"
                duration = _mission_state.get("duration") or 3
                _emit_auto_log(f"⬆️ Moving {direction} for {duration}s", "info", direction=direction)
                _send_esp32_move(direction)
                # Sleep in small increments so we can be cancelled
                for _ in range(int(duration * 10)):
                    if not _auto_nav_active:
                        break
                    time.sleep(0.1)
                _send_esp32_move("stop")
                _emit_auto_log(f"✅ Movement complete", "ok", direction="stop")
                _clear_mission()
                continue

            # ═════════════════════════════════════════���══
            # FIND_OBJECT with YOLO fast loop
            # ════════════════════════════════════════════
            if mission == "find_object" and _yolo_model and _mission_state.get("target"):
                target = _mission_state["target"]
                frame = latest_video_frame
                if frame:
                    found, x_center, area_ratio, cls = _yolo_detect_in_frame(frame, target)
                    if found:
                        # Object detected by YOLO — fast tracking
                        if area_ratio > YOLO_APPROACH_RATIO:
                            # Close enough — stop
                            _send_esp32_move("stop")
                            _emit_auto_log(f"✅ FOUND {cls}! Object reached.", "ok", direction="stop")
                            _mission_state["status"] = "found"
                            socketio.emit("autonomous_mission", {
                                "type": "find_object", "target": target, "status": "found"})
                            _emit_auto_cmd_response(f"✅ I found the {target}! I've stopped in front of it.")
                            _clear_mission()
                            time.sleep(2)
                            continue
                        elif abs(x_center - 0.5) > YOLO_CENTER_THRESH:
                            # Not centered — turn toward it
                            direction = "left" if x_center < 0.5 else "right"
                            _send_esp32_move(direction)
                            _emit_auto_log(f"🎯 {cls} detected — turning {direction}", "info", direction=direction)
                            time.sleep(AUTO_NAV_YOLO_INTERVAL)
                            continue
                        else:
                            # Centered — approach
                            _send_esp32_move("forward")
                            _emit_auto_log(f"🎯 {cls} centered — approaching ({int(area_ratio*100)}%)", "ok", direction="forward")
                            time.sleep(AUTO_NAV_YOLO_INTERVAL)
                            continue
                    # YOLO didn't find it — fall through to LLM vision below

            # ════════════════════════════════════════════
            # LLM VISION — explore / find / navigate
            # ════════════════════════════════════════════
            frame = latest_video_frame
            if not frame:
                _emit_auto_log("📷 No camera frame — waiting…", "warn")
                time.sleep(AUTO_NAV_CYCLE_INTERVAL)
                continue

            _emit_auto_log(f"📷 Frame #{cycle} — LLM analyzing…", "info")

            user_content = [
                {"type": "text", "text": "Analyze this image and decide the next movement."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame}"}},
            ]
            messages = [
                {"role": "system", "content": _build_goal_prompt()},
                {"role": "user", "content": user_content},
            ]
            payload = {
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 200,
                "top_p": 0.9,
            }

            try:
                res = _http.post(LLAMA_URL, json=payload, timeout=15)
                if not res.ok:
                    _emit_auto_log(f"⚠ LLM error: HTTP {res.status_code}", "danger")
                    consecutive_errors += 1
                    time.sleep(AUTO_NAV_CYCLE_INTERVAL)
                    continue
                raw = res.json()["choices"][0]["message"]["content"].strip()
            except requests.exceptions.Timeout:
                _emit_auto_log("⏱ LLM timed out", "warn")
                consecutive_errors += 1
                time.sleep(AUTO_NAV_CYCLE_INTERVAL)
                continue
            except Exception as e:
                _emit_auto_log(f"⚠ LLM error: {e}", "danger")
                consecutive_errors += 1
                time.sleep(AUTO_NAV_CYCLE_INTERVAL)
                continue

            # ── Parse LLM JSON response ──
            action = "stop"
            reason = "unknown"
            scene_desc = ""
            primary_landmark = ""
            status = "exploring"
            try:
                json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
                if json_match:
                    decision = json.loads(json_match.group())
                    action = decision.get("action", "stop").lower().strip()
                    reason = decision.get("reason", "")
                    scene_desc = decision.get("scene_description", "")
                    primary_landmark = decision.get("primary_landmark", "")
                    status = decision.get("status", "exploring")
                else:
                    _emit_auto_log(f"⚠ Parse error: {raw[:60]}", "warn")
            except json.JSONDecodeError:
                _emit_auto_log(f"⚠ JSON error: {raw[:60]}", "warn")

            if action not in ("forward", "backward", "left", "right", "stop"):
                action = "stop"

            # ── Execute movement ──
            icon_map = {"forward": "⬆️", "backward": "⬇️", "left": "⬅️", "right": "➡️", "stop": "⏹"}
            _emit_auto_log(f"{icon_map.get(action, '🔄')} {action.upper()} — {reason}", "ok", direction=action)
            _send_esp32_move(action)

            # ── Handle mission status from LLM ──
            if status == "found" and mission in ("find_object", "search_by_landmarks"):
                target = _mission_state.get("target") or "target"
                _emit_auto_log(f"✅ Mission complete: found {target}!", "ok")
                _emit_auto_cmd_response(f"✅ I found what I was looking for — {scene_desc[:80]}")
                _send_esp32_move("stop")
                _clear_mission()

            # ── Store spatial memory (async, non-blocking) ──
            if scene_desc and spatial_engine and cycle % AUTO_NAV_MEMORY_INTERVAL == 0:
                meta = {
                    "timestamp": int(time.time()),
                    "mission": mission,
                    "primary_landmark": primary_landmark,
                    "secondary_landmarks": "",
                }
                _threading.Thread(
                    target=spatial_engine.remember,
                    args=(scene_desc, meta),
                    daemon=True,
                ).start()
                _emit_auto_log(f"🧠 Memory stored: {primary_landmark or scene_desc[:30]}", "info")

            consecutive_errors = 0

        except Exception as e:
            print(f"[AutoNav] Loop error: {e}")
            _emit_auto_log(f"❌ Error: {str(e)[:60]}", "danger")
            consecutive_errors += 1

        if consecutive_errors >= MAX_ERRORS:
            _emit_auto_log(f"🛑 Too many errors — stopping", "danger")
            _auto_nav_active = False
            _send_esp32_move("stop")
            break

        time.sleep(AUTO_NAV_CYCLE_INTERVAL)

    print("[AutoNav] 🔴 Autonomous navigation STOPPED")
    _emit_auto_log("🔴 Navigation engine stopped", "danger")
    _send_esp32_move("stop")


def _emit_auto_log(message: str, log_type: str = "info", direction: str | None = None):
    """Emit an autonomous navigation log entry to all clients."""
    payload = {"message": message, "type": log_type}
    if direction:
        payload["direction"] = direction
    socketio.emit("autonomous_log", payload)

def _emit_auto_cmd_response(text: str):
    """Send a response to the autonomous command chatbox."""
    socketio.emit("autonomous_cmd_response", {
        "text": text,
        "timestamp": int(time.time()),
    })

# ── Parse natural language commands ───────────────────────
_DIRECTION_WORDS = {
    "forward": "forward", "ahead": "forward", "straight": "forward", "front": "forward",
    "backward": "backward", "back": "backward", "reverse": "backward",
    "left": "left", "right": "right",
    "stop": "stop", "halt": "stop", "freeze": "stop",
}

def _parse_nav_command(text: str):
    """Parse a natural language navigation command into a mission."""
    text_lower = text.lower().strip()

    # Stop command
    if any(w in text_lower for w in ("stop", "halt", "freeze", "cancel")):
        return {"type": "stop"}

    # Move direction
    for word, direction in _DIRECTION_WORDS.items():
        if word in text_lower and any(w in text_lower for w in ("move", "go", "drive", "تحرك", "روح")):
            # Extract duration if mentioned
            dur = 3
            dur_match = re.search(r'(\d+)\s*(second|sec|s\b)', text_lower)
            if dur_match:
                dur = min(int(dur_match.group(1)), 30)
            return {"type": "move_direction", "direction": direction, "duration": dur}

    # Find object
    find_match = re.search(r'(?:find|search\s+for|look\s+for|locate|ابحث|اعثر|دور)\s+(?:a |an |the )?(.+)', text_lower)
    if find_match:
        target = find_match.group(1).strip().rstrip('.!?')
        return {"type": "find_object", "target": target}

    # Go to remembered location
    goto_match = re.search(r'(?:go to|navigate to|take me to|go back to|روح)\s+(?:the )?(.+)', text_lower)
    if goto_match:
        target = goto_match.group(1).strip().rstrip('.!?')
        return {"type": "go_to_remembered", "target": target}

    # Explore
    if any(w in text_lower for w in ("explore", "wander", "patrol", "map", "survey", "استكشف")):
        return {"type": "explore"}

    # Default: treat as explore
    return {"type": "explore"}


# ── Socket Events ─────────────────────────────────────────

@socketio.on("autonomous_mode")
def handle_autonomous_mode(data):
    """Toggle autonomous navigation mode.
    Payload: { "enabled": true/false }
    """
    global _auto_nav_active, _auto_nav_thread
    enabled = data.get("enabled", False)

    with _auto_nav_lock:
        if enabled and not _auto_nav_active:
            _auto_nav_active = True
            _auto_nav_thread = _threading.Thread(
                target=_auto_nav_loop, daemon=True
            )
            _auto_nav_thread.start()
            print("[AutoNav] ✅ Enabled by client")
            emit("autonomous_status", {"active": True}, broadcast=True)

        elif not enabled and _auto_nav_active:
            _auto_nav_active = False
            _clear_mission()
            print("[AutoNav] 🔴 Disabled by client")
            emit("autonomous_status", {"active": False}, broadcast=True)
            _send_esp32_move("stop")

        else:
            emit("autonomous_status", {"active": _auto_nav_active})


@socketio.on("autonomous_command")
def handle_autonomous_command(data):
    """Receive a text command for autonomous navigation.
    Payload: { "text": "find a box" }
    """
    text = (data.get("text") or "").strip()
    if not text:
        return

    _emit_auto_cmd_response(f"📝 Command received: {text}")
    parsed = _parse_nav_command(text)
    cmd_type = parsed["type"]

    if cmd_type == "stop":
        _send_esp32_move("stop")
        _clear_mission()
        _emit_auto_log("⏹ STOP command received", "warn", direction="stop")
        _emit_auto_cmd_response("⏹ Stopped. Awaiting new commands.")
        return

    if cmd_type == "move_direction":
        direction = parsed["direction"]
        duration = parsed.get("duration", 3)
        _set_mission("move_direction", direction=direction, duration=duration)
        _emit_auto_log(f"➡️ Moving {direction} for {duration}s", "info", direction=direction)
        _emit_auto_cmd_response(f"Moving {direction} for {duration} seconds…")
        # Auto-enable if not active
        _ensure_auto_nav_running()
        return

    if cmd_type == "find_object":
        target = parsed["target"]
        yolo_status = "YOLO+Vision" if _yolo_model else "Vision LLM only"
        _set_mission("find_object", target=target)
        _emit_auto_log(f"🔍 Searching for: {target} ({yolo_status})", "info")
        _emit_auto_cmd_response(f"🔍 Searching for \"{target}\" using {yolo_status}…")
        _ensure_auto_nav_running()
        return

    if cmd_type == "go_to_remembered":
        target = parsed["target"]
        if spatial_engine and spatial_engine.is_available():
            memories = spatial_engine.recall_as_context(target)
            if memories:
                _set_mission("search_by_landmarks", target=target, memory_context=memories)
                _emit_auto_log(f"🧭 Navigating to remembered: {target}", "info")
                _emit_auto_cmd_response(f"🧭 I remember seeing \"{target}\". Navigating using landmarks…")
                _ensure_auto_nav_running()
                return
            else:
                _emit_auto_cmd_response(f"🤷 I don't remember seeing \"{target}\". I'll explore to find it.")
                _set_mission("find_object", target=target)
                _ensure_auto_nav_running()
                return
        else:
            _emit_auto_cmd_response(f"🧠 Spatial memory not available. Searching directly…")
            _set_mission("find_object", target=target)
            _ensure_auto_nav_running()
            return

    # Default: explore
    _set_mission("explore")
    _emit_auto_log("🏠 Explore mode activated", "info")
    _emit_auto_cmd_response("🏠 Exploring the area. I'll remember what I see.")
    _ensure_auto_nav_running()


def _ensure_auto_nav_running():
    """Start the nav loop if not already running."""
    global _auto_nav_active, _auto_nav_thread
    with _auto_nav_lock:
        if not _auto_nav_active:
            _auto_nav_active = True
            _auto_nav_thread = _threading.Thread(target=_auto_nav_loop, daemon=True)
            _auto_nav_thread.start()
            socketio.emit("autonomous_status", {"active": True})


@socketio.on("autonomous_whisper")
def handle_autonomous_whisper(data):
    """Receive audio from the command chatbox mic, transcribe via Whisper.
    Payload: { "audio": "<base64 webm>" }
    """
    audio_b64 = data.get("audio")
    if not audio_b64:
        return

    audio_bytes = base64.b64decode(audio_b64)
    raw_tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    raw_path, wav_path = raw_tmp.name, wav_tmp.name
    raw_tmp.close(); wav_tmp.close()

    try:
        with open(raw_path, "wb") as f:
            f.write(audio_bytes)
        subprocess.run(
            [FFMPEG_PATH, "-y", "-i", raw_path,
             "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-f", "wav", wav_path],
            capture_output=True, timeout=15,
        )
        with open(wav_path, "rb") as f:
            wr = requests.post(
                WHISPER_URL,
                files={"file": ("audio.wav", f, "audio/wav")},
                data=_whisper_data(),
                timeout=WHISPER_TIMEOUT,
            )
        transcript = ""
        if wr.ok:
            transcript = wr.json().get("text", "").strip()

        if transcript:
            _emit_auto_cmd_response(f"🎤 \"{transcript}\"")
            # Re-dispatch as text command
            handle_autonomous_command({"text": transcript})
        else:
            _emit_auto_cmd_response("🎤 Couldn't hear that. Try again.")
    except Exception as e:
        print(f"[AutoNav-Whisper] Error: {e}")
        _emit_auto_cmd_response("⚠ Voice processing error.")
    finally:
        for p in (raw_path, wav_path):
            try:
                os.remove(p)
            except OSError:
                pass


@socketio.on("get_spatial_memories")
def handle_get_spatial_memories():
    """Return stored spatial memories for the UI."""
    if not spatial_engine or not spatial_engine.is_available():
        emit("spatial_memories", {"ok": False, "memories": [], "count": 0})
        return
    memories = spatial_engine.get_all_memories(limit=50)
    emit("spatial_memories", {
        "ok": True,
        "memories": memories,
        "count": spatial_engine.count(),
    })


@socketio.on("clear_spatial_memory")
def handle_clear_spatial_memory():
    """Wipe all spatial memories."""
    if spatial_engine:
        spatial_engine.clear_memory()
        emit("spatial_memories", {"ok": True, "memories": [], "count": 0})
        _emit_auto_log("🧹 Spatial memory cleared", "warn")
        _emit_auto_cmd_response("🧹 All spatial memories have been cleared.")
    else:
        emit("spatial_memories", {"ok": False, "memories": [], "count": 0})



# ==========================================
# GAME SOCKET EVENTS
# ==========================================
@socketio.on("launch_game")
def handle_launch_game(data):
    """Forward game launch command to robot face (and all clients)."""
    game = data.get("game", "face")
    print(f"[Game] launch_game: {game}")
    emit("launch_game", {"game": game}, broadcast=True, include_self=False)

@socketio.on("game_signal")
def handle_game_signal(data):
    """
    Relay game control signals (start/jump/move) from the Control
    Station to the Robot Face, which forwards them into the game iframe via postMessage.
    """
    action = data.get("action", "")
    game   = data.get("game", "")
    print(f"[GameSignal] action={action} game={game}")
    emit("game_signal", {"action": action, "game": game}, broadcast=True, include_self=False)

@socketio.on("music_cmd")
def handle_music_cmd(data):
    """
    Relay music control commands (next/prev/toggle_mute) from any client
    to the Robot Face, which is the sole audio player.
    """
    cmd = data.get("cmd", "")
    print(f"[MusicCmd] cmd={cmd}")
    emit("music_cmd", {"cmd": cmd}, broadcast=True, include_self=False)

# ==========================================
# GAME MENU
# ==========================================
@socketio.on("open_game_menu")
def handle_open_game_menu():
    emit("open_game_menu", {}, broadcast=True, include_self=False)

@socketio.on("robot_customize")
def handle_robot_customize(data):
    """Forward face customization to robot face.
    Handles: { hue, theme } and { customFace: { slot, dataUrl } } and { clearFace: true }
    Note: customFace.dataUrl can be large (base64 image) — SocketIO default max is 1MB.
    """
    emit("robot_customize", data, broadcast=True, include_self=False)

# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    local_ip = get_local_ip()
    print("\n" + "═" * 60)
    print("  ◆  ARIA NEXUS — Unified Command Center  [v1.0.0]")
    print("═" * 60)
    print(f"  Dashboard : https://{local_ip}:{FLASK_PORT}/nexus/")
    print(f"  LLM       : temp={LLM_TEMPERATURE} top_p={LLM_TOP_P} "
          f"repeat_pen={LLM_REPEAT_PENALTY}")
    print(f"  History   : last {LLM_HISTORY_TURNS} messages")
    print("═" * 60 + "\n")

    # Start Piper immediately so the model is in RAM before the first request
    _threading.Thread(target=_piper_warmup, daemon=True).start()

    # Warm the LLM + Whisper (sequentially) so the FIRST chat/voice request is
    # fast instead of paying the slow cold-start lag. Runs in the background so
    # the server still comes up instantly.
    _threading.Thread(target=_models_warmup, daemon=True).start()

    # Start IoT WebSocket listener for real-time state updates
    if iot_controller:
        def _ha_state_callback(entity_id, new_state):
            """Forward HA state changes to all connected browser clients."""
            attrs = new_state.get("attributes", {})
            domain = entity_id.split(".")[0] if "." in entity_id else ""
            if domain in HAController.UI_DOMAINS:
                socketio.emit("iot_state_changed", {
                    "entity_id": entity_id,
                    "state":     new_state.get("state", "unknown"),
                    "name":      attrs.get("friendly_name", entity_id),
                    "attributes": attrs,
                })
        iot_controller._on_state_changed = _ha_state_callback
        iot_controller.start_ws_subscription()

    # certs/ sits at project root (one level above backend/)
    _cert_dir = os.path.join(_PROJECT_ROOT, "certs")
    _cert_file = os.path.join(_cert_dir, "cert.pem")
    _key_file = os.path.join(_cert_dir, "key.pem")

    if os.path.exists(_cert_file) and os.path.exists(_key_file):
        _ssl_ctx = (_cert_file, _key_file)
    else:
        print("[SSL] ⚠ certs/cert.pem not found — falling back to adhoc SSL")
        _ssl_ctx = "adhoc"

    # Suppress harmless werkzeug "write() before start_response" assertion
    # that fires when a client disconnects mid-response over SSL.
    import logging as _logging
    _wz_log = _logging.getLogger('werkzeug')
    _wz_log.setLevel(_logging.ERROR)

    socketio.run(
        app,
        host=FLASK_HOST,
        port=FLASK_PORT,
        ssl_context=_ssl_ctx,
        debug=False,
        allow_unsafe_werkzeug=True,
    )