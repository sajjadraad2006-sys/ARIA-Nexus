/* =====================================================================
   ARIA NEXUS — wake.js  (ALWAYS-ON, GLOBAL WAKE WORD)
   window.WakeManager

   openWakeWord runs in the backend. This manager keeps the listener
   running app-wide (not only on the Robot Face page). When the wake
   word is detected anywhere in the app, it jumps to the Robot Face and
   runs one hands-free turn (FacePage.runWakeTurn): listen → think →
   reply out loud, then re-arms automatically.

   Master on/off persists in localStorage 'nexus_wake_enabled'
   (default ON). It is shared by the Face toggle and the Settings toggle.

   Public API:
     init()                 — start at app boot (called by nexus.js)
     setEnabled(bool)       — master on/off (persisted)
     isEnabled() / isAvailable() / getState()
     suspend() / resume()   — used by tap-to-talk to free the mic
     onChange(cb)           — subscribe to state changes (UI badges)
   ===================================================================== */
(function () {
  'use strict';

  var LS_KEY = 'nexus_wake_enabled';
  var POLL_MS = 1200;

  // Default ON: the wake word listener starts automatically at app boot.
  // The user can disable it from the Face/Settings toggle. Set localStorage
  // 'nexus_wake_enabled' to '0' to disable.
  var enabled = (localStorage.getItem(LS_KEY) !== '0');  // default ON
  var available = null;     // null = unknown yet
  var reason = '';
  var suspended = false;    // paused while tap-to-talk owns the mic
  var running = false;      // a hands-free turn is in progress
  var pollTimer = null;
  var status = 'off';       // off | unavailable | listening | detected
  var listeners = [];

  function getState() {
    return { status: status, enabled: enabled, available: available, reason: reason };
  }
  function notify() {
    var st = getState();
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](st); } catch (e) {}
    }
  }
  function setStatus(s) { if (status !== s) { status = s; } notify(); }

  function clearPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPoll() { clearPoll(); pollTimer = setInterval(poll, POLL_MS); }

  function api() { return window.API; }

  // Wake source: 'device' = THIS browser's mic listens for “aria” (works on
  // any connected device; needs internet), 'jetson' = backend openWakeWord on
  // the Jetson mic (fully offline). Stored in localStorage 'nexus_wake_source'.
  function usingDevice() { return (localStorage.getItem('nexus_wake_source') || 'device') === 'device'; }

  function startDevice() {
    if (!window.BrowserWake || !BrowserWake.isSupported()) {
      available = false;
      reason = 'This browser can\u2019t access the microphone (try Chrome/Edge)';
      setStatus('unavailable');
      return;
    }
    // 'stream' = capture mic here, stream to the Jetson openWakeWord (offline,
    // LAN only); 'speech' = browser SpeechRecognition (needs internet).
    var devMode = localStorage.getItem('nexus_wake_device_mode') || 'stream';
    if (BrowserWake.setMode) BrowserWake.setMode(devMode);
    available = true; reason = '';
    BrowserWake.setHandler(onDetect);
    BrowserWake.start();
    setStatus('listening');
  }

  function start() {
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','start',{enabled:enabled,suspended:suspended,running:running,usingDevice:usingDevice()});
    if (!enabled || suspended || running) return;
    if (usingDevice()) { startDevice(); return; }
    var A = api();
    if (!A || !A.wakeStart) { available = false; reason = 'API unavailable'; setStatus('unavailable'); return; }
    A.wakeStart().then(function (res) {
      if (res && res.ok === false) {
        available = false;
        reason = res.error || 'openWakeWord not available';
        setStatus('unavailable');
        return;
      }
      available = true; reason = '';
      setStatus('listening');
      startPoll();
    }).catch(function () {
      available = false; reason = 'Could not start wake listener';
      setStatus('unavailable');
    });
  }

  function stop() {
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','stop');
    clearPoll();
    if (window.BrowserWake) { try { BrowserWake.stop(); } catch (e) {} }
    var A = api();
    if (A && A.wakeStop) { try { A.wakeStop(); } catch (e) {} }
  }

  function poll() {
    if (!enabled || suspended || running) return;
    var A = api();
    if (!A || !A.wakeStatus) return;
    A.wakeStatus().then(function (data) {
      if (data && data.available === false) {
        available = false; reason = data.reason || '';
        clearPoll(); setStatus('unavailable');
        return;
      }
      available = true;
      if (data && data.detected) { onDetect(); }
    }).catch(function () { /* silent on background poll */ });
  }

  function onDetect() {
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','onDetect',{ui:localStorage.getItem('nexus_wake_ui')||'call'});
    clearPoll();
    running = true;
    setStatus('detected');
    // Where should the wake word take us? 'call' = the full-screen Assistant
    // Call screen (default, like a phone call), 'face' = the Robot Face page.
    // The choice lives in localStorage 'nexus_wake_ui' (set in Settings).
    var ui = localStorage.getItem('nexus_wake_ui') || 'call';
    var turn;
    if (ui !== 'face' && window.AssistantCall && AssistantCall.openFromWake) {
      // Opens the hands-free call; resolves when the user ends it, then we
      // re-arm the wake word in rearm() below.
      turn = AssistantCall.openFromWake();
    } else {
      // Bring the Robot Face to the foreground so the user sees ARIA react.
      try { if (window.nexus && nexus.showPage) nexus.showPage('face'); } catch (e) {}
      turn = (window.FacePage && FacePage.runWakeTurn)
        ? FacePage.runWakeTurn()
        : Promise.resolve();
    }
    Promise.resolve(turn).then(rearm, rearm);
  }

  function rearm() {
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','rearm',{enabled:enabled,suspended:suspended});
    running = false;
    if (!enabled || suspended) { setStatus(enabled ? 'off' : 'off'); return; }
    // small delay so the OS fully releases the mic before re-listening
    setTimeout(function () {
      (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','rearm.fire',{enabled:enabled,suspended:suspended,running:running});
      if (enabled && !suspended && !running) { start(); }
    }, 600);
  }

  /* ---- public controls ---- */
  function setEnabled(b) {
    enabled = !!b;
    try { localStorage.setItem(LS_KEY, enabled ? '1' : '0'); } catch (e) {}
    if (enabled) { start(); }
    else { stop(); setStatus('off'); }
  }

  function suspend() {
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','suspend');
    suspended = true;
    stop();
  }
  function resume() {
    if (!suspended) return;
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('WMGR','resume',{enabled:enabled,running:running});
    suspended = false;
    if (enabled && !running) start();
  }

  function init() {
    if (enabled) start();
    else setStatus('off');
  }

  // Re-arm after a settings change (e.g. switching wake source device<->jetson).
  function refresh() {
    stop();
    if (enabled && !suspended && !running) start();
    else setStatus(enabled ? status : 'off');
  }

  function onChange(cb) {
    if (typeof cb === 'function') { listeners.push(cb); try { cb(getState()); } catch (e) {} }
  }

  window.WakeManager = {
    init: init,
    setEnabled: setEnabled,
    isEnabled: function () { return enabled; },
    isAvailable: function () { return available; },
    getState: getState,
    suspend: suspend,
    resume: resume,
    refresh: refresh,
    onChange: onChange
  };
})();
