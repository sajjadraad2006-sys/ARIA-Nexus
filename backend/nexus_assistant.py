# =====================================================================
#  nexus_assistant.py  --  ARIA Nexus "Assistant Brain"
#
#  A single, fully-local intent layer that sits in front of the LLM.
#  Every utterance from the chatbot OR the talking face passes through
#  handle_command(). The brain decides, in order:
#
#    1. SMART HOME   -> deterministic Arabic/English parsing of phrases
#                       like "طفّي الضوء" / "turn off the light" and a
#                       DIRECT Home Assistant service call.
#    2. PERSONAL MEM -> remembers / recalls the user's name, prefs, facts.
#    3. ROUTINES     -> trigger phrases such as "صباح الخير" run a chain
#                       of steps (weather + news + schedule + scenes).
#    4. CHAT         -> falls back to the local LLM, with personal memory
#                       injected into the system prompt, and any
#                       [IOT:...] tags the model emits are executed.
#
#  Everything degrades gracefully when Home Assistant / network / LLM
#  are unreachable, so the box never crashes a request.
# =====================================================================
import json
import os
import re
import time

try:
    import requests
except Exception:
    requests = None

try:
    import nexus_memory as MEM
except Exception:
    MEM = None

try:
    import nexus_rag_store as RAGS
except Exception:
    RAGS = None


# =====================================================================
#  Config access (HA + LLM + locations)
# =====================================================================
def _cfg(attr, default=None):
    try:
        import config as c
        return getattr(c, attr, default)
    except Exception:
        return default


def _ha_url():
    url = os.environ.get("HA_URL") or _cfg("HA_URL") or "http://127.0.0.1:8123"
    return url.rstrip("/")


def _ha_token():
    return (os.environ.get("HA_TOKEN") or os.environ.get("HASS_TOKEN")
            or _cfg("HA_TOKEN") or _cfg("HASS_TOKEN") or "")


def _ha_headers():
    h = {"Content-Type": "application/json"}
    tok = _ha_token()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def _llm_url():
    return (_cfg("LLAMA_URL") or "http://127.0.0.1:8080").rstrip("/")


# =====================================================================
#  Arabic / text normalisation
# =====================================================================
_AR_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def _norm(text):
    """Lower-case, strip Arabic diacritics, unify alef/ya/ta-marbuta and
    collapse whitespace so matching is robust to spelling variants."""
    if not text:
        return ""
    t = str(text).strip().lower()
    t = _AR_DIACRITICS.sub("", t)
    t = t.replace("\u0623", "\u0627").replace("\u0625", "\u0627").replace("\u0622", "\u0627")  # hamza alefs -> alef
    t = t.replace("\u0649", "\u064a")   # alef maqsura -> ya
    t = t.replace("\u0629", "\u0647")   # ta marbuta -> ha
    t = t.replace("\u0640", "")          # tatweel
    t = re.sub(r"\s+", " ", t)
    return t


def _has(text, words):
    return any(w in text for w in words)


# =====================================================================
#  SMART HOME  (deterministic phrase -> Home Assistant service call)
# =====================================================================
# action keyword -> HA service
OFF_WORDS = ["turn off", "switch off", "shut", "power off", "طفي", "طفئ", "اطفي",
             "اطفئ", "سكر", "سد", "سدها", "بطل", "وقف"]
ON_WORDS = ["turn on", "switch on", "power on", "شغل", "اشغل", "افتح", "ولع",
            "شعل", "فعل", "چعل"]
TOGGLE_WORDS = ["toggle", "بدل", "عكس", "اعكس"]
ALL_WORDS = ["all", "everything", "كل", "الكل", "جميع", "كلهن", "كلهم"]

# device alias -> HA domain.  Order matters (first match wins for domain).
DOMAIN_ALIASES = [
    ("light",   ["light", "lights", "lamp", "ضوء", "الضوء", "ضو", "الضو", "لمبه",
                 "لمبة", "ليت", "نور", "النور", "اضاءه", "الاضاءه", "ابليكه"]),
    ("fan",     ["fan", "مروحه", "المروحه", "بنكه", "پنکه"]),
    ("climate", ["climate", "ac", "air conditioner", "تكييف", "التكييف", "مكيف",
                 "المكيف", "اي سي", "كولر", "الكولر", "سبليت"]),
    ("cover",   ["cover", "curtain", "curtains", "blind", "ستاره", "الستاره",
                 "ستائر", "الستائر", "بردايه", "شتر"]),
    ("switch",  ["switch", "plug", "socket", "relay", "مفتاح", "المفتاح", "سويچ",
                 "سويتش", "رلي", "الرلي", "بريز", "مأخذ"]),
]


def ha_available():
    if requests is None:
        return False
    try:
        r = requests.get(_ha_url() + "/api/", headers=_ha_headers(), timeout=3)
        return r.ok
    except Exception:
        return False


def ha_states():
    """Return list of HA state dicts, or [] on any error."""
    if requests is None:
        return []
    try:
        r = requests.get(_ha_url() + "/api/states", headers=_ha_headers(), timeout=5)
        if r.ok:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def ha_call(domain, service, entity_id=None, data=None):
    """Call a Home Assistant service. Returns (ok, error_str)."""
    if requests is None:
        return False, "requests unavailable"
    payload = dict(data) if data else {}
    if entity_id:
        payload["entity_id"] = entity_id
    url = _ha_url() + "/api/services/" + domain + "/" + service
    try:
        r = requests.post(url, headers=_ha_headers(), json=payload, timeout=6)
        if r.ok:
            return True, ""
        return False, "HTTP " + str(r.status_code)
    except Exception as exc:
        return False, str(exc)


def _service_for(text_norm):
    if _has(text_norm, OFF_WORDS):
        return "turn_off"
    if _has(text_norm, TOGGLE_WORDS):
        return "toggle"
    if _has(text_norm, ON_WORDS):
        return "turn_on"
    return None


def _entity_friendly(st):
    attrs = st.get("attributes") or {}
    return attrs.get("friendly_name") or st.get("entity_id", "")


def _match_smart_home(text_norm, states):
    """Resolve (service, [entity_ids], label) from an utterance, or None."""
    service = _service_for(text_norm)
    if not service:
        return None

    controllable = {"light", "switch", "fan", "climate", "cover", "input_boolean"}
    ents = [s for s in states
            if (s.get("entity_id", "").split(".")[0] in controllable)]

    want_all = _has(text_norm, ALL_WORDS)

    # 1) Try to match a specific entity by its friendly name appearing in text.
    if not want_all:
        best = None
        best_len = 0
        for s in ents:
            fname = _norm(_entity_friendly(s))
            if fname and len(fname) >= 3 and fname in text_norm and len(fname) > best_len:
                best = s
                best_len = len(fname)
        if best is not None:
            return service, [best["entity_id"]], _entity_friendly(best)

    # 2) Match by domain alias keyword (e.g. "الضوء" -> light domain).
    for domain, aliases in DOMAIN_ALIASES:
        if _has(text_norm, aliases):
            in_domain = [s["entity_id"] for s in ents
                         if s.get("entity_id", "").startswith(domain + ".")]
            if not in_domain:
                # HA not reachable / no such entity: still report the domain so
                # we can answer gracefully.
                return service, [], domain
            if want_all or len(in_domain) == 1:
                label = domain + (" (all)" if (want_all and len(in_domain) > 1) else "")
                return service, in_domain, label
            # Multiple candidates and no "all": act on all of that domain anyway,
            # which matches the common intent of "turn off the lights".
            return service, in_domain, domain

    # 3) Generic "turn everything off/on".
    if want_all and ents:
        return service, [e["entity_id"] for e in ents], "all devices"

    return None


def _ar_action(service, ar=True):
    if service == "turn_off":
        return "طفّيت" if ar else "turned off"
    if service == "turn_on":
        return "شغّلت" if ar else "turned on"
    return "بدّلت" if ar else "toggled"


def try_smart_home(text, states=None):
    """Return a result dict if this looks like a smart-home command, else None."""
    tn = _norm(text)
    if not _service_for(tn):
        return None
    if states is None:
        states = ha_states()
    match = _match_smart_home(tn, states)
    ar = _is_arabic(text)

    # If HA matched, execute via Home Assistant
    if match:
        service, entity_ids, label = match

        if not entity_ids:
            # HA domain matched but no entities — try generic devices first
            generic_result = _try_generic_devices(tn, text)
            if generic_result:
                return generic_result
            msg = ("ماكو جهاز \"" + str(label) + "\" متصل بالبيت الذكي حالياً."
                   if ar else "No \"" + str(label) + "\" device is connected to Home Assistant right now.")
            return {"handled": True, "action": "smarthome", "ok": False,
                    "response": msg, "entities": []}

        ok_any = False
        errors = []
        for eid in entity_ids:
            domain = eid.split(".")[0]
            ok, err = ha_call(domain, service, eid)
            ok_any = ok_any or ok
            if not ok:
                errors.append(err)

        if ok_any:
            verb = _ar_action(service, ar)
            if ar:
                msg = verb + " " + _ar_label(label) + (" ✅")
            else:
                msg = verb.capitalize() + " " + str(label) + "."
            return {"handled": True, "action": "smarthome", "ok": True,
                    "response": msg, "service": service, "entities": entity_ids}

        # HA call failed — try generic devices as fallback
        generic_result = _try_generic_devices(tn, text)
        if generic_result:
            return generic_result

        msg = ("حاولت أنفّذ الأمر بس ماكدر أوصل للبيت الذكي (Home Assistant). تأكد إنه شغّال."
               if ar else "I tried but couldn't reach Home Assistant. Is it running?")
        return {"handled": True, "action": "smarthome", "ok": False,
                "response": msg, "service": service, "entities": entity_ids,
                "error": "; ".join(errors)[:200]}

    # No HA match — try generic devices
    generic_result = _try_generic_devices(tn, text)
    if generic_result:
        return generic_result

    return None


def _try_generic_devices(text_norm, original_text):
    """Try to match and control a generic (Tasmota/ESP) device from the utterance."""
    service = _service_for(text_norm)
    if not service:
        return None
    gdm = _get_generic_mgr()
    if not gdm:
        return None
    try:
        devs = gdm.list_devices()
    except Exception:
        return None
    if not devs:
        return None

    ar = _is_arabic(original_text)
    want_all = _has(text_norm, ALL_WORDS)

    # Map service to generic action
    gen_action = "on" if service == "turn_on" else ("off" if service == "turn_off" else "toggle")

    # 1) Match by device name or channel name
    if not want_all:
        for d in devs:
            dname = _norm(d.get("name", ""))
            if dname and len(dname) >= 2 and dname in text_norm:
                ok, result = (gdm.set_device_state(d["id"], gen_action)
                              if gen_action in ("on", "off")
                              else gdm.toggle_device(d["id"]))
                verb = _ar_action(service, ar)
                label = d.get("name", d["id"])
                if ok:
                    msg = verb + " " + label + " ✅" if ar else verb.capitalize() + " " + label + "."
                    print(f"[Assist-Generic] ✅ {service} → {d['id']}")
                    return {"handled": True, "action": "smarthome", "ok": True,
                            "response": msg, "service": service, "entities": [d["id"]]}
                else:
                    print(f"[Assist-Generic] ❌ {service} → {d['id']}: {result}")

            # Check multi-channel names
            if d.get("device_type") == "multi_channel":
                for i, ch_name in enumerate(d.get("channels", []), 1):
                    cn = _norm(ch_name)
                    if cn and len(cn) >= 2 and cn in text_norm:
                        ok, result = (gdm.set_device_state(d["id"], gen_action, channel=i)
                                      if gen_action in ("on", "off")
                                      else gdm.toggle_device(d["id"], channel=i))
                        verb = _ar_action(service, ar)
                        if ok:
                            msg = verb + " " + ch_name + " ✅" if ar else verb.capitalize() + " " + ch_name + "."
                            print(f"[Assist-Generic] ✅ {service} → {d['id']}|ch{i}")
                            return {"handled": True, "action": "smarthome", "ok": True,
                                    "response": msg, "service": service,
                                    "entities": [d["id"] + "|" + str(i)]}

    # 2) Match by domain alias (e.g. "الضوء" → find any generic device that
    #    looks like a light by its name or type)
    for domain, aliases in DOMAIN_ALIASES:
        if _has(text_norm, aliases):
            # Find generic devices whose name/type hints at this domain
            matching = []
            for d in devs:
                dname = _norm(d.get("name", ""))
                dtype = d.get("device_type", "")
                # Check if device name contains domain hints
                if any(a in dname for a in aliases) or dtype == domain:
                    matching.append(d)
            if not matching and domain in ("light", "switch"):
                # Any switch-type generic device counts
                matching = [d for d in devs if d.get("device_type", "switch") in ("switch", "multi_channel")]
            if matching:
                ok_any = False
                for d in matching:
                    try:
                        if d.get("device_type") == "multi_channel" and want_all:
                            for i in range(1, len(d.get("channels", [])) + 1):
                                ok, _ = (gdm.set_device_state(d["id"], gen_action, channel=i)
                                         if gen_action in ("on", "off")
                                         else gdm.toggle_device(d["id"], channel=i))
                                ok_any = ok_any or ok
                        else:
                            ok, _ = (gdm.set_device_state(d["id"], gen_action)
                                     if gen_action in ("on", "off")
                                     else gdm.toggle_device(d["id"]))
                            ok_any = ok_any or ok
                    except Exception as exc:
                        print(f"[Assist-Generic] Error controlling {d['id']}: {exc}")
                if ok_any:
                    verb = _ar_action(service, ar)
                    label = _ar_label(domain) if ar else domain
                    msg = verb + " " + label + " ✅" if ar else verb.capitalize() + " " + label + "."
                    print(f"[Assist-Generic] ✅ {service} → {domain} ({len(matching)} device(s))")
                    return {"handled": True, "action": "smarthome", "ok": True,
                            "response": msg, "service": service,
                            "entities": [d["id"] for d in matching]}

    return None


def _ar_label(label):
    table = {
        "light": "الضوء", "switch": "المفتاح", "fan": "المروحة",
        "climate": "التكييف", "cover": "الستارة", "all devices": "كل الأجهزة",
    }
    base = label.replace(" (all)", "")
    out = table.get(base, label)
    if "(all)" in label or base == "all devices":
        if base != "all devices":
            out = "كل " + out
    return out


# =====================================================================
#  LLM [IOT:...] + [GENERIC:...] tag execution
# =====================================================================
_IOT_TAG = re.compile(r"\[IOT:(turn_on|turn_off|toggle)\|([^\]]+)\]", re.IGNORECASE)
_GENERIC_TAG = re.compile(r"\[GENERIC:(\w+)\|([^|\]]+)(?:\|([^\]]*))?\]", re.IGNORECASE)
_ANY_TAG = re.compile(r"\[(?:IOT|GENERIC):[^\]]*\]")


def _get_generic_mgr():
    """Try to get the GenericDeviceManager from the running server module."""
    try:
        import server
        return getattr(server, "generic_device_mgr", None)
    except Exception:
        pass
    # Fallback: instantiate our own from the project-level JSON
    try:
        from iot_controller import GenericDeviceManager
        _backend = os.path.dirname(os.path.abspath(__file__))
        _path = os.path.join(_backend, "generic_devices.json")
        if not os.path.exists(_path):
            _project = os.path.dirname(_backend)
            _path = os.path.join(_project, "generic_devices.json")
        return GenericDeviceManager(_path)
    except Exception:
        return None


def execute_tags(reply):
    """Find [IOT:action|entity] and [GENERIC:action|dev_id|value] tags
    in an LLM reply, execute each, and return a list of results."""
    executed = []

    # HA [IOT:...] tags
    for m in _IOT_TAG.finditer(reply or ""):
        service = m.group(1).lower()
        entity_id = m.group(2).strip()
        domain = entity_id.split(".")[0] if "." in entity_id else ""
        if not domain:
            continue
        ok, err = ha_call(domain, service, entity_id)
        print(f"[Assist-IoT] {service}({entity_id}) → {'✅' if ok else '❌ ' + err}")
        executed.append({"service": service, "entity_id": entity_id, "ok": ok})

    # Generic [GENERIC:...] tags (Tasmota / ESP devices)
    gdm = _get_generic_mgr()
    for m in _GENERIC_TAG.finditer(reply or ""):
        action = m.group(1).lower().strip()
        dev_id = m.group(2).strip()
        value_str = (m.group(3) or "").strip()
        ok = False
        if gdm:
            try:
                if action in ("turn_on", "on"):
                    ch = int(value_str) if value_str else None
                    ok, result = gdm.set_device_state(dev_id, "on", channel=ch)
                elif action in ("turn_off", "off"):
                    ch = int(value_str) if value_str else None
                    ok, result = gdm.set_device_state(dev_id, "off", channel=ch)
                elif action == "toggle":
                    ch = int(value_str) if value_str else None
                    ok, result = gdm.toggle_device(dev_id, channel=ch)
                elif action in ("dimmer", "fan"):
                    val = int(value_str) if value_str else 0
                    if hasattr(gdm, "send_command"):
                        ok, result = gdm.send_command(dev_id, action, val)
                    else:
                        ok, result = False, "unsupported"
                else:
                    result = "unknown action"
                print(f"[Assist-Generic] {action}({dev_id}|{value_str}) → {'✅' if ok else '❌ ' + str(result)}")
            except Exception as exc:
                print(f"[Assist-Generic] Error {action}({dev_id}): {exc}")
        executed.append({"service": action, "entity_id": dev_id, "ok": ok})

    return executed


def strip_tags(reply):
    return re.sub(r"\s*" + _ANY_TAG.pattern, "", reply or "").strip()


# =====================================================================
#  PERSONAL MEMORY  (deterministic store / recall)
# =====================================================================
_NAME_SET_PATTERNS = [
    r"(?:my name is|i am|i'm|call me)\s+(.+)$",
    r"(?:اسمي|انا اسمي|اسمي هو|اني اسمي|نادني)\s+(.+)$",
]
_NAME_GET_WORDS = ["what is my name", "what's my name", "who am i",
                   "شنو اسمي", "شكو اسمي", "منو اني", "تعرف اسمي", "شتعرف عني اسمي"]
_REMEMBER_PATTERNS = [
    r"(?:remember that|remember|note that|keep in mind that|keep in mind)\s+(.+)$",
    r"(?:تذكر اني|تذكر ان|تذكر انه|افتكر اني|افتكر ان|خلي ببالك ان|خلي ببالك انه|تذكر)\s+(.+)$",
]
_RECALL_WORDS = ["what do you remember", "what do you know about me",
                 "شنو تتذكر", "شتتذكر عني", "شتعرف عني", "شنو تعرف عني", "شكو عندك عني"]


def _clean_capture(s):
    s = (s or "").strip().strip(".!؟?،,").strip()
    # drop a leading "that/ان/انه" if it slipped through
    return s


def try_memory(text):
    if MEM is None:
        return None
    tn = _norm(text)
    ar = _is_arabic(text)

    # --- recall name ---
    if _has(tn, [_norm(w) for w in _NAME_GET_WORDS]):
        name = MEM.get_name()
        if name:
            msg = ("اسمك " + name + " \U0001F60A") if ar else ("Your name is " + name + ".")
        else:
            msg = ("لسه ما گلتلي اسمك. گول \"اسمي ...\" وأتذكره."
                   if ar else "You haven't told me your name yet. Say \"my name is ...\".")
        return {"handled": True, "action": "memory", "response": msg}

    # --- recall everything ---
    if _has(tn, [_norm(w) for w in _RECALL_WORDS]):
        items = MEM.all_items()
        name = items.get("name", "")
        facts = items.get("facts", {})
        if not name and not facts:
            msg = ("لحد الحين ما عندي شي محفوظ عنك." if ar
                   else "I don't have anything saved about you yet.")
            return {"handled": True, "action": "memory", "response": msg}
        lines = []
        if name:
            lines.append(("الاسم: " if ar else "Name: ") + name)
        for k, v in facts.items():
            lines.append("- " + k + ((": " + v) if v else ""))
        head = ("هذا اللي أتذكره عنك:" if ar else "Here's what I remember about you:")
        return {"handled": True, "action": "memory",
                "response": head + "\n" + "\n".join(lines)}

    # --- set name ---
    for pat in _NAME_SET_PATTERNS:
        m = re.search(pat, text.strip(), re.IGNORECASE)
        if m:
            name = _clean_capture(m.group(1))
            # avoid capturing long sentences as a name
            if name and len(name.split()) <= 4:
                MEM.set_name(name)
                msg = ("تشرفت " + name + "! رح أتذكر اسمك." if ar
                       else "Nice to meet you, " + name + "! I'll remember that.")
                return {"handled": True, "action": "memory", "response": msg}

    # --- remember a free-form fact ---
    for pat in _REMEMBER_PATTERNS:
        m = re.search(pat, text.strip(), re.IGNORECASE)
        if m:
            fact = _clean_capture(m.group(1))
            if fact:
                key = "note " + time.strftime("%Y-%m-%d %H:%M")
                MEM.remember(key, fact)
                msg = ("تمام، رح أتذكر: " + fact if ar
                       else "Got it, I'll remember: " + fact)
                return {"handled": True, "action": "memory", "response": msg}

    return None


def _is_arabic(text):
    return bool(re.search(r"[\u0600-\u06FF]", str(text or "")))


# =====================================================================
#  ROUTINES
# =====================================================================
def _routines_path():
    try:
        import config_nexus_append as NX
        p = getattr(NX, "NEXUS_ROUTINES_PATH", None)
        if p:
            return p
    except Exception:
        pass
    return os.path.join("data", "nexus_routines.json")


def _default_routines():
    return [
        {
            "id": "morning",
            "name": "صباح الخير",
            "triggers": ["صباح الخير", "صباح النور", "good morning"],
            "steps": [
                {"type": "say", "text": "صباح الخير! هذا ملخص يومك."},
                {"type": "weather"},
                {"type": "news"},
                {"type": "schedule"},
                {"type": "scene", "entity": "scene.morning"},
            ],
        },
        {
            "id": "goodnight",
            "name": "تصبح على خير",
            "triggers": ["تصبح على خير", "ليلة سعيدة", "good night"],
            "steps": [
                {"type": "say", "text": "تصبح على خير، رح أطفي الأضواء."},
                {"type": "ha", "domain": "light", "service": "turn_off", "target": "all"},
            ],
        },
        {
            "id": "leaving",
            "name": "طالع برة",
            "triggers": ["طالع برة", "راح اطلع", "i'm leaving", "leaving home"],
            "steps": [
                {"type": "say", "text": "بأمان الله، رح أطفي الأجهزة."},
                {"type": "ha", "domain": "light", "service": "turn_off", "target": "all"},
                {"type": "ha", "domain": "fan", "service": "turn_off", "target": "all"},
            ],
        },
    ]


def load_routines():
    p = _routines_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    # seed defaults on first run
    save_routines(_default_routines())
    return _default_routines()


def save_routines(routines):
    p = _routines_path()
    try:
        directory = os.path.dirname(p)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(routines, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def _match_routine(text_norm):
    for r in load_routines():
        for trig in (r.get("triggers") or []):
            tn = _norm(trig)
            if tn and tn in text_norm:
                return r
    return None


# ---- routine step data providers (offline-safe) --------------------
def get_weather():
    """Open-Meteo: no API key, free. Returns a short Arabic sentence or a
    graceful fallback when offline."""
    if requests is None:
        return "تعذّر جلب الطقس (لا يوجد اتصال)."
    lat = _cfg("NEXUS_WEATHER_LAT", 33.3152)
    lon = _cfg("NEXUS_WEATHER_LON", 44.3661)
    city = _cfg("NEXUS_WEATHER_CITY", "بغداد")
    try:
        url = ("https://api.open-meteo.com/v1/forecast?latitude=" + str(lat)
               + "&longitude=" + str(lon)
               + "&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
               + "&daily=temperature_2m_max,temperature_2m_min&timezone=auto")
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        d = r.json()
        cur = d.get("current", {})
        daily = d.get("daily", {})
        temp = cur.get("temperature_2m")
        tmax = (daily.get("temperature_2m_max") or [None])[0]
        tmin = (daily.get("temperature_2m_min") or [None])[0]
        msg = "\U0001F324 طقس " + str(city) + ": " + str(temp) + "\u00B0"
        if tmax is not None and tmin is not None:
            msg += " (الكبرى " + str(tmax) + "\u00B0 / الصغرى " + str(tmin) + "\u00B0)"
        return msg
    except Exception:
        return "تعذّر جلب حالة الطقس الآن."


def get_news(limit=3):
    """Fetch a few headlines from a configurable RSS feed. Offline-safe."""
    if requests is None:
        return "تعذّر جلب الأخبار (لا يوجد اتصال)."
    feed = _cfg("NEXUS_NEWS_RSS", "https://feeds.bbci.co.uk/arabic/rss.xml")
    try:
        r = requests.get(feed, timeout=6)
        r.raise_for_status()
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                            r.text, re.DOTALL)
        titles = [t.strip() for t in titles if t.strip()]
        # first title is usually the feed name
        if len(titles) > 1:
            titles = titles[1:]
        titles = titles[:limit]
        if not titles:
            return "ماكو عناوين أخبار حالياً."
        return "\U0001F4F0 أهم الأخبار:\n" + "\n".join("\u2022 " + t for t in titles)
    except Exception:
        return "تعذّر جلب الأخبار الآن."


def _schedule_path():
    try:
        import config_nexus_append as NX
        p = getattr(NX, "NEXUS_SCHEDULE_PATH", None)
        if p:
            return p
    except Exception:
        pass
    return os.path.join("data", "nexus_schedule.json")


def get_schedule():
    """Read today's agenda from a local JSON file the user can edit:
    [{"time":"09:00","title":"اجتماع"}, ...]."""
    p = _schedule_path()
    try:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as fh:
                items = json.load(fh)
            if isinstance(items, list) and items:
                lines = []
                for it in items:
                    if isinstance(it, dict):
                        tm = it.get("time", "")
                        ti = it.get("title", "")
                        lines.append("\u2022 " + (tm + " - " if tm else "") + ti)
                return "\U0001F4C5 جدول اليوم:\n" + "\n".join(lines)
    except Exception:
        pass
    return "\U0001F4C5 ماكو مواعيد مسجّلة لليوم."


def run_routine(routine):
    """Execute a routine's steps and return a combined spoken/text response."""
    parts = []
    executed = []
    for step in (routine.get("steps") or []):
        stype = (step.get("type") or "").lower()
        if stype == "say":
            if step.get("text"):
                parts.append(step["text"])
        elif stype == "weather":
            parts.append(get_weather())
        elif stype == "news":
            parts.append(get_news(int(step.get("limit", 3))))
        elif stype == "schedule":
            parts.append(get_schedule())
        elif stype == "scene":
            ent = step.get("entity")
            if ent:
                ok, _ = ha_call("scene", "turn_on", ent)
                executed.append({"scene": ent, "ok": ok})
        elif stype == "ha":
            domain = step.get("domain", "")
            service = step.get("service", "")
            target = step.get("target", "")
            if domain and service:
                if target == "all":
                    states = ha_states()
                    eids = [s["entity_id"] for s in states
                            if s.get("entity_id", "").startswith(domain + ".")]
                    for eid in eids:
                        ok, _ = ha_call(domain, service, eid)
                        executed.append({"entity_id": eid, "ok": ok})
                elif step.get("entity"):
                    ok, _ = ha_call(domain, service, step["entity"])
                    executed.append({"entity_id": step["entity"], "ok": ok})
    response = "\n\n".join(p for p in parts if p)
    if not response:
        response = "تم تشغيل الروتين."
    return {"handled": True, "action": "routine", "routine": routine.get("id"),
            "response": response, "executed": executed}


def try_routine(text):
    tn = _norm(text)
    r = _match_routine(tn)
    if not r:
        return None
    return run_routine(r)


# =====================================================================
#  LLM fallback (with personal memory + FULL IoT context injected)
# =====================================================================
def llm_chat(message, history):
    if requests is None:
        return "خدمة الذكاء غير متوفرة حالياً.", 0, 4096
    msgs = [{"role": h.get("role"), "content": h.get("content")}
            for h in (history or []) if h.get("content")]
    if message and (not msgs or msgs[-1].get("content") != message):
        msgs.append({"role": "user", "content": message})

    # Start with the FULL IoT-aware system prompt from config so the LLM
    # knows the tag syntax ([IOT:...], [GENERIC:...]) and the rules.
    sys_prompt = _cfg("ROBOT_SYSTEM_PROMPT", "")
    if not sys_prompt:
        sys_prompt = RAGS.system_prompt() if RAGS else ""

    # Personal memory injection
    mem_block = MEM.as_prompt() if MEM else ""
    if mem_block:
        sys_prompt = (sys_prompt + "\n\n" + mem_block).strip()

    # RAG knowledge injection
    if RAGS:
        try:
            ctx = RAGS.rag_context(message)
            if ctx:
                sys_prompt = (sys_prompt + "\n\n" + ctx).strip()
        except Exception:
            pass

    # Inject the LIVE Home Assistant entity list so the model emits REAL
    # entity_ids in [IOT:...] tags.
    try:
        _devs = ha_states()
        if _devs:
            _ctrl = ("light", "switch", "fan", "input_boolean",
                     "climate", "cover", "media_player", "lock")
            _lines = []
            for _s in _devs:
                _eid = _s.get("entity_id", "")
                if _eid.split(".")[0] in _ctrl:
                    _state = _s.get("state", "unknown")
                    _lines.append("- " + _eid + " (" + _entity_friendly(_s)
                                  + ") = " + _state)
            if _lines:
                sys_prompt = (sys_prompt
                    + "\n\nLIVE Home Assistant devices you can control. Use the"
                    + " EXACT entity_id in any [IOT:action|entity_id] tag:\n"
                    + "\n".join(_lines[:40])).strip()
        else:
            print("[Assist-LLM] No HA devices returned (HA offline or empty)")
    except Exception as exc:
        print(f"[Assist-LLM] HA device injection failed: {exc}")

    # Inject generic (Tasmota/ESP) devices so the LLM knows about them
    # and can emit [GENERIC:...] tags with the correct device IDs.
    try:
        gdm = _get_generic_mgr()
        if gdm:
            gen_devs = gdm.list_devices()
            if gen_devs:
                gen_lines = []
                for gd in gen_devs:
                    dtype = gd.get('device_type', 'switch')
                    room = gd.get('room', '')
                    prefix = (room + ": ") if room else ""
                    if dtype == 'multi_channel':
                        channels = gd.get('channels', [])
                        ch_states = gd.get('state', {})
                        for i, ch_name in enumerate(channels, 1):
                            ch_st = (ch_states.get(str(i), 'unknown')
                                     if isinstance(ch_states, dict) else 'unknown')
                            gen_lines.append(
                                "  - " + prefix + ch_name + " (ch" + str(i)
                                + ") = " + ch_st + " [Target: " + gd['id'] + "|" + str(i) + "]")
                    else:
                        gen_lines.append(
                            "  - " + prefix + gd['name'] + " = "
                            + str(gd.get('state', 'unknown'))
                            + " [Target: " + gd['id'] + "]")
                if gen_lines:
                    sys_prompt = (sys_prompt
                        + "\n\n--- Generic IP Devices (use [GENERIC:action|target] tags) ---\n"
                        + "\n".join(gen_lines)
                        + "\n--- End ---").strip()
                    print(f"[Assist-LLM] Injected {len(gen_devs)} generic device(s)")
    except Exception as exc:
        print(f"[Assist-LLM] Generic device injection failed: {exc}")

    full = ([{"role": "system", "content": sys_prompt}] if sys_prompt else []) + msgs
    try:
        _body = {"messages": full, "stream": False}
        try:
            import nexus_settings as _S
            _body.update(_S.get_llm_params())
        except Exception:
            _body["temperature"] = 0.6
        r = requests.post(_llm_url() + "/v1/chat/completions",
                          json=_body,
                          timeout=120)
        r.raise_for_status()
        payload = r.json()
        choice = (payload.get("choices") or [{}])[0]
        reply = (choice.get("message") or {}).get("content", "") or "(empty response)"
        usage = payload.get("usage") or {}
        return reply, usage.get("total_tokens", 0), usage.get("context_size", 4096)
    except Exception as exc:
        print(f"[Assist-LLM] LLM call failed: {exc}")
        return "تعذّر الاتصال بنموذج الذكاء: " + str(exc), 0, 4096


# =====================================================================
#  PUBLIC ENTRY POINT
# =====================================================================
def handle_command(message, history=None):
    """Route an utterance through the full assistant brain.

    Returns a dict always containing at least:
      { response, action, handled, context_used, context_max }
    """
    history = history or []
    message = (message or "").strip()
    if not message:
        return {"response": "", "action": "none", "handled": False,
                "context_used": 0, "context_max": 4096}

    # 1) Personal memory (cheap, deterministic, no network).
    try:
        r = try_memory(message)
        if r:
            r.setdefault("context_used", 0)
            r.setdefault("context_max", 4096)
            return r
    except Exception:
        pass

    # 2) Routines (trigger phrases).
    try:
        r = try_routine(message)
        if r:
            r.setdefault("context_used", 0)
            r.setdefault("context_max", 4096)
            return r
    except Exception:
        pass

    # 3) Smart-home control.
    try:
        r = try_smart_home(message)
        if r:
            r.setdefault("context_used", 0)
            r.setdefault("context_max", 4096)
            return r
    except Exception:
        pass

    # 4) Fallback to the LLM (with memory) + execute any [IOT:] tags.
    reply, used, cmax = llm_chat(message, history)
    executed = []
    try:
        executed = execute_tags(reply)
        reply = strip_tags(reply)
    except Exception:
        pass
    # Make the SPOKEN confirmation reflect the ACTUAL device result. The model
    # is instructed to say "done" next to a tag, but if the HA call failed we
    # must NOT let that optimistic text stand (Issue 6, failure mode ii:
    # "says done, turned on, while nothing physically changes").
    if executed:
        ok_n = sum(1 for e in executed if e.get("ok"))
        _ar = any("\u0600" <= c <= "\u06ff" for c in message)
        if ok_n == 0:
            reply = ("تعذّر تنفيذ الأمر على الجهاز — تحقّق من اتصال Home Assistant."
                     if _ar else
                     "I couldn't actually carry that out on the device \u2014 "
                     "please check the Home Assistant connection.")
        elif ok_n < len(executed):
            reply = (reply + (" (لكن بعض الأجهزة لم تستجب.)" if _ar
                              else " (But some devices didn't respond.)")).strip()
    return {"response": reply or "(empty response)", "action": "chat",
            "handled": True, "executed": executed,
            "context_used": used, "context_max": cmax}
