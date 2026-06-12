/* =====================================================================
   ARIA NEXUS — pages/tts.js
   window.TTSPage = { init }
   IDs aligned to nexus_app.html.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var voices = [];
  var activeVoiceId = null;
  var langFilter = 'all';
  var searchTerm = '';
  var currentAudio = null;

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* Returns an inline SVG language chip (flag-style). Local, scalable. */
  function languageFlag(lang) {
    return (window.nxLangBadge ? nxLangBadge(lang) : '');
  }

  function voiceId(v) { return v.id || v.voice_id; }

  async function loadTTSStatus() {
    var dot = $('tts-status-dot');
    var text = $('tts-status-text');
    try {
      await API.health();
      if (dot) dot.className = 'status-dot online';
      if (text) text.textContent = 'TTS server online';
    } catch (e) {
      if (dot) dot.className = 'status-dot offline';
      if (text) text.textContent = 'TTS server offline (:5002)';
    }
  }

  async function loadVoices() {
    var grid = $('tts-voice-grid');
    if (grid) grid.innerHTML = '<p class="empty-state">Loading voices\u2026</p>';
    try {
      var data = await API.getTTSVoices();
      voices = Array.isArray(data) ? data : (data && data.voices) || [];
      if (data && data.active) activeVoiceId = data.active;
      voices.forEach(function (v) { if (v.active) activeVoiceId = voiceId(v); });

      // ── Auto-assign per-language voices (Arabic + English) ──────────
      voices.forEach(function (v) {
        var id  = voiceId(v);
        var langCode = (v.language || v.lang || '').slice(0, 2).toLowerCase();
        if (!langCode) {
          var n = (v.name || id || '').toLowerCase();
          if (n.indexOf('ar') !== -1 || n.indexOf('kareem') !== -1) langCode = 'ar';
          else if (n.indexOf('en') !== -1 || n.indexOf('semaine') !== -1 || n.indexOf('amy') !== -1) langCode = 'en';
        }
        if (langCode === 'ar' && !localStorage.getItem('nexus_voice_ar'))
          localStorage.setItem('nexus_voice_ar', id);
        if (langCode === 'en' && !localStorage.getItem('nexus_voice_en'))
          localStorage.setItem('nexus_voice_en', id);
      });

      // ── If no active voice set yet, pick the first one ───────────────
      if (!activeVoiceId && voices.length) {
        activeVoiceId = voiceId(voices[0]);
        try { await API.setTTSVoice(activeVoiceId); } catch (e) {}
        localStorage.setItem('nexus_tts_voice', activeVoiceId);
      }

      renderLangFilter();
      renderVoices();
      renderCurrentVoice();
    } catch (e) {
      if (grid) grid.innerHTML = '<p class="empty-state">TTS service unavailable at :5002.</p>';
    }
  }

  function renderLangFilter() {
    var sel = $('tts-lang-filter');
    if (!sel) return;
    var langs = {};
    voices.forEach(function (v) { var l = (v.language || v.lang || '').slice(0, 2); if (l) langs[l] = true; });
    var opts = ['<option value="all">All Languages</option>'].concat(
      Object.keys(langs).sort().map(function (l) {
        return '<option value="' + escapeHTML(l) + '"' + (l === langFilter ? ' selected' : '') + '>' +
          escapeHTML(l.toUpperCase()) + '</option>';
      })
    );
    sel.innerHTML = opts.join('');
  }

  function renderVoices() {
    var grid = $('tts-voice-grid');
    if (!grid) return;
    var filtered = voices.filter(function (v) {
      var lang = (v.language || v.lang || '').slice(0, 2);
      var matchLang = langFilter === 'all' || lang === langFilter;
      var name = (v.name || voiceId(v) || '').toLowerCase();
      var matchSearch = !searchTerm || name.indexOf(searchTerm.toLowerCase()) !== -1;
      return matchLang && matchSearch;
    });
    if (filtered.length === 0) {
      grid.innerHTML = '<p class="empty-state">No voices match your filters.</p>';
      return;
    }
    grid.innerHTML = filtered.map(function (v) {
      var id = voiceId(v);
      var quality = (v.quality || 'medium').toLowerCase();
      var isActive = String(id) === String(activeVoiceId);
      var speakers = v.num_speakers || v.speakers;
      return '' +
        '<div class="voice-card glass' + (isActive ? ' voice-active' : '') + '">' +
        '  <div class="entity-header">' +
        '    <span class="voice-lang-flag">' + languageFlag(v.language || v.lang) + '</span>' +
        '    <div class="voice-info">' +
        '      <span class="voice-name">' + escapeHTML(v.name || id) + '</span>' +
        '      <span class="voice-lang">' + escapeHTML((v.language || v.lang || '').toUpperCase()) + '</span>' +
        '    </div>' +
        '  </div>' +
        '  <span class="voice-quality quality-' + escapeHTML(quality) + '">' + escapeHTML(quality) + '</span>' +
        (speakers ? '<span class="voice-speakers">' + escapeHTML(speakers) + ' speaker(s)</span>' : '') +
        '  <div class="voice-actions">' +
        '    <button class="btn-secondary tts-preview" data-id="' + escapeHTML(id) + '" aria-label="Preview ' + escapeHTML(v.name || id) + '">' + (window.nxIcon ? nxIcon('play', { size: 14 }) + ' ' : '') + 'Preview</button>' +
        (isActive
          ? '    <button class="btn-primary" disabled aria-label="Active voice">' + (window.nxIcon ? nxIcon('check', { size: 14 }) + ' ' : '') + 'Active</button>'
          : '    <button class="btn-primary tts-set" data-id="' + escapeHTML(id) + '" aria-label="Set ' + escapeHTML(v.name || id) + ' active">Set active</button>') +
        '  </div>' +
        '</div>';
    }).join('');
    wireVoiceCards();
  }

  function renderCurrentVoice() {
    var nameEl = $('tts-active-voice-name');
    var metaEl = $('tts-active-voice-meta');
    var v = voices.filter(function (x) { return String(voiceId(x)) === String(activeVoiceId); })[0];
    if (!v) {
      if (nameEl) nameEl.textContent = 'None selected';
      if (metaEl) metaEl.textContent = '';
      return;
    }
    if (nameEl) nameEl.innerHTML = languageFlag(v.language || v.lang) + ' ' + escapeHTML(v.name || voiceId(v));
    if (metaEl) metaEl.textContent = (v.language || v.lang || '').toUpperCase() + ' \u00b7 ' + (v.quality || 'medium');
  }

  function wireVoiceCards() {
    var grid = $('tts-voice-grid');
    if (!grid) return;
    var previews = grid.querySelectorAll('.tts-preview');
    for (var i = 0; i < previews.length; i++) {
      (function (btn) { btn.addEventListener('click', function () { previewVoice(btn.dataset.id, btn); }); })(previews[i]);
    }
    var sets = grid.querySelectorAll('.tts-set');
    for (var j = 0; j < sets.length; j++) {
      (function (btn) { btn.addEventListener('click', function () { setActiveVoice(btn.dataset.id); }); })(sets[j]);
    }
  }

  function previewText() {
    var ta = $('tts-preview-text');
    return (ta && ta.value.trim()) || 'Hello, I am ARIA, your personal AI assistant.';
  }

  async function previewVoice(id, btn) {
    if (btn) btn.disabled = true;
    try {
      var blob = await API.previewTTSVoice(id, previewText());
      if (currentAudio) { currentAudio.pause(); currentAudio = null; }
      var url = URL.createObjectURL(blob);
      currentAudio = new Audio(url);
      currentAudio.addEventListener('ended', function () { URL.revokeObjectURL(url); });
      await currentAudio.play();
    } catch (e) {
      toast('Preview failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function setActiveVoice(id) {
    try {
      await API.setTTSVoice(id);
      activeVoiceId = id;
      // Persist so the Chatbot and Robot Face pages speak with this same voice.
      try { localStorage.setItem('nexus_tts_voice', id); } catch (e) {}
      toast('Voice updated', 'success');
      renderVoices();
      renderCurrentVoice();
    } catch (e) { toast('Could not set voice', 'error'); }
  }

  function wire() {
    var sel = $('tts-lang-filter');
    if (sel) sel.addEventListener('change', function () { langFilter = sel.value; renderVoices(); });
    var search = $('tts-voice-search');
    if (search) search.addEventListener('input', function () { searchTerm = search.value; renderVoices(); });
    var previewActive = $('tts-preview-active-btn');
    if (previewActive) previewActive.addEventListener('click', function () {
      if (activeVoiceId) previewVoice(activeVoiceId, previewActive);
      else toast('No active voice selected', 'warning');
    });
  }

  function init() {
    if (!initialized) { initialized = true; wire(); }
    loadTTSStatus();
    loadVoices();
  }

  window.TTSPage = { init: init };
})();
