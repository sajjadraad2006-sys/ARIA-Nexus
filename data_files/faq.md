# Frequently Asked Questions — ARIA Assistant

## General Questions

### What is ARIA?
ARIA stands for Advanced Robotic Intelligence Assistant. It is a smart home control system and AI chatbot that runs completely offline on local hardware (Jetson Orin Nano). ARIA can control IoT devices, answer questions, listen to voice commands, and navigate autonomously as a robot.

### Does ARIA need the internet?
No. ARIA runs 100% offline. All AI models (LLM, speech recognition, text-to-speech) run locally on the device. No data is sent to any cloud service.

### What languages does ARIA support?
ARIA supports English and Arabic, including Iraqi Arabic dialect. It automatically detects the language and responds accordingly.

### Can ARIA control any smart device?
ARIA can control:
- Any device registered in Home Assistant
- Tasmota/ESP-based devices directly over LAN (via HTTP API)
- Devices must be reachable on the same network

---

## Voice Recognition

### Why isn't ARIA understanding me?
- Make sure you are speaking clearly
- Check if the microphone button is active (green icon)
- Ensure Whisper server is running (port 8081)
- Try speaking in a quiet environment
- If using Arabic, the large-v3-turbo model works best

### Which Whisper model should I use?
For best accuracy: ggml-large-v3-turbo.bin
For faster response on limited hardware: ggml-small.bin or ggml-base.bin
The model is configured in config.py under WHISPER_MODEL_PATH.

### Can ARIA detect the wake word?
Yes. ARIA has a custom wake word detection system (aarya_wakeword). When enabled, you can say "Hey ARIA" or the configured wake word to activate listening without pressing the microphone button.

---

## Text-to-Speech

### How do I change ARIA's voice?
Edit config.py and set PIPER_VOICE to:
- English: en_GB-semaine-medium
- Arabic: ar_JO-kareem-medium
Then restart the Piper TTS server.

### ARIA is speaking too fast/slow?
Adjust the PIPER_SPEED setting in config.py. Default is 1.0. Lower = slower, higher = faster.

---

## Knowledge Base (RAG)

### How do I add knowledge to ARIA?
1. Create a .txt, .md, or .pdf file with your information
2. Place it in the data_files/ folder
3. Run: cd backend && python -m ingest
4. ARIA will now use that knowledge when answering questions

### How does ARIA use the knowledge base?
When you ask ARIA a question, it searches the ChromaDB vector database for relevant information from your documents. It then includes that context in the prompt sent to the LLM, so the AI can give accurate, specific answers based on your data.

### How do I update the knowledge base?
Simply modify your files in data_files/ and run python -m ingest again. Files that haven't changed are automatically skipped. Use --reset flag to rebuild from scratch.

---

## Troubleshooting

### The LLM is not responding
1. Check if llama-server is running: ps aux | grep llama
2. Test manually: curl http://localhost:8080/health
3. Check VRAM usage — the model needs enough memory
4. Restart with: ./run.bash

### Home Assistant is not connecting
1. Verify HA is running on port 8123
2. Check HA_URL and HA_TOKEN in backend/.env
3. Ensure the long-lived access token is valid and not expired
4. Check network connectivity between ARIA and HA

### How do I restart all services?
Run from the project root:
  bash backend/run.bash
This script starts llama-server, whisper server, and Flask in the correct order.

### Where are the logs?
- Flask output: printed to terminal / run.bash
- LLM logs: llama_server.log
- Whisper logs: whisper_server.log
Check these files for errors if a service isn't working.
