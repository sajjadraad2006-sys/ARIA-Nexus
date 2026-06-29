/* =====================================================================
   ARIA NEXUS — icons.js
   Self-contained inline-SVG icon system. ZERO network requests, ZERO
   external sprite files. All icons are stroke-based (currentColor), so
   they inherit text color and look crisp at any size.

   Public API (all on window):
     nxIcon(name, opts?)   -> returns an <svg> string
         opts = { size?:number, stroke?:number, cls?:string }
     nxLangBadge(code)     -> returns a small flag-style language chip <svg>
     nxHydrateIcons(root?) -> replaces [data-icon] placeholders in static
                              HTML with their SVG (idempotent)
     NX_ICON_NAMES         -> array of available icon names

   Static HTML usage:   <span class="nx-i" data-icon="home"></span>
   Dynamic JS usage:    el.innerHTML = nxIcon('home', { size: 18 });
   ===================================================================== */
(function () {
  'use strict';

  /* Each entry is the inner markup of a 24x24 viewBox icon. */
  var P = {
    /* ----- navigation / shell ----- */
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    chatbot: '<path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2z"/><circle cx="9" cy="10" r=".7" fill="currentColor" stroke="none"/><circle cx="12.5" cy="10" r=".7" fill="currentColor" stroke="none"/><circle cx="16" cy="10" r=".7" fill="currentColor" stroke="none"/>',
    home: '<path d="M3 9.6 12 3l9 6.6"/><path d="M5 9v11h14V9"/><path d="M9.5 20v-6h5v6"/>',
    monitor: '<path d="M22 12h-4l-3 8L9 4l-3 8H2"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v4"/><path d="M8.5 22h7"/>',
    knowledge: '<path d="M12 6c-1.6-1.2-4.1-2-7-2v14c2.9 0 5.4.8 7 2 1.6-1.2 4.1-2 7-2V4c-2.9 0-5.4.8-7 2z"/><path d="M12 6v14"/>',
    package: '<path d="M21 16V8l-9-5-9 5v8l9 5 9-5z"/><path d="M3.3 7 12 12l8.7-5"/><path d="M12 22V12"/>',

    /* ----- actions / controls ----- */
    power: '<path d="M12 3v9"/><path d="M7.5 6.5a7 7 0 1 0 9 0"/>',
    fullscreen: '<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M16 3h3a2 2 0 0 1 2 2v3"/><path d="M21 16v3a2 2 0 0 1-2 2h-3"/><path d="M8 21H5a2 2 0 0 1-2-2v-3"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    reindex: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    scan: '<path d="M4.5 12.5a11 11 0 0 1 15 0"/><path d="M8 16a6 6 0 0 1 8 0"/><circle cx="12" cy="19" r="1" fill="currentColor" stroke="none"/>',
    pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    play: '<path d="M7 4.5v15l12-7.5z"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    upload: '<path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 17v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>',
    download: '<path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M4 18v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/>',
    plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
    trash: '<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/>',

    /* ----- monitor stats ----- */
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/>',
    memory: '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7.5 7V4M12 7V4M16.5 7V4"/><path d="M6 17v3M10 17v3M14 17v3M18 17v3"/>',
    disk: '<path d="M3.5 13 6 6.6A2 2 0 0 1 7.9 5.3h8.2A2 2 0 0 1 18 6.6L20.5 13"/><rect x="3" y="13" width="18" height="6" rx="2"/><path d="M7 16h.01M11 16h.01"/>',
    gpu: '<rect x="2.5" y="7" width="19" height="10" rx="2"/><circle cx="8" cy="12" r="2.4"/><circle cx="15" cy="12" r="2.4"/><path d="M19 7v10"/>',
    robot: '<rect x="3.5" y="8" width="17" height="11.5" rx="3.5"/><path d="M12 8V5"/><circle cx="12" cy="3.5" r="1.3"/><circle cx="9" cy="13.2" r="1.6" fill="currentColor" stroke="none"/><circle cx="15" cy="13.2" r="1.6" fill="currentColor" stroke="none"/><path d="M9.5 16.6h5"/><path d="M2 12.5v3"/><path d="M22 12.5v3"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 12a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7.3 7.3 0 0 0-2-1.2l-.3-2.5H8.3L8 5.7a7.3 7.3 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5a7.5 7.5 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-1c.6.5 1.3.9 2 1.2l.3 2.5h4.4l.3-2.5c.7-.3 1.4-.7 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/>',

    /* ----- IoT device domains / types ----- */
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    bulb: '<path d="M9.5 18h5"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.6c.6.5 1 1.3 1 2.1V18h6v-1.3c0-.8.4-1.6 1-2.1A7 7 0 0 0 12 2z"/>',
    sensor: '<circle cx="12" cy="12" r="2"/><path d="M4.9 4.9a10 10 0 0 0 0 14.2"/><path d="M19.1 4.9a10 10 0 0 1 0 14.2"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/>',
    bell: '<path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9z"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    warn: '<path d="M10.3 3.8 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z"/><path d="M12 9v4"/><circle cx="12" cy="17" r=".6" fill="currentColor" stroke="none"/>',
    doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    fan: '<circle cx="12" cy="12" r="2"/><path d="M12 10c.2-3 .8-5.7-1-6.8C9 4.4 9.4 8 12 10z"/><path d="M14 12c3-.2 5.7.8 6.8-1C19.6 9 16 9.4 14 12z"/><path d="M12 14c-.2 3-.8 5.7 1 6.8 2-1.2 1.6-4.8-1-6.8z"/><path d="M10 12c-3 .2-5.7-.8-6.8 1C4.4 15 8 14.6 10 12z"/>',
    cover: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 8.5h18M3 13h18M3 17.5h18"/>',
    climate: '<path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z"/><path d="M12 16.5a1.5 1.5 0 1 0 0 .01"/>',
    toggle: '<rect x="2" y="7" width="20" height="10" rx="5"/><circle cx="8" cy="12" r="3"/>',
    plug: '<path d="M9 2v6M15 2v6"/><path d="M7 8h10v2.5a5 5 0 0 1-10 0z"/><path d="M12 15.5V22"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18"/><path d="M12 3a14 14 0 0 0 0 18"/>',
    network: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><path d="M6.5 10v3a2 2 0 0 0 2 2H15"/>',
    voice: '<path d="M4 10v4M8 6v12M12 3v18M16 6v12M20 10v4"/>',

    /* ----- NEW: assistant / AI / models ----- */
    assistant: '<path d="M12 2.6l1.9 5.05 5.05 1.9-5.05 1.9L12 16.5l-1.9-5.05L5.05 9.55l5.05-1.9z" fill="currentColor" stroke="none"/><path d="M18.4 13.6l.7 1.95 1.95.7-1.95.7-.7 1.95-.7-1.95-1.95-.7 1.95-.7z" fill="currentColor" stroke="none"/><path d="M5.2 15.2l.5 1.4 1.4.5-1.4.5-.5 1.4-.5-1.4-1.4-.5 1.4-.5z" fill="currentColor" stroke="none"/>',
    brain: '<path d="M12 5.5a3 3 0 0 0-5.9-.7A2.8 2.8 0 0 0 4 8a2.8 2.8 0 0 0 .8 4.6A3 3 0 0 0 6 17a3 3 0 0 0 6 .3z"/><path d="M12 5.5a3 3 0 0 1 5.9-.7A2.8 2.8 0 0 1 20 8a2.8 2.8 0 0 1-.8 4.6A3 3 0 0 1 18 17a3 3 0 0 1-6 .3z"/><path d="M12 5.5v12"/>',
    sparkles: '<path d="M12 3l1.5 3.8L17 8l-3.5 1.2L12 13l-1.5-3.8L7 8l3.5-1.2z"/><path d="M18 13l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
    model: '<path d="M12 3 3 7.5 12 12l9-4.5z"/><path d="M3 12l9 4.5L21 12"/><path d="M3 16.5 12 21l9-4.5"/>',
    chip: '<rect x="7" y="7" width="10" height="10" rx="2"/><rect x="10" y="10" width="4" height="4" rx="1" fill="currentColor" stroke="none"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>',
    server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',

    /* ----- NEW: networking / discovery ----- */
    wifi: '<path d="M2 8.5a16 16 0 0 1 20 0"/><path d="M5 12a11 11 0 0 1 14 0"/><path d="M8.5 15.5a6 6 0 0 1 7 0"/><circle cx="12" cy="19" r="1" fill="currentColor" stroke="none"/>',
    radar: '<circle cx="12" cy="12" r="9"/><path d="M12 12 18.5 7"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21"/>',
    tag: '<path d="M3 12V5.5A2.5 2.5 0 0 1 5.5 3H12l9 9-8.5 8.5z"/><circle cx="7.5" cy="7.5" r="1.4"/>',
    link: '<path d="M10 14a4 4 0 0 1 0-5.7l2.3-2.3a4 4 0 0 1 5.7 5.7L16.5 13"/><path d="M14 10a4 4 0 0 1 0 5.7l-2.3 2.3a4 4 0 0 1-5.7-5.7L7.5 11"/>',

    /* ----- NEW: misc UI ----- */
    sliders: '<path d="M4 6h9M18 6h2"/><path d="M4 12h2M10 12h10"/><path d="M4 18h11M19 18h1"/><circle cx="15.5" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    headset: '<path d="M4 13v-1a8 8 0 0 1 16 0v1"/><rect x="3" y="13" width="4" height="6" rx="1.5"/><rect x="17" y="13" width="4" height="6" rx="1.5"/><path d="M20 19a4 4 0 0 1-4 3h-2"/>',
    speaker: '<rect x="5" y="3" width="14" height="18" rx="2"/><circle cx="12" cy="14" r="3.2"/><circle cx="12" cy="7" r="1" fill="currentColor" stroke="none"/>',
    lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
    'plus-circle': '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>'
  };

  var FALLBACK = 'gear';

  function nxIcon(name, opts) {
    opts = opts || {};
    var inner = P[name] || P[FALLBACK];
    var size = opts.size || 20;
    var sw = opts.stroke || 1.9;
    var cls = 'nx-icon' + (opts.cls ? (' ' + opts.cls) : '');
    return '<svg class="' + cls + '" width="' + size + '" height="' + size +
      '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' + sw +
      '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
      inner + '</svg>';
  }

  /* Flag-style language chip: rounded rect + glossy highlight + code.
     Fully local, scalable, no geopolitical flag rendering, no id collisions. */
  var LANG_COLOR = {
    en: '#3b6fd4', ar: '#1f9d57', de: '#caa12c', fr: '#2b5fd4',
    es: '#d4452b', it: '#2f9d4f', zh: '#d43b3b', ja: '#d4516e',
    pt: '#1f8f6b', ru: '#5566c9', nl: '#e08a2b', ko: '#2f7fb0',
    hi: '#e0762b', tr: '#d43b3b', sv: '#2f7fb0', pl: '#c94b6e'
  };

  function nxLangBadge(lang) {
    var code = String(lang || '').slice(0, 2).toUpperCase() || '\u2014';
    var accent = LANG_COLOR[code.toLowerCase()] || '#6ea8fe';
    return '<svg class="nx-lang" width="28" height="19" viewBox="0 0 28 19" ' +
      'role="img" aria-label="' + code + ' language">' +
      '<rect x="0.5" y="0.5" width="27" height="18" rx="4" fill="' + accent +
      '" stroke="rgba(255,255,255,0.28)"/>' +
      '<rect x="0.5" y="0.5" width="27" height="8" rx="4" fill="rgba(255,255,255,0.16)"/>' +
      '<text x="14" y="13.5" text-anchor="middle" ' +
      'font-family="JetBrains Mono, ui-monospace, monospace" font-size="9" ' +
      'font-weight="700" fill="#ffffff">' + code + '</text></svg>';
  }

  function nxHydrateIcons(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll('[data-icon]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      if (el.getAttribute('data-icon-done') === '1') continue;
      var name = el.getAttribute('data-icon');
      var size = parseInt(el.getAttribute('data-icon-size'), 10);
      el.innerHTML = nxIcon(name, { size: isNaN(size) ? undefined : size });
      el.setAttribute('data-icon-done', '1');
    }
  }

  window.nxIcon = nxIcon;
  window.nxLangBadge = nxLangBadge;
  window.nxHydrateIcons = nxHydrateIcons;
  window.NX_ICON_NAMES = Object.keys(P);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { nxHydrateIcons(document); });
  } else {
    nxHydrateIcons(document);
  }
})();
