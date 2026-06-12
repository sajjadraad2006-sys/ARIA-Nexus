/* =====================================================================
   ARIA NEXUS — pages/monitor.js
   window.MonitorPage = { init, destroy }
   Polls /api/monitor/stats every 3s; clears interval on destroy().
   IDs aligned to nexus_app.html (static stat cards).
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var pollTimer = null;
  var paused = false;
  var POLL_MS = 3000;

  var SERVICES = [
    { key: 'flask', name: 'Flask API', port: 5000 },
    { key: 'llm', name: 'LLM (Gemma)', port: 8080 },
    { key: 'stt', name: 'Whisper STT', port: 8081 },
    { key: 'tts', name: 'TTS (Piper)', port: 5002 },
    { key: 'ha', name: 'Home Assistant', port: 8123 }
  ];

  function $(id) { return document.getElementById(id); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function barClass(pct) {
    if (pct > 85) return 'danger';
    if (pct >= 60) return 'warn';
    return '';
  }

  function setStat(id, valueText, pct) {
    var safePct = Math.max(0, Math.min(100, Number(pct) || 0));
    var val = $('stat-' + id + '-val');
    var bar = $('stat-' + id + '-bar');
    if (val) val.textContent = valueText;
    if (bar) {
      bar.style.transform = 'scaleX(' + (safePct / 100) + ')';
      bar.className = 'stat-bar-fill ' + barClass(safePct);
    }
  }

  function renderStats(s) {
    s = s || {};
    var ramUsed = Number(s.ram_used_gb) || 0;
    var ramTotal = Number(s.ram_total_gb) || 0;
    var ramPct = ramTotal ? (ramUsed / ramTotal) * 100 : 0;
    var diskUsed = Number(s.disk_used_gb) || 0;
    var diskTotal = Number(s.disk_total_gb) || 0;
    var diskPct = diskTotal ? (diskUsed / diskTotal) * 100 : 0;
    var cpu = Number(s.cpu_percent) || 0;
    var gpuLoad = Number(s.gpu_load_percent) || 0;
    var gpuMem = Number(s.gpu_memory_used_mb) || 0;

    setStat('cpu', cpu.toFixed(1) + '%', cpu);
    setStat('ram', ramUsed.toFixed(1) + ' / ' + ramTotal.toFixed(1) + ' GB', ramPct);
    setStat('disk', diskUsed.toFixed(1) + ' / ' + diskTotal.toFixed(1) + ' GB', diskPct);
    setStat('gpu', gpuLoad.toFixed(1) + '% \u00b7 ' + gpuMem + ' MB', gpuLoad);
  }

  function renderServices(health) {
    var grid = $('services-grid');
    if (!grid) return;
    health = health || {};
    grid.innerHTML = SERVICES.map(function (svc) {
      var state = health[svc.key];
      if (state == null) state = health[svc.port] || health[String(svc.port)] || health[svc.name];
      var status = 'unknown';
      if (state === true || state === 'online' || state === 'ok' || state === 'up') status = 'online';
      else if (state === false || state === 'offline' || state === 'down') status = 'offline';
      else if (state === 'degraded') status = 'degraded';
      return '' +
        '<div class="service-card glass">' +
        '  <span class="status-dot ' + status + '"></span>' +
        '  <span class="service-name">' + escapeHTML(svc.name) + '</span>' +
        '  <span class="service-port">:' + svc.port + '</span>' +
        '</div>';
    }).join('');
  }

  async function poll() {
    if (paused) return;
    try {
      var stats = await API.getMonitorStats();
      renderStats(stats);
      if (stats && stats.services) renderServices(stats.services);
    } catch (e) { /* keep last values */ }
    try {
      var h = await API.health();
      if (h) renderServices(h.services || h);
    } catch (e) { /* keep last service render */ }
  }

  function togglePause() {
    paused = !paused;
    var btn = $('monitor-pause-btn');
    if (btn) {
      btn.innerHTML = window.nxIcon ? nxIcon(paused ? 'play' : 'pause', { size: 18 }) : (paused ? 'Resume' : 'Pause');
      btn.setAttribute('aria-label', paused ? 'Resume live refresh' : 'Pause live refresh');
    }
    if (!paused) poll();
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    poll();
    pollTimer = setInterval(poll, POLL_MS);
  }

  function destroy() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  function wire() {
    var pauseBtn = $('monitor-pause-btn');
    if (pauseBtn) pauseBtn.addEventListener('click', togglePause);
  }

  function init() {
    if (!initialized) { initialized = true; wire(); }
    paused = false;
    var btn = $('monitor-pause-btn');
    if (btn) btn.innerHTML = window.nxIcon ? nxIcon('pause', { size: 18 }) : 'Pause';
    renderServices({});
    startPolling();
  }

  window.MonitorPage = { init: init, destroy: destroy };
})();
