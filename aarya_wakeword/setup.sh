#!/usr/bin/env bash
# One-time setup for the Aarya wake word detector.
set -e

echo "==> Creating virtual environment (venv)"
python3 -m venv venv
source venv/bin/activate

echo "==> Installing Python dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Downloading openWakeWord preprocessing models (melspectrogram + embeddings)"
python3 -c "import openwakeword.utils; openwakeword.utils.download_models()"

echo ""
echo "==> Done! To run the detector:"
echo "    source venv/bin/activate"
echo "    python3 aarya_wakeword.py"
echo ""
echo "NOTE (Linux): if you hit a PortAudio error, install the system lib:"
echo "    sudo apt install -y libportaudio2     # Debian/Ubuntu/Kubuntu"
echo "    sudo dnf install -y portaudio          # Fedora/RHEL"
