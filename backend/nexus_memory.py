# =====================================================================
#  nexus_memory.py  --  ARIA Nexus personal long-term memory.
#
#  A tiny, 100% local JSON store that remembers the user's name,
#  preferences and free-form facts across sessions. It is injected
#  into the LLM system prompt (so ARIA "knows" you) and is also used
#  by the deterministic assistant brain for instant recall.
#
#  Storage: data/nexus_memory.json  (UTF-8, atomic writes)
#  Schema : { "name": str, "facts": { key: value }, "updated": ts }
# =====================================================================
import json
import os
import threading
import time

_lock = threading.RLock()


def _path():
    # Mirror the location convention used by the other Nexus json stores.
    try:
        import config_nexus_append as NX
        gp = getattr(NX, "NEXUS_MEMORY_PATH", None)
        if gp:
            return gp
    except Exception:
        pass
    return os.path.join("data", "nexus_memory.json")


def _empty():
    return {"name": "", "facts": {}, "updated": 0}


def load():
    with _lock:
        try:
            p = _path()
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    data.setdefault("name", "")
                    data.setdefault("facts", {})
                    data.setdefault("updated", 0)
                    if not isinstance(data["facts"], dict):
                        data["facts"] = {}
                    return data
        except Exception:
            pass
        return _empty()


def save(data):
    with _lock:
        try:
            p = _path()
            directory = os.path.dirname(p)
            if directory:
                os.makedirs(directory, exist_ok=True)
            data["updated"] = time.time()
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
            return True
        except Exception:
            return False


# ---- high level helpers --------------------------------------------
def get_name():
    return (load().get("name") or "").strip()


def set_name(name):
    data = load()
    data["name"] = (name or "").strip()
    save(data)
    return data["name"]


def remember(key, value):
    key = (key or "").strip()
    if not key:
        return None
    data = load()
    data["facts"][key] = ("" if value is None else str(value)).strip()
    save(data)
    return {"key": key, "value": data["facts"][key]}


def forget(key):
    key = (key or "").strip()
    data = load()
    existed = key in data["facts"]
    if existed:
        del data["facts"][key]
        save(data)
    return existed


def clear():
    save(_empty())
    return True


def all_items():
    data = load()
    return {"name": data.get("name", ""), "facts": data.get("facts", {}),
            "updated": data.get("updated", 0)}


def as_prompt():
    """Return a system-prompt block describing what ARIA knows about the
    user, or an empty string if nothing is stored yet."""
    data = load()
    lines = []
    name = (data.get("name") or "").strip()
    if name:
        lines.append("- The user's name is " + name + ". Address them by name when natural.")
    facts = data.get("facts") or {}
    for k, v in facts.items():
        if v:
            lines.append("- " + str(k) + ": " + str(v))
        else:
            lines.append("- " + str(k))
    if not lines:
        return ""
    header = ("What you already know about the user (personal memory). "
              "Use it naturally; do not read it back as a list unless asked:")
    return header + "\n" + "\n".join(lines)
