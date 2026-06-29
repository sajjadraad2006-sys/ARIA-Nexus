/* =====================================================================
   ARIA NEXUS — debug.js   window.NexusDebug
   Unified client-side logger. Mirrors events to the console AND ships them
   (batched) to the Jetson so wake / mic / whisper events from a REMOTE phone
   appear in one ordered timeline at  /api/debug/log.txt

   - Consecutive identical events (e.g. WAKE/dot.armed) collapse into one line
     with a count (x142) plus one heartbeat every ~8s, so the log never floods.
   - Overlay is mobile-friendly: throttled rendering + a Pause button + it will
     NOT clobber your text selection, so you can actually copy on a phone.
     (Easiest: just tap Copy -> the whole log goes to the clipboard.)

   OPEN THE ON-SCREEN LOG:
     • Tap the 🐞 button (bottom-right)        <- phone
     • OR triple-tap the top-right corner       <- phone fallback
     • OR press Ctrl+Shift+D                     <- desktop
     • OR run window.NexusDebug.toggle()         <- console

   Load FIRST in index.html, before api.js / wake.js / wakelistener.js.
   ===================================================================== */
(function () {
  'use strict';

  var T0 = (window.performance && performance.now) ? performance.now() : Date.now();
  var ENABLED = (localStorage.getItem('nexus_debug') !== '0'); // default ON
  var buf = [];      // events pending upload
  var ring = [];     // last N events for the overlay
  var RING_MAX = 400;
  var HEARTBEAT_MS = 8000;   // while an event repeats, emit at most one line per 8s
  var SRC = localStorage.getItem('nexus_debug_src');
  if (!SRC) {
    SRC = 'dev-' + Math.random().toString(36).slice(2, 6);
    try { localStorage.setItem('nexus_debug_src', SRC); } catch (e) {}
  }
  var overlayEl = null, bodyEl = null, btnEl = null, pauseB = null, shown = false;

  // de-dupe state
  var _lastKey = null, _lastRec = null, _dupCount = 0, _lastEmit = -1e9;
  // overlay render state
  var paused = false, autoFollow = true, renderPending = false;

  function nowMs() {
    var t = (window.performance && performance.now) ? performance.now() : Date.now();
    return Math.round((t - T0) * 10) / 10;
  }
  function wall() {
    var d = new Date();
    var p = function (n, w) { return String(n).padStart(w || 2, '0'); };
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds()) +
           '.' + p(d.getMilliseconds(), 3);
  }

  function store(rec) {
    buf.push(rec);
    ring.push(rec); if (ring.length > RING_MAX) ring.shift();
    _lastRec = rec;
    if (buf.length >= 25) flush();
  }

  function log(stage, event, data) {
    if (!ENABLED) return;
    var d = data || {};
    var key = stage + '|' + event + '|' + JSON.stringify(d);
    var tn = nowMs();

    // collapse consecutive identical events
    if (key === _lastKey) {
      _dupCount++;
      if (_lastRec) _lastRec.n = _dupCount;     // live-update the count
      if (shown) scheduleRender();
      if ((tn - _lastEmit) < HEARTBEAT_MS) return; // suppress flood
      _lastEmit = tn;                              // periodic heartbeat
      store({ t: tn, cwall: wall(), src: SRC, stage: stage, event: event,
              data: d, n: _dupCount });
      return;
    }

    // new distinct event
    _lastKey = key; _dupCount = 1; _lastEmit = tn;
    try {
      console.debug('%c[' + stage + ']%c ' + event,
        'color:#6cf;font-weight:bold', 'color:inherit', d);
    } catch (e) {}
    store({ t: tn, cwall: wall(), src: SRC, stage: stage, event: event, data: d, n: 1 });
    if (shown) scheduleRender();
  }

  var flushing = false;
  function flush() {
    if (flushing || buf.length === 0) return;
    flushing = true;
    var batch = buf.splice(0, buf.length);
    fetch(window.location.origin + '/api/debug/client', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: batch }),
      keepalive: true
    }).catch(function () {
      buf = batch.concat(buf);   // best-effort retry
    }).finally(function () { flushing = false; });
  }
  setInterval(flush, 1000);
  window.addEventListener('beforeunload', flush);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush();
  });

  /* timer helper:
       var end = NexusDebug.time('STT','capture');
       ... later ...  end({ bytes: blob.size }); */
  function time(stage, event, data) {
    var t0 = nowMs();
    log(stage, event + '.start', data);
    return function (extra) {
      var d = {}, k;
      if (data) for (k in data) d[k] = data[k];
      if (extra) for (k in extra) d[k] = extra[k];
      d.ms = Math.round((nowMs() - t0) * 10) / 10;
      log(stage, event + '.done', d);
    };
  }

  function fmt(r) {
    var d = r.data || {}, kv = [];
    for (var k in d) kv.push(k + '=' + d[k]);
    var line = r.cwall + ' ' + r.stage + '/' + r.event + ' ' + kv.join(' ');
    if (r.n && r.n > 1) line += '  x' + r.n;
    return line;
  }

  /* ---- on-screen overlay ---- */
  function ensureOverlay() {
    if (overlayEl) return;
    overlayEl = document.createElement('div');
    overlayEl.style.cssText = 'position:fixed;left:0;right:0;bottom:0;' +
      'max-height:46vh;overflow:auto;z-index:2147483646;background:rgba(0,0,0,.92);' +
      'color:#0f0;font:11px/1.4 monospace;padding:6px 8px;white-space:pre-wrap;' +
      'border-top:2px solid #0a6;display:none;-webkit-overflow-scrolling:touch;' +
      'user-select:text;-webkit-user-select:text';
    var bar = document.createElement('div');
    bar.style.cssText = 'display:flex;gap:6px;align-items:center;color:#9cf;' +
      'margin-bottom:4px;font-weight:bold;position:sticky;top:0;background:rgba(0,0,0,.92)';
    var title = document.createElement('span');
    title.textContent = 'ARIA DEBUG';
    title.style.flex = '1';
    pauseB = mkBtn('⏸ Pause', function () {
      paused = !paused;
      pauseB.textContent = paused ? '▶ Live' : '⏸ Pause';
      pauseB.style.background = paused ? '#a40' : '#0a6';
      if (!paused) { autoFollow = true; doRender(); }
    });
    var clearB = mkBtn('Clear', function () { ring = []; doRender(); });
    var copyB = mkBtn('Copy', function () { copyLog(copyB); });
    var hideB = mkBtn('Hide', function () { toggle(); });
    bar.appendChild(title); bar.appendChild(pauseB); bar.appendChild(clearB);
    bar.appendChild(copyB); bar.appendChild(hideB);
    bodyEl = document.createElement('div');
    overlayEl.appendChild(bar);
    overlayEl.appendChild(bodyEl);
    // if the user scrolls up, stop auto-following the tail
    overlayEl.addEventListener('scroll', function () {
      autoFollow = (overlayEl.scrollTop + overlayEl.clientHeight >=
                    overlayEl.scrollHeight - 24);
    });
    (document.body || document.documentElement).appendChild(overlayEl);
  }
  function mkBtn(label, fn) {
    var b = document.createElement('button');
    b.textContent = label;
    b.style.cssText = 'background:#0a6;color:#fff;border:0;border-radius:4px;' +
      'padding:3px 8px;font:11px monospace;cursor:pointer;white-space:nowrap';
    b.onclick = fn;
    return b;
  }
  function copyLog(btn) {
    var txt = ring.map(fmt).join('\n');
    var done = function () { if (btn) { var o = btn.textContent; btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = o; }, 1200); } };
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(done, done);
      } else {
        var ta = document.createElement('textarea');
        ta.value = txt; document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta); done();
      }
    } catch (e) {}
  }
  // throttled render: at most once per 600ms, never while paused,
  // and never clobber an active text selection inside the overlay.
  function scheduleRender() {
    if (!shown || paused || renderPending) return;
    renderPending = true;
    setTimeout(function () { renderPending = false; doRender(); }, 600);
  }
  function doRender() {
    if (!bodyEl || !shown || paused) return;
    var sel = window.getSelection && window.getSelection();
    if (sel && String(sel) && overlayEl.contains(sel.anchorNode)) return; // keep selection
    bodyEl.textContent = ring.slice(-160).map(fmt).join('\n');
    if (autoFollow) overlayEl.scrollTop = overlayEl.scrollHeight;
  }
  function toggle() {
    ensureOverlay();
    shown = !shown;
    overlayEl.style.display = shown ? 'block' : 'none';
    if (shown) { autoFollow = true; doRender(); }
  }

  /* ---- floating toggle button ---- */
  function ensureButton() {
    if (btnEl) return;
    btnEl = document.createElement('div');
    btnEl.textContent = '\uD83D\uDC1E';
    btnEl.setAttribute('aria-label', 'Toggle ARIA debug log');
    btnEl.style.cssText = 'position:fixed;right:10px;bottom:10px;z-index:2147483647;' +
      'width:40px;height:40px;border-radius:50%;background:rgba(0,140,90,.85);' +
      'color:#fff;font-size:20px;display:flex;align-items:center;justify-content:center;' +
      'box-shadow:0 2px 8px rgba(0,0,0,.4);cursor:pointer;user-select:none;' +
      '-webkit-tap-highlight-color:transparent;touch-action:manipulation';
    btnEl.addEventListener('click', function (e) { e.preventDefault(); toggle(); });
    (document.body || document.documentElement).appendChild(btnEl);
  }

  /* ---- triple-tap top-right corner = fallback opener ---- */
  var taps = [];
  document.addEventListener('touchstart', function (e) {
    var t = e.touches && e.touches[0]; if (!t) return;
    if (t.clientX < window.innerWidth - 80 || t.clientY > 80) { taps = []; return; }
    var now = Date.now();
    taps.push(now);
    taps = taps.filter(function (x) { return now - x < 1200; });
    if (taps.length >= 3) { taps = []; toggle(); }
  }, { passive: true });

  /* ---- desktop keyboard shortcut ---- */
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && e.shiftKey && (e.key === 'D' || e.key === 'd')) {
      e.preventDefault(); toggle();
    }
  });

  function boot() { if (ENABLED) ensureButton(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }

  window.NexusDebug = {
    log: log,
    time: time,
    toggle: toggle,
    flush: flush,
    setEnabled: function (b) {
      ENABLED = !!b;
      try { localStorage.setItem('nexus_debug', b ? '1' : '0'); } catch (e) {}
      if (b) ensureButton();
    },
    isEnabled: function () { return ENABLED; }
  };

  log('BOOT', 'debug-ready', { src: SRC, ua: navigator.userAgent.slice(0, 80) });
})();
