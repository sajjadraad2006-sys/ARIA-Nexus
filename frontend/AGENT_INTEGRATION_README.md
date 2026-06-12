# ARIA NEXUS — Integration & Run Guide (READ THIS FIRST)

> **Audience:** the next AI agent (or developer) who must connect this UI to a
> real backend and make it run correctly. Follow the steps in order. Every
> endpoint the frontend calls is listed with its exact request/response shape.
> If you implement these endpoints and serve the `application/` folder, the app
> works end to end.

---

## 0. What ARIA NEXUS is

A single-page “command center” front end for a local AI rig. Six modules:

| Module | Page id | Purpose | Talks to |
|---|---|---|---|
| ARIA Chatbot | `chatbot` | Conversational AI | local LLM (Qwen2.5-3B-Instruct via llama.cpp) |
| IoT Control | `iot` | Home Assistant + generic LAN devices + web actions | HA REST API, your device layer |
| System Monitor | `monitor` | CPU/RAM/Disk/GPU + services | `psutil` / `pynvml` |
| TTS Studio | `tts` | Piper voice manager | Piper |
| Knowledge Base | `knowledge` | RAG documents | your vector store |
| System Exporter | `exporter` | Backup / restore config | filesystem |

**Stack:** vanilla HTML/CSS/JS (no build step, no framework, no bundler) + a
Flask blueprint. 100%% offline — no CDN, no web fonts over the network, inline
SVG icons, bundled `.woff` fonts.

---

## 1. File layout

```
aria_build/
├─ application/                 # <-- the front end (serve this folder)
│  ├─ nexus_app.html            # entry point
│  ├─ assets/fonts/*.woff       # bundled fonts (local, offline)
│  ├─ css/  nexus.css fonts.css textures.css settings.css animations.css
│  └─ js/   icons.js settings.js nexus.js particles.js api.js
│         js/pages/  chatbot.js iot.js monitor.js tts.js knowledge.js exporter.js
└─ backend/                     # <-- Flask blueprint + helpers
   ├─ nexus_routes_additions.py # Blueprint `nexus_bp` + register_nexus(app)
   ├─ web_action_manager.py     # generic web-action store (stub-friendly)
   ├─ config_nexus_append.py    # config keys to append to your settings
   └─ README.md                 # backend-specific notes
```

---

## 2. Wire the backend (3 steps)

### Step 1 — Register the blueprint
In your main Flask app:

```python
from flask import Flask
from nexus_routes_additions import register_nexus  # adjust import path

app = Flask(__name__)
register_nexus(app)   # mounts all /api/* routes AND serves the SPA at /nexus
```

`register_nexus(app)` does two things:
1. Registers `nexus_bp` (every `/api/...` route below).
2. Serves `application/` so the UI is reachable at **`http://127.0.0.1:5000/nexus`**.

> If your app already owns some of these routes, edit `nexus_routes_additions.py`
> and delete the duplicates, or mount the blueprint under a `url_prefix`.

### Step 2 — Point the frontend at your API
`application/js/api.js` has one constant at the top:

```js
var BASE = 'http://127.0.0.1:5000';   // change if your API runs elsewhere
```
If you serve the SPA from the same Flask app (recommended), you can set
`BASE = ''` to use same-origin requests.

### Step 3 — Replace the stubs with real logic
Every route in `nexus_routes_additions.py` currently returns safe placeholder
data so the UI runs immediately. Search the file for `# TODO` and wire each to
your real services (LLM, HA, psutil, Piper, RAG). The contract in §3 must stay
the same so the frontend keeps working.

---

## 3. API CONTRACT (authoritative)

All requests/responses are JSON. Base path `BASE` (default `http://127.0.0.1:5000`).
For any list endpoint, returning `[]` is valid and renders an empty state.

### Launcher / health
| Method | Path | Response |
|---|---|---|
| GET | `/api/launcher/health` | `{ "ok": true }` |
| GET | `/api/launcher/modules` | `[{ "id": "chatbot", "status": "online|degraded|offline|unknown" }, ...]` |

`id` must be one of: `chatbot, iot, monitor, tts, knowledge, exporter`.

### Chatbot
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/chat` | `{ "message": "hi", "history": [...] }` | `{ "reply": "...", "context_used": 1200, "context_max": 8192 }` |

### Monitor
| Method | Path | Response |
|---|---|---|
| GET | `/api/monitor/stats` | `{ cpu_percent, ram_percent, ram_used_mb, ram_total_mb, disk_percent, disk_used_gb, disk_total_gb, gpu_name, gpu_load_percent, gpu_memory_used_mb, gpu_memory_total_mb, services: { "<name>": "online|offline" } }` |

### IoT — Home Assistant
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/iot/entities` | — | `[{ entity_id, domain, name, state, attributes }]` |
| POST | `/api/iot/toggle` | `{ entity_id }` | `{ ok, state }` |
| POST | `/api/iot/service` | `{ domain, service, entity_id, data? }` | `{ ok }` |
| POST | `/api/iot/virtual` | `{ name }` | `{ ok, entity }` |

### IoT — generic LAN devices
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/iot/generic/devices` | — | `[{ id, name, ip, room, device_type, channels?, state }]` |
| POST | `/api/iot/generic/device` | `{ name, ip, room, device_type, channels? }` | `{ ok, device }` |
| POST | `/api/iot/generic/toggle` | `{ id, channel? }` | `{ ok, state }` |
| POST | `/api/iot/generic/command` | `{ id, command, value? }` | `{ ok }` |
| DELETE | `/api/iot/generic/device/<id>` | — | `{ ok }` |
| GET | `/api/iot/generic/test?ip=<ip>` | — | `{ reachable: true }` |
| POST | `/api/iot/generic/scan` | `{ subnet? }` | `{ devices: [{ ip, hostname }] }` |

`device_type` is one of: `switch, multi_channel, dimmer, fan, rgb_light`.

### IoT — web actions
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/iot/webactions` | — | `[{ id, name, url, method, headers, body }]` |
| POST | `/api/iot/webactions` | `{ name, url, method, headers?, body? }` | `{ ok, action }` |
| PATCH | `/api/iot/webactions/<id>` | partial fields | `{ ok }` |
| DELETE | `/api/iot/webactions/<id>` | — | `{ ok }` |
| POST | `/api/iot/webactions/<id>/trigger` | — | `{ ok, status, response? }` |

### TTS (Piper)
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/tts/voices` | — | `[{ id, name, language, quality, speakers? }]` |
| POST | `/api/tts/voice` | `{ id }` | `{ ok }` |
| POST | `/api/tts/preview` | `{ id, text }` | audio (wav/mp3) or `{ ok, audio_url }` |

### STT (chatbot mic)
| Method | Path | Response |
|---|---|---|
| POST | `/api/stt/start` | `{ ok }` |
| POST | `/api/stt/stop` | `{ ok, text }` |

### Knowledge / RAG
| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/rag/stats` | — | `{ collection, document_count, chunk_count, embedding_model, documents: [{ filename, chunks, size_bytes, modified }], settings }` |
| POST | `/api/rag/query` | `{ query, top_k? }` | `{ results: [{ text, source, score }] }` |
| **POST** | **`/api/rag/document`** | `{ title?, text }` | `{ ok, filename, chunks }` — **add knowledge by pasting text** |
| **GET** | **`/api/rag/document/<filename>`** | — | `{ ok, filename, text, modified }` — **read a document's full text (for viewing/editing)** |
| **PATCH** | **`/api/rag/document/<filename>`** | `{ text }` | `{ ok, filename, chunks }` — **edit/replace a document's text** |
| DELETE | `/api/rag/document/<filename>` | — | `{ ok, deleted }` |
| POST | `/api/rag/settings` | `{ chunk_size, chunk_overlap, top_k, min_relevance }` | `{ ok, settings }` |
| POST | `/api/rag/reindex` | — | `{ ok }` |

> The backend ships an **in-memory `_RAG_DOCS` store** so add/view/edit/delete
> work immediately for testing. Replace each route's body (marked `# TODO`)
> with your real vector store: on add/edit → chunk + embed + upsert; on delete
> → remove vectors; on query → similarity search. Keep the JSON shapes above.
> The frontend Knowledge page already wires: **Add Knowledge** (paste text),
> **View / Edit** per document (textarea + live Markdown preview), and Delete.

### Exporter
| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/exporter/export` | `{ sections: [...] }` | JSON file download (manifest v1.0) |
| POST | `/api/exporter/import?dry_run=1\|0` | manifest JSON | `{ ok, applied?, validation }` |

Export manifest shape: `{ manifest_version: "1.0", checksum, sections: [...], data: {...} }`.

---

## 4. Run it

```bash
# 1. deps
pip install flask psutil          # + pynvml (NVIDIA GPU), requests (HA), your RAG/LLM libs

# 2. start your Flask app that called register_nexus(app)
python app.py                      # serves on http://127.0.0.1:5000

# 3. open the UI
#    http://127.0.0.1:5000/nexus
```

**Static-only preview (no backend):** the UI still loads and shows empty/offline
states. From `application/`:
```bash
python3 -m http.server 8000   # then open http://127.0.0.1:8000/nexus_app.html
```

**Ports the UI expects (status pills only):** Flask `5000`, LLM `8080`,
Whisper STT `8081`, Piper TTS `5002`, Home Assistant `8123`. Adjust in
`backend/nexus_routes_additions.py` (`NEXUS_SERVICES`).

---

## 5. Front-end systems you should know about

### Icon system — `js/icons.js` (load FIRST, before everything)
- `nxIcon(name, { size, stroke, cls })` → returns an inline `<svg>` string.
- `nxLangBadge(code)` → a language chip used by TTS.
- `nxHydrateIcons(root?)` → swaps `[data-icon]` placeholders in static HTML;
  runs automatically on `DOMContentLoaded`.
- Static: `<span class="nx-i" data-icon="home"></span>`; dynamic:
  `el.innerHTML = nxIcon('home', { size: 18 })`.
- **Rule: never put emoji in markup or JS strings.** Add a new icon to the `P`
  map in `icons.js` and reference it by name. (`NX_ICON_NAMES` lists them all.)
  Existing names include: grid, chatbot, home, monitor, mic, knowledge, package,
  power, fullscreen, refresh, reindex, search, scan, pause, play, x, check,
  upload, download, folder, save, plus, trash, cpu, memory, disk, gpu, gear,
  bolt, bulb, sensor, bell, warn, doc, fan, cover, climate, toggle, plug, globe,
  network, voice.

### Customization engine — `js/settings.js` + `css/settings.css`
- Gear button in the header opens a slide-in drawer (`window.NexusSettings`).
- Options: 6 accent themes, custom accent hue, glass-blur, interface scale,
  toggles for ambient glow / grid / film grain / reduce-motion.
- Persisted to `localStorage` key `aria.nexus.settings.v1` and re-applied on load.
- Implemented by overriding CSS variables on `:root`
  (`--nexus-accent-1/2/3`, `--nx-glass-blur`, `--nx-ui-scale`) and body classes
  (`nx-no-depth`, `nx-no-grid`, `nx-no-grain`, `nx-reduce-motion`).
- **To add an option:** add a default in `DEFAULTS`, a control in `buildUI()`,
  and handle it in `apply()`.

### Texture layer — `css/textures.css`
- Decorative, click-through divs at the top of `<body>`: `.nx-depth` (ambient
  glow), `.nx-grid` (grid weave), `.nx-grain` (inline-SVG film grain).
- All transform/opacity only; respects `prefers-reduced-motion`.

### Local “assist” library — `js/vendor/nx-markdown.js`
- `window.nxMarkdown(text)` → safe HTML (headings, bold/italic/strike, inline
  + fenced code, links, lists, blockquotes, hr). HTML-escapes first, so
  untrusted RAG/chat text is rendered safely. Used by the Knowledge page
  (live edit preview + query results) and available to the chatbot.
- **Why it's hand-written:** the build sandbox had NO network access, so
  `marked.js` / `DOMPurify` couldn't be downloaded. To upgrade later, drop the
  real library `.js` into `js/vendor/` and re-point the `<script>` tag in
  `nexus_app.html` (and keep exposing a `nxMarkdown(text)` shim if you want
  zero page-code changes). Style hooks live under `.nxmd` in `nexus.css`.

### Sound engine — `js/vendor/nx-sound.js` + `assets/audio/*.mp3`
- `window.NexusSound.configure({ enabled, hover, music, volume })` (volume 0..1),
  `play(name)`, `startMusic()`, `stopMusic()`. Effect names: `click`, `hover`,
  `toggle`, `nav`, `notify`, `success`, `error`, `startup`. Plus an `ambient`
  music loop.
- Auto-wired (delegated): clicks on buttons/cards/nav → `click`; checkbox
  changes → `toggle`; card hover → `hover` (off by default); `showToast` →
  `success`/`error`/`notify`; page switch → `nav`; entering the app → `startup`
  and (if enabled) the ambient loop. Audio is unlocked on the first user
  gesture (browser autoplay policy).
- Controlled from the **Customize** drawer: Sound effects / Hover sounds /
  Ambient music toggles + a master Volume slider (persisted in settings).
- **Why the audio is synthesized:** the build sandbox had NO network access,
  so royalty-free sound packs / `howler.js` couldn't be downloaded. The MP3s
  in `assets/audio/` were generated offline with **ffmpeg** (sine tones +
  fades; the ambient loop is layered low sines + tremolo + low-pass). To
  upgrade: drop nicer `.mp3` files into `assets/audio/` keeping the same
  filenames, or swap `nx-sound.js` for `howler.js` and keep the same
  `window.NexusSound` API.

### Fonts — `css/fonts.css` + `assets/fonts/*.woff`
- Bundled, offline: `Nexus Sans` (Latin + Arabic) and `Nexus Mono`.
- **No internet was available in the build sandbox**, so premium display fonts
  (Space Grotesk / JetBrains Mono) could NOT be downloaded. To add them later:
  drop their `.woff2` into `assets/fonts/`, add `@font-face` blocks in
  `fonts.css`, and they’ll be picked up first (the CSS font stacks already list
  them ahead of the bundled fallbacks).

---

## 6. Conventions / gotchas

- **No build step.** Edit files directly; reload the browser.
- **No frameworks.** Plain ES5-ish JS, IIFE modules attaching to `window`.
  Page modules expose `window.{Chatbot,IoT,TTS,Knowledge,Exporter}Page = {init}`
  and `window.MonitorPage = { init, destroy }`.
- **Script order matters** (see bottom of `nexus_app.html`): `icons.js` first,
  then `particles.js`, `api.js`, the page modules, `nexus.js`, `settings.js`.
- **Inject SVG with `innerHTML`, never `textContent`** (textContent escapes the
  markup and you’ll see raw `<svg>` text).
- **`<option>` and `<select>` cannot contain SVG/HTML** — use plain text there.
- Keep the white-flash guard in `<head>`:
  `<style>html,body{background:#060d1f;margin:0}</style>`.
- All colors come from CSS variables in `:root` (see `nexus.css`). Use them
  rather than hard-coding hex, so theme switching keeps working.

---

## 7. Quick verification checklist

- [ ] `register_nexus(app)` called; `GET /api/launcher/health` returns `{ok:true}`.
- [ ] Visit `/nexus`; splash → Enter → launcher shows 6 cards with SVG icons (no emoji).
- [ ] Gear icon opens the customization drawer; changing a theme recolors the UI and survives reload.
- [ ] Each module page loads without console errors (empty states are fine until you wire data).
- [ ] `node --check` passes on every file in `application/js/` after edits.
- [ ] Grep shows zero emoji: see command in `application/UI_TEXTURE_NOTES.md`.
