#!/usr/bin/env bash
# ============================================================
#  ARIA NEXUS — Unified Command Center Launch
#  Opens 3 terminals:
#    1) Llama Server  (LLM — text only, no vision)
#    2) Whisper Server (STT — speech-to-text for mic)
#    3) Flask Server   (Nexus Dashboard + all modules)
#
#  Single Entry Point:
#    /nexus     → ARIA Nexus Command Center
#
#  ⚡ All features accessible from Nexus Dashboard
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ============================================================
#  CLEANUP (KILL OLD PROCESSES & CLEAR SYSTEM CACHE)
# ============================================================
echo "Cleaning up old processes and system cache to free RAM..."
pkill -f "llama-server" || true
pkill -f "whisper-server" || true
pkill -f "server.py" || true
pkill -f "piper_server.py" || true

# Clear Linux system cache (best-effort, non-blocking — skipped if no sudo)
if sudo -n true 2>/dev/null; then
    echo "Dropping system cache..."
    sudo sync
    echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null
else
    echo "⚠️  Skipping cache drop (no passwordless sudo). Not critical."
fi

sleep 1

# ============================================================
#  PREFLIGHT CHECKS
# ============================================================
echo "Running Preflight Checks..."

# ── Load .env secrets (HA_TOKEN, etc.) ──────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    echo "✅ Loaded secrets from .env"
fi

# Warn if Home Assistant token is missing
if [ -z "${HA_TOKEN:-}" ]; then
    echo "⚠️  WARNING: HA_TOKEN is not set — IoT WebSocket auth will fail."
    echo "   Create backend/.env with: HA_TOKEN=your_long_lived_token"
fi

VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ ERROR: venv not found! Please run 'bash setup.sh' first."
    exit 1
fi

WHISPER_BIN="$PROJECT_ROOT/vendor/whisper.cpp/build/bin/whisper-server"
if [ ! -f "$WHISPER_BIN" ]; then
    echo "❌ ERROR: whisper-server binary missing at $WHISPER_BIN"
    echo "   Please compile whisper.cpp first."
    exit 1
fi

WHISPER_MODEL="$PROJECT_ROOT/models/ggml-large-v3-turbo.bin"
if [ ! -f "$WHISPER_MODEL" ]; then
    echo "❌ ERROR: Whisper model missing at $WHISPER_MODEL"
    echo "   Please run 'bash download_models.sh' first."
    exit 1
fi

LLAMA_BIN="$PROJECT_ROOT/vendor/llama.cpp/build/bin/llama-server"
if [ ! -f "$LLAMA_BIN" ]; then
    echo "❌ ERROR: llama-server binary missing at $LLAMA_BIN"
    echo "   Please compile llama.cpp first."
    exit 1
fi

LLAMA_MODEL="$PROJECT_ROOT/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
if [ ! -f "$LLAMA_MODEL" ]; then
    echo "❌ ERROR: LLM model missing at $LLAMA_MODEL"
    echo "   Please run 'bash download_models.sh' first."
    exit 1
fi

echo "✅ Preflight Checks Passed."

# ── Shared libs for CUDA builds ─────────────────────────────
export LD_LIBRARY_PATH="$PROJECT_ROOT/vendor/llama.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/src:$PROJECT_ROOT/vendor/piper:${LD_LIBRARY_PATH:-}"

# ── wait_for_port: poll until a port is open OR timeout ─────
# Usage: wait_for_port <port> <service_name> <timeout_seconds>
wait_for_port() {
    local port="$1" name="$2" timeout="${3:-60}"
    local elapsed=0
    echo "Waiting for $name (port $port)..."
    while ! nc -z 127.0.0.1 "$port" 2>/dev/null; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ "$elapsed" -ge "$timeout" ]; then
            echo "❌ TIMEOUT: $name did not start within ${timeout}s — continuing anyway."
            return 1
        fi
    done
    echo "✅ $name is online."
    return 0
}

# ── Paths ────────────────────────────────────────────────────
WHISPER_PORT=8081
LLAMA_PORT=8080
LLAMA_CTX=2048        # 512 tokens — minimal context for fast responses
LLAMA_NGL=99         # 100% GPU offload (ensure you have ~4GB free RAM before starting)
LLAMA_BATCH=256      # Batch size for prompt processing
FLASK_PORT=5000

# ── Get local IP ────────────────────────────────────────────
LOCAL_IP=$(hostname -I | awk '{print $1}')
if [ -z "$LOCAL_IP" ]; then
    LOCAL_IP="127.0.0.1"
fi

# ── Helper: open a new gnome-terminal ────────────────────────
# Open a service in a new terminal, auto-detecting the emulator. Falls back to
# running in the BACKGROUND with a log file when no terminal emulator exists
# (headless Jetson / minimal Ubuntu). This is what makes the launcher work
# everywhere instead of dying on "gnome-terminal: command not found" (which left
# HA_TOKEN unexported and silently broke IoT). Logs: $TMPDIR_ARIA/<name>.log
open_term() {
    local title="$1"
    local script_file="$2"
    local logfile="${script_file%.sh}.log"
    chmod +x "$script_file" 2>/dev/null
    if command -v gnome-terminal >/dev/null 2>&1; then
        gnome-terminal --title="$title" -- bash "$script_file" &
    elif command -v konsole >/dev/null 2>&1; then
        konsole -p "tabtitle=$title" -e bash "$script_file" &
    elif command -v xfce4-terminal >/dev/null 2>&1; then
        xfce4-terminal --title="$title" -e "bash $script_file" &
    elif command -v xterm >/dev/null 2>&1; then
        xterm -T "$title" -e bash "$script_file" &
    elif command -v x-terminal-emulator >/dev/null 2>&1; then
        x-terminal-emulator -e bash "$script_file" &
    else
        echo "  [run] No terminal emulator found - starting '$title' in the background."
        echo "        Logs: $logfile"
        bash "$script_file" > "$logfile" 2>&1 &
    fi
}

# ============================================================
#  Create temp launcher scripts
# ============================================================
TMPDIR_ARIA=$(mktemp -d)

# --- Terminal 1: Llama Server (TEXT ONLY — no mmproj) ---
cat > "$TMPDIR_ARIA/llama.sh" << LLAMA_EOF
#!/usr/bin/env bash
export LD_LIBRARY_PATH="$PROJECT_ROOT/vendor/llama.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/src:$PROJECT_ROOT/vendor/piper:\${LD_LIBRARY_PATH:-}"
echo ""
echo -e "\033[1;36m══════════════════════════════════════════════════════\033[0m"
echo -e "\033[1;36m  Qwen2.5 7B-Instruct LLM — TEXT ONLY — port $LLAMA_PORT\033[0m"
echo -e "\033[1;36m  GPU layers: $LLAMA_NGL | Context: $LLAMA_CTX tokens\033[0m"
echo -e "\033[1;36m  ⚡ Optimized for speed — no vision model loaded\033[0m"
echo -e "\033[1;36m══════════════════════════════════════════════════════\033[0m"
echo ""
"$LLAMA_BIN" \\
    --model "$LLAMA_MODEL" \\
    --port $LLAMA_PORT \\
    --host 0.0.0.0 \\
    --ctx-size $LLAMA_CTX \\
    -ngl $LLAMA_NGL \\
    --batch-size $LLAMA_BATCH \\
    --threads \$(nproc) \\
    --cont-batching
echo ""
echo -e "\033[0;31mLlama server exited.\033[0m"
exec bash
LLAMA_EOF
chmod +x "$TMPDIR_ARIA/llama.sh"

# --- Terminal 2: Whisper Server (STT for microphone) ---
cat > "$TMPDIR_ARIA/whisper.sh" << WHISPER_EOF
#!/usr/bin/env bash
export LD_LIBRARY_PATH="$PROJECT_ROOT/vendor/llama.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/src:$PROJECT_ROOT/vendor/piper:\${LD_LIBRARY_PATH:-}"
echo ""
echo -e "\033[1;36m══════════════════════════════════════\033[0m"
echo -e "\033[1;36m  Whisper STT Server — port $WHISPER_PORT\033[0m"
echo -e "\033[1;36m  🎤 Microphone speech-to-text\033[0m"
echo -e "\033[1;36m══════════════════════════════════════\033[0m"
echo ""
"$WHISPER_BIN" \\
    --model "$WHISPER_MODEL" \\
    --port $WHISPER_PORT \\
    --host 0.0.0.0 \\
    --threads \$(nproc) \\
    --processors 1
echo ""
echo -e "\033[0;31mWhisper server exited.\033[0m"
exec bash
WHISPER_EOF
chmod +x "$TMPDIR_ARIA/whisper.sh"

# --- Terminal 3: Flask Server ---
cat > "$TMPDIR_ARIA/flask.sh" << FLASK_EOF
#!/usr/bin/env bash
# Flask runs CPU-only — never touches GPU so llama-server gets all VRAM
export CUDA_VISIBLE_DEVICES=""
export CUDA_DEVICE_ORDER="PCI_BUS_ID"
export LD_LIBRARY_PATH="$PROJECT_ROOT/vendor/llama.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/bin:$PROJECT_ROOT/vendor/whisper.cpp/build/src:$PROJECT_ROOT/vendor/piper:\${LD_LIBRARY_PATH:-}"
export HA_TOKEN="${HA_TOKEN:-}"
export HA_URL="${HA_URL:-http://127.0.0.1:8123}"
cd "$SCRIPT_DIR"
# Use absolute path to the venv python binary because the activate script
# breaks if the project directory is renamed.
echo ""
echo -e "\033[1;36m══════════════════════════════════════\033[0m"
echo -e "\033[1;36m  ARIA Flask Server — port $FLASK_PORT\033[0m"
echo -e "\033[1;36m══════════════════════════════════════\033[0m"
echo ""
"$VENV_DIR/bin/python3" server.py
echo ""
echo -e "\033[0;31mFlask server exited.\033[0m"
exec bash
FLASK_EOF
chmod +x "$TMPDIR_ARIA/flask.sh"

# --- Terminal 4: Piper TTS Server (TTS Studio) ---
cat > "$TMPDIR_ARIA/piper.sh" << PIPER_EOF
#!/usr/bin/env bash
export CUDA_VISIBLE_DEVICES=""
cd "$SCRIPT_DIR"
echo "Piper TTS Server on port 5002"
"$VENV_DIR/bin/python3" piper_server.py
echo "Piper server exited."
exec bash
PIPER_EOF
chmod +x "$TMPDIR_ARIA/piper.sh"

# ============================================================
#  Launch — Llama first (needs time), then Whisper, then Flask
# ============================================================
echo ""
echo -e "\033[1;36m  ╔═══════════════════════════════════════════════════════════╗"
echo -e "  ║       ◆  ARIA NEXUS — Unified Command Center             ║"
echo -e "  ║          🧠 LLM + 🎤 Whisper + 🌐 Flask                   ║"
echo -e "  ╠═══════════════════════════════════════════════════════════╣"
echo -e "  ║                                                           ║"
echo -e "  ║   ◆  Nexus Dashboard:                                     ║"
echo -e "  ║   \033[1;33m   https://$LOCAL_IP:$FLASK_PORT/nexus/\033[1;36m                   ║"
echo -e "  ║                                                           ║"
echo -e "  ║   📱 Open on your phone/tablet                            ║"
echo -e "  ║      Accept the SSL warning → full access!                ║"
echo -e "  ║                                                           ║"
echo -e "  ╚═══════════════════════════════════════════════════════════╝\033[0m"
echo ""
echo "Starting services..."
echo ""

open_term "🧠 Qwen2.5 LLM"     "$TMPDIR_ARIA/llama.sh"
wait_for_port $LLAMA_PORT "LLM" 90
sleep 2

open_term "🎤 Whisper STT"     "$TMPDIR_ARIA/whisper.sh"
wait_for_port $WHISPER_PORT "Whisper" 60
sleep 2

open_term "Piper TTS"   "$TMPDIR_ARIA/piper.sh"
wait_for_port 5002 "Piper TTS" 45
sleep 1

open_term "🌐 ARIA Flask"      "$TMPDIR_ARIA/flask.sh"
wait_for_port $FLASK_PORT "Flask" 30

echo ""
echo -e "\033[1;32m  ✔ All services are healthy and running!\033[0m"
echo ""
echo -e "  \033[1;33m◆ Nexus Dashboard → https://$LOCAL_IP:$FLASK_PORT/nexus/\033[0m"
echo ""
echo "Press Enter to clean up temp files (terminals will keep running)..."
read -r
rm -rf "$TMPDIR_ARIA" 2>/dev/null