#!/usr/bin/env bash
# ============================================================
#  ARIA NEXUS FULL — Deploy & Fix Script
#  يجمع كل الملفات المطلوبة ويشغّل الـ ingest
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AI_PROJECT="/home/mecha/Desktop/ai_project"

echo ""
echo -e "\033[1;36m══════════════════════════════════════════════\033[0m"
echo -e "\033[1;36m  ARIA NEXUS — Deploy & Fix\033[0m"
echo -e "\033[1;36m══════════════════════════════════════════════\033[0m"
echo ""

# ── 1. Copy chroma_db ───────────────────────────────────────
echo "📦 [1/4] Copying chroma_db..."
if [ -d "$AI_PROJECT/chroma_db" ]; then
    rm -rf "$PROJECT_ROOT/chroma_db"
    cp -r "$AI_PROJECT/chroma_db" "$PROJECT_ROOT/chroma_db"
    echo "   ✅ chroma_db copied from ai_project"
else
    echo "   ⚠️  No chroma_db found in ai_project — will run fresh ingest"
fi

# ── 2. Copy data_files ──────────────────────────────────────
echo ""
echo "📄 [2/4] Syncing data_files..."
if [ -d "$AI_PROJECT/data_files" ]; then
    cp -n "$AI_PROJECT/data_files/"* "$PROJECT_ROOT/data_files/" 2>/dev/null || true
    echo "   ✅ data_files synced"
else
    echo "   ⚠️  No data_files in ai_project"
fi

# ── 3. Ensure venv is accessible ───────────────────────────
echo ""
echo "🐍 [3/4] Checking venv..."
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    # Check if venv exists in ai_project root
    if [ -d "$AI_PROJECT/venv" ]; then
        echo "   Found venv in ai_project — creating symlink..."
        ln -sf "$AI_PROJECT/venv" "$VENV_DIR"
        echo "   ✅ Symlinked venv from ai_project"
    else
        echo "   ⚠️  venv not found — creating new one..."
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip -q
        pip install -r "$SCRIPT_DIR/requirements.txt" -q
        echo "   ✅ New venv created and dependencies installed"
    fi
else
    echo "   ✅ venv already exists"
fi

# ── 4. Run Ingest to build vector DB ───────────────────────
echo ""
echo "🔄 [4/4] Running RAG ingest..."
source "$VENV_DIR/bin/activate"

# Set HF offline mode to use local embedding model
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

cd "$SCRIPT_DIR"
python3 ingest.py

echo ""
echo -e "\033[1;32m══════════════════════════════════════════════\033[0m"
echo -e "\033[1;32m  ✅ Deploy complete! Run: bash run.bash\033[0m"
echo -e "\033[1;32m══════════════════════════════════════════════\033[0m"
echo ""
