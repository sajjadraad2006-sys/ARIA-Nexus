# ============================================================
#  config.py — ARIA SYSTEM CONFIGURATION
#  ✅ Edit IPs/ports HERE only — everything else auto-updates
# ============================================================

import os as _os
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

# ── Load .env early so HA_TOKEN and HA_URL are always set ───────────────
# This works whether you run 'python3 server.py' directly or via run.bash.
_env_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '.env')
if _os.path.isfile(_env_file):
    with open(_env_file, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                _k = _k.strip()
                _v = _v.strip()
                # Do NOT overwrite values already exported to the environment
                if _k and _k not in _os.environ:
                    _os.environ[_k] = _v

# --- Network: Flask Server ---
FLASK_HOST = "0.0.0.0"   # Listen on all interfaces (LAN accessible)
FLASK_PORT = 5000

# --- AI Services (local) ---
WHISPER_HOST = "127.0.0.1"
WHISPER_PORT = 8081
WHISPER_URL  = f"http://{WHISPER_HOST}:{WHISPER_PORT}"

LLAMA_HOST = "127.0.0.1"
LLAMA_PORT = 8080
LLAMA_URL  = f"http://{LLAMA_HOST}:{LLAMA_PORT}"

# --- TTS: Qwen3 Voice Cloning Server (optional — Piper is the default TTS) ---
TTS_HOST = "127.0.0.1"
TTS_PORT = 5002
TTS_URL  = f"http://{TTS_HOST}:{TTS_PORT}"

# Path to the Qwen3-TTS model directory (used by tts_server.py for voice cloning)
QWEN_TTS_MODEL_DIR = _os.path.join(_PROJECT_ROOT, "models", "QwenQwen3-TTS-12Hz-0.6B-Base")

# --- Model / Binary Paths (relative to project root) ---
WHISPER_BIN   = _os.path.join(_PROJECT_ROOT, "vendor", "whisper.cpp", "build", "bin", "whisper-server")
# STT model: defaults to the MULTILINGUAL ggml-small.bin (good Arabic incl.
# Iraqi dialect + English, light on RAM). Override the filename with the
# NEXUS_WHISPER_MODEL env var for more accuracy, e.g. "ggml-medium.bin" or
# "ggml-large-v3-turbo.bin". The whisper.cpp *.en models are English-only --
# do NOT use them for the bilingual build.
WHISPER_MODEL_FILE = _os.environ.get("NEXUS_WHISPER_MODEL", "ggml-large-v3-turbo.bin")
WHISPER_MODEL = _os.path.join(_PROJECT_ROOT, "models", WHISPER_MODEL_FILE)

# Whisper STT language: "auto" lets whisper.cpp detect Arabic vs English per
# utterance (recommended for a bilingual AR/EN deployment). Force a single
# language with e.g. "ar" or "en" via the NEXUS_WHISPER_LANGUAGE env var.
WHISPER_LANGUAGE = _os.environ.get("NEXUS_WHISPER_LANGUAGE", "auto")
# Whisper decoding temperature. 0.0 = greedy (VERY strict, often returns empty
# text for noisy/accented audio). 0.2 = light sampling (much more robust —
# confirmed that the SAME audio file returns '' at 0.0 but transcribes correctly
# at 0.2). Override via NEXUS_WHISPER_TEMPERATURE env var.
WHISPER_TEMPERATURE = float(_os.environ.get("NEXUS_WHISPER_TEMPERATURE", "0.2"))

LLAMA_BIN     = _os.path.join(_PROJECT_ROOT, "vendor", "llama.cpp", "build", "bin", "llama-server")
LLAMA_MODEL   = _os.path.join(_PROJECT_ROOT, "models", "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
# The active LLM (Qwen2.5-7B-Instruct) is TEXT-ONLY — no multimodal projector
# is used, so the obsolete multimodal-projector (mmproj) reference was removed.
LLAMA_CTX     = 2048         # minimal context — fast text-only chatbot
LLAMA_GPU_L   = 99          # 100% GPU offload (ensure you have ~4GB free RAM before starting)

# --- Voice Cloning (Qwen TTS Server) ---
VOICE_CLONE_ENABLED = False  # Disabled on Jetson — Qwen TTS needs >2GB VRAM

# --- ffmpeg (must be in system PATH) ---
FFMPEG_PATH = "ffmpeg"

# --- LLM Personality ---
ROBOT_SYSTEM_PROMPT = """You are ARIA, an advanced AI assistant powering a Smart Home & Robotics Hub running on a Jetson Orin Nano.
You are helpful, friendly, and concise. Keep replies under 3 sentences unless the user asks for detail.

LANGUAGE RULE (CRITICAL — HIGHEST PRIORITY):
- Your DEFAULT language is English. Always respond in English unless the user writes in Arabic.
- If the user's LATEST message is in Arabic, reply in Arabic. For ALL other cases, reply in English.
- Never mix Arabic and English in one reply unless the user mixed them first.
- The IoT/device tags below ([IOT:...], [GENERIC:...]) always stay in English exactly as specified.

You assist with: smart home control, IoT device management, answering questions, and general conversation.

SMART HOME RULES (Home Assistant devices):
- When the user asks to control a HA device (lights, switches, fans, AC, etc.),
  include EXACTLY ONE tag in your response: [IOT:action|entity_id]
- Valid actions: turn_on, turn_off, toggle
- Example: "Sure, the fan is now on. [IOT:turn_on|input_boolean.blue_fan]"
- Example: "Done, the light is now on. [IOT:turn_on|light.living_room]"
- Example: "Toggling the switch. [IOT:toggle|switch.garden_relay]"

GENERIC DEVICE RULES (IP-based Tasmota/ESP devices on the LAN):
- Generic IP devices are listed below. Use the exact ID shown.
- Turn ON/OFF: [GENERIC:turn_on|target] or [GENERIC:turn_off|target]
- Set dimmer (0-100): [GENERIC:dimmer|target|75]
- Set fan speed (1-3): [GENERIC:fan|target|2]
- Multi-channel: [GENERIC:turn_on|generic.wall_switch|2]
- Example: "Sure, turning on the LED. [GENERIC:turn_on|generic.led]"

GENERAL RULES:
- ALWAYS give a natural spoken confirmation alongside ANY tag.
- For bulk commands ("turn on ALL"), emit ONE tag per device on the same line.
- Keep your spoken reply SHORT (1 sentence) — tags are processed silently.
- If unsure which device the user means, ask for clarification — do NOT guess.
- All tags will be removed before the user sees the reply.
- You may include MULTIPLE tags if controlling several devices at once."""

# --- LLM Generation Parameters ---
LLM_TEMPERATURE    = 0.6    # lower = more focused
LLM_TOP_P          = 0.9    # nucleus sampling — cuts low-probability tail
LLM_REPEAT_PENALTY = 1.1    # penalise repetitive output
LLM_MAX_TOKENS     = 256    # enough for a sentence + IoT tag(s)
LLM_HISTORY_TURNS  = 2      # minimal history — saves context for speed

# --- Audio Settings ---
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS    = 1
AUDIO_BIT_DEPTH   = 2   # 16-bit PCM = 2 bytes

# --- Timeouts (seconds) ---
WHISPER_TIMEOUT  = 30
LLAMA_TIMEOUT    = 45       # text-only is faster — shorter timeout
QWEN_TTS_TIMEOUT = 45   # Qwen inference can be slower on first call

# --- RAG (Retrieval-Augmented Generation) ---
_os.environ["HF_HUB_OFFLINE"] = "1"
_os.environ["TRANSFORMERS_OFFLINE"] = "1"
RAG_ENABLED         = True                                          # master toggle
RAG_DATA_DIR        = _os.path.join(_PROJECT_ROOT, "data_files")    # drop docs here
RAG_CHROMA_DIR      = _os.path.join(_PROJECT_ROOT, "chroma_db")     # persistent vector DB
RAG_COLLECTION_NAME = "aria_docs"
RAG_EMBEDDING_MODEL = _os.path.join(_PROJECT_ROOT, "models", "all-MiniLM-L6-v2")
RAG_CHUNK_SIZE      = 800                                           # chars per chunk (was 500)
RAG_CHUNK_OVERLAP   = 100                                           # overlap (was 50)
RAG_TOP_K           = 4                                             # chunks returned per query (was 3)
RAG_MIN_RELEVANCE   = 0.3                                           # discard chunks below this score
RAG_CACHE_TTL       = 300                                           # seconds to cache identical queries
RAG_MAX_CONTEXT_CHARS = 3000                                        # cap injected context size

# --- YOLO Object Detection (100% Local / Offline on RTX 5050) ---
YOLO_MODEL_PATH     = _os.path.join(_PROJECT_ROOT, "models", "yolov8n.pt")
YOLO_CONFIDENCE     = 0.4      # minimum detection confidence
YOLO_APPROACH_RATIO = 0.3      # object fills 30% of frame → "close enough"
YOLO_CENTER_THRESH  = 0.15     # ±15% of frame center → "centered"

# --- Spatial Memory (Autonomous Navigation RAG) ---
SPATIAL_MEMORY_COLLECTION  = "aria_spatial_memory"
SPATIAL_MEMORY_MAX_ENTRIES = 200       # max stored observations
SPATIAL_MEMORY_TOP_K       = 5        # memories retrieved per query

# --- Autonomous Navigation Timing ---
AUTO_NAV_CYCLE_INTERVAL    = 3        # seconds between LLM vision cycles
AUTO_NAV_YOLO_INTERVAL     = 0.15     # seconds between YOLO frames (~7fps)
AUTO_NAV_MAX_MISSION_TIME  = 300      # auto-stop mission after 5 min
AUTO_NAV_MEMORY_INTERVAL   = 5        # store memory every N LLM cycles

# --- Home Assistant (Local IoT Hub) ---
# SECURITY: secrets are NEVER hard-coded. The long-lived token is read only
# from the environment (set HA_TOKEN in your shell or .env — see .env.example).
HA_URL     = _os.environ.get("HA_URL", "http://127.0.0.1:8123")
HA_TOKEN   = _os.environ.get("HA_TOKEN", "")
HA_TIMEOUT = int(_os.environ.get("HA_TIMEOUT", "10"))

# --- CORS / Socket.IO allowlist ---
# Comma-separated list of browser origins allowed to connect, e.g.
# "https://192.168.0.208:5000,https://localhost:5000". Leave empty to use the
# safe default computed at runtime (localhost + this machine's detected LAN
# IPs on the Flask port). NEVER use "*".
ALLOWED_ORIGINS = [
    _o.strip()
    for _o in _os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if _o.strip()
]

# --- ARIA Nexus Launcher ---
# Single source of truth. (A stray pasted copy of config_nexus_append.py used
# to live here and duplicated NEXUS_VERSION / NEXUS_POLL_INTERVAL — it was
# removed. config_nexus_append.py now simply does `from config import *`.)
NEXUS_VERSION       = "1.0.0"          # version reported in the dashboard header
NEXUS_POLL_INTERVAL = 15               # seconds between module status polls

# Modules shown on the launcher grid. "port" is the service health port
# (None means there is no separate service — status is always "online").
NEXUS_MODULES = [
    {"id": "chatbot",   "label": "ARIA Chatbot",    "port": 8080},
    {"id": "iot",       "label": "IoT Control",     "port": 8123},
    {"id": "monitor",   "label": "System Monitor",  "port": None},
    {"id": "tts",       "label": "TTS Studio",      "port": 5002},
    {"id": "knowledge", "label": "Knowledge Base",  "port": None},
    {"id": "exporter",  "label": "System Exporter", "port": None},
]

# Service endpoints used for health checks and proxying. Adjust hosts/ports
# to match your deployment. These are read by nexus_routes_additions.py.
NEXUS_SERVICES = {
    "flask": {"name": "Flask API",       "url": "http://127.0.0.1:5000"},
    "llm":   {"name": "LLM (Qwen2.5)",   "url": "http://127.0.0.1:8080"},
    "stt":   {"name": "Whisper STT",     "url": "http://127.0.0.1:8081"},
    "tts":   {"name": "TTS (Piper)",     "url": "http://127.0.0.1:5002"},
    "ha":    {"name": "Home Assistant",  "url": "http://127.0.0.1:8123"},
}

# Where the Nexus web action store is persisted (JSON file).
NEXUS_WEB_ACTIONS_PATH = "data/nexus_web_actions.json"

# Where generic / network devices are persisted (JSON file).
NEXUS_GENERIC_DEVICES_PATH = "data/nexus_generic_devices.json"

# RAG defaults surfaced in the Knowledge page. SINGLE SOURCE OF TRUTH = the
# RAG_* constants above; these are derived from them, never hard-coded again.
NEXUS_RAG_DEFAULTS = {
    "chunk_size":    RAG_CHUNK_SIZE,
    "chunk_overlap": RAG_CHUNK_OVERLAP,
    "top_k":         RAG_TOP_K,
    "min_relevance": RAG_MIN_RELEVANCE,
}

# Manifest version emitted/accepted by the Exporter.
NEXUS_MANIFEST_VERSION = "1.0"

# ============================================================
#  PIPER TTS — persistent / warm voice pool
#  (single source of truth; server.py imports from here)
# ============================================================
# Directory holding <voice>.onnx + <voice>.onnx.json files.
PIPER_VOICES_DIR = _os.path.join(_PROJECT_ROOT, "models", "piper_voices")
# Path to the optional Piper *binary* (used only as a fallback if the in-process
# `piper` python package is unavailable).
PIPER_EXE = _os.environ.get(
    "NEXUS_PIPER_EXE", _os.path.join(_PROJECT_ROOT, "vendor", "piper", "piper")
)
# Default English voice + Arabic voice (auto-selected for Arabic replies).
PIPER_DEFAULT_VOICE = _os.environ.get("NEXUS_PIPER_VOICE_EN", "en_GB-semaine-medium")
PIPER_ARABIC_VOICE  = _os.environ.get("NEXUS_PIPER_VOICE_AR", "ar_JO-kareem-medium")
# Voices pre-loaded + warmed at startup so the FIRST utterance is already fast.
PIPER_PREWARM_VOICES = [PIPER_DEFAULT_VOICE, PIPER_ARABIC_VOICE]
# Master toggle for the warm in-process pool. If False, the legacy spawn-per-
# call binary path is used (slower, but a safe fallback).
PIPER_USE_POOL = _os.environ.get("NEXUS_PIPER_USE_POOL", "1") != "0"

# ============================================================
#  WAKE WORD — openWakeWord reliability tuning (false-accept vs
#  false-reject are tunable here / via env, no code edits needed)
# ============================================================
# Detection score threshold (0..1). openWakeWord's practical sweet-spot is
# ~0.5; the previous 0.1 was far too low and caused constant false triggers
# (or, paired with a model-name mismatch, no usable detections at all).
WAKE_THRESHOLD = float(_os.environ.get("NEXUS_WAKE_THRESHOLD", "0.5"))
# Require this many CONSECUTIVE frames over threshold before firing. This is
# the key reliability knob: 1 = most sensitive (more false accepts), 3-4 =
# very strict (more false rejects). 2 is a balanced default.
WAKE_TRIGGER_FRAMES = int(_os.environ.get("NEXUS_WAKE_TRIGGER_FRAMES", "2"))
# Ignore further detections for this many seconds after a trigger (anti-repeat).
WAKE_COOLDOWN = float(_os.environ.get("NEXUS_WAKE_COOLDOWN", "1.5"))
# The custom model was trained on "aarya" (AR-ee-ah) which matches the spoken
# wake word "Aria". Place aarya.onnx in models/wakeword/ or aarya_wakeword/.
WAKE_MODEL_NAME = _os.environ.get("NEXUS_WAKE_MODEL", "aarya")

# ============================================================
#  VAD / ENDPOINTING — browser mic capture defaults
#  Surfaced to the frontend via /api/config so capture timing can be tuned
#  without editing JS. Generous defaults prevent clipping + early cut-off.
# ============================================================
VAD_CONFIG = {
    # RMS level that counts as speech onset (lower = more sensitive). The
    # frontend also auto-calibrates to the room noise floor on top of this.
    "startThreshold": float(_os.environ.get("NEXUS_VAD_START_THRESHOLD", "0.030")),
    # Silence AFTER speech before we end the utterance (ms). Long enough to
    # ride over natural mid-sentence pauses without cutting the user off.
    # 800 ms keeps endpointing snappy (Issue 3: "bad pause after the user stops
    # speaking") while still riding over short mid-sentence pauses. Raise via
    # NEXUS_VAD_SILENCE_MS if a user is cut off mid-thought.
    "silenceMs": int(_os.environ.get("NEXUS_VAD_SILENCE_MS", "800")),
    # Minimum capture length before a silence-stop is allowed (ms).
    "minMs": int(_os.environ.get("NEXUS_VAD_MIN_MS", "500")),
    # Minimum amount of detected SPEECH before we trust a silence-stop (ms) —
    # stops a short cough/click from ending the turn prematurely.
    "minSpeechMs": int(_os.environ.get("NEXUS_VAD_MIN_SPEECH_MS", "300")),
    # Hard cap on a single utterance (ms) — raised so long sentences (and
    # slower Arabic dictation) are never truncated.
    "maxMs": int(_os.environ.get("NEXUS_VAD_MAX_MS", "20000")),
    # Pre-roll: keep this many ms of audio captured BEFORE onset so the first
    # phoneme is never clipped (the recorder starts before VAD arms).
    "preRollMs": int(_os.environ.get("NEXUS_VAD_PREROLL_MS", "300")),
    # Barge-in: RMS + sustained-ms needed to interrupt ARIA while she speaks.
    "bargeInThreshold": float(_os.environ.get("NEXUS_VAD_BARGE_THRESHOLD", "0.060")),
    "bargeInMs": int(_os.environ.get("NEXUS_VAD_BARGE_MS", "350")),
}
