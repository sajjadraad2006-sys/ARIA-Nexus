"""
iot_controller.py — ARIA ↔ Home Assistant Bridge
=================================================
100 % local — communicates with Home Assistant via its REST API and
WebSocket API using a Long-Lived Access Token.

Features
--------
* Fetch all entity states or a single entity.
* Call any HA service (turn_on, turn_off, toggle, set_value …).
* Return a curated list of switches / lights / sensors for the UI.
* Subscribe to real-time state-change events over WebSocket and
  forward them to the Flask app through a callback function.
"""

import json
import os
import threading
import time
import requests

# Optional — websocket-client is NOT in stdlib; if missing, the
# real-time subscription feature is gracefully disabled.
try:
    import websocket as _ws_mod          # pip install websocket-client
    _HAS_WS = True
except ImportError:
    _HAS_WS = False


# ──────────────────────────────────────────────────────────────────
#  HAController
# ──────────────────────────────────────────────────────────────────
class HAController:
    """Bridge between ARIA and a local Home Assistant instance."""

    # Entity-domain whitelist for the Smart Home dashboard
    UI_DOMAINS = {"switch", "light", "sensor", "binary_sensor",
                  "input_boolean", "fan", "cover", "climate"}

    # ── init ──────────────────────────────────────────────────────
    def __init__(self, ha_url: str, ha_token: str, timeout: int = 10,
                 on_state_changed=None):
        """
        Parameters
        ----------
        ha_url : str
            Base URL of Home Assistant (e.g. ``http://192.168.1.X:8123``).
        ha_token : str
            Long-Lived Access Token generated in HA.
        timeout : int
            HTTP request timeout in seconds.
        on_state_changed : callable | None
            ``fn(entity_id, new_state_dict)`` — called on every
            real-time state-change event received via WebSocket.
        """
        self.base_url = ha_url.rstrip("/")
        self.token    = ha_token
        self.timeout  = timeout

        # Persistent HTTP session — connection pooling
        self._http = requests.Session()
        self._http.headers.update({
            "Authorization":  f"Bearer {self.token}",
            "Content-Type":   "application/json",
            "Connection":     "keep-alive",
        })

        # WebSocket real-time subscription
        self._on_state_changed = on_state_changed
        self._ws: "_ws_mod.WebSocketApp | None" = None
        self._ws_thread: threading.Thread | None = None
        self._ws_alive = False
        self._ws_id = 1          # HA WS message id counter

    # ── health check ──────────────────────────────────────────────
    def is_available(self) -> bool:
        """Return True if HA responds on ``/api/``."""
        try:
            r = self._http.get(f"{self.base_url}/api/",
                               timeout=self.timeout)
            return r.ok
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────
    #  REST API — Entity States
    # ──────────────────────────────────────────────────────────────
    def get_states(self) -> list[dict]:
        """Fetch ALL entity states from ``/api/states``.

        Returns a list of HA state objects (dicts) or an empty list
        on error.
        """
        try:
            r = self._http.get(f"{self.base_url}/api/states",
                               timeout=self.timeout)
            if r.ok:
                return r.json()
            print(f"[IoT] GET /api/states → HTTP {r.status_code}")
        except requests.exceptions.ConnectionError:
            print("[IoT] Connection refused — is Home Assistant running?")
        except requests.exceptions.Timeout:
            print(f"[IoT] Timeout fetching states ({self.timeout}s)")
        except Exception as exc:
            print(f"[IoT] get_states error: {exc}")
        return []

    def get_entity_state(self, entity_id: str) -> dict | None:
        """Fetch a single entity's state from
        ``/api/states/<entity_id>``.

        Returns the state dict or ``None`` on error.
        """
        try:
            r = self._http.get(
                f"{self.base_url}/api/states/{entity_id}",
                timeout=self.timeout,
            )
            if r.ok:
                return r.json()
            print(f"[IoT] GET state({entity_id}) → HTTP {r.status_code}")
        except Exception as exc:
            print(f"[IoT] get_entity_state error: {exc}")
        return None

    # ──────────────────────────────────────────────────────────────
    #  REST API — Service Calls
    # ──────────────────────────────────────────────────────────────
    def call_service(self, domain: str, service: str,
                     entity_id: str | None = None,
                     data: dict | None = None) -> bool:
        """Call a HA service via ``POST /api/services/<domain>/<service>``.

        Parameters
        ----------
        domain : str       e.g. ``"switch"``, ``"light"``
        service : str      e.g. ``"turn_on"``, ``"turn_off"``, ``"toggle"``
        entity_id : str    e.g. ``"switch.irrigation_relay"``
        data : dict | None Extra service data (brightness, temperature …)

        Returns True on success, False otherwise.
        """
        payload = dict(data) if data else {}
        if entity_id:
            payload["entity_id"] = entity_id

        url = f"{self.base_url}/api/services/{domain}/{service}"
        try:
            r = self._http.post(url, json=payload, timeout=self.timeout)
            if r.ok:
                print(f"[IoT] ✅ {domain}.{service}({entity_id})")
                return True
            print(f"[IoT] Service call → HTTP {r.status_code}: "
                  f"{r.text[:200]}")
        except requests.exceptions.ConnectionError:
            print("[IoT] Connection refused — HA not reachable")
        except requests.exceptions.Timeout:
            print(f"[IoT] Service call timed out ({self.timeout}s)")
        except Exception as exc:
            print(f"[IoT] call_service error: {exc}")
        return False

    # Convenience shortcuts
    def turn_on(self, entity_id: str, **kwargs) -> bool:
        domain = entity_id.split(".")[0]
        return self.call_service(domain, "turn_on", entity_id, kwargs or None)

    def turn_off(self, entity_id: str, **kwargs) -> bool:
        domain = entity_id.split(".")[0]
        return self.call_service(domain, "turn_off", entity_id, kwargs or None)

    def toggle(self, entity_id: str) -> bool:
        domain = entity_id.split(".")[0]
        return self.call_service(domain, "toggle", entity_id)

    # ──────────────────────────────────────────────────────────────
    #  Virtual Device Creation — Input Boolean helpers (WebSocket)
    # ──────────────────────────────────────────────────────────────
    def create_input_boolean(self, friendly_name: str) -> tuple[bool, str]:
        """Create a new Input Boolean helper in Home Assistant.

        Uses the **WebSocket API** command ``input_boolean/create``
        which is the only reliable method for external clients using
        Long-Lived Access Tokens.  The REST Config API restricts
        CRUD operations for helpers when accessed via token auth.

        After sending the WS command, polls ``get_entity_state()``
        up to 10 times (200 ms apart) to confirm the entity has
        materialized in the HA state machine before returning.

        The friendly_name may contain a ``[Room]`` suffix (e.g.
        ``"Red Light [Living Room]"``).  The slug is derived from the
        base name only so entity IDs stay clean.
        """
        import re as _re

        # Strip "[Room]" suffix for slug generation, keep full name as friendly
        base_name = _re.sub(r'\s*\[[^\]]*\]\s*$', '', friendly_name).strip()
        slug = _re.sub(r"[^a-z0-9]+", "_",
                       base_name.lower()).strip("_")
        if not slug:
            return False, "Invalid device name"
        entity_id = f"input_boolean.{slug}"

        # ── Guard: WebSocket must be connected ──
        if not self._ws_alive or not self._ws:
            print("[IoT] WebSocket not connected — cannot create helper")
            return False, "WebSocket not connected to Home Assistant"

        # ── Send WS command: input_boolean/create ──
        ws_msg = {
            "id":   self._next_ws_id(),
            "type": "input_boolean/create",
            "name": friendly_name,
            "icon": "mdi:toggle-switch-outline",
        }
        try:
            self._ws.send(json.dumps(ws_msg))
            print(f"[IoT-WS] Sent input_boolean/create for "
                  f"{friendly_name!r} (id={ws_msg['id']})")
        except Exception as exc:
            print(f"[IoT-WS] Failed to send create command: {exc}")
            return False, f"WebSocket send failed: {exc}"

        # ── Poll for entity to appear in the state machine ──
        for attempt in range(1, 11):
            time.sleep(0.2)
            state = self.get_entity_state(entity_id)
            if state:
                print(f"[IoT] ✅ Created {entity_id} via WebSocket "
                      f"(confirmed after {attempt * 200}ms)")
                return True, entity_id

        # Entity didn't appear within 2 s — may still be processing
        print(f"[IoT] ⚠️ WS command sent but {entity_id} not yet in "
              f"state machine after 2s — returning optimistically")
        return True, entity_id

    # ──────────────────────────────────────────────────────────────
    #  Device Deletion (WebSocket)
    # ──────────────────────────────────────────────────────────────
    def delete_device(self, entity_id: str) -> tuple[bool, str]:
        """Delete a virtual input_boolean helper from Home Assistant.

        Uses the **WebSocket API** command ``input_boolean/delete``
        which is the only reliable method for external clients.

        Returns ``(success, message)``.
        """
        if not entity_id or "." not in entity_id:
            return False, "Invalid entity_id"

        domain, slug = entity_id.split(".", 1)
        if domain != "input_boolean":
            return False, "Only virtual input_boolean devices can be deleted"

        # ── Guard: WebSocket must be connected ──
        if not self._ws_alive or not self._ws:
            print("[IoT] WebSocket not connected — cannot delete helper")
            return False, "WebSocket not connected to Home Assistant"

        # ── Send WS command: input_boolean/delete ──
        ws_msg = {
            "id":                self._next_ws_id(),
            "type":              "input_boolean/delete",
            "input_boolean_id":  slug,
        }
        try:
            self._ws.send(json.dumps(ws_msg))
            print(f"[IoT-WS] Sent input_boolean/delete for {entity_id} "
                  f"(id={ws_msg['id']})")
            return True, f"Deleted {entity_id}"
        except Exception as exc:
            print(f"[IoT-WS] Failed to send delete command: {exc}")
            return False, f"WebSocket send failed: {exc}"

    # ──────────────────────────────────────────────────────────────
    #  Device Rename / Update Friendly Name (WebSocket)
    # ──────────────────────────────────────────────────────────────
    def update_friendly_name(self, entity_id: str,
                             new_name: str) -> tuple[bool, str]:
        """Update the friendly_name of an input_boolean entity.

        Uses the **WebSocket API** command ``input_boolean/update``
        which is the only reliable method for external clients.

        For non-input_boolean entities, falls back to overwriting
        attributes via the REST state API.
        """
        if not entity_id or not new_name:
            return False, "entity_id and new_name are required"

        domain = entity_id.split(".")[0] if "." in entity_id else ""
        slug = entity_id.split(".", 1)[1] if "." in entity_id else ""

        # ── WebSocket API (input_boolean only) ──
        if domain == "input_boolean":
            if not self._ws_alive or not self._ws:
                print("[IoT] WebSocket not connected — cannot rename helper")
                return False, "WebSocket not connected to Home Assistant"

            ws_msg = {
                "id":                self._next_ws_id(),
                "type":              "input_boolean/update",
                "input_boolean_id":  slug,
                "name":              new_name,
            }
            try:
                self._ws.send(json.dumps(ws_msg))
                print(f"[IoT-WS] Sent input_boolean/update for "
                      f"{entity_id} → {new_name!r} (id={ws_msg['id']})")
                return True, new_name
            except Exception as exc:
                print(f"[IoT-WS] Failed to send update command: {exc}")
                return False, f"WebSocket send failed: {exc}"

        # ── Fallback for non-input_boolean: overwrite state attrs ──
        current = self.get_entity_state(entity_id)
        if not current:
            return False, "Entity not found"

        attrs = dict(current.get("attributes", {}))
        attrs["friendly_name"] = new_name
        state_url = f"{self.base_url}/api/states/{entity_id}"
        try:
            r = self._http.post(state_url, json={
                "state": current.get("state", "unknown"),
                "attributes": attrs,
            }, timeout=self.timeout)
            if r.ok:
                print(f"[IoT] ✅ Renamed {entity_id} → {new_name!r} "
                      f"(state API)")
                return True, new_name
            return False, f"HA returned HTTP {r.status_code}"
        except Exception as exc:
            print(f"[IoT] Rename error: {exc}")
            return False, str(exc)

    # ──────────────────────────────────────────────────────────────
    #  Device Info / Attributes
    # ──────────────────────────────────────────────────────────────
    def get_entity_attributes(self, entity_id: str) -> dict | None:
        """Return a rich dict of entity attributes for the settings UI."""
        state = self.get_entity_state(entity_id)
        if not state:
            return None
        attrs = state.get("attributes", {})
        return {
            "entity_id":          entity_id,
            "domain":             entity_id.split(".")[0] if "." in entity_id else "",
            "state":              state.get("state", "unknown"),
            "friendly_name":     attrs.get("friendly_name", entity_id),
            "icon":              attrs.get("icon", ""),
            "device_class":      attrs.get("device_class", ""),
            "unit_of_measurement": attrs.get("unit_of_measurement", ""),
            "editable":          attrs.get("editable", False),
            "last_changed":      state.get("last_changed", ""),
            "last_updated":      state.get("last_updated", ""),
        }

    # ──────────────────────────────────────────────────────────────
    #  UI-Friendly Filtered Device List
    # ──────────────────────────────────────────────────────────────
    def get_filtered_devices(self) -> list[dict]:
        """Return a curated list of devices for the Smart Home dashboard.

        Each item is a simplified dict::

            {
                "entity_id":   "switch.irrigation",
                "domain":      "switch",
                "name":        "Irrigation",
                "state":       "on",
                "icon":        "💧",
                "is_toggle":   True,       # can be toggled
                "attributes":  { … },      # unit_of_measurement, etc.
            }
        """
        all_states = self.get_states()
        devices: list[dict] = []

        for entity in all_states:
            eid: str = entity.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else ""
            if domain not in self.UI_DOMAINS:
                continue

            attrs = entity.get("attributes", {})
            friendly = attrs.get("friendly_name", eid)
            state    = entity.get("state", "unknown")

            filtered_attrs = {
                k: v for k, v in attrs.items()
                if k in ("unit_of_measurement", "device_class",
                         "friendly_name", "brightness",
                         "current_temperature", "temperature",
                         "humidity", "icon", "editable")
            }
            filtered_attrs["entity_id"] = eid  # always include for UI

            devices.append({
                "entity_id":  eid,
                "domain":     domain,
                "name":       friendly,
                "state":      state,
                "icon":       self._pick_icon(domain, attrs, state),
                "is_toggle":  domain in ("switch", "light", "input_boolean",
                                         "fan", "cover"),
                "is_virtual": domain == "input_boolean",
                "attributes": filtered_attrs,
            })

        # Sort: toggleables first, then sensors; alphabetical within
        devices.sort(key=lambda d: (0 if d["is_toggle"] else 1, d["name"]))
        return devices

    @staticmethod
    def _pick_icon(domain: str, attrs: dict, state: str) -> str:
        """Choose an emoji icon based on domain and device class."""
        dc = attrs.get("device_class", "")
        if domain == "light":
            return "💡"
        if domain in ("switch", "input_boolean"):
            if "irrigation" in dc or "water" in dc:
                return "💧"
            if "power" in dc:
                return "⚡"
            return "🔌"
        if domain == "sensor":
            if dc == "temperature":
                return "🌡️"
            if dc == "humidity":
                return "💧"
            if dc == "battery":
                return "🔋"
            if dc in ("power", "energy"):
                return "⚡"
            if dc == "illuminance":
                return "☀️"
            return "📊"
        if domain == "binary_sensor":
            if dc == "motion":
                return "🏃"
            if dc in ("door", "window", "opening"):
                return "🚪"
            if dc == "moisture":
                return "💧"
            return "🔔"
        if domain == "fan":
            return "🌀"
        if domain == "cover":
            return "🪟"
        if domain == "climate":
            return "❄️"
        return "📟"

    # ──────────────────────────────────────────────────────────────
    #  WebSocket — Real-time State Subscription
    # ──────────────────────────────────────────────────────────────
    def start_ws_subscription(self) -> None:
        """Connect to HA WebSocket API and subscribe to state_changed
        events.  Runs in a background daemon thread.

        Requires ``pip install websocket-client``.
        """
        if not _HAS_WS:
            print("[IoT] websocket-client not installed — "
                  "real-time updates disabled.  "
                  "Install with: pip install websocket-client")
            return

        if self._ws_alive:
            print("[IoT] WS already running")
            return

        ws_url = self.base_url.replace("http://", "ws://") \
                               .replace("https://", "wss://") \
                 + "/api/websocket"

        def _on_open(ws):
            print(f"[IoT-WS] Connected to {ws_url}")

        def _on_message(ws, raw):
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                return

            msg_type = msg.get("type", "")

            # Step 1: HA sends auth_required → we authenticate
            if msg_type == "auth_required":
                ws.send(json.dumps({
                    "type": "auth",
                    "access_token": self.token,
                }))
                return

            # Step 2: auth_ok → subscribe to state_changed events
            if msg_type == "auth_ok":
                print("[IoT-WS] ✅ Authenticated — subscribing to events")
                self._ws_alive = True
                sub_msg = {
                    "id":         self._next_ws_id(),
                    "type":       "subscribe_events",
                    "event_type": "state_changed",
                }
                ws.send(json.dumps(sub_msg))
                return

            if msg_type == "auth_invalid":
                print(f"[IoT-WS] ❌ Auth failed: {msg.get('message')}")
                ws.close()
                return

            # Step 3: relay state_changed events to the callback
            if msg_type == "event":
                event_data = msg.get("event", {}).get("data", {})
                entity_id  = event_data.get("entity_id", "")
                new_state  = event_data.get("new_state")
                if entity_id and new_state and self._on_state_changed:
                    self._on_state_changed(entity_id, new_state)

        def _on_error(ws, err):
            print(f"[IoT-WS] Error: {err}")

        def _on_close(ws, code, reason):
            self._ws_alive = False
            print(f"[IoT-WS] Closed (code={code}, reason={reason})")
            # Auto-reconnect after 10 s
            time.sleep(10)
            if not self._ws_alive:
                print("[IoT-WS] Reconnecting…")
                self._start_ws_loop(ws_url, _on_open, _on_message,
                                    _on_error, _on_close)

        self._start_ws_loop(ws_url, _on_open, _on_message,
                            _on_error, _on_close)

    def _start_ws_loop(self, url, on_open, on_message, on_error, on_close):
        """Spawn a daemon thread running the WS event loop."""
        self._ws = _ws_mod.WebSocketApp(
            url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self._ws_thread = threading.Thread(
            target=self._ws.run_forever,
            kwargs={"ping_interval": 30, "ping_timeout": 10},
            daemon=True,
        )
        self._ws_thread.start()

    def stop_ws_subscription(self) -> None:
        """Cleanly shut down the WebSocket connection."""
        self._ws_alive = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _next_ws_id(self) -> int:
        """HA requires a monotonically increasing id per WS message."""
        wid = self._ws_id
        self._ws_id += 1
        return wid


# ──────────────────────────────────────────────────────────────────
#  GenericDeviceManager — Direct LAN control for unsupported devices
# ──────────────────────────────────────────────────────────────────
class GenericDeviceManager:
    """Manage generic network devices (Tasmota / ESP8266 / ESP32) via
    direct HTTP commands, bypassing Home Assistant entirely.

    Devices are persisted in a JSON file so they survive server restarts.

    Each device has:
        ``id``, ``name``, ``ip``, ``room``, ``device_type``,
        ``channels`` (list), ``state`` (str or dict), ``protocol``.

    Supported device_type values:
        * ``switch``        — single on/off toggle (Power Toggle)
        * ``dimmer``        — brightness 0-100% (Dimmer <val>)
        * ``fan``           — speed 1-3, 0=off (FanSpeed <val>)
        * ``multi_channel`` — 2-4 independent channels (Power<N> Toggle)
    """

    VALID_TYPES = {"switch", "dimmer", "fan", "multi_channel"}

    def __init__(self, storage_path: str, http_timeout: int = 3):
        self._path = storage_path
        self._timeout = http_timeout
        self._lock = threading.Lock()
        self._devices: list[dict] = []
        self._mtime = 0.0
        self._load()

    # ── Persistence ───────────────────────────────────────────
    def _file_mtime(self) -> float:
        """Last-modified time of the store, or 0.0 if it does not exist yet."""
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    def _maybe_reload(self) -> None:
        """Re-read the store if it changed on disk since we last loaded it.

        The dashboard routes, the assistant brain and this manager all target
        the SAME canonical file (config.NEXUS_GENERIC_DEVICES_PATH). Any of
        them may write it, so we refresh on access whenever the mtime moves to
        avoid serving a stale in-memory device list.
        """
        try:
            mtime = self._file_mtime()
            if mtime and mtime != self._mtime:
                self._load()
        except Exception:
            pass

    def _load(self) -> None:
        """Load devices from the JSON file."""
        self._mtime = self._file_mtime()
        try:
            if os.path.isfile(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    # Migrate legacy devices that lack new fields
                    for d in data:
                        d.setdefault("room", "")
                        d.setdefault("device_type", "switch")
                        d.setdefault("channels", [])
                    self._devices = data
                    print(f"[GenDev] Loaded {len(data)} generic device(s) "
                          f"from {self._path}")
        except Exception as exc:
            print(f"[GenDev] Error loading {self._path}: {exc}")
            self._devices = []

    def _save(self) -> None:
        """Persist devices to the JSON file (atomic write)."""
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._devices, f, indent=2)
            os.replace(tmp, self._path)
            self._mtime = self._file_mtime()
        except Exception as exc:
            print(f"[GenDev] Error saving {self._path}: {exc}")
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ── CRUD ──────────────────────────────────────────────────
    def list_devices(self) -> list[dict]:
        """Return a copy of all generic devices."""
        with self._lock:
            self._maybe_reload()
            return [dict(d) for d in self._devices]

    def add_device(self, name: str, ip: str, room: str = "",
                   device_type: str = "switch",
                   channels: list[str] | None = None) -> tuple[bool, dict | str]:
        """Add a new generic device.

        Parameters
        ----------
        name        : Human-readable device name.
        ip          : LAN IPv4 address.
        room        : Optional room assignment (e.g. "Living Room").
        device_type : One of switch, dimmer, fan, multi_channel.
        channels    : For multi_channel only — list of sub-names
                      e.g. ["Chandelier", "Spotlights", "LED Strip"].

        Returns ``(True, device_dict)`` on success or
        ``(False, error_message)`` on failure.
        """
        import re as _re

        name = name.strip()
        ip = ip.strip()
        room = (room or "").strip()
        device_type = (device_type or "switch").strip().lower()
        channels = channels or []

        if not name:
            return False, "Device name cannot be empty"
        if not _re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
            return False, "Invalid IP address format"
        if device_type not in self.VALID_TYPES:
            return False, f"Invalid device_type: {device_type}"
        if device_type == "multi_channel":
            if not channels or len(channels) < 2 or len(channels) > 4:
                return False, "multi_channel requires 2-4 channel names"

        slug = _re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        dev_id = f"generic.{slug}"

        with self._lock:
            # Check for duplicate IP or ID
            for d in self._devices:
                if d["ip"] == ip:
                    return False, f"Device with IP {ip} already exists"
                if d["id"] == dev_id:
                    return False, f"Device '{name}' already exists"

            # Build initial state
            if device_type == "multi_channel":
                # Dict of channel states: {"1": "unknown", "2": "unknown", ...}
                state = {str(i + 1): "unknown" for i in range(len(channels))}
            elif device_type == "dimmer":
                state = "unknown"   # will hold "on"/"off" or a numeric string
            else:
                state = "unknown"

            device = {
                "id":          dev_id,
                "name":        name,
                "ip":          ip,
                "room":        room,
                "device_type": device_type,
                "channels":    channels,
                "state":       state,
                "protocol":    "tasmota",
            }
            self._devices.append(device)
            self._save()

        print(f"[GenDev] ✅ Added: {name} @ {ip} "
              f"(type={device_type}, room={room or '—'})")
        return True, device

    def delete_device(self, dev_id: str) -> tuple[bool, str]:
        """Delete a generic device by ID."""
        with self._lock:
            before = len(self._devices)
            self._devices = [d for d in self._devices if d["id"] != dev_id]
            if len(self._devices) < before:
                self._save()
                print(f"[GenDev] 🗑️ Deleted: {dev_id}")
                return True, f"Deleted {dev_id}"
        return False, f"Device {dev_id} not found"

    # ── Device Control (Tasmota HTTP API) ─────────────────────

    # ── Virtual device helper ─────────────────────────────────
    @staticmethod
    def _is_virtual(dev: dict) -> bool:
        """Return True if the device is a locally-simulated virtual device."""
        return bool(dev.get("virtual"))

    def _toggle_virtual(self, dev: dict,
                        channel: int | None = None) -> tuple[bool, str]:
        """Flip the in-memory state of a virtual device (no HTTP)."""
        with self._lock:
            dtype = dev.get("device_type", "switch")
            if dtype == "multi_channel" and channel is not None:
                if not isinstance(dev.get("state"), dict):
                    dev["state"] = {}
                cur = dev["state"].get(str(channel), "off")
                new = "off" if str(cur).lower() in ("on", "true") else "on"
                dev["state"][str(channel)] = new
            else:
                cur = dev.get("state", False)
                if isinstance(cur, bool):
                    new = "on" if not cur else "off"
                    dev["state"] = not cur
                else:
                    new = "off" if str(cur).lower() in ("on", "true") else "on"
                    dev["state"] = (new == "on")
            self._save()
        ch_label = f" ch{channel}" if channel else ""
        print(f"[GenDev] ✅ Toggled virtual {dev['name']}{ch_label} → {new}")
        return True, new

    def _set_virtual_state(self, dev: dict, desired: str,
                           channel: int | None = None) -> tuple[bool, str]:
        """Set the in-memory state of a virtual device (no HTTP)."""
        is_on = desired.strip().upper() == "ON"
        new = "on" if is_on else "off"
        with self._lock:
            dtype = dev.get("device_type", "switch")
            if dtype == "multi_channel" and channel is not None:
                if not isinstance(dev.get("state"), dict):
                    dev["state"] = {}
                dev["state"][str(channel)] = new
            else:
                dev["state"] = is_on
            self._save()
        ch_label = f" ch{channel}" if channel else ""
        print(f"[GenDev] ✅ Set virtual {dev['name']}{ch_label} → {new}")
        return True, new

    def toggle_device(self, dev_id: str,
                      channel: int | None = None) -> tuple[bool, str]:
        """Toggle a Tasmota device.

        For ``switch`` type:         ``Power Toggle``
        For ``multi_channel`` type:  ``Power<channel> Toggle``
        For ``dimmer``/``fan``:      ``Power Toggle`` (on/off)
        Virtual devices are toggled in-memory (no HTTP call).

        Returns ``(True, new_state)`` or ``(False, error)``.
        """
        dev = self._find(dev_id)
        if not dev:
            return False, f"Device {dev_id} not found"

        # ── Virtual: flip state in memory, no HTTP ──
        if self._is_virtual(dev):
            return self._toggle_virtual(dev, channel)

        dtype = dev.get("device_type", "switch")

        # Build the correct Tasmota command
        if dtype == "multi_channel" and channel is not None:
            cmd = f"Power{channel}+Toggle"
            power_key = f"POWER{channel}"
        else:
            cmd = "Power+Toggle"
            power_key = "POWER"

        url = f"http://{dev['ip']}/cm?cmnd={cmd}"
        try:
            r = requests.get(url, timeout=self._timeout)
            if r.ok:
                body = r.json()
                power = body.get(power_key,
                                 body.get("POWER",
                                          body.get("POWER1", "TOGGLE")))
                new_state = power.lower() if power else "unknown"

                with self._lock:
                    if dtype == "multi_channel" and channel is not None:
                        # Update individual channel state
                        if not isinstance(dev.get("state"), dict):
                            dev["state"] = {}
                        dev["state"][str(channel)] = new_state
                    else:
                        dev["state"] = new_state
                    self._save()

                ch_label = f" ch{channel}" if channel else ""
                print(f"[GenDev] ✅ Toggled {dev['name']}{ch_label}"
                      f" → {new_state}")
                return True, new_state
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, f"Device at {dev['ip']} not reachable"
        except requests.exceptions.Timeout:
            return False, f"Timeout connecting to {dev['ip']}"
        except Exception as exc:
            return False, str(exc)

    def set_device_state(self, dev_id: str, desired_state: str,
                         channel: int | None = None) -> tuple[bool, str]:
        """Set a device to an explicit state (ON or OFF).

        Unlike ``toggle_device`` which flips the current state, this
        sends ``Power ON`` or ``Power OFF`` to guarantee the outcome.
        Virtual devices are updated in-memory (no HTTP call).

        Parameters
        ----------
        desired_state : "on" or "off"
        channel       : For multi_channel devices, the channel number.

        Returns ``(True, new_state)`` or ``(False, error)``.
        """
        dev = self._find(dev_id)
        if not dev:
            return False, f"Device {dev_id} not found"

        desired = desired_state.strip().upper()
        if desired not in ("ON", "OFF"):
            return False, f"Invalid state: {desired_state} (must be on/off)"

        # ── Virtual: set state in memory, no HTTP ──
        if self._is_virtual(dev):
            return self._set_virtual_state(dev, desired, channel)

        dtype = dev.get("device_type", "switch")

        # Build the Tasmota command
        if dtype == "multi_channel" and channel is not None:
            cmd = f"Power{channel}+{desired}"
            power_key = f"POWER{channel}"
        else:
            cmd = f"Power+{desired}"
            power_key = "POWER"

        url = f"http://{dev['ip']}/cm?cmnd={cmd}"
        try:
            r = requests.get(url, timeout=self._timeout)
            if r.ok:
                body = r.json()
                power = body.get(power_key,
                                 body.get("POWER",
                                          body.get("POWER1", desired)))
                new_state = power.lower() if power else desired.lower()

                with self._lock:
                    if dtype == "multi_channel" and channel is not None:
                        if not isinstance(dev.get("state"), dict):
                            dev["state"] = {}
                        dev["state"][str(channel)] = new_state
                    else:
                        dev["state"] = new_state
                    self._save()

                ch_label = f" ch{channel}" if channel else ""
                print(f"[GenDev] ✅ Set {dev['name']}{ch_label}"
                      f" → {new_state}")
                return True, new_state
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, f"Device at {dev['ip']} not reachable"
        except requests.exceptions.Timeout:
            return False, f"Timeout connecting to {dev['ip']}"
        except Exception as exc:
            return False, str(exc)

    def send_command(self, dev_id: str, command: str,
                     value: int) -> tuple[bool, str]:
        """Send a specific command to a device.

        Supported commands:
            ``dimmer``  → ``Dimmer <value>``   (0-100)
            ``fan``     → ``FanSpeed <value>``  (0-3)

        Returns ``(True, result)`` or ``(False, error)``.
        """
        dev = self._find(dev_id)
        if not dev:
            return False, f"Device {dev_id} not found"

        command = command.lower().strip()

        if command == "dimmer":
            value = max(0, min(100, int(value)))
            tasmota_cmd = f"Dimmer+{value}"
        elif command == "fan":
            value = max(0, min(3, int(value)))
            tasmota_cmd = f"FanSpeed+{value}"
        else:
            return False, f"Unknown command: {command}"

        url = f"http://{dev['ip']}/cm?cmnd={tasmota_cmd}"
        try:
            r = requests.get(url, timeout=self._timeout)
            if r.ok:
                body = r.json()

                with self._lock:
                    if command == "dimmer":
                        # Dimmer > 0 means device is ON
                        dev["state"] = "on" if value > 0 else "off"
                    elif command == "fan":
                        dev["state"] = "on" if value > 0 else "off"
                    self._save()

                print(f"[GenDev] ✅ {command}({dev['name']}) = {value}")
                return True, str(value)
            return False, f"HTTP {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, f"Device at {dev['ip']} not reachable"
        except requests.exceptions.Timeout:
            return False, f"Timeout connecting to {dev['ip']}"
        except Exception as exc:
            return False, str(exc)

    def get_device_state(self, dev_id: str) -> tuple[bool, str]:
        """Query current power state of a Tasmota device."""
        dev = self._find(dev_id)
        if not dev:
            return False, "not found"

        url = f"http://{dev['ip']}/cm?cmnd=Power"
        try:
            r = requests.get(url, timeout=self._timeout)
            if r.ok:
                body = r.json()
                power = body.get("POWER", body.get("POWER1", "unknown"))
                new_state = power.lower() if power else "unknown"
                with self._lock:
                    dev["state"] = new_state
                    self._save()
                return True, new_state
            return False, f"HTTP {r.status_code}"
        except Exception:
            return False, "unreachable"

    def _find(self, dev_id: str) -> dict | None:
        """Find a device by ID or by name (returns reference — caller may
        mutate).  Name-based lookup is tried as a fallback when the exact
        ID is not found, since virtual devices use opaque UUIDs that the
        LLM cannot predict."""
        self._maybe_reload()
        # 1) Exact ID match
        for d in self._devices:
            if d["id"] == dev_id:
                return d
        # 2) Fallback: case-insensitive name match
        dev_id_lower = dev_id.lower().replace("generic.", "").replace("_", " ")
        for d in self._devices:
            if d.get("name", "").lower() == dev_id_lower:
                return d
        return None
