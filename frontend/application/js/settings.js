/* =====================================================================
   ARIA NEXUS — settings.js  (CUSTOMIZATION ENGINE)
   ---------------------------------------------------------------------
   A self-contained customization layer. No dependencies except the
   (optional) icon system. Everything persists to localStorage and is
   re-applied on every load — so the look survives restarts and is 100%%
   local (no server, no network).

   Exposes window.NexusSettings = { open, close, get, set, reset, apply }.

   NEXT AGENT: to add a new option, (1) add a default in DEFAULTS,
   (2) render/read a control in buildUI(), (3) handle it in apply().
   ===================================================================== */
(function () {
  'use strict';

  var LS_KEY = 'aria.nexus.settings.v1';

  /* Accent presets: [accent1, accent2, accent3] as HSL triples. */
  var THEMES = {
    aurora:  { label: 'Aurora',  a: [195,100,55], b: [265,80,65], c: [150,70,50] },
    violet:  { label: 'Violet',  a: [265,85,62],  b: [315,80,65], c: [200,90,58] },
    emerald: { label: 'Emerald', a: [160,80,46],  b: [185,80,50], c: [140,70,55] },
    crimson: { label: 'Crimson', a: [352,82,58],  b: [18,90,58],  c: [330,75,62] },
    sunset:  { label: 'Sunset',  a: [30,96,58],   b: [8,88,60],   c: [45,95,55] },
    mono:    { label: 'Slate',   a: [210,16,70],  b: [212,22,56], c: [200,24,60] }
  };

  /* Heuristic: is this a low-power device (e.g. Jetson Orin Nano)?
     Used to default "Lite mode" ON the first time, before any user choice.
     - ?lite / ?lite=1 in the URL forces it on; ?lite=0 forces it off.
     - Few CPU cores or little RAM => treat as low-power.
     The user can always override it from Settings afterwards. */
  function detectLowPower() {
    try {
      var q = (location.search || '').toLowerCase();
      if (/[?&]lite=0/.test(q)) return false;
      if (/[?&]lite(=1)?(&|$)/.test(q)) return true;
      var cores = navigator.hardwareConcurrency || 8;
      var mem = navigator.deviceMemory || 8;   /* GB (rough, may be undefined) */
      if (cores <= 6) return true;             /* Orin Nano = 6 cores */
      if (mem <= 4) return true;
    } catch (e) {}
    return false;
  }

  var DEFAULTS = {
    theme: 'aurora',
    hue: null,       /* when set (0-360), overrides preset with a custom accent */
    blur: 20,        /* glass backdrop blur in px */
    lite: detectLowPower(), /* true = Jetson/lite mode: no blur, no ambient FX */
    scale: 100,      /* interface zoom in %  */
    depth: true,     /* ambient glow layer  */
    grid: true,      /* grid overlay        */
    grain: true,     /* film grain          */
    motion: false,   /* true = reduce motion */
    sound: true,     /* UI sound effects    */
    hover: false,    /* hover sounds        */
    music: false,    /* ambient music loop  */
    volume: 60       /* master volume 0-100 */
  };

  var state = load();

  function load() {
    try {
      var raw = localStorage.getItem(LS_KEY);
      if (raw) return assign({}, DEFAULTS, JSON.parse(raw));
    } catch (e) {}
    return assign({}, DEFAULTS);
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (e) {}
  }
  function assign(t) {
    for (var i = 1; i < arguments.length; i++) {
      var s = arguments[i]; if (!s) continue;
      for (var k in s) if (Object.prototype.hasOwnProperty.call(s, k)) t[k] = s[k];
    }
    return t;
  }
  function hsl(a) { return 'hsl(' + a[0] + ', ' + a[1] + '%, ' + a[2] + '%)'; }

  function accents() {
    if (state.hue != null) {
      var h = ((state.hue % 360) + 360) % 360;
      return {
        a: [h, 95, 56],
        b: [(h + 45) % 360, 80, 64],
        c: [(h + 310) % 360, 70, 52]
      };
    }
    var t = THEMES[state.theme] || THEMES.aurora;
    return { a: t.a, b: t.b, c: t.c };
  }

  /* ---- apply state to the live document ---- */
  function apply() {
    var root = document.documentElement;
    var ac = accents();
    root.style.setProperty('--nexus-accent-1', hsl(ac.a));
    root.style.setProperty('--nexus-accent-2', hsl(ac.b));
    root.style.setProperty('--nexus-accent-3', hsl(ac.c));
    root.style.setProperty('--nx-glass-blur', state.blur + 'px');
    root.style.setProperty('--nx-ui-scale', (state.scale / 100).toString());

    var b = document.body;
    if (b) {
      b.classList.toggle('nx-no-depth', !state.depth);
      b.classList.toggle('nx-no-grid', !state.grid);
      b.classList.toggle('nx-no-grain', !state.grain);
      b.classList.toggle('nx-reduce-motion', !!state.motion);
      b.classList.toggle('nx-lite', !!state.lite);
    }

    if (window.NexusSound) {
      NexusSound.configure({
        enabled: state.sound,
        hover: state.hover,
        music: state.music,
        volume: state.volume / 100
      });
    }
  }

  /* ---- public setters ---- */
  function set(key, val) { state[key] = val; save(); apply(); syncUI(); }
  function get(key) { return key ? state[key] : assign({}, state); }
  function reset() { state = assign({}, DEFAULTS); save(); apply(); syncUI(); }

  /* ---- drawer open/close ---- */
  function open() {
    var d = document.getElementById('settings-drawer');
    var s = document.getElementById('settings-scrim');
    if (d) { d.classList.add('open'); d.setAttribute('aria-hidden', 'false'); }
    if (s) s.classList.add('open');
  }
  function close() {
    var d = document.getElementById('settings-drawer');
    var s = document.getElementById('settings-scrim');
    if (d) { d.classList.remove('open'); d.setAttribute('aria-hidden', 'true'); }
    if (s) s.classList.remove('open');
  }

  /* ---- build swatches + wire controls ---- */
  function buildUI() {
    var sw = document.getElementById('theme-swatches');
    if (sw) {
      sw.innerHTML = Object.keys(THEMES).map(function (key) {
        var t = THEMES[key];
        var grad = 'linear-gradient(135deg,' + hsl(t.a) + ',' + hsl(t.b) + ' 60%,' + hsl(t.c) + ')';
        return '<button type="button" class="theme-swatch" data-theme="' + key + '" ' +
          'data-name="' + t.label + '" aria-label="' + t.label + ' theme" ' +
          'style="--sw:' + grad + '"></button>';
      }).join('');
      var btns = sw.querySelectorAll('.theme-swatch');
      for (var i = 0; i < btns.length; i++) {
        (function (btn) {
          btn.addEventListener('click', function () {
            state.theme = btn.dataset.theme; state.hue = null; save(); apply(); syncUI();
          });
        })(btns[i]);
      }
    }
    bindRange('set-hue', function (v) { state.hue = v; }, true);
    bindRange('set-blur', function (v) { state.blur = v; });
    bindRange('set-scale', function (v) { state.scale = v; });
    bindToggle('set-depth', 'depth');
    bindToggle('set-grid', 'grid');
    bindToggle('set-grain', 'grain');
    bindToggle('set-motion', 'motion');
    bindToggle('set-lite', 'lite');
    bindRange('set-volume', function (v) { state.volume = v; });
    bindToggle('set-sound', 'sound');
    bindToggle('set-hover', 'hover');
    bindToggle('set-music', 'music');
    bindLSToggle('set-chat-voice', 'nexus_chat_tts', true, null);
    bindLSToggle('set-wake', 'nexus_wake_enabled', true, function (on) {
      if (window.WakeManager) WakeManager.setEnabled(on);
    });
    // What the wake word opens: 'call' (Assistant Call screen) or 'face'.
    bindSelectLS('set-wake-ui', 'nexus_wake_ui', 'call');
    // Wake SOURCE: 'device' = this browser's mic, 'jetson' = backend mic.
    bindSelectLS('set-wake-source', 'nexus_wake_source', 'device', function () {
      updateMicVisibility();
      if (window.WakeManager && WakeManager.refresh) WakeManager.refresh();
    });
    // Device listening mode: 'stream' (offline, sent to Jetson) | 'speech' (online).
    bindSelectLS('set-wake-device-mode', 'nexus_wake_device_mode', 'stream', function (v) {
      if (window.BrowserWake && BrowserWake.setMode) BrowserWake.setMode(v);
      updateDeviceModeHint();
      if (window.WakeManager && WakeManager.refresh) WakeManager.refresh();
    });
    // Confirmation chime when the wake word is heard.
    bindLSToggle('set-wake-chime', 'nexus_wake_chime', true, null);
    // Tiny “listening” dot in the corner (does not show the call screen).
    bindLSToggle('set-wake-dot', 'nexus_wake_dot', true, function (on) {
      if (window.BrowserWake) BrowserWake.setDot(on);
    });
    // Per-language Piper voices (Arabic / English) for auto voice switching.
    populateVoiceSelectors();

    // New sectioned-settings wiring.
    setupTabs();
    setupMicSection();
    setupLLMSection();
    setupLanguage();
    updateMicVisibility();
    updateDeviceModeHint();

    var closeBtn = document.getElementById('settings-close');
    if (closeBtn) closeBtn.addEventListener('click', close);
    var scrim = document.getElementById('settings-scrim');
    if (scrim) scrim.addEventListener('click', close);
    var resetBtn = document.getElementById('settings-reset');
    if (resetBtn) resetBtn.addEventListener('click', reset);
    var gear = document.getElementById('btn-settings');
    if (gear) gear.addEventListener('click', open);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  }

  function bindRange(id, setter, isHue) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', function () {
      setter(Number(el.value));
      if (isHue) state.theme = 'custom';
      save(); apply(); syncValLabels();
      if (isHue) markActiveSwatch();
    });
  }
  function bindToggle(id, key) {
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', function () { set(key, el.checked); });
  }

  /* Standalone localStorage toggles (not part of the themed settings blob). */
  function lsOn(key, defOn) {
    var v = localStorage.getItem(key);
    return v === null ? !!defOn : (v !== '0');
  }
  function bindLSToggle(id, key, defOn, onChange) {
    var el = document.getElementById(id);
    if (!el) return;
    el.checked = lsOn(key, defOn);
    el.addEventListener('change', function () {
      try { localStorage.setItem(key, el.checked ? '1' : '0'); } catch (e) {}
      if (onChange) onChange(el.checked);
    });
  }
  function syncLSToggle(id, key, defOn) {
    var el = document.getElementById(id);
    if (el) el.checked = lsOn(key, defOn);
  }

  /* Bind a <select> straight to a localStorage key (used by wake-UI choice). */
  function bindSelectLS(id, key, def, onChange) {
    var el = document.getElementById(id);
    if (!el) return;
    el.value = localStorage.getItem(key) || def;
    el.addEventListener('change', function () {
      try { localStorage.setItem(key, el.value); } catch (e) {}
      if (onChange) onChange(el.value);
    });
  }

  /* Fill the Arabic + English voice pickers from the TTS server so the user
     can choose which Piper voice answers each language (voice.js reads the
     'nexus_voice_ar' / 'nexus_voice_en' keys to auto-switch). */
  function populateVoiceSelectors() {
    if (!window.API || !API.getTTSVoices) return;
    API.getTTSVoices().then(function (data) {
      var voices = (data && data.voices) || [];
      fillVoiceSelect('set-voice-ar', 'nexus_voice_ar', voices);
      fillVoiceSelect('set-voice-en', 'nexus_voice_en', voices);
    }).catch(function () {});
  }
  function fillVoiceSelect(id, key, voices) {
    var el = document.getElementById(id);
    if (!el) return;
    var cur = localStorage.getItem(key) || '';
    var html = '<option value="">Auto / default</option>';
    for (var i = 0; i < voices.length; i++) {
      var v = voices[i] || {};
      var vid = v.voice_id || v.id || '';
      if (!vid) continue;
      var label = vid + (v.language ? ' \u00b7 ' + v.language : '');
      html += '<option value="' + vid + '">' + label + '</option>';
    }
    el.innerHTML = html;
    if (cur) el.value = cur;
    if (!el._wired) {
      el._wired = 1;
      el.addEventListener('change', function () {
        try { localStorage.setItem(key, el.value); } catch (e) {}
      });
    }
  }

  /* ---- reflect state into controls ---- */
  function syncUI() { syncControls(); syncValLabels(); markActiveSwatch(); }
  function syncControls() {
    setVal('set-hue', state.hue == null ? defaultHue() : state.hue);
    setVal('set-blur', state.blur);
    setVal('set-scale', state.scale);
    setChk('set-depth', state.depth);
    setChk('set-grid', state.grid);
    setChk('set-grain', state.grain);
    setChk('set-motion', state.motion);
    setChk('set-lite', state.lite);
    setVal('set-volume', state.volume);
    setChk('set-sound', state.sound);
    setChk('set-hover', state.hover);
    setChk('set-music', state.music);
    syncLSToggle('set-chat-voice', 'nexus_chat_tts', true);
    syncLSToggle('set-wake', 'nexus_wake_enabled', true);
  }
  function defaultHue() { var t = THEMES[state.theme] || THEMES.aurora; return t.a[0]; }
  function syncValLabels() {
    setText('hue-val', state.hue == null ? 'preset' : state.hue + '\u00b0');
    setText('blur-val', state.blur + 'px');
    setText('scale-val', state.scale + '%');
    setText('volume-val', state.volume + '%');
  }
  function markActiveSwatch() {
    var sw = document.getElementById('theme-swatches');
    if (!sw) return;
    var btns = sw.querySelectorAll('.theme-swatch');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('active', state.hue == null && btns[i].dataset.theme === state.theme);
    }
  }
  function setVal(id, v) { var el = document.getElementById(id); if (el) el.value = v; }
  function setChk(id, v) { var el = document.getElementById(id); if (el) el.checked = !!v; }
  function setText(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; }

  /* ===================================================================
     Sectioned settings: tabs, microphone, wake tuning, and LLM params.
     =================================================================== */

  /* Tab switching between the Appearance / Mic / Voice / Assistant / Sound
     panels. Pure client-side; remembers the last tab for the session. */
  function setupTabs() {
    var nav = document.getElementById('set-tabs');
    if (!nav || nav._wired) return;
    nav._wired = 1;
    var tabs = nav.querySelectorAll('.set-tab');
    for (var i = 0; i < tabs.length; i++) {
      (function (tab) {
        tab.addEventListener('click', function () { showTab(tab.dataset.tab); });
      })(tabs[i]);
    }
  }
  function showTab(name) {
    var nav = document.getElementById('set-tabs');
    var body = document.getElementById('settings-drawer');
    if (!nav || !body) return;
    var tabs = nav.querySelectorAll('.set-tab');
    for (var i = 0; i < tabs.length; i++) {
      tabs[i].classList.toggle('active', tabs[i].dataset.tab === name);
    }
    var panels = body.querySelectorAll('.set-panel');
    for (var j = 0; j < panels.length; j++) {
      panels[j].classList.toggle('active', panels[j].dataset.panel === name);
    }
  }

  /* Show/hide the rows that only apply to one wake source: the browser-mic
     picker + device-mode for 'device', the Jetson-input picker for 'jetson'. */
  function updateMicVisibility() {
    var source = localStorage.getItem('nexus_wake_source') || 'device';
    var isDevice = (source === 'device');
    showRow('row-device-mode', isDevice);
    showRow('row-mic-browser', isDevice);
    showRow('hint-device-mode', isDevice);
    showRow('row-mic-jetson', !isDevice);
  }
  function showRow(id, on) {
    var el = document.getElementById(id);
    if (el) el.style.display = on ? '' : 'none';
  }
  /* Language switcher: drives the global I18N engine, which flips every
     [data-i18n] node + the page text direction (LTR/RTL) and persists the
     choice. We also refresh the JS-built strings on every language change. */
  function setupLanguage() {
    var el = document.getElementById('set-language');
    if (el && window.I18N) {
      el.value = I18N.getLang();
      if (!el._wired) {
        el._wired = 1;
        el.addEventListener('change', function () { I18N.setLang(el.value); });
      }
    }
    if (!setupLanguage._bound) {
      setupLanguage._bound = 1;
      window.addEventListener('nexus:langchange', function () {
        var sel = document.getElementById('set-language');
        if (sel && window.I18N) sel.value = I18N.getLang();
        // Re-render dynamically-built strings in the chosen language.
        updateDeviceModeHint();
        populateBrowserMics();
        populateJetsonMics();
      });
    }
  }
  function tr(key, fallback) {
    return (window.I18N && I18N.t) ? I18N.t(key, fallback) : fallback;
  }
  function updateDeviceModeHint() {
    var el = document.getElementById('hint-device-mode');
    if (!el) return;
    var m = localStorage.getItem('nexus_wake_device_mode') || 'stream';
    el.textContent = (m === 'speech')
      ? tr('set.deviceModeSpeechHint', 'Uses the browser speech engine \u2014 needs internet.')
      : tr('set.deviceModeStreamHint', 'Streams the mic to the Jetson so openWakeWord runs locally \u2014 works with no internet (same network).');
  }

  /* Microphone + wake-tuning section: device pickers (browser via
     enumerateDevices, Jetson via /api/mic/devices) and the sensitivity
     slider (mapped to the openWakeWord threshold, applied live + persisted). */
  function setupMicSection() {
    populateBrowserMics();
    populateJetsonMics();
    bindSelectLS('set-mic-device', 'nexus_mic_device', 'default', function () {
      if (window.WakeManager && WakeManager.refresh) WakeManager.refresh();
    });
    setupSensitivity();
    // Re-enumerate browser mics once permission is granted (labels appear then).
    if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) {
      try { navigator.mediaDevices.addEventListener('devicechange', populateBrowserMics); } catch (e) {}
    }
  }

  function populateBrowserMics() {
    var el = document.getElementById('set-mic-device');
    if (!el || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    navigator.mediaDevices.enumerateDevices().then(function (devs) {
      var cur = localStorage.getItem('nexus_mic_device') || 'default';
      var html = '<option value="default">' + esc(tr('opt.default', 'Default')) + '</option>';
      var n = 0;
      for (var i = 0; i < devs.length; i++) {
        if (devs[i].kind !== 'audioinput') continue;
        n++;
        var label = devs[i].label || ('Microphone ' + n);
        html += '<option value="' + devs[i].deviceId + '">' + esc(label) + '</option>';
      }
      el.innerHTML = html;
      el.value = cur;
      if (el.value !== cur) el.value = 'default';
    }).catch(function () {});
  }

  function populateJetsonMics() {
    var el = document.getElementById('set-jetson-device');
    if (!el || !window.API || !API.getMicDevices) return;
    API.getMicDevices().then(function (data) {
      var devs = (data && data.devices) || [];
      var html = '<option value="">' + esc(tr('opt.systemDefault', 'System default')) + '</option>';
      var selected = '';
      for (var i = 0; i < devs.length; i++) {
        var d = devs[i] || {};
        if (d.selected) selected = String(d.index);
        html += '<option value="' + d.index + '">' + esc(d.name || ('Input ' + d.index)) + '</option>';
      }
      el.innerHTML = html;
      el.value = selected;
      if (!el._wired) {
        el._wired = 1;
        el.addEventListener('change', function () {
          var dev = (el.value === '') ? null : Number(el.value);
          if (API.wakeConfig) API.wakeConfig({ device: dev }).catch(function () {});
        });
      }
    }).catch(function () {
      el.innerHTML = '<option value="">' + esc(tr('opt.jetsonUnreachable', 'Jetson not reachable')) + '</option>';
    });
  }

  /* Sensitivity 0-100 (UI) <-> openWakeWord threshold 0.5..0.02 (backend).
     Higher sensitivity = lower threshold = wakes more easily. */
  function sensToThreshold(s) {
    var t = 0.5 - (s / 100) * 0.48;   // s=0 -> 0.5 (strict), s=100 -> 0.02 (loose)
    return Math.round(t * 1000) / 1000;
  }
  function thresholdToSens(t) {
    var s = (0.5 - t) / 0.48 * 100;
    return Math.max(0, Math.min(100, Math.round(s / 5) * 5));
  }
  function setupSensitivity() {
    var el = document.getElementById('set-wake-sensitivity');
    if (!el) return;
    var stored = localStorage.getItem('nexus_wake_sensitivity');
    var sens = (stored == null) ? 80 : Number(stored);   // default fairly sensitive
    el.value = sens;
    setText('wake-sensitivity-val', sens + '%');
    var t = null;
    el.addEventListener('input', function () {
      var v = Number(el.value);
      setText('wake-sensitivity-val', v + '%');
      try { localStorage.setItem('nexus_wake_sensitivity', String(v)); } catch (e) {}
      if (t) clearTimeout(t);
      t = setTimeout(function () {
        if (window.API && API.wakeConfig) {
          API.wakeConfig({ threshold: sensToThreshold(v) }).catch(function () {});
        }
      }, 250);
    });
    // Reconcile with the backend's actual threshold on first load.
    if (window.API && API.getSettings) {
      API.getSettings().then(function (data) {
        var wk = data && data.settings && data.settings.wake;
        if (wk && typeof wk.threshold === 'number' && stored == null) {
          var s = thresholdToSens(wk.threshold);
          el.value = s; setText('wake-sensitivity-val', s + '%');
        }
      }).catch(function () {});
    }
  }

  /* Assistant / LLM section: temperature, top-p, and max reply length.
     These persist on the Jetson via /api/settings so every reply uses them. */
  function setupLLMSection() {
    var temp = document.getElementById('set-llm-temp');
    var topp = document.getElementById('set-llm-topp');
    var maxt = document.getElementById('set-llm-maxtokens');
    if (!temp && !topp && !maxt) return;
    // Seed with defaults, then overwrite from the server.
    setLLMControls({ temperature: 0.6, top_p: 0.95, max_tokens: 0 });
    if (window.API && API.getSettings) {
      API.getSettings().then(function (data) {
        var llm = data && data.settings && data.settings.llm;
        if (llm) setLLMControls(llm);
      }).catch(function () {});
    }
    var save = debounce(function () {
      if (!window.API || !API.saveSettings) return;
      API.saveSettings({ llm: {
        temperature: temp ? Number(temp.value) : undefined,
        top_p: topp ? Number(topp.value) : undefined,
        max_tokens: maxt ? Number(maxt.value) : undefined
      } }).catch(function () {});
    }, 350);
    if (temp) temp.addEventListener('input', function () { setText('llm-temp-val', Number(temp.value).toFixed(2)); save(); });
    if (topp) topp.addEventListener('input', function () { setText('llm-topp-val', Number(topp.value).toFixed(2)); save(); });
    if (maxt) maxt.addEventListener('input', function () {
      setText('llm-maxtokens-val', Number(maxt.value) === 0 ? 'unlimited' : maxt.value); save();
    });
  }
  function setLLMControls(llm) {
    var temp = document.getElementById('set-llm-temp');
    var topp = document.getElementById('set-llm-topp');
    var maxt = document.getElementById('set-llm-maxtokens');
    if (temp && llm.temperature != null) { temp.value = llm.temperature; setText('llm-temp-val', Number(llm.temperature).toFixed(2)); }
    if (topp && llm.top_p != null) { topp.value = llm.top_p; setText('llm-topp-val', Number(llm.top_p).toFixed(2)); }
    if (maxt && llm.max_tokens != null) { maxt.value = llm.max_tokens; setText('llm-maxtokens-val', Number(llm.max_tokens) === 0 ? 'unlimited' : llm.max_tokens); }
  }

  function debounce(fn, ms) {
    var t = null;
    return function () { if (t) clearTimeout(t); t = setTimeout(fn, ms || 300); };
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ---- boot ---- */
  function boot() {
    apply();      /* apply persisted look immediately */
    buildUI();
    syncUI();
    if (window.nxHydrateIcons) nxHydrateIcons(document.getElementById('settings-drawer'));
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }

  window.NexusSettings = { open: open, close: close, get: get, set: set, reset: reset, apply: apply };
})();
