# ARIA Nexus

> Local, offline-first AI assistant for a Smart Home & Delivery Robot Hub.

## Overview
ARIA (ARIA NEXUS) is an advanced, fully offline personal AI assistant engineered to run locally on an NVIDIA Jetson Orin Nano (Kubuntu/Linux). It provides seamless voice-based interaction, local smart home control, and intelligent autonomous features without relying on internet connectivity. The system is bilingual, supporting both English and Arabic (including Iraqi dialects).

## Goals
- **Fully Offline:** Guarantee 100% functionality without internet dependency for privacy and reliability.
- **Hardware Optimization:** Run efficiently on the edge using the NVIDIA Jetson Orin Nano.
- **Fast Voice Pipeline:** Achieve low-latency conversational AI with a local Wake Word -> STT -> LLM -> TTS pipeline.
- **Smart Hub:** Serve as the central command hub for local IoT devices and robot navigation.

## Features
### Current Features
- **Offline Voice Interaction:** Highly responsive text and voice chatbot using Qwen2.5 LLM.
- **Bilingual Support:** Understands and speaks English and Arabic dynamically based on the user's input.
- **Smart Home Integration:** Direct control of Home Assistant entities and generic LAN (Tasmota/ESP) devices.
- **Local Knowledge Base (RAG):** Answers queries based on custom documents stored in `data_files/` using ChromaDB.
- **Autonomous Vision (YOLOv8):** Local object detection for spatial memory and navigation capabilities.
- **Web Command Center:** A beautiful, responsive Nexus Dashboard to monitor and control all services.

### Planned / Roadmap
- **Model Upgrades:** Download and switch to larger Whisper models (`ggml-medium` or `ggml-large-v3-turbo`) for improved Iraqi-dialect speech recognition.
- **Autonomous Navigation Refinement:** Enhance the autonomous navigation loop using the existing YOLO object detection and spatial memory logic.

## Architecture
ARIA is built using a modular architecture orchestrated by a central Flask application.
- **Wake Word:** Local hot-word detection via `openWakeWord` configured for the wake word "Aria".
- **Speech-to-Text (STT):** `whisper.cpp` running a multilingual GGML model.
- **Language Model (LLM):** Text-only Qwen2.5-Instruct running via `llama.cpp` for maximum generation speed.
- **Text-to-Speech (TTS):** `Piper TTS` (warm resident pool) for fast English and Arabic voice synthesis.
- **Retrieval-Augmented Generation (RAG):** `ChromaDB` using `all-MiniLM-L6-v2` embeddings for local document search.
- **Backend Orchestrator:** `Flask` + `Flask-SocketIO` proxying commands to local hardware and managing state.

## Tech Stack
- **Backend:** Python 3, Flask, Flask-SocketIO.
- **Frontend:** Vanilla JavaScript, HTML5, CSS3 (No build step required).
- **Core AI Inference:** `llama.cpp`, `whisper.cpp`.
- **Machine Learning / Audio:** `Piper`, `openWakeWord`, `ffmpeg`.

## Requirements
### Hardware
- **Target:** NVIDIA Jetson Orin Nano (or equivalent local Linux machine).
- **Memory:** Minimum 8GB unified memory recommended to hold LLM, STT, and TTS models in RAM/VRAM simultaneously.

### Software
- **OS:** Kubuntu / Linux.
- **Dependencies:** Python 3, `ffmpeg`, and basic C++ build tools (GCC/Make/CMake) to compile `llama.cpp` and `whisper.cpp`.

## Installation

1. **Clone & Setup Environment:**
   Ensure you have the repository downloaded and Python 3 installed.
   ```bash
   cd Jaston-project/backend
   bash setup.sh   # Creates the virtual environment and installs Python dependencies
   ```

2. **Download AI Models:**
   ```bash
   bash download_models.sh
   ```
   *(Ensure you have compiled the binaries in `vendor/llama.cpp` and `vendor/whisper.cpp` beforehand).*

3. **Configure Secrets:**
   Duplicate the example environment file and add your Home Assistant token:
   ```bash
   cp .env.example .env
   # Edit .env to add your HA_TOKEN and adjust URLs if necessary.
   ```

## Usage

ARIA is designed to be launched with a single unified bash script that spins up the LLM, STT, TTS, and the Flask server in separate terminals (or background processes).

```bash
# From the project root:
cd backend
bash run.bash
```

Once the terminal outputs confirm that all services are online, open your browser and navigate to:
```
http://localhost:5000/nexus/
```
*(Or replace `localhost` with your Jetson's local IP address if accessing from a phone/tablet).*

## Project Structure
```text
Jaston-project/
├── aarya_wakeword/   # Wake word listener scripts and models
├── backend/          # Core Python logic (Flask, RAG, IoT control, configs)
│   ├── run.bash      # Main launcher script
│   ├── config.py     # Centralized system configurations
│   └── server.py     # Main Flask server entry point
├── chroma_db/        # Persistent vector database for the Knowledge Base
├── data_files/       # Drop text/PDF documents here for RAG indexing
├── frontend/         # Vanilla JS/CSS/HTML for the Nexus Dashboard
├── models/           # Downloaded weights (.gguf, .bin, .onnx, .pt)
├── vendor/           # Submodules (llama.cpp, whisper.cpp, piper)
└── README.md         # Project documentation (this file)
```

## Assumptions & Notes
- **IoT Dependency:** It is assumed a local Home Assistant instance is running on the LAN (default `http://127.0.0.1:8123`) to handle smart home actions.
- **Terminal Emulator:** The `run.bash` script attempts to open native terminal windows (gnome-terminal, xterm, etc.) to show live logs of AI models. If run headlessly, it falls back to background processes and writes to temporary log files.
- **VRAM constraints:** The Flask server forces CPU-only execution to leave the entirety of the GPU memory available for `llama-server`.
