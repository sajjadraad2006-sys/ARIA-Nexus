#!/usr/bin/env python3
"""
streaming_pipeline.py — Low-Latency Streaming Voice Assistant
=============================================================
Multi-threaded pipeline for Jetson Orin Nano (8GB):

  [Whisper STT] → [llama-cpp-python stream] → [sentence buffer]
                                                     ↓
                                              [Queue (thread-safe)]
                                                     ↓
                                          [Piper TTS → aplay]
                                          (background thread)

Key design decisions:
  • llama-cpp-python runs with CUDA (n_gpu_layers=-1) for full GPU offload
  • Token streaming (stream=True) feeds a sentence buffer in real-time
  • Completed sentences are pushed to a queue.Queue immediately
  • A dedicated TTS worker thread consumes sentences and pipes them
    through Piper → aplay, so audio plays while the LLM keeps generating
  • Audio playback is non-blocking relative to LLM inference

Requirements:
  pip install llama-cpp-python  (built with GGML_CUDA=on)
  pip install faster-whisper    (or use whisper.cpp server)

Usage:
  python3 streaming_pipeline.py

Environment:
  CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --force-reinstall --no-cache-dir
"""

import os
import sys
import re
import queue
import time
import signal
import subprocess
import threading
import tempfile
import readline  # noqa: F401 — enables arrow-key editing in input()

# ──────────────────────────────────────────────────────────────
# PROJECT PATHS — import from config.py (single source of truth)
# ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import (
    LLAMA_MODEL,
    LLAMA_CTX,
    LLAMA_GPU_L,
    ROBOT_SYSTEM_PROMPT,
    LLM_TEMPERATURE,
    LLM_TOP_P,
    LLM_REPEAT_PENALTY,
    LLM_MAX_TOKENS,
    LLM_HISTORY_TURNS,
)

# Piper paths
PIPER_EXE = os.path.join(_PROJECT_ROOT, "vendor", "piper", "piper")
PIPER_VOICES_DIR = os.path.join(_PROJECT_ROOT, "models", "piper_voices")
PIPER_DEFAULT_VOICE = "en_GB-semaine-medium"
PIPER_ARABIC_VOICE = "ar_JO-kareem-medium"

# Audio playback command (aplay for ALSA, paplay for PulseAudio)
AUDIO_PLAYER = "aplay"  # change to "paplay" if using PulseAudio

# Whisper settings (for faster-whisper local mode)
WHISPER_MODEL_SIZE = "small"  # tiny/base/small — tradeoff speed vs accuracy
WHISPER_DEVICE = "cuda"       # "cuda" or "cpu"
WHISPER_COMPUTE = "float16"   # "float16" for GPU, "int8" for CPU

# ──────────────────────────────────────────────────────────────
# SENTENCE BOUNDARY DETECTION
# ──────────────────────────────────────────────────────────────
# Matches: . ! ? \n and Arabic ؟ ، (as sentence-ending punctuation)
_SENTENCE_END_RE = re.compile(r'[.!?\n؟]')

# Arabic detection (for auto voice switching)
def _is_arabic(text: str) -> bool:
    if not text:
        return False
    arabic = sum(1 for c in text if '\u0600' <= c <= '\u06FF' or '\u0750' <= c <= '\u077F')
    return arabic > len(text) * 0.3

def _resolve_voice(voice_name: str) -> tuple:
    """Return (model_path, config_path) for a Piper voice."""
    model = os.path.join(PIPER_VOICES_DIR, f"{voice_name}.onnx")
    config = os.path.join(PIPER_VOICES_DIR, f"{voice_name}.onnx.json")
    if not os.path.exists(model):
        model = os.path.join(PIPER_VOICES_DIR, f"{PIPER_DEFAULT_VOICE}.onnx")
        config = os.path.join(PIPER_VOICES_DIR, f"{PIPER_DEFAULT_VOICE}.onnx.json")
    return model, config

# ──────────────────────────────────────────────────────────────
# STRIP IOT/GENERIC TAGS — so TTS never reads control tags
# ──────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r'\[(IOT|GENERIC):[^\]]*\]')

def _strip_tags(text: str) -> str:
    return _TAG_RE.sub('', text).strip()

# ──────────────────────────────────────────────────────────────
# TTS WORKER — background thread consuming sentence queue
# ──────────────────────────────────────────────────────────────
_tts_queue: queue.Queue = queue.Queue()
_tts_stop = threading.Event()

def _tts_worker():
    """
    Continuously consume sentences from the queue and synthesise + play audio.

    Each sentence is piped into Piper via stdin. Piper writes a WAV to a temp
    file, which is then played by aplay/paplay. This runs in its own thread
    so LLM generation continues unblocked.
    """
    while not _tts_stop.is_set():
        try:
            sentence = _tts_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if sentence is None:  # poison pill — shutdown signal
            break

        sentence = _strip_tags(sentence).strip()
        if not sentence:
            _tts_queue.task_done()
            continue

        # Pick voice based on language
        voice = PIPER_ARABIC_VOICE if _is_arabic(sentence) else PIPER_DEFAULT_VOICE
        model_path, config_path = _resolve_voice(voice)

        out_wav = None
        try:
            # Create temp WAV file for Piper output
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                out_wav = tmp.name

            # Synthesise: pipe sentence into Piper → WAV file
            piper_cmd = [
                PIPER_EXE,
                "--model", model_path,
                "--config", config_path,
                "--output_file", out_wav,
            ]
            t0 = time.monotonic()
            result = subprocess.run(
                piper_cmd,
                input=sentence.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            tts_ms = (time.monotonic() - t0) * 1000

            if result.returncode != 0:
                print(f"\n  [TTS] ⚠ Piper error (rc={result.returncode})")
                _tts_queue.task_done()
                continue

            # Verify WAV is valid (> 44 byte header)
            if not os.path.exists(out_wav) or os.path.getsize(out_wav) <= 44:
                print(f"\n  [TTS] ⚠ Empty WAV output")
                _tts_queue.task_done()
                continue

            # Play audio (blocking within this thread, but non-blocking to LLM)
            play_cmd = [AUDIO_PLAYER, out_wav] if AUDIO_PLAYER == "aplay" else [AUDIO_PLAYER, out_wav]
            subprocess.run(play_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)

            print(f"  [TTS] ✅ {tts_ms:.0f}ms | \"{sentence[:60]}\"")

        except subprocess.TimeoutExpired:
            print(f"\n  [TTS] ⚠ Timeout on: \"{sentence[:40]}\"")
        except Exception as exc:
            print(f"\n  [TTS] ⚠ Error: {exc}")
        finally:
            if out_wav:
                try:
                    os.remove(out_wav)
                except OSError:
                    pass
            _tts_queue.task_done()


# Start TTS worker thread
_tts_thread = threading.Thread(target=_tts_worker, daemon=True, name="tts-worker")
_tts_thread.start()

# ──────────────────────────────────────────────────────────────
# LLM — llama-cpp-python with CUDA
# ──────────────────────────────────────────────────────────────
print("=" * 60)
print("  ARIA Streaming Pipeline — Jetson Orin Nano")
print("=" * 60)

try:
    from llama_cpp import Llama
except ImportError:
    print("\n❌ llama-cpp-python not installed!")
    print("   Install with CUDA support:")
    print("   CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python --force-reinstall --no-cache-dir")
    sys.exit(1)

print(f"\n[LLM] Loading model: {os.path.basename(LLAMA_MODEL)}")
print(f"[LLM] Context: {LLAMA_CTX} | GPU layers: {LLAMA_GPU_L}")

_llm = Llama(
    model_path=LLAMA_MODEL,
    n_ctx=LLAMA_CTX,            # context window (keep small for speed)
    n_gpu_layers=LLAMA_GPU_L,   # -1 or 99 = offload everything to GPU
    n_batch=256,                # batch size for prompt eval
    n_threads=4,                # CPU threads (Orin has 6 A78AE cores)
    verbose=False,              # suppress llama.cpp logs after init
    use_mmap=True,              # memory-map the model file
    use_mlock=False,            # don't lock — let unified memory manage pages
)
print("[LLM] ✅ Model loaded and ready\n")

# ──────────────────────────────────────────────────────────────
# WHISPER STT — optional, for voice input mode
# ──────────────────────────────────────────────────────────────
_whisper_model = None

def _load_whisper():
    """Lazy-load faster-whisper on first voice input."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
        print(f"[STT] Loading faster-whisper ({WHISPER_MODEL_SIZE})...")
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
        )
        print("[STT] ✅ Whisper ready")
        return _whisper_model
    except ImportError:
        print("[STT] faster-whisper not installed — voice input disabled")
        print("      pip install faster-whisper")
        return None
    except Exception as e:
        print(f"[STT] Failed to load: {e}")
        return None

def transcribe_audio(wav_path: str) -> str:
    """Transcribe a WAV file using faster-whisper. Returns text or ''."""
    model = _load_whisper()
    if model is None:
        return ""
    try:
        segments, info = model.transcribe(wav_path, beam_size=1, language=None)
        text = " ".join(seg.text for seg in segments).strip()
        print(f"[STT] \"{text}\" ({info.language}, {info.language_probability:.0%})")
        return text
    except Exception as e:
        print(f"[STT] Error: {e}")
        return ""

# ──────────────────────────────────────────────────────────────
# STREAMING LLM → SENTENCE BUFFER → TTS QUEUE
# ──────────────────────────────────────────────────────────────
# Conversation history (rolling window)
_history: list = []

def _trim_history():
    """Keep only the last N turns (user+assistant pairs)."""
    max_msgs = LLM_HISTORY_TURNS * 2
    while len(_history) > max_msgs:
        _history.pop(0)

def stream_response(user_text: str) -> str:
    """
    Stream LLM response token-by-token, buffering into sentences.
    Each completed sentence is immediately pushed to the TTS queue.

    Returns the full response text (for history tracking).
    """
    _trim_history()

    # Build message list: system + history + user
    messages = [{"role": "system", "content": ROBOT_SYSTEM_PROMPT}]
    messages += _history
    messages.append({"role": "user", "content": user_text})

    # Track for output
    full_response = ""
    sentence_buf = ""
    sentence_count = 0

    t0 = time.monotonic()
    first_token_time = None

    print("\n  ARIA: ", end="", flush=True)

    try:
        stream = _llm.create_chat_completion(
            messages=messages,
            temperature=LLM_TEMPERATURE,
            top_p=LLM_TOP_P,
            repeat_penalty=LLM_REPEAT_PENALTY,
            max_tokens=LLM_MAX_TOKENS,
            stream=True,
        )

        for chunk in stream:
            delta = chunk["choices"][0].get("delta", {})
            token = delta.get("content", "")
            if not token:
                continue

            if first_token_time is None:
                first_token_time = time.monotonic()

            # Print token to console in real-time
            print(token, end="", flush=True)

            full_response += token
            sentence_buf += token

            # Check for sentence boundary
            if _SENTENCE_END_RE.search(token):
                # We have a complete sentence — push to TTS
                sentence = sentence_buf.strip()
                if sentence and len(sentence) > 1:
                    _tts_queue.put(sentence)
                    sentence_count += 1
                sentence_buf = ""

        # Flush any remaining text in the buffer
        remainder = sentence_buf.strip()
        if remainder and len(remainder) > 1:
            _tts_queue.put(remainder)
            sentence_count += 1

    except Exception as e:
        print(f"\n  [LLM] Error during streaming: {e}")
        full_response = full_response or "Sorry, something went wrong."

    # Timing stats
    total_ms = (time.monotonic() - t0) * 1000
    ttft_ms = ((first_token_time - t0) * 1000) if first_token_time else 0
    print(f"\n  [{total_ms:.0f}ms total | {ttft_ms:.0f}ms TTFT | {sentence_count} sentences queued]")

    # Update history
    _history.append({"role": "user", "content": user_text})
    _history.append({"role": "assistant", "content": full_response})

    return full_response

# ──────────────────────────────────────────────────────────────
# MAIN INTERACTIVE LOOP
# ──────────────────────────────────────────────────────────────
def _wait_for_tts():
    """Block until all queued sentences have been spoken."""
    _tts_queue.join()

def main():
    print("─" * 60)
    print("  Commands:")
    print("    Type a message   → text chat with streaming TTS")
    print("    /voice <file>    → transcribe WAV and chat")
    print("    /clear           → clear conversation history")
    print("    /quit or Ctrl+C  → exit")
    print("─" * 60)
    print()

    def _shutdown(signum=None, frame=None):
        print("\n\nShutting down...")
        _tts_stop.set()
        _tts_queue.put(None)  # poison pill
        _tts_thread.join(timeout=3)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)

    while True:
        try:
            user_input = input("  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            _shutdown()
            break

        if not user_input:
            continue

        # Commands
        if user_input.lower() == "/quit":
            _shutdown()
            break
        elif user_input.lower() == "/clear":
            _history.clear()
            print("  [History cleared]\n")
            continue
        elif user_input.lower().startswith("/voice "):
            wav_path = user_input[7:].strip()
            if not os.path.exists(wav_path):
                print(f"  [File not found: {wav_path}]\n")
                continue
            user_input = transcribe_audio(wav_path)
            if not user_input:
                print("  [No speech detected]\n")
                continue
            print(f"  You (voice): {user_input}")

        # Stream LLM response with sentence-level TTS
        stream_response(user_input)

        # Wait for all audio to finish before next prompt
        _wait_for_tts()
        print()


if __name__ == "__main__":
    main()
