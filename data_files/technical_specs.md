# ARIA Project Technical Specifications

## Project Identity
- **Project Name**: ARIA (Advanced Robotic Intelligence Assistant)  
- **Code Name**: Jaston-Project  
- **Category**: Edge AI / Smart Home / Autonomous Robot  
- **Target Platform**: NVIDIA Jetson Orin Nano  
- **Primary Language**: Python (backend), HTML/CSS/JavaScript (frontend)  

---

## Architecture Overview

```
[ Browser Dashboard ]
        |
    HTTPS:5000
        |
[ Flask Web Server ] ─── Config.py (central settings)
   |       |       |
   |       |       └── [ ChromaDB RAG ] ←── data_files/*.md, *.txt, *.pdf
   |       |
   |       └── [ Home Assistant API ] ─── HA_URL:8123
   |
   ├── [ llama-server ] (LLM) ─── port 8080
   ├── [ whisper-server ] (STT) ─── port 8081
   └── [ piper-server ] (TTS) ─── port 5002
```

---

## File Structure

```
jaston-project/
├── backend/
│   ├── server.py              # Main Flask application
│   ├── config.py              # All configuration constants
│   ├── rag_engine.py          # ChromaDB RAG interface
│   ├── ingest.py              # Document ingestion pipeline
│   ├── nexus_assistant.py     # AI chat logic and context
│   ├── iot_controller.py      # IoT device control (HA + Generic)
│   ├── nexus_routes_additions.py  # Additional API routes
│   ├── piper_tts.py           # Piper TTS integration
│   ├── tts_server.py          # TTS HTTP server
│   ├── nexus_wakeword.py      # Wake word detection
│   ├── nexus_memory.py        # Conversation memory
│   ├── streaming_pipeline.py  # Streaming LLM responses
│   ├── web_action_manager.py  # Browser automation actions
│   ├── requirements.txt       # Python dependencies
│   └── run.bash               # Service orchestration script
├── frontend/
│   └── application/
│       ├── js/pages/chatbot.js    # Voice interaction UI
│       └── ...                    # Other frontend pages
├── data_files/                # RAG knowledge base documents
├── chroma_db/                 # ChromaDB vector storage
├── models/                    # AI model files (GGUF, bin, onnx)
├── certs/                     # SSL certificates
├── vendor/                    # Pre-built binaries (llama.cpp, whisper.cpp)
├── aarya_wakeword/            # Wake word model and training data
└── generic_devices.json       # Non-HA device definitions
```

---

## API Endpoints

### Chat API
- `POST /api/chat` — Send a message, get AI response
- `POST /api/chat/stream` — Streaming response (Server-Sent Events)
- `GET /api/chat/history` — Get conversation history
- `DELETE /api/chat/history` — Clear conversation history

### Voice API
- `POST /api/stt` — Speech-to-text (audio → text)
- `POST /api/tts` — Text-to-speech (text → audio)

### IoT Control API
- `GET /api/devices` — List all controllable devices
- `POST /api/device/control` — Control a specific device
- `GET /api/ha/states` — Get all Home Assistant entity states

### RAG API
- `POST /api/rag/query` — Direct RAG query (for testing)
- `POST /api/rag/ingest` — Trigger document ingestion
- `GET /api/rag/status` — RAG system status

### System API
- `GET /api/system/stats` — CPU, RAM, GPU, disk stats
- `GET /api/services/status` — All service health checks
- `GET /nexus/` — Main dashboard

---

## Configuration Reference (config.py)

### LLM Settings
```python
LLM_URL = "http://localhost:8080"      # llama-server URL
LLM_MODEL_PATH = "models/qwen2.5-3b.gguf"
LLM_MAX_TOKENS = 512
LLM_TEMPERATURE = 0.7
LLM_CONTEXT_SIZE = 4096
```

### Whisper STT Settings
```python
WHISPER_URL = "http://localhost:8081"   # whisper-server URL
WHISPER_MODEL_PATH = "models/ggml-large-v3-turbo.bin"
WHISPER_LANGUAGE = "auto"              # auto-detect language
```

### Piper TTS Settings
```python
PIPER_URL = "http://localhost:5002"    # piper-server URL
PIPER_VOICE_AR = "ar_JO-kareem-medium"
PIPER_VOICE_EN = "en_GB-semaine-medium"
```

### RAG Settings
```python
RAG_DATA_DIR = "../data_files"
RAG_CHROMA_DIR = "../chroma_db"
RAG_COLLECTION_NAME = "aria_docs"
RAG_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RAG_CHUNK_SIZE = 800
RAG_CHUNK_OVERLAP = 100
RAG_TOP_K = 4
RAG_MIN_RELEVANCE = 0.3
RAG_CACHE_TTL = 300                    # seconds
RAG_MAX_CONTEXT_CHARS = 3000
```

### Home Assistant Settings
```python
HA_URL = os.getenv("HA_URL")          # from .env file
HA_TOKEN = os.getenv("HA_TOKEN")      # long-lived access token
```

---

## Dependencies

### Python Packages (requirements.txt)
- flask — Web framework
- flask-cors — Cross-origin resource sharing
- requests — HTTP client for HA/LLM APIs
- langchain — LLM orchestration framework
- langchain-community — Community integrations
- langchain-huggingface — HuggingFace embeddings
- langchain-chroma — ChromaDB integration
- chromadb — Vector database
- sentence-transformers — Embedding models
- torch — PyTorch (CPU-only for RAG)
- pypdf — PDF document loading
- python-dotenv — .env file loading

### External Binaries
- llama-server (from llama.cpp) — LLM inference
- whisper-server (from whisper.cpp) — Speech recognition
- piper — Text-to-speech synthesis

---

## Performance Benchmarks (Jetson Orin Nano)

| Task | Speed |
|------|-------|
| LLM first token (Qwen 3B Q4) | ~1.2s |
| LLM generation speed | ~15 tokens/sec |
| Whisper transcription (5s audio) | ~2.5s |
| Piper TTS (50 words) | ~0.3s |
| RAG query (cache miss) | ~0.2s |
| RAG query (cache hit) | <1ms |
| YOLO object detection | ~30 FPS |
