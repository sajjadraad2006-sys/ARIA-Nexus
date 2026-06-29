# ARIA — Capabilities & Features Reference

## Core System Overview
ARIA (Advanced Robotic Intelligence Assistant) is a fully offline, edge-deployed AI assistant built on NVIDIA Jetson Orin Nano hardware. It integrates speech recognition, language modeling, text-to-speech, smart home control, and autonomous navigation into a unified web-based dashboard.

## Voice Interaction Pipeline
1. User presses microphone button in the browser
2. Audio is recorded and sent to the Whisper STT server (port 8081)
3. Whisper transcribes the audio to text (supports Arabic and English)
4. Text is sent to the LLM (Qwen2.5 3B) via llama.cpp (port 8080)
5. LLM generates a response, possibly including IoT control tags
6. Response is read aloud using Piper TTS (port 5002)
7. IoT tags are parsed and device commands are executed

## Smart Home Control
ARIA can control any Home Assistant entity:
- Lights: turn on/off, adjust brightness
- Switches: toggle smart plugs and relays
- Fans: control speed (1, 2, 3)
- Dimmers: set level 0–100%
- Sensors: read temperature, humidity, motion
- Climate: set thermostat temperature and mode

## Generic Device Support (Non-Home Assistant)
ARIA supports Tasmota-based and ESP8266/ESP32 devices directly over LAN:
- Single-channel relay boards
- Multi-channel relay boards (channels 1–8)
- PWM dimmers
- Variable speed fans
- Any HTTP-controllable device

## RAG Knowledge Base
The RAG system allows ARIA to answer questions using local documents:
- Documents stored in: data_files/ directory
- Supported formats: .txt, .md, .pdf
- Vector store: ChromaDB with sentence-transformers embeddings
- Model: all-MiniLM-L6-v2 (runs on CPU, no GPU needed)
- To add knowledge: place files in data_files/, then run: python -m ingest

## Autonomous Robot Navigation
- Camera: Real-time video feed for object detection
- YOLO: Object detection and classification
- Spatial memory: Remembers landmark locations
- Path planning: Avoids obstacles using sensor data
- Mission modes: Explore, Deliver, Return to base

## System Monitoring Dashboard
Real-time metrics visible on the /nexus/ dashboard:
- CPU usage and temperature
- RAM usage
- Disk space
- GPU utilization (Jetson integrated GPU)
- Service status (LLM, Whisper, Piper, Home Assistant)

## Security
- HTTPS only (self-signed certificates in /certs)
- All processing is local — no cloud APIs
- No data sent outside the local network
- Voice data processed and discarded immediately
