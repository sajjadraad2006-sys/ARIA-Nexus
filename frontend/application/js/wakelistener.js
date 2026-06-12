/* =====================================================================
   ARIA NEXUS — wakelistener.js   (window.BrowserWake)
   ---------------------------------------------------------------------
   ALWAYS-ON, hidden wake word for ANY device that opens the site. The
   connecting device's microphone stays armed quietly in the background;
   NOTHING is shown on screen — no waveform, no call UI — until it hears
   “aria”. Then it fires the handler (opens the Assistant Call), releases
   the mic for the call, and re-arms after the call ends.

   TWO listening modes (localStorage 'nexus_wake_device_mode'):

     'stream'  (DEFAULT — fully offline on the LAN):
         Capture the mic, downsample to 16 kHz PCM16, and stream it to the
         Jetson (/api/wake/feed). openWakeWord runs LOCALLY on the Jetson,
         so this works with the internet completely OFF — any laptop/phone
         on the same network becomes a microphone for the Jetson.

     'speech'  (online convenience fallback):
         Use the browser SpeechRecognition engine. Chrome/Edge stream audio
         to a cloud recognizer, so this needs internet — offered only as a
         fallback when streaming is undesirable.

   A tiny corner dot is the only visual hint that the mic is armed; it can
   be turned off in Settings ('nexus_wake_dot').

   Public API:
     isSupported()       -> bool (true if either mode can run)
     setMode(mode)       -> 'stream' | 'speech'
     getMode()           -> current mode
     setHandler(fn)      -> called once each time ‘aria’ is detected
     start() / stop()    -> arm / disarm background listening
     isActive()          -> bool
     setDot(bool)        -> show/hide the tiny armed indicator
   ===================================================================== */
(function () {
  'use strict';

  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;

  var mode = null;             // resolved lazily from localStorage
  var wantOn = false;          // we WANT to be listening
  var active = false;          // a listener is actually running
  var handler = null;          // fired on detection
  var lastHit = 0;

  /* ---------- shared helpers ---------- */
  function getMode() {
    if (mode) return mode;
    try { mode = localStorage.getItem('nexus_wake_device_mode') || 'stream'; }
    catch (e) { mode = 'stream'; }
    return mode;
  }
  function setMode(m) {
    m = (m === 'speech') ? 'speech' : 'stream';
    if (m === mode) return;
    var wasOn = wantOn;
    stop();
    mode = m;
    try { localStorage.setItem('nexus_wake_device_mode', m); } catch (e) {}
    if (wasOn) start();
  }
  function micDeviceId() {
    try {
      var id = localStorage.getItem('nexus_mic_device');
      return (id && id !== 'default') ? id : null;
    } catch (e) { return null; }
  }
  function audioConstraints() {
    var id = micDeviceId();
    var a = { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    if (id) a.deviceId = { exact: id };
    return { audio: a };
  }

  function isSupported() {
    var canStream = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
                       (window.AudioContext || window.webkitAudioContext) &&
                       window.API && API.wakeFeed);
    return canStream || !!SR;
  }
  function setHandler(fn) { handler = fn; }
  function isActive() { return active; }

  function matches(text) {
    if (!text) return false;
    var t = String(text).toLowerCase();
    if (/آريا|اريا|اريه|آريه|أريا|عاريا/.test(text)) return true;
    if (/a+\s*r+\s*i+\s*a+|ar(i|y|e)+a|aaria|ariya|areya|aria/i.test(t)) return true;
    if (/aria/.test(t.replace(/\s+/g, ''))) return true;
    return false;
  }

  function setDotState(s) {
    var el = document.getElementById('wake-indicator');
    if (!el) return;
    el.classList.remove('armed', 'off', 'error', 'hit');
    el.classList.add(s);
    el.title = {
      armed: 'Listening for “aria” · أسمع لـ “aria”',
      off:   'Wake word off',
      error: 'Tap to enable mic · تاب للسماح بالمايك',
      hit:   'Heard you!'
    }[s] || '';
  }
  function setDot(on) {
    var el = document.getElementById('wake-indicator');
    if (!el) return;
    var show;
    try { show = (on !== false) && (localStorage.getItem('nexus_wake_dot') !== '0'); }
    catch (e) { show = (on !== false); }
    el.style.display = show ? '' : 'none';
  }

  /* A short, friendly confirmation chime when the wake word is heard
     (Settings 'nexus_wake_chime', default ON). Anti-false-trigger UX: the
     user gets immediate feedback that ARIA woke up. */
  function chime() {
    try {
      if (localStorage.getItem('nexus_wake_chime') === '0') return;
    } catch (e) {}
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      var ctx = new AC();
      var o = ctx.createOscillator(), g = ctx.createGain();
      o.type = 'sine';
      o.frequency.setValueAtTime(660, ctx.currentTime);
      o.frequency.exponentialRampToValueAtTime(990, ctx.currentTime + 0.12);
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.03);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.28);
      o.connect(g); g.connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + 0.3);
      setTimeout(function () { try { ctx.close(); } catch (e) {} }, 500);
    } catch (e) {}
  }

  function onHit() {
    var now = Date.now();
    if (now - lastHit < 1500) return;     // debounce repeats (anti false-trigger)
    lastHit = now;
    if (window.AssistantCall && AssistantCall.isOpen && AssistantCall.isOpen()) return;
    setDotState('hit');
    chime();
    wantOn = false;                        // release the mic for the call
    stopInternal();
    if (handler) { try { handler(); } catch (e) {} }
  }

  /* =================================================================
     MODE 1 — STREAM to Jetson (offline, LAN only)
     ================================================================= */
  var sCtx = null, sSrc = null, sProc = null, sZero = null, sStream = null;
  var sResample = [];          // accumulated 16 kHz float samples
  var sInRate = 48000;
  var sSending = false;
  var sPending = null;         // queued Int16 chunk awaiting send
  var FLUSH_SAMPLES = 12800;   // ~0.8 s @ 16 kHz

  function floatTo16LE(floatArr) {
    var buf = new ArrayBuffer(floatArr.length * 2);
    var view = new DataView(buf);
    for (var i = 0; i < floatArr.length; i++) {
      var s = Math.max(-1, Math.min(1, floatArr[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buf;
  }

  var sUnavailWarned = false;
  function sendChunk(buf) {
    if (!window.API || !API.wakeFeed) return;
    if (sSending) { sPending = buf; return; }   // coalesce: keep only newest
    sSending = true;
    API.wakeFeed(buf).then(function (res) {
      sSending = false;
      // The Jetson reports available:false when openWakeWord/numpy aren't
      // installed or the wake model failed to load. Previously this was
      // swallowed silently, so offline wake just "never fired" with no clue —
      // pushing users to the online 'speech' mode (Issue 2). Surface it once.
      if (res && res.available === false && !sUnavailWarned) {
        sUnavailWarned = true;
        setDotState('error');
        try {
          console.warn('[wake] Offline wake word unavailable on the Jetson ' +
            '(openWakeWord/model not loaded). Install openwakeword + numpy and ' +
            'ensure the "aarya" model is present, then reload. ' +
            (res.error ? ('Server: ' + res.error) : ''));
        } catch (e) {}
      } else if (res && res.available !== false) {
        sUnavailWarned = false;
        if (active) setDotState('armed');
      }
      if (res && res.detected && wantOn) { onHit(); }
      else if (sPending) { var n = sPending; sPending = null; sendChunk(n); }
    }).catch(function () {
      sSending = false; sPending = null;
      // network/Jetson hiccup — keep listening; LAN should recover
    });
  }

  function startStream() {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) { setDotState('error'); return; }
    navigator.mediaDevices.getUserMedia(audioConstraints()).then(function (stream) {
      sStream = stream;
      var AC = window.AudioContext || window.webkitAudioContext;
      sCtx = new AC();
      if (sCtx.state === 'suspended') { try { sCtx.resume(); } catch (e) {} }
      sInRate = sCtx.sampleRate || 48000;
      sSrc = sCtx.createMediaStreamSource(stream);
      var bufSize = 4096;
      sProc = sCtx.createScriptProcessor(bufSize, 1, 1);
      sResample = [];
      var ratio = sInRate / 16000;
      sProc.onaudioprocess = function (e) {
        if (!wantOn) return;
        var input = e.inputBuffer.getChannelData(0);
        for (var i = 0; i < input.length; i += ratio) {
          sResample.push(input[Math.floor(i)] || 0);
        }
        if (sResample.length >= FLUSH_SAMPLES) {
          var slice = sResample.splice(0, sResample.length);
          sendChunk(floatTo16LE(slice));
        }
      };
      // mute path to destination (gain 0) so we never echo the mic to speakers
      sZero = sCtx.createGain();
      sZero.gain.value = 0;
      sSrc.connect(sProc);
      sProc.connect(sZero);
      sZero.connect(sCtx.destination);
      active = true;
      setDotState('armed');
      if (window.API && API.wakeFeedReset) { try { API.wakeFeedReset(); } catch (e) {} }
    }).catch(function () {
      active = false;
      wantOn = true;          // remember intent; user can tap the dot to grant
      setDotState('error');
    });
  }

  function stopStream() {
    try { if (sProc) sProc.onaudioprocess = null; } catch (e) {}
    try { if (sSrc) sSrc.disconnect(); } catch (e) {}
    try { if (sProc) sProc.disconnect(); } catch (e) {}
    try { if (sZero) sZero.disconnect(); } catch (e) {}
    try { if (sCtx) sCtx.close(); } catch (e) {}
    try { if (sStream) sStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    sCtx = sSrc = sProc = sZero = sStream = null;
    sResample = []; sPending = null; sSending = false;
  }

  /* =================================================================
     MODE 2 — browser SpeechRecognition (online fallback)
     ================================================================= */
  var rec = null, restartTimer = null;
  function clearRestart() { if (restartTimer) { clearTimeout(restartTimer); restartTimer = null; } }
  function scheduleRestart(ms) {
    clearRestart();
    restartTimer = setTimeout(function () { if (wantOn) startSpeech(); }, ms || 600);
  }
  function startSpeech() {
    if (!SR) { setDotState('error'); return; }
    if (active && rec) return;
    try {
      rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.maxAlternatives = 3;
      try { rec.lang = (localStorage.getItem('nexus_wake_lang') || 'en-US'); } catch (e) {}
      rec.onstart = function () { active = true; setDotState('armed'); };
      rec.onresult = function (e) {
        for (var i = e.resultIndex; i < e.results.length; i++) {
          var r = e.results[i];
          for (var a = 0; a < r.length; a++) {
            if (matches(r[a].transcript)) { onHit(); return; }
          }
        }
      };
      rec.onerror = function (ev) {
        active = false;
        var err = ev && ev.error;
        if (err === 'not-allowed' || err === 'service-not-allowed') { wantOn = true; setDotState('error'); return; }
        if (wantOn) scheduleRestart(err === 'network' ? 2500 : 500);
      };
      rec.onend = function () {
        active = false;
        if (wantOn) scheduleRestart(400); else setDotState('off');
      };
      rec.start();
    } catch (e) {
      active = false; setDotState('error');
      if (wantOn) scheduleRestart(1200);
    }
  }
  function stopSpeech() {
    clearRestart();
    if (rec) {
      try { rec.onend = null; rec.onerror = null; rec.onresult = null; rec.stop(); } catch (e) {}
      try { rec.abort && rec.abort(); } catch (e) {}
    }
    rec = null;
  }

  /* =================================================================
     Public lifecycle (mode-aware)
     ================================================================= */
  function startInternal() {
    if (getMode() === 'speech') startSpeech();
    else startStream();
  }
  function stopInternal() {
    stopStream();
    stopSpeech();
    active = false;
  }

  function start() {
    wantOn = true;
    setDot(true);
    startInternal();
  }
  function stop() {
    wantOn = false;
    stopInternal();
    setDotState('off');
  }

  /* tiny corner dot: tap to (re)enable / grant mic permission */
  function wireDot() {
    var el = document.getElementById('wake-indicator');
    if (!el || el._wired) return;
    el._wired = 1;
    setDot(true);
    el.addEventListener('click', function () {
      if (active) return;
      wantOn = true; startInternal();
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wireDot);
  } else { wireDot(); }

  window.BrowserWake = {
    isSupported: isSupported,
    setMode: setMode,
    getMode: getMode,
    setHandler: setHandler,
    start: start,
    stop: stop,
    isActive: isActive,
    setDot: setDot
  };
})();
