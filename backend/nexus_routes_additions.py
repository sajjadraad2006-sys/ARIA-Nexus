# =====================================================================
#  ARIA NEXUS — nexus_routes_additions.py
#  A self-contained Flask Blueprint exposing every endpoint the
#  ARIA Nexus frontend (application/) calls.
#
#  Integration:
#      from nexus_routes_additions import register_nexus
#      register_nexus(app)          # in your existing Flask app factory
#
#  Every route degrades gracefully: if an upstream service (HA, TTS, LLM,
#  RAG) is unavailable, the route returns a sensible fallback / error JSON
#  with an appropriate status code instead of crashing the server.
# =====================================================================
import json
import os
import time
import uuid

from flask import Blueprint, jsonify, request, Response

try:
    import requests
except Exception:
    requests = None

try:
    import psutil
except Exception:
    psutil = None

from web_action_manager import WebActionManager

try:
    import nexus_rag_store as RAGS
except Exception:
    RAGS = None

try:
    import nexus_wakeword as WAKE
except Exception:
    WAKE = None

try:
    import nexus_settings as SETTINGS
except Exception:
    SETTINGS = None


def _llm_body(base):
    """Merge the user's saved LLM generation params (temperature/top_p/
    max_tokens) into an outgoing llama.cpp request body."""
    params = SETTINGS.get_llm_params() if SETTINGS else {"temperature": 0.6}
    body = dict(base)
    body.update(params)
    return body

# --- Optional config import (falls back to defaults) ------------------
try:
    import config_nexus_append as NX
except Exception:
    class NX:  # minimal fallback
        NEXUS_VERSION = "1.0.0"
        NEXUS_POLL_INTERVAL = 15
        NEXUS_MODULES = [
            {"id": "chatbot", "label": "ARIA Chatbot", "port": 8080},
            {"id": "iot", "label": "IoT Control", "port": 8123},
            {"id": "monitor", "label": "System Monitor", "port": None},
            {"id": "tts", "label": "TTS Studio", "port": 5002},
            {"id": "knowledge", "label": "Knowledge Base", "port": None},
            {"id": "exporter", "label": "System Exporter", "port": None},
        ]
        NEXUS_SERVICES = {
            "flask": {"name": "Flask API", "url": "http://127.0.0.1:5000"},
            "llm": {"name": "LLM (Qwen2.5)", "url": "http://127.0.0.1:8080"},
            "stt": {"name": "Whisper STT", "url": "http://127.0.0.1:8081"},
            "tts": {"name": "TTS (Piper)", "url": "http://127.0.0.1:5002"},
            "ha": {"name": "Home Assistant", "url": "http://127.0.0.1:8123"},
        }
        NEXUS_WEB_ACTIONS_PATH = "data/nexus_web_actions.json"
        NEXUS_GENERIC_DEVICES_PATH = "data/nexus_generic_devices.json"
        NEXUS_RAG_DEFAULTS = {"chunk_size": 512, "chunk_overlap": 64, "top_k": 5, "min_relevance": 0.25}
        NEXUS_MANIFEST_VERSION = "1.0"


nexus_bp = Blueprint("nexus", __name__)
web_actions = WebActionManager(path=getattr(NX, "NEXUS_WEB_ACTIONS_PATH", "data/nexus_web_actions.json"))


# =====================================================================
#  Small helpers
# =====================================================================
def _service_url(key):
    svc = getattr(NX, "NEXUS_SERVICES", {}).get(key) or {}
    return svc.get("url")


def _ping(url, timeout=1.5):
    if not url or requests is None:
        return False
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False


def _load_json_file(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    return default


def _save_json_file(path, data):
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


GENERIC_PATH = getattr(NX, "NEXUS_GENERIC_DEVICES_PATH", "data/nexus_generic_devices.json")


# =====================================================================
#  LAUNCHER
# =====================================================================
@nexus_bp.route("/api/launcher/health", methods=["GET"])
def launcher_health():
    services = {}
    for key, svc in getattr(NX, "NEXUS_SERVICES", {}).items():
        if key == "flask":
            services[key] = True  # we are answering, so Flask is up
        else:
            services[key] = _ping(svc.get("url"))
    return jsonify({"ok": True, "version": NX.NEXUS_VERSION, "services": services})


@nexus_bp.route("/api/launcher/modules", methods=["GET"])
def launcher_modules():
    out = []
    for m in NX.NEXUS_MODULES:
        port = m.get("port")
        if port is None:
            status = "online"
        else:
            url = None
            for svc in getattr(NX, "NEXUS_SERVICES", {}).values():
                if svc.get("url", "").endswith(":" + str(port)):
                    url = svc["url"]
                    break
            url = url or ("http://127.0.0.1:%s" % port)
            status = "online" if _ping(url) else "offline"
        out.append({"id": m["id"], "label": m["label"], "status": status})
    return jsonify(out)


# =====================================================================
#  CHATBOT
# =====================================================================
@nexus_bp.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    history = data.get("history", [])
    llm_url = _service_url("llm")
    if requests is None or not llm_url:
        return jsonify({"response": "LLM service is not configured.", "context_used": 0, "context_max": 4096}), 503
    try:
        # OpenAI-compatible chat completion (llama.cpp / Ollama style).
        messages = [{"role": h.get("role"), "content": h.get("content")} for h in history if h.get("content")]
        if message and (not messages or messages[-1].get("content") != message):
            messages.append({"role": "user", "content": message})
        sys_prompt = RAGS.system_prompt() if RAGS else ""
        ctx = RAGS.rag_context(message) if RAGS else ""
        if ctx:
            sys_prompt = (sys_prompt + chr(10) + chr(10) + ctx).strip()
        full_messages = ([{"role": "system", "content": sys_prompt}] if sys_prompt else []) + messages
        resp = requests.post(
            llm_url.rstrip("/") + "/v1/chat/completions",
            json=_llm_body({"messages": full_messages, "stream": False}),
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        choice = (payload.get("choices") or [{}])[0]
        reply = (choice.get("message") or {}).get("content", "")
        usage = payload.get("usage") or {}
        return jsonify({
            "response": reply or "(empty response)",
            "context_used": usage.get("total_tokens", 0),
            "context_max": usage.get("context_size", 4096),
        })
    except Exception as exc:
        return jsonify({"response": "Error contacting LLM: %s" % exc, "context_used": 0, "context_max": 4096}), 502


@nexus_bp.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    history = data.get("history", [])
    llm_url = _service_url("llm")
    sep = chr(10) + chr(10)

    def gen():
        if requests is None or not llm_url:
            yield "data: " + json.dumps({"error": "LLM not configured"}) + sep
            yield "data: [DONE]" + sep
            return
        try:
            messages = [{"role": h.get("role"), "content": h.get("content")} for h in history if h.get("content")]
            if message and (not messages or messages[-1].get("content") != message):
                messages.append({"role": "user", "content": message})
            sys_prompt = RAGS.system_prompt() if RAGS else ""
            ctx = RAGS.rag_context(message) if RAGS else ""
            if ctx:
                sys_prompt = (sys_prompt + sep + ctx).strip()
            full = ([{"role": "system", "content": sys_prompt}] if sys_prompt else []) + messages
            with requests.post(
                llm_url.rstrip("/") + "/v1/chat/completions",
                json=_llm_body({"messages": full, "stream": True}),
                stream=True, timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                    except Exception:
                        delta = ""
                    if delta:
                        yield "data: " + json.dumps({"delta": delta}) + sep
            yield "data: [DONE]" + sep
        except Exception as exc:
            yield "data: " + json.dumps({"error": str(exc)}) + sep
            yield "data: [DONE]" + sep

    return Response(gen(), mimetype="text/event-stream")


# =====================================================================
#  SYSTEM MONITOR
# =====================================================================
@nexus_bp.route("/api/monitor/stats", methods=["GET"])
def monitor_stats():
    stats = {
        "cpu_percent": 0.0,
        "ram_used_gb": 0.0, "ram_total_gb": 0.0,
        "disk_used_gb": 0.0, "disk_total_gb": 0.0,
        "gpu_name": "GPU", "gpu_load_percent": 0.0, "gpu_memory_used_mb": 0,
    }
    if psutil is not None:
        try:
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.0)
            vm = psutil.virtual_memory()
            stats["ram_used_gb"] = round((vm.total - vm.available) / (1024 ** 3), 2)
            stats["ram_total_gb"] = round(vm.total / (1024 ** 3), 2)
            du = psutil.disk_usage("/")
            stats["disk_used_gb"] = round(du.used / (1024 ** 3), 2)
            stats["disk_total_gb"] = round(du.total / (1024 ** 3), 2)
        except Exception:
            pass
    # Optional GPU stats via pynvml (best-effort).
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        stats["gpu_name"] = pynvml.nvmlDeviceGetName(h).decode("utf-8", "ignore") if isinstance(
            pynvml.nvmlDeviceGetName(h), bytes) else str(pynvml.nvmlDeviceGetName(h))
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        stats["gpu_load_percent"] = float(util.gpu)
        stats["gpu_memory_used_mb"] = int(mem.used / (1024 ** 2))
        pynvml.nvmlShutdown()
    except Exception:
        pass

    services = {}
    for key, svc in getattr(NX, "NEXUS_SERVICES", {}).items():
        services[key] = True if key == "flask" else _ping(svc.get("url"))
    stats["services"] = services
    return jsonify(stats)


# =====================================================================
#  IOT — HOME ASSISTANT  (proxied via REST API if configured)
# =====================================================================
def _ha_headers():
    token = os.environ.get("HA_TOKEN") or os.environ.get("HASS_TOKEN")
    if not token:
        try:
            import config as _cfg
            token = getattr(_cfg, "HA_TOKEN", "") or getattr(_cfg, "HASS_TOKEN", "")
        except Exception:
            pass
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


@nexus_bp.route("/api/iot/entities", methods=["GET"])
def iot_entities():
    ha_url = _service_url("ha")
    if requests is None or not ha_url:
        return jsonify({"entities": []}), 503
    try:
        resp = requests.get(ha_url.rstrip("/") + "/api/states", headers=_ha_headers(), timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify({"entities": [], "error": str(exc)}), 502


@nexus_bp.route("/api/iot/toggle", methods=["POST"])
def iot_toggle():
    data = request.get_json(silent=True) or {}
    entity_id = data.get("entity_id", "")
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    ha_url = _service_url("ha")
    if requests is None or not ha_url or not domain:
        return jsonify({"ok": False, "error": "Home Assistant not configured"}), 503
    try:
        resp = requests.post(
            ha_url.rstrip("/") + "/api/services/%s/toggle" % domain,
            headers=_ha_headers(), json={"entity_id": entity_id}, timeout=5,
        )
        resp.raise_for_status()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@nexus_bp.route("/api/iot/service", methods=["POST"])
def iot_service():
    data = request.get_json(silent=True) or {}
    domain = data.get("domain", "")
    service = data.get("service", "")
    entity_id = data.get("entity_id", "")
    extra = data.get("data", {}) or {}
    ha_url = _service_url("ha")
    if requests is None or not ha_url or not domain or not service:
        return jsonify({"ok": False, "error": "Home Assistant not configured"}), 503
    try:
        payload = {"entity_id": entity_id}
        payload.update(extra)
        resp = requests.post(
            ha_url.rstrip("/") + "/api/services/%s/%s" % (domain, service),
            headers=_ha_headers(), json=payload, timeout=5,
        )
        resp.raise_for_status()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@nexus_bp.route("/api/iot/virtual", methods=["POST"])
def iot_virtual():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    device_type = (data.get("device_type") or "switch").strip() or "switch"
    room = (data.get("room") or "").strip()
    # Persist as a generic 'input_boolean'-style virtual device. We also try
    # to register it in Home Assistant as an input_boolean helper when a token
    # is configured, but local persistence always succeeds (offline-friendly).
    devices = _load_json_file(GENERIC_PATH, [])
    entity = {"id": uuid.uuid4().hex, "name": name, "device_type": device_type,
              "ip": "", "room": room, "virtual": True, "state": False,
              "channels": []}
    devices.append(entity)
    _save_json_file(GENERIC_PATH, devices)
    # Best-effort push to Home Assistant (non-fatal if it is offline).
    ha_pushed = False
    try:
        headers = _ha_headers()
        if headers:
            url = config.HA_URL.rstrip("/") + "/api/services/input_boolean/reload"
            requests.post(url, headers=headers, timeout=2)
            ha_pushed = True
    except Exception:
        ha_pushed = False
    return jsonify({"ok": True, "device": entity, "ha_pushed": ha_pushed})


@nexus_bp.route("/api/iot/virtual/devices", methods=["GET"])
def iot_virtual_devices():
    """List only the locally-created virtual devices."""
    devices = _load_json_file(GENERIC_PATH, [])
    return jsonify({"devices": [d for d in devices if d.get("virtual")]})


@nexus_bp.route("/api/iot/virtual/toggle", methods=["POST"])
def iot_virtual_toggle():
    """Flip the stored on/off state of a virtual device."""
    data = request.get_json(silent=True) or {}
    dev_id = data.get("id")
    devices = _load_json_file(GENERIC_PATH, [])
    found = None
    for d in devices:
        if d.get("id") == dev_id and d.get("virtual"):
            d["state"] = not bool(d.get("state"))
            found = d
            break
    if not found:
        return jsonify({"ok": False, "error": "device not found"}), 404
    _save_json_file(GENERIC_PATH, devices)
    return jsonify({"ok": True, "device": found, "state": found["state"]})


@nexus_bp.route("/api/iot/virtual/<dev_id>", methods=["DELETE"])
def iot_virtual_delete(dev_id):
    devices = _load_json_file(GENERIC_PATH, [])
    new_devices = [d for d in devices if not (d.get("id") == dev_id and d.get("virtual"))]
    _save_json_file(GENERIC_PATH, new_devices)
    return jsonify({"ok": True, "deleted": len(devices) - len(new_devices)})


# =====================================================================
#  IOT — GENERIC / NETWORK DEVICES (local JSON store)
# =====================================================================
@nexus_bp.route("/api/iot/generic/devices", methods=["GET"])
def generic_devices():
    return jsonify({"devices": _load_json_file(GENERIC_PATH, [])})


@nexus_bp.route("/api/iot/generic/device", methods=["POST"])
def generic_add():
    data = request.get_json(silent=True) or {}
    devices = _load_json_file(GENERIC_PATH, [])
    device = {
        "id": uuid.uuid4().hex,
        "name": (data.get("name") or "").strip(),
        "ip": (data.get("ip") or "").strip(),
        "room": (data.get("room") or "").strip(),
        "device_type": data.get("device_type") or "switch",
        "channels": data.get("channels") or [],
        "brand": data.get("brand") or "generic",
        "added_via": data.get("added_via") or "manual",
    }
    if not device["name"] or not device["ip"]:
        return jsonify({"ok": False, "error": "name and ip required"}), 400
    devices.append(device)
    _save_json_file(GENERIC_PATH, devices)
    return jsonify({"ok": True, "device": device})


@nexus_bp.route("/api/iot/generic/device/<dev_id>", methods=["DELETE"])
def generic_delete(dev_id):
    devices = _load_json_file(GENERIC_PATH, [])
    new_devices = [d for d in devices if d.get("id") != dev_id and d.get("dev_id") != dev_id]
    _save_json_file(GENERIC_PATH, new_devices)
    return jsonify({"ok": True, "deleted": len(devices) - len(new_devices)})


def _generic_http(device, path, payload=None):
    """Best-effort TASMOTA-style HTTP command to a device IP."""
    if requests is None or not device or not device.get("ip"):
        return {"ok": False, "error": "device unreachable"}
    try:
        url = "http://%s/%s" % (device["ip"], path.lstrip("/"))
        resp = requests.get(url, params=payload or {}, timeout=4)
        return {"ok": resp.status_code < 400, "status_code": resp.status_code}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@nexus_bp.route("/api/iot/generic/toggle", methods=["POST"])
def generic_toggle():
    data = request.get_json(silent=True) or {}
    dev_id = data.get("dev_id")
    channel = data.get("channel", 0)
    devices = _load_json_file(GENERIC_PATH, [])
    device = next((d for d in devices if d.get("id") == dev_id), None)
    if not device:
        return jsonify({"ok": False, "error": "device not found"}), 404
    res = _generic_http(device, "cm", {"cmnd": "Power%s TOGGLE" % (int(channel) + 1)})
    return jsonify(res)


@nexus_bp.route("/api/iot/generic/command", methods=["POST"])
def generic_command():
    data = request.get_json(silent=True) or {}
    dev_id = data.get("dev_id")
    command = data.get("command")
    value = data.get("value")
    devices = _load_json_file(GENERIC_PATH, [])
    device = next((d for d in devices if d.get("id") == dev_id), None)
    if not device:
        return jsonify({"ok": False, "error": "device not found"}), 404
    res = _generic_http(device, "cm", {"cmnd": "%s %s" % (command, value)})
    return jsonify(res)


@nexus_bp.route("/api/iot/generic/test", methods=["GET"])
def generic_test():
    ip = request.args.get("ip", "").strip()
    if not ip:
        return jsonify({"ok": False, "reachable": False, "error": "ip required"}), 400
    reachable = _ping("http://%s/" % ip, timeout=2)
    return jsonify({"ok": True, "reachable": reachable})


@nexus_bp.route("/api/iot/generic/scan", methods=["POST"])
def generic_scan():
    """Lightweight ARP-table scan (best-effort; returns known hosts)."""
    found = []
    try:
        import subprocess
        out = subprocess.check_output(["arp", "-a"], timeout=5).decode("utf-8", "ignore")
        for line in out.splitlines():
            parts = line.replace("(", " ").replace(")", " ").split()
            for tok in parts:
                if tok.count(".") == 3 and tok.replace(".", "").isdigit():
                    found.append({"ip": tok, "hostname": parts[0] if parts else ""})
                    break
    except Exception:
        pass
    return jsonify({"ok": True, "devices": found})


# =====================================================================
#  IOT — WEB ACTIONS
# =====================================================================
@nexus_bp.route("/api/iot/webactions", methods=["GET"])
def webactions_list():
    return jsonify({"actions": web_actions.list()})


@nexus_bp.route("/api/iot/webactions", methods=["POST"])
def webactions_add():
    data = request.get_json(silent=True) or {}
    action = web_actions.add(
        name=data.get("name"), url=data.get("url"),
        method=data.get("method", "POST"),
        headers=data.get("headers") or {}, body=data.get("body") or "",
    )
    return jsonify({"ok": True, "action": action})


@nexus_bp.route("/api/iot/webactions/<action_id>", methods=["PATCH"])
def webactions_update(action_id):
    data = request.get_json(silent=True) or {}
    action = web_actions.update(action_id, data)
    if not action:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "action": action})


@nexus_bp.route("/api/iot/webactions/<action_id>", methods=["DELETE"])
def webactions_delete(action_id):
    existed = web_actions.delete(action_id)
    return jsonify({"ok": existed})


@nexus_bp.route("/api/iot/webactions/<action_id>/trigger", methods=["POST"])
def webactions_trigger(action_id):
    return jsonify(web_actions.trigger_action(action_id))


# =====================================================================
#  TTS
# =====================================================================
@nexus_bp.route("/api/tts/voices", methods=["GET"])
def tts_voices():
    tts_url = _service_url("tts")
    if requests is None or not tts_url:
        return jsonify({"voices": []}), 503
    try:
        resp = requests.get(tts_url.rstrip("/") + "/voices", timeout=5)
        resp.raise_for_status()
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify({"voices": [], "error": str(exc)}), 502


@nexus_bp.route("/api/tts/voice", methods=["POST"])
def tts_set_voice():
    data = request.get_json(silent=True) or {}
    tts_url = _service_url("tts")
    if requests is None or not tts_url:
        return jsonify({"ok": False, "error": "TTS not configured"}), 503
    try:
        resp = requests.post(tts_url.rstrip("/") + "/voice", json=data, timeout=5)
        resp.raise_for_status()
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502


@nexus_bp.route("/api/tts/preview", methods=["POST"])
def tts_preview():
    data = request.get_json(silent=True) or {}
    tts_url = _service_url("tts")
    if requests is None or not tts_url:
        return jsonify({"error": "TTS not configured"}), 503
    try:
        resp = requests.post(tts_url.rstrip("/") + "/synthesize", json=data, timeout=30)
        resp.raise_for_status()
        return Response(resp.content, mimetype=resp.headers.get("Content-Type", "audio/wav"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


# =====================================================================
#  RAG / KNOWLEDGE
# =====================================================================
import time as _time

_RAG_SETTINGS = RAGS.SETTINGS if RAGS else dict(getattr(NX, "NEXUS_RAG_DEFAULTS", {}))

# In-memory demo knowledge store so the UI's add / view / edit / delete
# flows work out of the box. Replace with your real vector store: on add /
# edit, chunk + embed + upsert; on delete, remove vectors; on query, do a
# real similarity search. Keep the JSON response shapes identical.
_RAG_DOCS = {}  # filename -> {"text": str, "modified": float}


def _chunk_count(text):
    size = int(_RAG_SETTINGS.get("chunk_size", 512)) or 512
    return max(1, (len(text) + size - 1) // size)


@nexus_bp.route("/api/rag/stats", methods=["GET"])
def rag_stats():
    return jsonify(RAGS.stats())


@nexus_bp.route("/api/rag/query", methods=["POST"])
def rag_query():
    data = request.get_json(silent=True) or {}
    return jsonify(RAGS.query(data.get("query") or ""))


@nexus_bp.route("/api/rag/document", methods=["POST"])
def rag_add_document():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    name = (data.get("title") or data.get("filename") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "text is required"}), 400
    try:
        r = RAGS.add(name, text)
        return jsonify({"ok": True, "filename": r["filename"], "chunks": r["chunks"]})
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": "Failed to add document: " + str(exc)}), 500


@nexus_bp.route("/api/rag/document/<path:filename>", methods=["GET"])
def rag_get_document(filename):
    d = RAGS.get(filename)
    if d is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "filename": filename, "text": d["text"], "modified": d["modified"]})


@nexus_bp.route("/api/rag/document/<path:filename>", methods=["PATCH"])
def rag_update_document(filename):
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if text is None:
        return jsonify({"ok": False, "error": "text is required"}), 400
    try:
        r = RAGS.update(filename, text)
        return jsonify({"ok": True, "filename": r["filename"], "chunks": r["chunks"]})
    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"ok": False, "error": "Failed to update document: " + str(exc)}), 500


@nexus_bp.route("/api/rag/document/<path:filename>", methods=["DELETE"])
def rag_delete_document(filename):
    RAGS.delete(filename)
    return jsonify({"ok": True, "deleted": filename})


@nexus_bp.route("/api/rag/settings", methods=["POST"])
def rag_settings():
    data = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "settings": RAGS.set_settings(data)})


@nexus_bp.route("/api/rag/reindex", methods=["POST"])
def rag_reindex():
    return jsonify(RAGS.reindex())


# =====================================================================
#  STT (chatbot voice input)
# =====================================================================
@nexus_bp.route("/api/stt/start", methods=["POST"])
def stt_start():
    # whisper.cpp server doesn't have a /start endpoint — just confirm ok
    return jsonify({"ok": True, "status": "use /api/stt/inference to submit audio"})


@nexus_bp.route("/api/stt/stop", methods=["POST"])
def stt_stop():
    # whisper.cpp server doesn't have a /stop endpoint — just confirm ok
    return jsonify({"ok": True, "text": ""})


@nexus_bp.route("/api/stt/inference", methods=["POST"])
def nexus_stt_inference_proxy():
    """
    Proxy: browser HTTPS → Flask (webm→wav via ffmpeg) → Whisper HTTP.

    whisper.cpp ONLY accepts WAV (16 kHz, mono, PCM s16le).
    The browser's MediaRecorder always sends WebM/Opus, so we MUST
    transcode with ffmpeg before forwarding to whisper-server.
    """
    import tempfile, subprocess, os as _os
    from flask import request as _req

    stt_url = _service_url("stt")
    if requests is None or not stt_url:
        return jsonify({"error": "STT not configured"}), 503

    f = _req.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400

    audio_bytes = f.read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio file"}), 400

    # --- ffmpeg: webm/ogg/any → 16 kHz mono WAV (what whisper.cpp needs) ---
    raw_tmp = tempfile.NamedTemporaryFile(suffix=".webm", delete=False)
    wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav",  delete=False)
    raw_path, wav_path = raw_tmp.name, wav_tmp.name
    raw_tmp.close(); wav_tmp.close()

    try:
        with open(raw_path, "wb") as fh:
            fh.write(audio_bytes)

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", raw_path,
             "-ar", "16000", "-ac", "1",
             "-acodec", "pcm_s16le", "-f", "wav", wav_path],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            err_msg = result.stderr.decode("utf-8", "ignore")[-300:]
            return jsonify({"error": "ffmpeg conversion failed: " + err_msg}), 500

        with open(wav_path, "rb") as wf:
            wav_bytes = wf.read()

        # Minimum size gate: < 0.5 s of audio = skip transcription
        if len(wav_bytes) < 16000:
            return jsonify({"text": ""}), 200

    finally:
        for p in (raw_path, wav_path):
            try:
                if _os.path.exists(p):
                    _os.remove(p)
            except OSError:
                pass

    # --- Forward WAV to whisper.cpp /inference ---
    # CRITICAL: forward the language + temperature too. whisper.cpp's server
    # defaults `language` to "en" when the field is absent, which forces every
    # utterance to be transcribed as English (Issue 5: "STT only recognizes
    # English"). "auto" lets it detect Arabic vs English per utterance. Single
    # source of truth: config.WHISPER_LANGUAGE / WHISPER_TEMPERATURE.
    _wlang, _wtemp = "auto", 0.0
    try:
        import config as _cfg
        _wlang = getattr(_cfg, "WHISPER_LANGUAGE", "auto") or "auto"
        _wtemp = getattr(_cfg, "WHISPER_TEMPERATURE", 0.0)
    except Exception:
        pass
    try:
        resp = requests.post(
            stt_url.rstrip("/") + "/inference",
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"response_format": "json", "language": _wlang,
                  "temperature": str(_wtemp)},
            timeout=30,
        )
        if not resp.ok:
            return jsonify({"error": "Whisper HTTP %d" % resp.status_code}), resp.status_code
        return (resp.content, resp.status_code, {"Content-Type": "application/json"})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Whisper server not running on port 8081"}), 503
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# =====================================================================
#  WAKE WORD (hands-free, openWakeWord) — Robot Face page
# =====================================================================
@nexus_bp.route("/api/wake/start", methods=["POST"])
def wake_start():
    if WAKE is None:
        return jsonify({"ok": False, "error": "wake module unavailable"}), 503
    ok, err = WAKE.get_listener().start()
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 503


@nexus_bp.route("/api/wake/stop", methods=["POST"])
def wake_stop():
    if WAKE is None:
        return jsonify({"ok": True})
    WAKE.get_listener().stop()
    return jsonify({"ok": True})


@nexus_bp.route("/api/wake/status", methods=["GET"])
def wake_status():
    if WAKE is None:
        return jsonify({
            "available": False,
            "reason": "wake module unavailable",
            "listening": False,
            "detected": False,
        })
    return jsonify(WAKE.get_listener().status())


@nexus_bp.route("/api/wake/feed", methods=["POST"])
def wake_feed():
    """Run openWakeWord on streamed browser-mic audio.

    Any device that opens the web app can POST raw little-endian PCM16
    mono @ 16 kHz here; the Jetson runs the model locally, so it works
    with the internet completely off (only the LAN is needed).
    """
    if WAKE is None:
        return jsonify({"available": False, "detected": False,
                        "error": "wake module unavailable"}), 503
    pcm = request.get_data() or b""
    try:
        result = WAKE.get_listener().feed(pcm)
    except Exception as exc:
        return jsonify({"available": False, "detected": False,
                        "error": str(exc)}), 500
    return jsonify(result)


@nexus_bp.route("/api/wake/feed/reset", methods=["POST"])
def wake_feed_reset():
    if WAKE is not None:
        try:
            WAKE.get_listener().reset_feed()
        except Exception:
            pass
    return jsonify({"ok": True})


@nexus_bp.route("/api/mic/devices", methods=["GET"])
def mic_devices():
    """List local (Jetson) input devices for the Settings mic picker."""
    if WAKE is None:
        return jsonify({"devices": [], "reason": "wake module unavailable"})
    listener = WAKE.get_listener()
    return jsonify({
        "devices": listener.list_devices(),
        "available": listener.available(),
        "reason": listener.reason(),
    })


@nexus_bp.route("/api/wake/config", methods=["POST"])
def wake_config():
    """Live-tune the wake listener: { threshold?, device?, always_on? }.
    Persists to nexus_settings so it survives restarts."""
    data = request.get_json(silent=True) or {}
    patch = {}
    if WAKE is not None:
        listener = WAKE.get_listener()
        if "threshold" in data and data["threshold"] is not None:
            patch["threshold"] = listener.set_threshold(data["threshold"])
        if "device" in data:
            patch["device"] = listener.set_device(data["device"])
    if "always_on" in data:
        patch["always_on"] = bool(data["always_on"])
    if SETTINGS is not None and patch:
        SETTINGS.update_settings({"wake": patch})
    status = WAKE.get_listener().status() if WAKE is not None else {}
    return jsonify({"ok": True, "status": status})


@nexus_bp.route("/api/settings", methods=["GET"])
def settings_get():
    """Return all live-tunable settings (llm + wake)."""
    if SETTINGS is None:
        return jsonify({"settings": {}, "reason": "settings store unavailable"})
    return jsonify({"settings": SETTINGS.get_settings()})


@nexus_bp.route("/api/settings", methods=["POST"])
def settings_set():
    """Deep-merge a settings patch, e.g. { llm: { temperature: 0.4 } }."""
    data = request.get_json(silent=True) or {}
    if SETTINGS is None:
        return jsonify({"ok": False, "error": "settings store unavailable"}), 503
    new_settings = SETTINGS.update_settings(data)
    # apply wake-affecting changes immediately
    if WAKE is not None and isinstance(data.get("wake"), dict):
        wk = data["wake"]
        if wk.get("threshold") is not None:
            WAKE.get_listener().set_threshold(wk["threshold"])
        if "device" in wk:
            WAKE.get_listener().set_device(wk["device"])
    return jsonify({"ok": True, "settings": new_settings})


# =====================================================================
#  EXPORTER
# =====================================================================
def _sha256_hex(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@nexus_bp.route("/api/exporter/export", methods=["POST"])
def exporter_export():
    flags = request.get_json(silent=True) or {}
    data = {}
    if flags.get("include_config"):
        data["config"] = {"version": NX.NEXUS_VERSION, "rag_settings": _RAG_SETTINGS}
    if flags.get("include_iot"):
        data["iot"] = {"generic_devices": _load_json_file(GENERIC_PATH, [])}
    if flags.get("include_webactions"):
        data["webactions"] = web_actions.list()
    if flags.get("include_rag"):
        data["rag"] = {"settings": _RAG_SETTINGS, "documents": []}

    manifest = {
        "manifest_version": getattr(NX, "NEXUS_MANIFEST_VERSION", "1.0"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sections": [k for k in data.keys()],
        "data": data,
    }
    # Real SHA-256 checksum over the canonical data payload.
    manifest["checksum"] = _sha256_hex(json.dumps(data, sort_keys=True, separators=(",", ":")))
    body = json.dumps(manifest, indent=2)
    return Response(
        body, mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=aria_export_%d.json" % int(time.time())},
    )


@nexus_bp.route("/api/exporter/import", methods=["POST"])
def exporter_import():
    dry_run = request.args.get("dry_run", "true").lower() == "true"
    manifest = request.get_json(silent=True) or {}
    version = manifest.get("manifest_version") or manifest.get("version")
    if version != getattr(NX, "NEXUS_MANIFEST_VERSION", "1.0"):
        return jsonify({"ok": False, "error": "Unsupported manifest version: %s" % version}), 400

    data = manifest.get("data", {})
    expected = manifest.get("checksum")
    if expected:
        actual = _sha256_hex(json.dumps(data, sort_keys=True, separators=(",", ":")))
        if actual != expected:
            return jsonify({"ok": False, "error": "Checksum mismatch — file may be corrupt"}), 400

    if dry_run:
        return jsonify({"ok": True, "dry_run": True,
                        "message": "%d section(s) ready to import" % len(data)})

    applied = []
    try:
        if "iot" in data and isinstance(data["iot"], dict):
            _save_json_file(GENERIC_PATH, data["iot"].get("generic_devices", []))
            applied.append("iot")
        if "webactions" in data and isinstance(data["webactions"], list):
            _save_json_file(web_actions.path, data["webactions"])
            web_actions._load()
            applied.append("webactions")
        if "rag" in data and isinstance(data["rag"], dict):
            _RAG_SETTINGS.update(data["rag"].get("settings", {}))
            applied.append("rag")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "applied": applied})


# =====================================================================
#  REGISTRATION
# =====================================================================
def register_nexus(app, rag_engine=None):
    """Register the Nexus blueprint and serve the SPA from application/.

    Call this from your Flask app factory:  register_nexus(app)
    """
    if rag_engine is not None and RAGS is not None:
        RAGS.set_engine(rag_engine)
    app.register_blueprint(nexus_bp)

    # Serve the standalone SPA — application/ lives in frontend/application/
    from flask import send_from_directory
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    app_dir = os.path.normpath(os.path.join(project_root, "frontend", "application"))

    @app.route("/nexus/")
    def _nexus_index():
        return send_from_directory(app_dir, "nexus_app.html")

    @app.route("/nexus/<path:asset>")
    def _nexus_asset(asset):
        return send_from_directory(app_dir, asset)

    return app


# =====================================================================
#  ASSISTANT BRAIN  (smart-home voice control, memory, routines)
#  Appended additions. These register on the existing nexus_bp blueprint
#  at import time, so register_nexus(app) picks them up automatically.
# =====================================================================
@nexus_bp.route("/api/assistant/command", methods=["POST"])
def assistant_command():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    history = data.get("history", []) or []
    try:
        import nexus_assistant as ASSIST
    except Exception as exc:
        return jsonify({"response": "Assistant brain unavailable: %s" % exc,
                        "action": "error", "handled": False,
                        "context_used": 0, "context_max": 4096}), 500
    try:
        result = ASSIST.handle_command(message, history)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"response": "Assistant error: %s" % exc,
                        "action": "error", "handled": False,
                        "context_used": 0, "context_max": 4096}), 500


# ---- Personal memory CRUD -------------------------------------------
@nexus_bp.route("/api/assistant/memory", methods=["GET"])
def assistant_memory_get():
    try:
        import nexus_memory as MEM
        return jsonify({"ok": True, "memory": MEM.all_items()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "memory": {}}), 500


@nexus_bp.route("/api/assistant/memory", methods=["POST"])
def assistant_memory_set():
    data = request.get_json(silent=True) or {}
    try:
        import nexus_memory as MEM
        if "name" in data:
            MEM.set_name(data.get("name", ""))
        key = (data.get("key") or "").strip()
        if key:
            MEM.remember(key, data.get("value", ""))
        return jsonify({"ok": True, "memory": MEM.all_items()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@nexus_bp.route("/api/assistant/memory/<path:key>", methods=["DELETE"])
def assistant_memory_delete(key):
    try:
        import nexus_memory as MEM
        if key == "__name__":
            MEM.set_name("")
        else:
            MEM.forget(key)
        return jsonify({"ok": True, "memory": MEM.all_items()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---- Routines --------------------------------------------------------
@nexus_bp.route("/api/assistant/routines", methods=["GET"])
def assistant_routines_get():
    try:
        import nexus_assistant as ASSIST
        return jsonify({"ok": True, "routines": ASSIST.load_routines()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "routines": []}), 500


@nexus_bp.route("/api/assistant/routines", methods=["POST"])
def assistant_routines_save():
    data = request.get_json(silent=True) or {}
    routines = data.get("routines")
    if not isinstance(routines, list):
        return jsonify({"ok": False, "error": "routines must be a list"}), 400
    try:
        import nexus_assistant as ASSIST
        ASSIST.save_routines(routines)
        return jsonify({"ok": True, "routines": ASSIST.load_routines()})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@nexus_bp.route("/api/assistant/routines/run", methods=["POST"])
def assistant_routines_run():
    data = request.get_json(silent=True) or {}
    rid = (data.get("id") or "").strip()
    try:
        import nexus_assistant as ASSIST
        target = None
        for r in ASSIST.load_routines():
            if r.get("id") == rid:
                target = r
                break
        if not target:
            return jsonify({"ok": False, "error": "routine not found"}), 404
        return jsonify(ASSIST.run_routine(target))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
