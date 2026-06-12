# ARIA — Advanced Robotic Intelligence Assistant
## Smart Home & Delivery Robot Command Center

### What is ARIA?
ARIA is an advanced AI-powered command center for smart home control and autonomous delivery operations.
It runs 100% offline on Jetson Orin Nano hardware with full local AI inference.

### Main Capabilities
- **Smart Home Control**: Integrates with Home Assistant to control lights, switches, fans, dimmers, and sensors.
- **Voice Recognition**: Uses Whisper STT (speech-to-text) on port 8081 for hands-free microphone input.
- **AI Chat**: Powered by Qwen2.5 3B LLM running locally on port 8080 via llama.cpp.
- **Text-to-Speech**: Piper TTS engine with English (en_GB-semaine) and Arabic (ar_JO-kareem) voices.
- **RAG Knowledge Base**: Retrieval-Augmented Generation using ChromaDB and sentence-transformers embeddings.
- **IoT Device Control**: Supports Home Assistant entities AND generic IP-based Tasmota/ESP devices on LAN.
- **System Monitoring**: Real-time CPU, RAM, disk, and GPU statistics dashboard.

### IoT Control Tags (for AI responses)
- Home Assistant devices: [IOT:turn_on|switch.entity_id]
- Generic IP devices: [GENERIC:turn_on|generic.device_id]
- Multi-channel: [GENERIC:turn_on|generic.device|2]
- Dimmer (0-100%): [GENERIC:dimmer|generic.dimmer|75]
- Fan speed (1-3): [GENERIC:fan|generic.fan|2]

### Services & Ports
- Flask Web Server: port 5000 (HTTPS) — main dashboard at /nexus/
- LLM Server (llama.cpp): port 8080
- Whisper STT Server: port 8081
- Piper TTS Server: port 5002
- Home Assistant: port 8123

### Language Support
ARIA is bilingual — English and Arabic. It automatically detects Arabic script and responds in Arabic.
For Iraqi dialect, it understands expressions like: شنو تشوف، شو تريد، ايش قدامك.

### Robot Navigation
ARIA includes autonomous navigation capabilities with YOLO object detection and spatial memory.
The robot can recognize objects, remember locations, and navigate independently.
