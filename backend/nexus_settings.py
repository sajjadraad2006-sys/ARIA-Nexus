# =====================================================================
#  nexus_settings.py
#  ONE small, thread-safe JSON-backed settings store shared by the
#  whole backend (routes + assistant brain). Keeps runtime-tunable
#  options that the user can change live from the Settings panel:
#
#      • llm.temperature / top_p / max_tokens   — generation behaviour
#      • wake.threshold / device / always_on    — wake-word listener
#
#  Everything degrades gracefully: if the file is missing or corrupt we
#  fall back to DEFAULTS, so the server never crashes over settings.
# =====================================================================
import json
import os
import threading

_LOCK = threading.Lock()


def _project_root():
    try:
        import config as _cfg
        root = getattr(_cfg, "_PROJECT_ROOT", None)
        if root:
            return root
    except Exception:
        pass
    return os.getcwd()


_PATH = os.path.join(_project_root(), "data", "nexus_settings.json")

DEFAULTS = {
    "llm": {
        "temperature": 0.6,   # 0.0 = deterministic, ~1.0 = creative
        "top_p": 0.95,
        "max_tokens": 0,      # 0 / falsy => let the model decide (omitted)
    },
    "wake": {
        "threshold": 0.1,     # openWakeWord score needed to trigger (0..1)
        "device": None,       # sounddevice input index for the Jetson mic
        "always_on": True,    # keep the Jetson mic armed 24/7
        "phrase": "aria",
    },
}


def _deep_merge(base, patch):
    """Return a new dict: patch values override base, recursively."""
    out = dict(base)
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_file():
    try:
        if os.path.exists(_PATH):
            with open(_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh) or {}
    except Exception:
        pass
    return {}


def get_settings():
    """Full settings = DEFAULTS deep-merged with whatever is on disk."""
    with _LOCK:
        return _deep_merge(DEFAULTS, _read_file())


def update_settings(patch):
    """Deep-merge `patch` into the stored settings and persist. Returns the
    new full settings dict."""
    with _LOCK:
        merged_stored = _deep_merge(_read_file(), patch or {})
        try:
            directory = os.path.dirname(_PATH)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = _PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(merged_stored, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, _PATH)
        except Exception:
            pass
        return _deep_merge(DEFAULTS, merged_stored)


def get_llm_params():
    """Convenience: the generation params to splat into an LLM request body.
    Always includes temperature + top_p; includes max_tokens only when > 0."""
    llm = get_settings().get("llm", {})
    params = {
        "temperature": float(llm.get("temperature", 0.6)),
        "top_p": float(llm.get("top_p", 0.95)),
    }
    try:
        mt = int(llm.get("max_tokens", 0) or 0)
        if mt > 0:
            params["max_tokens"] = mt
    except Exception:
        pass
    return params


def get_wake():
    return get_settings().get("wake", {})
