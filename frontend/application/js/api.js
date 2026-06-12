/* =====================================================================
   ARIA NEXUS — api.js
   Single namespace: window.API. ALL fetch() calls live here.
   No page JS may call fetch() directly.
   ===================================================================== */
(function () {
  'use strict';

  // Always use the same origin as the page (works for any LAN IP and HTTPS)
  var BASE = window.location.origin;

  /* Core JSON request helper. Throws on network OR HTTP error. */
  async function request(path, options) {
    options = options || {};
    var res;
    try {
      res = await fetch(BASE + path, options);
    } catch (networkErr) {
      throw new Error('Network error: ' + (networkErr && networkErr.message ? networkErr.message : 'request failed'));
    }
    if (!res.ok) {
      var text = '';
      try { text = await res.text(); } catch (e) { text = ''; }
      throw new Error('HTTP ' + res.status + ': ' + (text || res.statusText));
    }
    return res;
  }

  async function getJSON(path) {
    var res = await request(path, { method: 'GET' });
    return res.json();
  }

  async function sendJSON(path, method, bodyObj) {
    var res = await request(path, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bodyObj || {})
    });
    return res.json();
  }

  var API = {
    BASE: BASE,

    /* ---- Launcher / health ---- */
    health: function () { return getJSON('/api/launcher/health'); },
    getModules: function () { return getJSON('/api/launcher/modules'); },

    /* ---- Chatbot ---- */
    chat: function (message, history) {
      return sendJSON('/api/chat', 'POST', { message: message, history: history || [] });
    },

    /* ---- Assistant brain (smart-home + memory + routines) ---- */
    assistantCommand: function (message, history) {
      return sendJSON('/api/assistant/command', 'POST', { message: message, history: history || [] });
    },
    getMemory: function () { return getJSON('/api/assistant/memory'); },
    setMemory: function (fields) { return sendJSON('/api/assistant/memory', 'POST', fields || {}); },
    deleteMemory: function (key) {
      return sendJSON('/api/assistant/memory/' + encodeURIComponent(key), 'DELETE');
    },
    getRoutines: function () { return getJSON('/api/assistant/routines'); },
    saveRoutines: function (routines) {
      return sendJSON('/api/assistant/routines', 'POST', { routines: routines || [] });
    },
    runRoutine: function (id) {
      return sendJSON('/api/assistant/routines/run', 'POST', { id: id });
    },

    /* ---- Monitor ---- */
    getMonitorStats: function () { return getJSON('/api/monitor/stats'); },

    /* ---- IoT: Home Assistant ---- */
    getHAEntities: function () { return getJSON('/api/iot/entities'); },
    toggleHAEntity: function (entity_id) {
      return sendJSON('/api/iot/toggle', 'POST', { entity_id: entity_id });
    },
    callHAService: function (domain, service, entity_id, data) {
      return sendJSON('/api/iot/service', 'POST', {
        domain: domain, service: service, entity_id: entity_id, data: data || {}
      });
    },
    createVirtualDevice: function (name, device_type, room) {
      return sendJSON('/api/iot/virtual', 'POST', {
        name: name, device_type: device_type || 'switch', room: room || ''
      });
    },
    getVirtualDevices: function () { return getJSON('/api/iot/virtual/devices'); },
    toggleVirtualDevice: function (id) {
      return sendJSON('/api/iot/virtual/toggle', 'POST', { id: id });
    },
    deleteVirtualDevice: function (id) {
      return sendJSON('/api/iot/virtual/' + encodeURIComponent(id), 'DELETE');
    },

    /* ---- IoT: Generic / network devices ---- */
    getGenericDevices: function () { return getJSON('/api/iot/generic/devices'); },
    addGenericDevice: function (name, ip, room, device_type, channels, brand, added_via) {
      return sendJSON('/api/iot/generic/device', 'POST', {
        name: name, ip: ip, room: room, device_type: device_type, channels: channels || [],
        brand: brand || 'generic', added_via: added_via || 'manual'
      });
    },
    toggleGenericDevice: function (dev_id, channel) {
      return sendJSON('/api/iot/generic/toggle', 'POST', { dev_id: dev_id, channel: channel });
    },
    sendGenericCommand: function (dev_id, command, value) {
      return sendJSON('/api/iot/generic/command', 'POST', { dev_id: dev_id, command: command, value: value });
    },
    deleteGenericDevice: function (dev_id) {
      return sendJSON('/api/iot/generic/device/' + encodeURIComponent(dev_id), 'DELETE');
    },
    testGenericIP: function (ip) {
      return getJSON('/api/iot/generic/test?ip=' + encodeURIComponent(ip));
    },
    scanLAN: function () { return sendJSON('/api/iot/generic/scan', 'POST'); },

    /* ---- IoT: Web actions ---- */
    getWebActions: function () { return getJSON('/api/iot/webactions'); },
    addWebAction: function (name, url, method, headers, body) {
      return sendJSON('/api/iot/webactions', 'POST', {
        name: name, url: url, method: method, headers: headers || {}, body: body || ''
      });
    },
    updateWebAction: function (id, fields) {
      return sendJSON('/api/iot/webactions/' + encodeURIComponent(id), 'PATCH', fields || {});
    },
    deleteWebAction: function (id) {
      return sendJSON('/api/iot/webactions/' + encodeURIComponent(id), 'DELETE');
    },
    triggerWebAction: function (id) {
      return sendJSON('/api/iot/webactions/' + encodeURIComponent(id) + '/trigger', 'POST');
    },

    /* ---- TTS ---- */
    getTTSVoices: function () { return getJSON('/api/tts/voices'); },
    setTTSVoice: function (voice_id) {
      return sendJSON('/api/tts/voice', 'POST', { voice_id: voice_id });
    },
    /* Returns an audio Blob (binary). Optional AbortSignal enables barge-in. */
    previewTTSVoice: async function (voice_id, text, signal) {
      var opts = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_id: voice_id, text: text })
      };
      if (signal) opts.signal = signal;
      var res = await request('/api/tts/preview', opts);
      return res.blob();
    },

    /* ---- RAG / Knowledge ---- */
    getRAGStats: function () { return getJSON('/api/rag/stats'); },
    queryRAG: function (query) { return sendJSON('/api/rag/query', 'POST', { query: query }); },
    addRAGDocument: function (title, text) {
      return sendJSON('/api/rag/document', 'POST', { title: title, text: text });
    },
    getRAGDocument: function (filename) {
      return getJSON('/api/rag/document/' + encodeURIComponent(filename));
    },
    updateRAGDocument: function (filename, text) {
      return sendJSON('/api/rag/document/' + encodeURIComponent(filename), 'PATCH', { text: text });
    },
    deleteRAGDocument: function (filename) {
      return sendJSON('/api/rag/document/' + encodeURIComponent(filename), 'DELETE');
    },
    saveRAGSettings: function (chunk_size, chunk_overlap, top_k, min_relevance) {
      return sendJSON('/api/rag/settings', 'POST', {
        chunk_size: chunk_size, chunk_overlap: chunk_overlap,
        top_k: top_k, min_relevance: min_relevance
      });
    },
    reindexRAG: function () { return sendJSON('/api/rag/reindex', 'POST'); },

    /* ---- STT (chatbot voice input) ---- */
    sttStart: function () { return sendJSON('/api/stt/start', 'POST'); },
    sttStop: function () { return sendJSON('/api/stt/stop', 'POST'); },
    /* Browser-recorded audio -> Whisper. This is the ONLY working speech
       path: send a webm/opus Blob as multipart to /api/stt/inference.
       (Do NOT set Content-Type here — the browser adds the boundary.) */
    sttInference: function (blob) {
      var form = new FormData();
      form.append('file', blob, 'recording.webm');
      form.append('response_format', 'json');
      return request('/api/stt/inference', { method: 'POST', body: form })
        .then(function (res) { return res.json(); });
    },

    // ---- Wake word (hands-free, openWakeWord) ----
    wakeStart: function () { return sendJSON('/api/wake/start', 'POST'); },
    wakeStop: function () { return sendJSON('/api/wake/stop', 'POST'); },
    wakeStatus: function () { return getJSON('/api/wake/status'); },
    /* Stream browser-mic audio (raw PCM16 16k mono ArrayBuffer) to the Jetson,
       which runs openWakeWord locally => fully offline on the LAN. */
    wakeFeed: function (pcmArrayBuffer) {
      return request('/api/wake/feed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: pcmArrayBuffer
      }).then(function (res) { return res.json(); });
    },
    wakeFeedReset: function () { return sendJSON('/api/wake/feed/reset', 'POST'); },
    /* Live-tune the Jetson wake listener: { threshold?, device?, always_on? } */
    wakeConfig: function (cfg) { return sendJSON('/api/wake/config', 'POST', cfg || {}); },
    /* Jetson microphone input devices (for the Settings mic picker). */
    getMicDevices: function () { return getJSON('/api/mic/devices'); },

    // ---- Live settings (LLM temperature, wake, ...) ----
    getSettings: function () { return getJSON('/api/settings'); },
    saveSettings: function (patch) { return sendJSON('/api/settings', 'POST', patch || {}); },

    /* ---- Exporter ---- */
    /* Returns a JSON Blob (server sets Content-Disposition). */
    exportManifest: async function (flags) {
      var res = await request('/api/exporter/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(flags || {})
      });
      return res.blob();
    },
    importManifest: async function (manifest_json, dry_run) {
      var res = await request('/api/exporter/import?dry_run=' + (dry_run ? 'true' : 'false'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: typeof manifest_json === 'string' ? manifest_json : JSON.stringify(manifest_json)
      });
      return res.json();
    }
    ,
    /* ---- Front-end tunables (VAD endpointing + wake word) ---- */
    getConfig: function () { return getJSON('/api/config'); }
  };

  window.API = API;

  /* Hydrate window.NEXUS_VAD from the backend so mic.js / call.js read VAD
     endpointing values from config.py (with safe built-in fallbacks if the
     backend or route is unavailable). Best-effort; never blocks the UI. */
  try {
    API.getConfig().then(function (cfg) {
      if (cfg && cfg.vad) { window.NEXUS_VAD = cfg.vad; }
      if (cfg && cfg.wake) { window.NEXUS_WAKE = cfg.wake; }
    }).catch(function () { /* offline: defaults apply */ });
  } catch (e) { /* ignore */ }
})();
