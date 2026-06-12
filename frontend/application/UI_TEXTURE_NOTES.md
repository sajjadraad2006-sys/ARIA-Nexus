# ARIA NEXUS — Visual System (Icons + Textures), 100%% Local

This update replaces emoji glyphs with a real SVG icon system and adds a
tactile texture layer. **Everything is local — there are no CDN links, no web
fonts fetched over the network, and no external image files.**

## What changed

### 1. SVG icon system — `js/icons.js`
- Stroke-based, inline-SVG icons that inherit text color (`currentColor`) and
  stay crisp at any size. Zero network requests, zero sprite files.
- Public API (all on `window`):
  - `nxIcon(name, { size, stroke, cls })` → returns an `<svg>` string (use in
    JS-built markup).
  - `nxLangBadge(code)` → a flag-style language chip (rounded rect + gloss +
    2-letter code), used by the TTS module.
  - `nxHydrateIcons(root?)` → swaps `[data-icon]` placeholders in static HTML
    for their SVG. Runs automatically on `DOMContentLoaded` (idempotent).
  - `NX_ICON_NAMES` → list of available icon names.
- **Static HTML usage:** `<span class="nx-i" data-icon="home"></span>`
  (optionally `data-icon-size="18"`).
- **Dynamic JS usage:** `el.innerHTML = nxIcon('bolt', { size: 20 });`
- Available icons include: grid, chatbot, home, monitor, mic, knowledge,
  package, power, fullscreen, refresh, reindex, search, scan, pause, play, x,
  check, upload, download, folder, save, plus, trash, cpu, memory, disk, gpu,
  gear, bolt, bulb, sensor, bell, fan, cover, climate, toggle, plug, globe,
  network, voice.

Load order matters — `icons.js` is now the **first** script (before
`particles.js`), so `nxIcon`/`nxLangBadge` are available to every page module.

### 2. Texture layer — `css/textures.css`
Adds depth without hurting performance (transform/opacity animations only):
- **Ambient depth glows** (`.nx-depth`) — slow-drifting cyan/purple/green
  radial gradients behind all content.
- **Fine grid weave** (`.nx-grid`) — subtle masked grid for structure.
- **Film grain** (`.nx-grain`) — an inline SVG `feTurbulence` noise data-URI
  layered on top at low opacity with `mix-blend-mode: overlay`. No image file.
- **Frosted-glass sheen** — a faint diagonal highlight on every `.glass` panel
  via `::after`, so panels read as real frosted glass.
- All decorative layers use `pointer-events: none` (fully click-through) and
  honor `prefers-reduced-motion`.

Three decorative divs were added at the top of `<body>`:
`<div class="nx-depth">`, `<div class="nx-grid">`, `<div class="nx-grain">`.

### 3. Fonts are now fully local
The Google Fonts `<link>` tags were removed. The CSS font stack tries
`Space Grotesk` / `JetBrains Mono` if the user already has them installed, then
falls back to system + Liberation/Noto fonts. **No network request is made for
fonts.**

## Verification
- `node --check` passes on all 10 JS files (including `icons.js`).
- Zero emoji glyphs remain in `application/`.
- Zero `http(s)`/CDN/font references remain (the only `https` string is
  placeholder text inside an input field, not a request).
