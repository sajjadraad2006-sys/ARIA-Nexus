# =====================================================================
#  ARIA NEXUS — web_action_manager.py
#  Persistent store + executor for user-defined HTTP "web actions".
#  Drop this file into your project and import WebActionManager.
#  No method raises to the caller — failures are returned as data.
# =====================================================================
import json
import os
import threading
import time
import uuid

try:
    import requests
except Exception:  # pragma: no cover - requests should be installed
    requests = None


class WebActionManager:
    """Manage a list of HTTP web actions persisted to a JSON file.

    Each action:
        {
          "id": str,
          "name": str,
          "url": str,
          "method": "GET|POST|PUT|PATCH|DELETE",
          "headers": dict,
          "body": str,
          "last_status": int|None,
          "last_triggered": iso-8601 str|None,
          "last_error": str|None
        }
    """

    def __init__(self, path="data/nexus_web_actions.json", timeout=10):
        self.path = path
        self.timeout = timeout
        self._lock = threading.Lock()
        self._actions = {}
        self._load()

    # ---- persistence -------------------------------------------------
    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    self._actions = {a["id"]: a for a in data if a.get("id")}
                elif isinstance(data, dict):
                    self._actions = data
        except Exception:
            # Corrupt or unreadable store — start clean rather than crash.
            self._actions = {}

    def _save(self):
        """Atomic write; never raises."""
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(list(self._actions.values()), fh, indent=2)
            os.replace(tmp, self.path)
            return True
        except Exception:
            return False

    # ---- CRUD --------------------------------------------------------
    def list(self):
        with self._lock:
            return list(self._actions.values())

    def get(self, action_id):
        with self._lock:
            return self._actions.get(action_id)

    def add(self, name, url, method="POST", headers=None, body=""):
        action = {
            "id": uuid.uuid4().hex,
            "name": (name or "Untitled").strip(),
            "url": (url or "").strip(),
            "method": (method or "POST").upper(),
            "headers": headers or {},
            "body": body or "",
            "last_status": None,
            "last_triggered": None,
            "last_error": None,
        }
        with self._lock:
            self._actions[action["id"]] = action
            self._save()
        return action

    def update(self, action_id, fields):
        with self._lock:
            action = self._actions.get(action_id)
            if not action:
                return None
            for key in ("name", "url", "method", "headers", "body"):
                if key in fields and fields[key] is not None:
                    action[key] = fields[key].upper() if key == "method" else fields[key]
            self._save()
            return action

    def delete(self, action_id):
        with self._lock:
            existed = action_id in self._actions
            self._actions.pop(action_id, None)
            self._save()
            return existed

    # ---- execution ---------------------------------------------------
    def trigger_action(self, action_id):
        """Execute the stored HTTP request. Always returns a dict."""
        action = self.get(action_id)
        if not action:
            return {"ok": False, "error": "Action not found"}
        if requests is None:
            return {"ok": False, "error": "python 'requests' library not available"}

        method = (action.get("method") or "POST").upper()
        url = action.get("url") or ""
        headers = action.get("headers") or {}
        body = action.get("body") or ""

        result = {"ok": False, "status_code": None, "response_body": "", "error": None}
        try:
            kwargs = {"headers": headers, "timeout": self.timeout}
            if method not in ("GET", "DELETE") and body:
                kwargs["data"] = body.encode("utf-8") if isinstance(body, str) else body
            resp = requests.request(method, url, **kwargs)
            result["status_code"] = resp.status_code
            result["response_body"] = (resp.text or "")[:2000]
            result["ok"] = 200 <= resp.status_code < 400
            if not result["ok"]:
                result["error"] = "HTTP %s" % resp.status_code
        except Exception as exc:  # network failure, timeout, bad URL, etc.
            result["error"] = str(exc)

        # Record outcome (best-effort).
        with self._lock:
            stored = self._actions.get(action_id)
            if stored:
                stored["last_status"] = result["status_code"]
                stored["last_triggered"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                stored["last_error"] = result["error"]
                self._save()
        return result
