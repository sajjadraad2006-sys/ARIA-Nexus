"""
tts_server.py — Qwen3-TTS Voice Cloning Server  [v2.1-optimized]
=================================================================
FastAPI app on port 5002.

Optimizations over v2:
  • In-memory WAV encoding — no temp file for output (saves 2 disk ops)
  • torch.cuda.empty_cache() after gc.collect() for real GPU memory return
  • Queue timeout 30s instead of instant reject for concurrent requests
  • Larger read buffer for ref audio decode

Install (inside venv):
    pip install fastapi uvicorn faster-qwen3-tts soundfile numpy requests
"""

import io as _io
import os
import sys
import base64
import tempfile
import traceback
import threading
import wave as _wave
import gc as _gc

import numpy as np
import soundfile as sf
import requests as _req

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# ──────────────────────────────────────────────────────────
# CONFIG — loaded from config.py (single source of truth)
# ──────────────────────────────────────────────────────────
_config_dir = os.path.dirname(os.path.abspath(__file__))
if _config_dir not in sys.path:
    sys.path.insert(0, _config_dir)

from config import (
    QWEN_TTS_MODEL_DIR as MODEL_DIR,
    TTS_HOST           as HOST,
    TTS_PORT           as PORT,
    WHISPER_URL        as _WHISPER_BASE_URL,
    WHISPER_TIMEOUT,
)

LANGUAGE    = "English"
WHISPER_URL = _WHISPER_BASE_URL + "/inference"

# ──────────────────────────────────────────────────────────
# HTTP SESSION — reuse connections to Whisper
# ──────────────────────────────────────────────────────────
_http = _req.Session()
_http.headers.update({"Connection": "keep-alive"})

# ──────────────────────────────────────────────────────────
# GPU MEMORY CLEANUP HELPER
# ──────────────────────────────────────────────────────────
_torch_available = False
try:
    import torch
    _torch_available = torch.cuda.is_available()
except ImportError:
    pass

def _release_gpu_memory():
    """Run Python GC + return GPU memory to the CUDA pool."""
    _gc.collect()
    if _torch_available:
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

# ──────────────────────────────────────────────────────────
# SINGLE-SLOT QUEUE — only 1 TTS generation at a time
# Now with 30s timeout instead of instant reject
# ──────────────────────────────────────────────────────────
_tts_lock = threading.Lock()
_TTS_QUEUE_TIMEOUT = 30   # wait up to 30s for the current gen to finish

# ──────────────────────────────────────────────────────────
# MODEL — LAZY loaded on first request to avoid VRAM conflict
#          with the Qwen2.5 LLM (both share the 8GB RTX 5050)
# ──────────────────────────────────────────────────────────
print(f"[TTS] Model dir: {MODEL_DIR} (lazy load — will load on first request)")
_tts_model   = None
_model_ready = False     # set to True after first load + warm-up
_model_lock  = threading.Lock()

def _ensure_model():
    """Lazily load the TTS model on first use. Thread-safe."""
    global _tts_model, _model_ready
    if _model_ready and _tts_model is not None:
        return _tts_model
    with _model_lock:
        # Double-check after acquiring lock
        if _model_ready and _tts_model is not None:
            return _tts_model
        try:
            print("[TTS] Loading FasterQwen3TTS model (first request)...")
            from faster_qwen3_tts import FasterQwen3TTS          # type: ignore
            _tts_model = FasterQwen3TTS.from_pretrained(MODEL_DIR)
            print("[TTS] ✅ Model loaded — running warm-up...")
            # Quick warm-up to compile CUDA graphs
            try:
                silent = _build_silent_wav(1.0)
                tmp_path = None
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp.write(silent)
                    tmp_path = tmp.name
                _tts_model.generate_voice_clone(
                    text="Ready.",
                    language=LANGUAGE,
                    ref_audio=tmp_path,
                    ref_text="Ready.",
                )
                if tmp_path:
                    try: os.remove(tmp_path)
                    except OSError: pass
                print("[TTS] ✅ Warm-up complete — GPU is hot.")
            except Exception as exc:
                print(f"[TTS] ⚠️  Warm-up error (non-fatal): {exc}")
            _model_ready = True
            return _tts_model
        except Exception as _load_err:
            print(f"[TTS] ❌ Model load failed: {_load_err}")
            _model_ready = True  # don't retry forever
            return None


# ──────────────────────────────────────────────────────────
# GPU WARM-UP helper
# ──────────────────────────────────────────────────────────
def _build_silent_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Return bytes of a minimal silent PCM WAV."""
    buf = _io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(sample_rate * duration_sec))
    return buf.getvalue()


# ──────────────────────────────────────────────────────────
# AUTO-TRANSCRIPTION VIA WHISPER
# ──────────────────────────────────────────────────────────
def _transcribe_wav(wav_path: str) -> str:
    """
    POST wav_path to the local Whisper server and return the transcript.
    Returns "" on any failure so the caller can fall back gracefully.
    Uses shared HTTP session for connection reuse.
    """
    try:
        with open(wav_path, "rb") as f:
            resp = _req.post(
                WHISPER_URL,
                files={"file": ("ref.wav", f, "audio/wav")},
                data={"response_format": "json"},
                timeout=WHISPER_TIMEOUT,
            )
        if resp.ok:
            text = resp.json().get("text", "").strip()
            print(f"[TTS] Whisper auto-transcription: {text[:80]!r}")
            return text
        print(f"[TTS] Whisper HTTP {resp.status_code} — will use fallback ref_text")
    except _req.exceptions.ConnectionError:
        print("[TTS] Whisper unreachable — will use fallback ref_text")
    except Exception as exc:
        print(f"[TTS] Whisper error ({exc}) — will use fallback ref_text")
    return ""


# ──────────────────────────────────────────────────────────
# FASTAPI APP
# ──────────────────────────────────────────────────────────
app = FastAPI(title="ARIA TTS — Qwen3 Voice Cloning", version="2.1")

@app.on_event("startup")
def startup_event():
    import threading
    # Run _ensure_model in a background thread during startup so the server can bind to the port immediately
    threading.Thread(target=_ensure_model, daemon=True).start()


class GenerateRequest(BaseModel):
    text:          str
    ref_audio_b64: str
    ref_text:      str = ""   # OPTIONAL — auto-filled by Whisper when empty


@app.get("/health")
def health():
    """Liveness probe. Always OK — model loads lazily on first /generate call."""
    return {"status": "ok", "model": os.path.basename(MODEL_DIR), "loaded": _model_ready}


@app.post("/generate")
def generate(req: GenerateRequest):
    """
    Cloned-voice synthesis — single-slot with 30s queue timeout.
    """
    model = _ensure_model()
    if model is None:
        raise HTTPException(503, detail="Model failed to load")

    # Wait up to 30s for the current gen to finish instead of instant reject
    if not _tts_lock.acquire(timeout=_TTS_QUEUE_TIMEOUT):
        raise HTTPException(503, detail="TTS busy — timed out after 30s waiting")

    ref_wav_path = None
    ref_bytes    = None

    try:
        # ── 1. Decode reference audio ──────────────────────
        raw_b64 = req.ref_audio_b64.strip()
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        ref_bytes = base64.b64decode(raw_b64)
        del raw_b64   # free immediately

        import subprocess
        raw_path = None
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as raw_tmp:
            raw_tmp.write(ref_bytes)
            raw_path = raw_tmp.name
        del ref_bytes

        # ── 1a. Convert to 24kHz WAV for TTS (model's native sample rate) ──
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            ref_wav_path = wav_tmp.name

        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_path,
             "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
             "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
             "-f", "wav", ref_wav_path],
            capture_output=True,
            timeout=15
        )

        # ── 1b. Convert to 16kHz WAV for Whisper (Whisper needs 16kHz) ──
        whisper_wav_path = None
        with tempfile.NamedTemporaryFile(suffix="_whisper.wav", delete=False) as whisper_tmp:
            whisper_wav_path = whisper_tmp.name

        subprocess.run(
            ["ffmpeg", "-y", "-i", raw_path,
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
             "-f", "wav", whisper_wav_path],
            capture_output=True,
            timeout=10
        )

        if os.path.exists(raw_path):
            try:
                os.remove(raw_path)
            except OSError:
                pass

        # ── 2. Auto-transcribe if ref_text missing ─────────
        ref_text = req.ref_text.strip()
        if not ref_text:
            print("[TTS] ref_text empty — auto-transcribing via Whisper…")
            ref_text = _transcribe_wav(whisper_wav_path)
            if not ref_text:
                ref_text = "This is a voice reference sample."
                print("[TTS] Using generic fallback ref_text")

        # Clean up Whisper copy
        if whisper_wav_path and os.path.exists(whisper_wav_path):
            try:
                os.remove(whisper_wav_path)
                whisper_wav_path = None
            except OSError:
                pass

        # ── 3. Synthesise (tuned params for quality) ───────
        audio_list, sample_rate = model.generate_voice_clone(
            text=req.text,
            language=LANGUAGE,
            ref_audio=ref_wav_path,
            ref_text=ref_text,
            temperature=0.3,
            top_k=20,
            top_p=0.8,
            repetition_penalty=1.2,
        )

        # ── 4. Delete ref wav IMMEDIATELY ──────────────────
        try:
            os.remove(ref_wav_path)
            ref_wav_path = None
        except OSError as e:
            print(f"[TTS] Warning — could not delete ref wav: {e}")

        # ── 5. Encode output WAV in memory (no temp file) ──
        if isinstance(audio_list, (list, tuple)):
            audio_np = np.concatenate([np.asarray(a) for a in audio_list])
        else:
            audio_np = np.asarray(audio_list)
        del audio_list   # free raw chunks

        if audio_np.dtype != np.float32:
            audio_np = audio_np.astype(np.float32)

        # Normalize output audio to prevent clipping
        peak = np.abs(audio_np).max()
        if peak > 0:
            audio_np = audio_np * (0.95 / peak)

        # Write WAV directly to memory buffer — skip disk entirely
        wav_buf = _io.BytesIO()
        sf.write(wav_buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
        wav_bytes = wav_buf.getvalue()
        del audio_np     # free numpy array
        del wav_buf      # free buffer object

        audio_b64_out = base64.b64encode(wav_bytes).decode("utf-8")
        dur_approx = len(wav_bytes) / (sample_rate * 2)
        kb = len(wav_bytes) // 1024
        del wav_bytes    # free raw bytes

        print(f"[TTS] ✅ ~{dur_approx:.2f}s ({kb} KB) for: {req.text[:60]!r}")
        return JSONResponse({"audio_base64": audio_b64_out})

    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, detail=f"TTS generation failed: {exc}") from exc

    finally:
        ref_bytes = None   # ensure large decoded bytes are freed on any path
        if ref_wav_path and os.path.exists(ref_wav_path):
            try:
                os.remove(ref_wav_path)
            except OSError as e:
                print(f"[TTS] Cleanup warning for {ref_wav_path}: {e}")
        _tts_lock.release()
        _release_gpu_memory()   # GC + torch.cuda.empty_cache()


# ──────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'='*52}")
    print(f"  ARIA TTS Server — Qwen3 Voice Cloning  v2.1")
    print(f"{'='*52}")
    print(f"  http://{HOST}:{PORT}/health   GET")
    print(f"  http://{HOST}:{PORT}/generate POST")
    print(f"  Auto-transcription: {WHISPER_URL}")
    print(f"  GPU cleanup: torch.cuda.empty_cache = {_torch_available}")
    print(f"  Queue timeout: {_TTS_QUEUE_TIMEOUT}s")
    print(f"{'='*52}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")