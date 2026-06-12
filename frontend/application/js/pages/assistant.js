/* =====================================================================
   ARIA NEXUS — pages/assistant.js   window.AssistantPage = { init }
   ---------------------------------------------------------------------
   The human-facing manager for ARIA's brain:
     • Language & Voice — pick a Piper voice per language (ar/en). The app
       auto-switches voice based on the language of each reply.
     • Personal memory — name + freeform facts.
     • Routines — full editor: add / rename / triggers / steps / run /
       delete, persisted to the backend via API.saveRoutines.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var voices = [];            // [{id,name,...}]
  var routinesState = [];     // working copy of routines

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function attr(str) { return escapeHTML(str).replace(/\n/g, ' '); }

  function feedback(msg, isErr) {
    var el = $('assist-feedback');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
    el.style.color = isErr ? 'var(--danger, #ff6a6a)' : '';
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.add('hidden'); }, 3500);
  }

  function speakSample(text, voiceId) {
    if (window.VoiceManager) { VoiceManager.speak(text, { voice: voiceId }); return; }
    if (!window.API || !API.previewTTSVoice) return;
    API.previewTTSVoice(voiceId || '', text).then(function (blob) {
      if (!blob || !blob.size) return;
      var url = URL.createObjectURL(blob);
      var a = new Audio(url);
      a.onended = function () { URL.revokeObjectURL(url); };
      a.play().catch(function () {});
    }).catch(function () {});
  }

  /* =================================================================
     LANGUAGE & VOICE
  ================================================================= */
  function voiceId(v) { return v.id || v.voice_id || ''; }
  function voiceLabel(v) {
    var name = v.name || v.label || voiceId(v);
    var lang = v.language || v.lang || v.locale;
    return lang ? (name + ' · ' + lang) : name;
  }

  function fillVoiceSelect(sel, savedKey, fallbackHint) {
    if (!sel) return;
    var saved = localStorage.getItem(savedKey) || '';
    var opts = ['<option value="">' + escapeHTML(fallbackHint) + '</option>'];
    voices.forEach(function (v) {
      var id = voiceId(v);
      opts.push('<option value="' + attr(id) + '"' +
        (id === saved ? ' selected' : '') + '>' + escapeHTML(voiceLabel(v)) + '</option>');
    });
    sel.innerHTML = opts.join('');
  }

  function loadVoicePanel() {
    var arSel = $('assist-voice-ar');
    var enSel = $('assist-voice-en');
    var tog = $('assist-tts-toggle');
    if (tog) tog.checked = localStorage.getItem('nexus_chat_tts') !== '0';
    if (!window.API || !API.getTTSVoices) {
      fillVoiceSelect(arSel, 'nexus_voice_ar', 'الافتراضي');
      fillVoiceSelect(enSel, 'nexus_voice_en', 'Default');
      return;
    }
    API.getTTSVoices().then(function (data) {
      voices = Array.isArray(data) ? data : (data && data.voices) || [];
      fillVoiceSelect(arSel, 'nexus_voice_ar', 'الافتراضي — auto');
      fillVoiceSelect(enSel, 'nexus_voice_en', 'Default — auto');
    }).catch(function () {
      fillVoiceSelect(arSel, 'nexus_voice_ar', 'الافتراضي');
      fillVoiceSelect(enSel, 'nexus_voice_en', 'Default');
    });
  }

  function wireVoicePanel() {
    var arSel = $('assist-voice-ar');
    var enSel = $('assist-voice-en');
    var tog = $('assist-tts-toggle');
    if (arSel) arSel.addEventListener('change', function () {
      localStorage.setItem('nexus_voice_ar', arSel.value);
      if (!localStorage.getItem('nexus_tts_voice') && arSel.value) {
        localStorage.setItem('nexus_tts_voice', arSel.value);
      }
      feedback('تم حفظ الصوت العربي');
    });
    if (enSel) enSel.addEventListener('change', function () {
      localStorage.setItem('nexus_voice_en', enSel.value);
      feedback('English voice saved');
    });
    if (tog) tog.addEventListener('change', function () {
      localStorage.setItem('nexus_chat_tts', tog.checked ? '1' : '0');
      feedback(tog.checked ? 'النطق مفعّل' : 'النطق متوقف');
    });
    var tests = document.querySelectorAll('.assist-voice-test');
    for (var i = 0; i < tests.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var lang = btn.dataset.lang;
          if (lang === 'ar') {
            speakSample('مرحباً، أنا آريا. هذا اختبار للصوت العربي.', (arSel || {}).value || '');
          } else {
            speakSample('Hi, I am ARIA. This is an English voice test.', (enSel || {}).value || '');
          }
        });
      })(tests[i]);
    }
  }

  /* =================================================================
     MEMORY
  ================================================================= */
  function renderMemory(mem) {
    mem = mem || { name: '', facts: {} };
    var nameInput = $('assist-name-input');
    if (nameInput && document.activeElement !== nameInput) {
      nameInput.value = mem.name || '';
    }
    var list = $('assist-mem-list');
    if (!list) return;
    var facts = mem.facts || {};
    var keys = Object.keys(facts);
    if (!keys.length) {
      list.innerHTML = '<p class="assist-empty">لا توجد معلومات محفوظة بعد.</p>';
      return;
    }
    list.innerHTML = keys.map(function (k) {
      return '' +
        '<div class="assist-row">' +
        '  <div class="assist-row-main">' +
        '    <span class="assist-key">' + escapeHTML(k) + '</span>' +
        '    <span class="assist-val">' + escapeHTML(facts[k]) + '</span>' +
        '  </div>' +
        '  <button class="btn-icon assist-del" data-key="' + attr(k) + '" aria-label="Delete">' +
        '    <span class="nx-i" data-icon="trash" data-icon-size="15"></span></button>' +
        '</div>';
    }).join('');
    if (window.nxHydrateIcons) nxHydrateIcons(list);
    var dels = list.querySelectorAll('.assist-del');
    for (var i = 0; i < dels.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          API.deleteMemory(btn.dataset.key).then(function (r) {
            renderMemory(r && r.memory);
            feedback('تم الحذف');
          }).catch(function () { feedback('تعذر الحذف', true); });
        });
      })(dels[i]);
    }
  }

  function loadMemory() {
    if (!window.API || !API.getMemory) return;
    API.getMemory().then(function (r) { renderMemory(r && r.memory); }).catch(function () {});
  }

  function saveName() {
    var v = ($('assist-name-input') || {}).value || '';
    API.setMemory({ name: v.trim() }).then(function (r) {
      renderMemory(r && r.memory);
      feedback('تم حفظ الاسم');
    }).catch(function () { feedback('تعذر الحفظ', true); });
  }

  function addFact() {
    var key = ($('assist-fact-key') || {}).value || '';
    var val = ($('assist-fact-val') || {}).value || '';
    key = key.trim();
    if (!key) { feedback('اكتب اسم المعلومة', true); return; }
    API.setMemory({ key: key, value: val.trim() }).then(function (r) {
      $('assist-fact-key').value = '';
      $('assist-fact-val').value = '';
      renderMemory(r && r.memory);
      feedback('تمت الإضافة');
    }).catch(function () { feedback('تعذر الحفظ', true); });
  }

  /* =================================================================
     ROUTINES — full editor
  ================================================================= */
  var STEP_TYPES = [
    { v: 'say', t: '🗣 قول نص — Say' },
    { v: 'weather', t: '🌤 الطقس — Weather' },
    { v: 'news', t: '📰 الأخبار — News' },
    { v: 'schedule', t: '📅 الجدول — Schedule' },
    { v: 'scene', t: '🎬 مشهد — Scene' },
    { v: 'ha', t: '🏠 جهاز/خدمة — Device' }
  ];

  function genId(name) {
    var base = (name || 'routine').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    return (base || 'routine') + '_' + Math.random().toString(36).slice(2, 6);
  }

  function stepFieldsHTML(step) {
    var t = (step && step.type) || 'say';
    if (t === 'say') {
      return '<input class="nexus-input assist-step-f" data-f="text" type="text" ' +
        'placeholder="النص المنطوق…" value="' + attr(step.text || '') + '">';
    }
    if (t === 'scene') {
      return '<input class="nexus-input assist-step-f" data-f="entity" type="text" ' +
        'placeholder="scene.morning" value="' + attr(step.entity || '') + '">';
    }
    if (t === 'ha') {
      return '' +
        '<input class="nexus-input assist-step-f assist-step-sm" data-f="domain" type="text" placeholder="light" value="' + attr(step.domain || '') + '">' +
        '<input class="nexus-input assist-step-f assist-step-sm" data-f="service" type="text" placeholder="turn_off" value="' + attr(step.service || '') + '">' +
        '<input class="nexus-input assist-step-f" data-f="entity" type="text" placeholder="entity_id (فارغ = الكل)" value="' + attr(step.entity || (step.target === 'all' ? '' : '')) + '">' +
        '<label class="assist-step-all"><input type="checkbox" data-f="all"' + (step.target === 'all' ? ' checked' : '') + '> الكل</label>';
    }
    return '<span class="assist-step-note">لا توجد إعدادات إضافية</span>';
  }

  function stepRowHTML(step) {
    var t = (step && step.type) || 'say';
    var typeOpts = STEP_TYPES.map(function (o) {
      return '<option value="' + o.v + '"' + (o.v === t ? ' selected' : '') + '>' + escapeHTML(o.t) + '</option>';
    }).join('');
    return '' +
      '<div class="assist-step-row">' +
      '  <select class="nexus-input assist-step-type" aria-label="Step type">' + typeOpts + '</select>' +
      '  <div class="assist-step-fields">' + stepFieldsHTML(step) + '</div>' +
      '  <button class="btn-icon assist-step-del" aria-label="Remove step">✕</button>' +
      '</div>';
  }

  function routineCardHTML(r) {
    var triggers = (r.triggers || []).join('، ');
    var steps = (r.steps || []).map(stepRowHTML).join('');
    return '' +
      '<div class="glass assist-routine" data-id="' + attr(r.id || '') + '">' +
      '  <div class="assist-routine-head">' +
      '    <input class="nexus-input assist-r-name" type="text" value="' + attr(r.name || '') + '" placeholder="اسم الروتين">' +
      '    <button class="btn-primary assist-run" aria-label="Run routine">▶ تشغيل</button>' +
      '  </div>' +
      '  <label class="form-label">كلمات التشغيل (افصلها بفاصلة):</label>' +
      '  <input class="nexus-input assist-r-trig" type="text" value="' + attr(triggers) + '" placeholder="صباح الخير، good morning">' +
      '  <label class="form-label">الخطوات:</label>' +
      '  <div class="assist-steps-edit">' + steps + '</div>' +
      '  <button class="btn-secondary assist-step-add">＋ خطوة</button>' +
      '  <div class="form-actions assist-routine-actions">' +
      '    <button class="btn-primary assist-r-save">💾 حفظ</button>' +
      '    <button class="btn-ghost assist-r-del">🗑 حذف</button>' +
      '  </div>' +
      '</div>';
  }

  function renderRoutines() {
    var list = $('assist-routine-list');
    if (!list) return;
    if (!routinesState.length) {
      list.innerHTML = '<p class="assist-empty">لا توجد روتينات. اضغط «روتين جديد».</p>';
      return;
    }
    list.innerHTML = routinesState.map(routineCardHTML).join('');
    wireRoutineCards();
  }

  // Read a routine object back out of its card DOM.
  function collectRoutine(card) {
    var id = card.getAttribute('data-id') || '';
    var name = (card.querySelector('.assist-r-name') || {}).value || '';
    name = name.trim();
    var trigStr = (card.querySelector('.assist-r-trig') || {}).value || '';
    var triggers = trigStr.split(/[،,]/).map(function (s) { return s.trim(); }).filter(Boolean);
    var steps = [];
    var rows = card.querySelectorAll('.assist-step-row');
    for (var i = 0; i < rows.length; i++) {
      var row = rows[i];
      var type = (row.querySelector('.assist-step-type') || {}).value || 'say';
      var step = { type: type };
      function fval(f) { var el = row.querySelector('[data-f="' + f + '"]'); return el ? el.value : ''; }
      if (type === 'say') { step.text = fval('text'); }
      else if (type === 'scene') { step.entity = fval('entity'); }
      else if (type === 'ha') {
        step.domain = fval('domain');
        step.service = fval('service');
        var allEl = row.querySelector('[data-f="all"]');
        var ent = fval('entity');
        if (allEl && allEl.checked) { step.target = 'all'; }
        else if (ent) { step.entity = ent; }
      }
      steps.push(step);
    }
    if (!id) id = genId(name);
    return { id: id, name: name || id, triggers: triggers, steps: steps };
  }

  function persistRoutines() {
    if (!window.API || !API.saveRoutines) { feedback('الحفظ غير متاح', true); return; }
    API.saveRoutines(routinesState).then(function (r) {
      if (r && Array.isArray(r.routines)) routinesState = r.routines;
      renderRoutines();
      feedback('✓ تم حفظ الروتينات');
    }).catch(function () { feedback('تعذر حفظ الروتينات', true); });
  }

  function wireRoutineCards() {
    var list = $('assist-routine-list');
    if (!list) return;
    var cards = list.querySelectorAll('.assist-routine');
    for (var i = 0; i < cards.length; i++) {
      (function (card, idx) {
        // Re-render a step's fields when its type changes.
        var typeSels = card.querySelectorAll('.assist-step-type');
        for (var s = 0; s < typeSels.length; s++) {
          typeSels[s].addEventListener('change', function (e) {
            var row = e.target.closest('.assist-step-row');
            var fields = row.querySelector('.assist-step-fields');
            if (fields) fields.innerHTML = stepFieldsHTML({ type: e.target.value });
          });
        }
        // Remove a step.
        var delSteps = card.querySelectorAll('.assist-step-del');
        for (var d = 0; d < delSteps.length; d++) {
          delSteps[d].addEventListener('click', function (e) {
            var row = e.target.closest('.assist-step-row');
            if (row) row.parentNode.removeChild(row);
          });
        }
        // Add a step.
        var addStep = card.querySelector('.assist-step-add');
        if (addStep) addStep.addEventListener('click', function () {
          var box = card.querySelector('.assist-steps-edit');
          if (!box) return;
          var tmp = document.createElement('div');
          tmp.innerHTML = stepRowHTML({ type: 'say', text: '' });
          var row = tmp.firstChild;
          box.appendChild(row);
          // wire the new row
          row.querySelector('.assist-step-type').addEventListener('change', function (e) {
            var f = row.querySelector('.assist-step-fields');
            if (f) f.innerHTML = stepFieldsHTML({ type: e.target.value });
          });
          row.querySelector('.assist-step-del').addEventListener('click', function () {
            row.parentNode.removeChild(row);
          });
        });
        // Save this routine (sync working copy from all cards, then persist).
        var saveBtn = card.querySelector('.assist-r-save');
        if (saveBtn) saveBtn.addEventListener('click', function () {
          syncStateFromDOM();
          var col = collectRoutine(card);
          if (!col.name) { feedback('اكتب اسم الروتين', true); return; }
          persistRoutines();
        });
        // Delete this routine.
        var delBtn = card.querySelector('.assist-r-del');
        if (delBtn) delBtn.addEventListener('click', function () {
          var id = card.getAttribute('data-id');
          routinesState = routinesState.filter(function (r) { return r.id !== id; });
          persistRoutines();
        });
        // Run this routine.
        var runBtn = card.querySelector('.assist-run');
        if (runBtn) runBtn.addEventListener('click', function () {
          var id = card.getAttribute('data-id');
          if (!id || !window.API || !API.runRoutine) { feedback('احفظ الروتين أولاً', true); return; }
          runBtn.disabled = true;
          API.runRoutine(id).then(function (r) {
            runBtn.disabled = false;
            var msg = (r && r.response) ? r.response : 'تم التشغيل';
            toast(msg.split('\n')[0], 'success');
            feedback('✓ ' + (r && r.routine ? r.routine : ''));
            if (window.VoiceManager) VoiceManager.speak(msg);
          }).catch(function () {
            runBtn.disabled = false;
            feedback('تعذر تشغيل الروتين', true);
          });
        });
      })(cards[i], i);
    }
  }

  // Pull current edits from every card into routinesState (preserves order).
  function syncStateFromDOM() {
    var list = $('assist-routine-list');
    if (!list) return;
    var cards = list.querySelectorAll('.assist-routine');
    var next = [];
    for (var i = 0; i < cards.length; i++) next.push(collectRoutine(cards[i]));
    routinesState = next;
  }

  function addRoutine() {
    syncStateFromDOM();
    routinesState.push({
      id: genId('routine'),
      name: 'روتين جديد',
      triggers: [],
      steps: [{ type: 'say', text: 'تم.' }]
    });
    renderRoutines();
    feedback('أضِف الخطوات ثم احفظ');
  }

  function loadRoutines() {
    if (!window.API || !API.getRoutines) return;
    API.getRoutines().then(function (r) {
      routinesState = (r && Array.isArray(r.routines)) ? r.routines : [];
      renderRoutines();
    }).catch(function () {});
  }

  function refreshHA() {
    var dot = $('assist-ha-dot');
    if (!dot || !window.API || !API.getHAEntities) return;
    API.getHAEntities().then(function (list) {
      dot.className = 'status-dot ' + (Array.isArray(list) && list.length ? 'online' : 'degraded');
    }).catch(function () { dot.className = 'status-dot offline'; });
  }

  /* =================================================================
     WIRING
  ================================================================= */
  function wire() {
    var ns = $('assist-name-save');
    if (ns) ns.addEventListener('click', saveName);
    var ni = $('assist-name-input');
    if (ni) ni.addEventListener('keydown', function (e) { if (e.key === 'Enter') saveName(); });
    var fa = $('assist-fact-add');
    if (fa) fa.addEventListener('click', addFact);
    var fv = $('assist-fact-val');
    if (fv) fv.addEventListener('keydown', function (e) { if (e.key === 'Enter') addFact(); });
    var ra = $('assist-routine-add');
    if (ra) ra.addEventListener('click', addRoutine);
    var rf = $('assist-refresh-btn');
    if (rf) rf.addEventListener('click', function () {
      loadVoicePanel(); loadMemory(); loadRoutines(); refreshHA();
    });
    wireVoicePanel();
  }

  function init() {
    if (!initialized) { initialized = true; wire(); }
    loadVoicePanel();
    loadMemory();
    loadRoutines();
    refreshHA();
  }

  window.AssistantPage = { init: init };
})();
