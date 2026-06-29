# ARIA Setup & Installation Guide

## System Requirements

### Hardware
- NVIDIA Jetson Orin Nano (8GB recommended)
- At least 32GB NVMe SSD
- USB or CSI camera (for robot navigation)
- Stable Wi-Fi or Ethernet connection
- Optional: USB microphone for direct voice input

### Software Prerequisites
- Ubuntu 22.04 (JetPack 6.x)
- Python 3.10 or higher
- Node.js (for frontend dependencies, if needed)
- Git

---

## Installation Steps

### Step 1: Clone the Repository
```bash
git clone https://github.com/your-repo/jaston-project.git
cd jaston-project
```

### Step 2: Create Python Virtual Environment
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy the example file and edit it:
```bash
cp backend/.env.example backend/.env
nano backend/.env
```

Key variables to set:
- HA_URL: Your Home Assistant URL (e.g., http://192.168.1.100:8123)
- HA_TOKEN: Home Assistant long-lived access token
- LLM_URL: Usually http://localhost:8080 (default llama.cpp port)
- WHISPER_URL: Usually http://localhost:8081
- PIPER_URL: Usually http://localhost:5002

### Step 4: Download AI Models
```bash
bash backend/download_models.sh
```
This downloads:
- LLM model (Qwen2.5-3B GGUF format)
- Whisper model (large-v3-turbo)
- Piper TTS voices (English and Arabic)
- Sentence-transformer embedding model

### Step 5: Generate SSL Certificates
```bash
mkdir -p certs
openssl req -x509 -newkey rsa:4096 -keyout certs/key.pem -out certs/cert.pem -days 365 -nodes
```

### Step 6: Ingest Knowledge Base Documents
```bash
cd backend
source venv/bin/activate
python -m ingest
```

### Step 7: Launch ARIA
```bash
bash backend/run.bash
```
This starts all services in order:
1. llama-server (LLM on port 8080)
2. whisper-server (STT on port 8081)
3. piper-server (TTS on port 5002)
4. Flask web server (dashboard on port 5000)

---

## Accessing the Dashboard

Open a browser on any device on the same network:
```
https://JETSON_IP:5000/nexus/
```

Replace JETSON_IP with your Jetson device's IP address.
Accept the self-signed certificate warning in the browser.

---

## Home Assistant Integration

### Getting a Long-Lived Access Token
1. Open Home Assistant web interface
2. Click your profile name (bottom left)
3. Scroll to "Long-Lived Access Tokens"
4. Click "Create Token"
5. Name it "ARIA" and copy the token
6. Paste into HA_TOKEN in backend/.env

### Testing the Connection
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://YOUR_HA_IP:8123/api/
```
Should return: {"message": "API running."}

---

## Adding New IoT Devices

### Home Assistant Devices
No configuration needed — ARIA automatically discovers all HA entities.
Just make sure the entity is properly set up in Home Assistant.

### Generic Tasmota/ESP Devices
Edit generic_devices.json in the project root:
```json
{
  "devices": [
    {
      "id": "generic.living_fan",
      "name": "Living Room Fan",
      "ip": "192.168.1.50",
      "type": "fan"
    }
  ]
}
```
Then restart the Flask server.

---

## Updating the Knowledge Base

To add new information ARIA can use when answering questions:
1. Create a .txt or .md file with your content
2. Place it in the data_files/ folder
3. Run: `python -m ingest` (from backend/ with venv active)
4. Use `python -m ingest --reset` to rebuild from scratch

---

## Troubleshooting Common Issues

### "Model not found" error
Check that model files exist in the models/ directory.
Run download_models.sh again if files are missing.

### "Connection refused" on port 8080
The LLM server didn't start. Check:
- Enough RAM/VRAM available
- Model file path in config.py is correct
- llama-server binary exists in vendor/

### Whisper not transcribing
- Check port 8081 is accessible
- Verify whisper model file path
- Try with a smaller model if VRAM is limited

### Home Assistant entities not found
- Verify HA_TOKEN is correct and not expired
- Check HA_URL is reachable from Jetson
- Enable "Allow CORS" in HA settings if needed
