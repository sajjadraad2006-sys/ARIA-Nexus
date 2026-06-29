"""
ARIA NEXUS — nexus_debug.py
Central, thread-safe debug logger with a UNIFIED timeline shared by the
backend AND every browser client. Wake-word / mic events coming from a remote
phone land in the SAME ordered log file as Whisper / LLM / TTS events on the
server — which is exactly what you need to debug the "second device" issues.

Backend usage:
    from nexus_debug import dlog, dtimer
    dlog("STT", "request", in_bytes=len(data))
    with dtimer("STT", "whisper"):
        resp = requests.post(...)

View the log:
    https://<jetson-ip>:5000/api/debug/log.txt?tail=300
    (or filter:  ?stage=WAKE   ?stage=STT   ?src=srv)
    Clear it:    https://<jetson-ip>:5000/api/debug/clear

Env switches (all default ON):
    NEXUS_DEBUG=0          -> disable everything (near-zero overhead)
    NEXUS_DEBUG_FILE=0     -> don't write to data/aria_debug.log
    NEXUS_DEBUG_CONSOLE=0  -> don't print to the server console
"""
import os
import time
import json
import threading
import datetime
from collections import deque

_LOCK = threading.Lock()
_RING = deque(maxlen=4000)
_T0 = time.monotonic()

_LOG_DIR = os.environ.get("NEXUS_DEBUG_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data")
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    pass
_LOG_PATH = os.path.join(_LOG_DIR, "aria_debug.log")

_ENABLED = os.environ.get("NEXUS_DEBUG", "1") != "0"
_TO_FILE = os.environ.get("NEXUS_DEBUG_FILE", "1") != "0"
_TO_CONSOLE = os.environ.get("NEXUS_DEBUG_CONSOLE", "1") != "0"

_RESERVED = ("t", "wall", "ct", "cwall", "src", "stage", "event")


def _now_ms():
    return round((time.monotonic() - _T0) * 1000.0, 1)


def _emit(rec):
    with _LOCK:
        _RING.append(rec)
        if _TO_FILE:
            try:
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception:
                pass
    if _TO_CONSOLE:
        try:
            extra = " ".join(
                "%s=%s" % (k, v) for k, v in rec.items() if k not in _RESERVED)
            print("[%9.1f] %-4s %-6s %-18s %s" % (
                rec.get("t", 0.0), rec.get("src", "?"),
                rec.get("stage", "?"), rec.get("event", "?"), extra))
        except Exception:
            pass


def dlog(stage, event, src="srv", **fields):
    """Log one event from the backend."""
    if not _ENABLED:
        return
    rec = {
        "t": _now_ms(),
        "wall": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "src": src,
        "stage": str(stage),
        "event": str(event),
    }
    for k, v in fields.items():
        rec[k] = v
    _emit(rec)


class dtimer:
    """Context manager: logs <stage>/<event>.start then .done with ms=elapsed."""

    def __init__(self, stage, event, **fields):
        self.stage = stage
        self.event = event
        self.fields = fields
        self.t0 = 0.0

    def __enter__(self):
        self.t0 = time.monotonic()
        dlog(self.stage, self.event + ".start", **self.fields)
        return self

    def __exit__(self, exc_type, exc, tb):
        f = dict(self.fields)
        f["ms"] = round((time.monotonic() - self.t0) * 1000.0, 1)
        if exc_type is not None:
            f["error"] = repr(exc)
        dlog(self.stage, self.event + ".done", **f)
        return False


def ingest_client(events):
    """Merge a batch of browser events into the unified timeline."""
    if not _ENABLED or not isinstance(events, list):
        return 0
    n = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        rec = {
            "t": _now_ms(),                # server arrival time
            "ct": ev.get("t"),            # client monotonic ms
            "wall": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "cwall": ev.get("cwall"),     # client wall clock
            "src": ev.get("src") or "cli",
            "stage": str(ev.get("stage", "?")),
            "event": str(ev.get("event", "?")),
        }
        data = ev.get("data")
        if isinstance(data, dict):
            for k, v in data.items():
                if k not in rec:
                    rec[k] = v
        _emit(rec)
        n += 1
    return n


def recent(tail=200, stage=None, src=None):
    with _LOCK:
        items = list(_RING)
    if stage:
        items = [r for r in items if r.get("stage") == stage]
    if src:
        items = [r for r in items if r.get("src") == src]
    return items[-int(tail):]


def clear():
    with _LOCK:
        _RING.clear()
        try:
            if os.path.exists(_LOG_PATH):
                os.replace(_LOG_PATH, _LOG_PATH + ".prev")
        except Exception:
            pass


def register_routes(bp):
    """Attach /api/debug/* routes to a Flask blueprint (or app).
    Call once from nexus_routes_additions.py:  register_debug_routes(nexus_bp)
    """
    from flask import request, jsonify, Response

    @bp.route("/api/debug/client", methods=["POST"])
    def _debug_client():
        try:
            body = request.get_json(force=True, silent=True) or {}
            n = ingest_client(body.get("events") or [])
            return jsonify({"ok": True, "ingested": n})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 200

    @bp.route("/api/debug/log", methods=["GET"])
    def _debug_log():
        tail = int(request.args.get("tail", 200))
        return jsonify({"events": recent(
            tail, request.args.get("stage") or None,
            request.args.get("src") or None)})

    @bp.route("/api/debug/log.txt", methods=["GET"])
    def _debug_log_txt():
        tail = int(request.args.get("tail", 300))
        rows = recent(tail, request.args.get("stage") or None,
                      request.args.get("src") or None)
        lines = []
        for r in rows:
            extra = " ".join("%s=%s" % (k, v) for k, v in r.items()
                             if k not in _RESERVED)
            cw = r.get("cwall") or r.get("wall") or ""
            lines.append("%-13s %-4s %-6s %-20s %s" % (
                cw, r.get("src", "?"), r.get("stage", "?"),
                r.get("event", "?"), extra))
        return Response("\n".join(lines), mimetype="text/plain")

    @bp.route("/api/debug/clear", methods=["GET", "POST"])
    def _debug_clear():
        clear()
        return jsonify({"ok": True})
