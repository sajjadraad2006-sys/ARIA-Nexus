/* =====================================================================
   ARIA NEXUS — nexus.js  (APP SHELL)
   Splash, fullscreen, clock, router, launcher grid, status polling, toasts.
   Exposes window.nexus = { showToast, showPage, closePage }.
   ===================================================================== */
(function () {
  'use strict';

  var PAGES = ['launcher', 'chatbot', 'face', 'iot', 'assistant', 'monitor', 'tts', 'knowledge', 'exporter'];
  var currentPage = null;
  var clockTimer = null;
  var moduleStatusTimer = null;
  var overviewTimer = null;

  var MODULES = [
    { id: 'chatbot',   label: 'ARIA Chatbot',    icon: 'chatbot',   desc: 'Conversational AI' },
    { id: 'face',      label: 'Robot Face',      icon: 'robot',     desc: 'Talking interactive face' },
    { id: 'iot',       label: 'IoT Control',     icon: 'home',      desc: 'Smart home devices' },
    { id: 'assistant', label: 'Assistant',       icon: 'robot',     desc: 'Voice control \u00b7 memory \u00b7 routines' },
    { id: 'monitor',   label: 'System Monitor',  icon: 'monitor',   desc: 'CPU \u00b7 RAM \u00b7 GPU' },
    { id: 'tts',       label: 'TTS Studio',      icon: 'mic',       desc: 'Piper voice manager' },
    { id: 'knowledge', label: 'Knowledge Base',  icon: 'knowledge', desc: 'RAG documents' },
    { id: 'exporter',  label: 'System Exporter', icon: 'package',   desc: 'Backup & restore' }
  ];

  /* ---------------------------------------------------------------
     4. TOAST SYSTEM
  --------------------------------------------------------------- */
  function showToast(message, type) {
    type = type || 'info';
    if (window.NexusSound) {
      NexusSound.play(type === 'success' ? 'success' : (type === 'error' || type === 'danger') ? 'error' : 'notify');
    }
    var container = document.getElementById('toast-container');
    if (!container) return null;
    var toast = document.createElement('div');
    toast.className = 'nexus-toast toast-' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(function () { toast.classList.add('toast-exiting'); }, 4500);
    setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 4800);
    return toast;
  }

  /* ---------------------------------------------------------------
     1. SPLASH + FULLSCREEN
  --------------------------------------------------------------- */
  function initSplash() {
    if (window.initParticles) window.initParticles('particles-canvas');
    var enterBtn = document.getElementById('btn-enter');
    if (enterBtn) enterBtn.addEventListener('click', enterFullscreen);
  }

  function enterFullscreen() {
    var el = document.documentElement;
    var req = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
    if (req) {
      try {
        var p = req.call(el);
        if (p && typeof p.then === 'function') {
          p.then(exitSplash).catch(function () {
            showToast('Fullscreen unavailable \u2014 continuing in window', 'warning');
            exitSplash();
          });
        } else {
          exitSplash();
        }
      } catch (e) {
        showToast('Fullscreen unavailable \u2014 continuing in window', 'warning');
        exitSplash();
      }
    } else {
      showToast('Fullscreen unavailable \u2014 continuing in window', 'warning');
      exitSplash();
    }
  }

  /* ---------------------------------------------------------------
     PERF: pause background polling (network + DOM) while the tab is
     hidden, and resume the moment the user returns. Keeps the UI
     smooth and avoids wasted work / failed fetches in the background.
  --------------------------------------------------------------- */
  function pauseBackgroundTimers() {
    if (moduleStatusTimer) { clearInterval(moduleStatusTimer); moduleStatusTimer = null; }
    if (overviewTimer) { clearInterval(overviewTimer); overviewTimer = null; }
    if (window.WakeManager) WakeManager.suspend();
  }

  function resumeBackgroundTimers() {
    var dash = document.getElementById('dashboard');
    if (!dash || dash.style.display === 'none') return;
    if (!moduleStatusTimer) { pollModuleStatuses(); moduleStatusTimer = setInterval(pollModuleStatuses, 15000); }
    if (!overviewTimer) { pollOverview(); overviewTimer = setInterval(pollOverview, 5000); }
    if (window.WakeManager) WakeManager.resume();
  }

  function onVisibilityChange() {
    if (document.hidden) pauseBackgroundTimers();
    else resumeBackgroundTimers();
  }

  function exitSplash() {
    var splash = document.getElementById('splash-screen');
    if (!splash) return;
    splash.classList.add('splash-exiting');
    setTimeout(function () {
      splash.style.display = 'none';
      if (window.particlesAnimId) cancelAnimationFrame(window.particlesAnimId);
      var dash = document.getElementById('dashboard');
      if (dash) dash.style.display = 'flex';
      startClock();
      renderLauncherGrid();
      pollModuleStatuses();
      if (!moduleStatusTimer) moduleStatusTimer = setInterval(pollModuleStatuses, 15000);
      pollOverview();
      if (!overviewTimer) overviewTimer = setInterval(pollOverview, 5000);
      document.addEventListener('visibilitychange', onVisibilityChange);
      if (window.NexusSound) NexusSound.play('startup');
      if (window.WakeManager) WakeManager.init();
      showPage('launcher');
    }, 650);
  }

  function wireFullscreenToggle() {
    document.addEventListener('fullscreenchange', function () {
      var btn = document.getElementById('btn-fullscreen-toggle');
      if (!btn) return;
      if (window.nxIcon) { btn.innerHTML = nxIcon('fullscreen', { size: 20 }); }
      btn.setAttribute('aria-label', document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen');
    });
    var toggle = document.getElementById('btn-fullscreen-toggle');
    if (toggle) {
      toggle.addEventListener('click', function () {
        if (document.fullscreenElement) {
          document.exitFullscreen();
        } else {
          var el = document.documentElement;
          var req = el.requestFullscreen || el.webkitRequestFullscreen;
          if (req) { try { var p = req.call(el); if (p && p.catch) p.catch(function () {}); } catch (e) {} }
        }
      });
    }
  }

  /* ---------------------------------------------------------------
     2. LIVE CLOCK
  --------------------------------------------------------------- */
  function startClock() {
    function tick() {
      var clock = document.getElementById('header-clock');
      if (clock) clock.textContent = new Date().toLocaleTimeString('en-US', { hour12: true });
    }
    tick();
    if (clockTimer) clearInterval(clockTimer);
    clockTimer = setInterval(tick, 1000);
  }

  /* ---------------------------------------------------------------
     3. PAGE ROUTER
  --------------------------------------------------------------- */
  function showPage(pageId) {
    if (PAGES.indexOf(pageId) === -1) return;
    if (currentPage === pageId) return;

    if (currentPage) {
      if (window.NexusSound) NexusSound.play('nav');
      var prev = document.getElementById('page-' + currentPage);
      if (prev) { prev.classList.remove('active'); prev.classList.add('hidden'); }
      // Tear down monitor polling when leaving the monitor page.
      if (currentPage === 'monitor' && window.MonitorPage && MonitorPage.destroy) {
        MonitorPage.destroy();
      }
    }

    var el = document.getElementById('page-' + pageId);
    if (el) { el.classList.remove('hidden'); el.classList.add('active'); }
    currentPage = pageId;

    var navItems = document.querySelectorAll('.nav-item');
    for (var i = 0; i < navItems.length; i++) {
      navItems[i].classList.toggle('active', navItems[i].dataset.page === pageId);
    }

    var inits = {
      chatbot:   function () { if (window.ChatbotPage)  ChatbotPage.init(); },
      face:      function () { if (window.FacePage)     FacePage.init(); },
      iot:       function () { if (window.IoTPage)      IoTPage.init(); },
      assistant: function () { if (window.AssistantPage) AssistantPage.init(); },
      monitor:   function () { if (window.MonitorPage)  MonitorPage.init(); },
      tts:       function () { if (window.TTSPage)      TTSPage.init(); },
      knowledge: function () { if (window.KnowledgePage) KnowledgePage.init(); },
      exporter:  function () { if (window.ExporterPage) ExporterPage.init(); },
      launcher:  function () { pollModuleStatuses(); pollOverview(); }
    };
    if (inits[pageId]) inits[pageId]();
  }

  function closePage() { showPage('launcher'); }

  function wireSidebar() {
    var navItems = document.querySelectorAll('.nav-item');
    for (var i = 0; i < navItems.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () { showPage(btn.dataset.page); });
      })(navItems[i]);
    }
  }

  function renderLauncherGrid() {
    var grid = document.getElementById('modules-grid');
    if (!grid) return;
    grid.innerHTML = MODULES.map(function (m) {
      return '' +
        '<article class="module-card" id="card-' + m.id + '" data-page="' + m.id + '" aria-label="Open ' + m.label + '">' +
        '  <div class="card-glow"></div>' +
        '  <div class="card-icon-wrap"><span class="card-icon">' + (window.nxIcon ? nxIcon(m.icon, { size: 26 }) : '') + '</span></div>' +
        '  <div class="card-content">' +
        '    <h3 class="card-title">' + m.label + '</h3>' +
        '    <p class="card-desc">' + m.desc + '</p>' +
        '  </div>' +
        '  <div class="card-status">' +
        '    <span class="status-dot unknown" id="dot-' + m.id + '"></span>' +
        '    <span class="status-label" id="status-label-' + m.id + '">\u2014</span>' +
        '  </div>' +
        '  <span class="card-arrow" aria-hidden="true">\u203A</span>' +
        '</article>';
    }).join('');

    var cards = document.querySelectorAll('.module-card');
    for (var i = 0; i < cards.length; i++) {
      (function (card) {
        card.setAttribute('role', 'button');
        card.setAttribute('tabindex', '0');
        card.addEventListener('click', function () { showPage(card.dataset.page); });
        card.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); showPage(card.dataset.page); }
        });
      })(cards[i]);
    }
  }

  function applyModuleStatus(id, status) {
    var dot = document.getElementById('dot-' + id);
    var label = document.getElementById('status-label-' + id);
    var valid = ['online', 'degraded', 'offline', 'unknown'];
    var s = valid.indexOf(status) === -1 ? 'unknown' : status;
    if (dot) dot.className = 'status-dot ' + s;
    if (label) label.textContent = s;
  }

  function pollModuleStatuses() {
    if (!window.API) return;
    API.getModules().then(function (modules) {
      if (!Array.isArray(modules)) return;
      modules.forEach(function (m) {
        if (m && m.id) applyModuleStatus(m.id, m.status || 'unknown');
      });
      var onlineCount = modules.filter(function (m) { return m && m.status === 'online'; }).length;
      ovSetStat('ov-services', onlineCount + ' / ' + modules.length);
      var ci = document.getElementById('connection-indicator');
      if (ci) ci.className = 'status-dot online';
    }).catch(function () {
      // Silent on background poll failure, but reflect connection loss.
      var ci = document.getElementById('connection-indicator');
      if (ci) ci.className = 'status-dot offline';
    });
  }

  /* ---------------------------------------------------------------
     COMMAND CENTER OVERVIEW (fills the launcher with live data)
  --------------------------------------------------------------- */
  function ovEscape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function ovSetStat(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = (val == null ? '\u2014' : val);
  }

  function ovUpdateVital(name, pct) {
    var v = (typeof pct === 'number' && isFinite(pct)) ? Math.max(0, Math.min(100, pct)) : null;
    var valEl = document.getElementById('ov-' + name + '-val');
    var barEl = document.getElementById('ov-' + name + '-bar');
    if (valEl) valEl.textContent = (v == null ? '\u2014' : Math.round(v) + '%');
    if (barEl) {
      barEl.style.width = (v == null ? 0 : v) + '%';
      barEl.className = 'ov-bar-fill' + (v != null && v > 85 ? ' danger' : (v != null && v > 60 ? ' warn' : ''));
    }
  }

  function ovRenderServices(services) {
    var list = document.getElementById('ov-service-list');
    if (!list) return;
    if (!services || typeof services !== 'object') {
      if (!list.querySelector('.ov-pill')) list.innerHTML = '<span class="ov-empty">No service data</span>';
      return;
    }
    var keys = Object.keys(services);
    if (keys.length === 0) { list.innerHTML = '<span class="ov-empty">No services reported</span>'; return; }
    list.innerHTML = keys.map(function (k) {
      var st = String(services[k]).toLowerCase() === 'online' ? 'online' : 'offline';
      return '<span class="ov-pill"><span class="status-dot ' + st + '"></span>' + ovEscape(k) + '</span>';
    }).join('');
  }

  function pollOverview() {
    if (!window.API || currentPage !== 'launcher') return;
    if (API.getMonitorStats) API.getMonitorStats().then(function (s) {
      s = s || {};
      ovUpdateVital('cpu', s.cpu_percent);
      ovUpdateVital('ram', s.ram_percent);
      ovUpdateVital('gpu', s.gpu_load_percent);
      ovRenderServices(s.services);
    }).catch(function () {});
    if (API.getRAGStats) API.getRAGStats().then(function (d) {
      ovSetStat('ov-kb', d && d.document_count != null ? d.document_count : '\u2014');
    }).catch(function () {});
    if (API.getHAEntities) API.getHAEntities().then(function (list) {
      ovSetStat('ov-iot', Array.isArray(list) ? list.length : '\u2014');
    }).catch(function () {});
    if (API.getTTSVoices) API.getTTSVoices().then(function (list) {
      ovSetStat('ov-tts', Array.isArray(list) ? list.length : '\u2014');
    }).catch(function () {});
  }

  /* ---------------------------------------------------------------
     BOOT
  --------------------------------------------------------------- */
  function boot() {
    window.nexus = { showToast: showToast, showPage: showPage, closePage: closePage };
    initSplash();
    wireFullscreenToggle();
    wireSidebar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
