#!/usr/bin/env bash
# ============================================================
#  ARIA NEXUS - Model Downloader (Idempotent)
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/../models"
mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

echo "============================================================"
echo "  Checking and Downloading Models..."
echo "============================================================"

# Helper function
download_if_missing() {
    local url="$1"
    local dest="$2"
    if [ -s "$dest" ]; then
        echo "[ok] [$dest] already exists. Skipping."
    else
        echo "[..] Downloading [$dest]..."
        curl -L -o "$dest" "$url"
    fi
}

HF="https://huggingface.co"

# 1. LLM (Qwen2.5 0.5B)
download_if_missing "$HF/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf" "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"

# 2. Whisper STT models
# The active model is configurable via NEXUS_WHISPER_MODEL (see config.py).
# Default is the MULTILINGUAL ggml-medium, which gives much better Arabic
# (incl. Iraqi dialect) + English accuracy than small. ggml-small.bin is always
# kept as a lightweight low-RAM fallback. Do NOT use *.en models (English only).
WHISPER_MODEL_FILE="${NEXUS_WHISPER_MODEL:-ggml-medium.bin}"

download_if_missing "$HF/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" "ggml-small.bin"

if [ "$WHISPER_MODEL_FILE" != "ggml-small.bin" ]; then
    download_if_missing "$HF/ggerganov/whisper.cpp/resolve/main/$WHISPER_MODEL_FILE" "$WHISPER_MODEL_FILE"
fi

# 3. RAG Embeddings (all-MiniLM-L6-v2)
if [ -d "all-MiniLM-L6-v2" ] && [ "$(ls -A all-MiniLM-L6-v2)" ]; then
    echo "[ok] [all-MiniLM-L6-v2] directory exists and is not empty. Skipping."
else
    echo "[..] Downloading [all-MiniLM-L6-v2] via Python/transformers..."
    python3 -c "from sentence_transformers import SentenceTransformer; model = SentenceTransformer('all-MiniLM-L6-v2'); model.save('all-MiniLM-L6-v2')"
fi

# 4. Piper Voices (English + Arabic)
mkdir -p "piper_voices"
download_if_missing "$HF/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx" "piper_voices/ar_JO-kareem-medium.onnx"
download_if_missing "$HF/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json" "piper_voices/ar_JO-kareem-medium.onnx.json"

download_if_missing "$HF/rhasspy/piper-voices/resolve/main/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx" "piper_voices/en_GB-semaine-medium.onnx"
download_if_missing "$HF/rhasspy/piper-voices/resolve/main/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx.json" "piper_voices/en_GB-semaine-medium.onnx.json"

echo "============================================================"
echo "All required models are present in $MODELS_DIR"
echo "  Active Whisper model: $WHISPER_MODEL_FILE  (override via NEXUS_WHISPER_MODEL)"
echo "============================================================"
