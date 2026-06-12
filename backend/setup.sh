#!/usr/bin/env bash
# ============================================================
#  ARIA NEXUS — Setup Script
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  1. Initialising Python Virtual Environment"
echo "============================================================"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created venv."
else
    echo "✅ venv already exists."
fi

source venv/bin/activate

echo ""
echo "============================================================"
echo "  2. Installing Python Dependencies"
echo "============================================================"
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ Dependencies installed."

echo ""
echo "============================================================"
echo "  3. Downloading openWakeWord Models"
echo "============================================================"
python -c "import openwakeword.utils as u; u.download_models()"
echo "✅ openWakeWord models ready."

echo ""
echo "============================================================"
echo "  4. Downloading Main AI Models"
echo "============================================================"
if [ -f "download_models.sh" ]; then
    bash download_models.sh
else
    echo "⚠️  download_models.sh not found. Skipping."
fi

echo ""
echo "============================================================"
echo "🎉 Setup Complete! You can now run: bash run.bash"
echo "============================================================"
