/* =====================================================================
   ARIA NEXUS — pages/knowledge.js
   window.KnowledgePage = { init }
   Features: view current KB, add knowledge (paste text), view/edit a
   document's text, test a query, tune RAG settings, reindex.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var documents = [];

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }
  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }
  function md(t) { return window.nxMarkdown ? nxMarkdown(t) : escapeHTML(t); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function formatBytes(bytes) {
    var b = Number(bytes) || 0;
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    if (b < 1024 * 1024 * 1024) return (b / (1024 * 1024)).toFixed(1) + ' MB';
    return (b / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }

  function formatTime(ts) {
    if (!ts) return '\u2014';
    var d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
    if (isNaN(d.getTime())) return String(ts);
    return d.toLocaleString('en-GB', { hour12: false });
  }

  function setText(id, value) { var el = $(id); if (el) el.textContent = (value == null ? '\u2014' : value); }

  async function loadRAGStats() {
    var dot = $('rag-status-dot');
    try {
      var data = await API.getRAGStats();
      if (dot) dot.className = 'status-dot online';
      documents = (data && data.documents) || [];
      setText('rag-collection-name', (data && data.collection) || (data && data.collection_name) || 'aria_kb');
      setText('rag-doc-count', (data && data.document_count != null) ? data.document_count : documents.length);
      setText('rag-chunk-count', (data && data.chunk_count != null) ? data.chunk_count : '\u2014');
      setText('rag-embed-model', (data && data.embedding_model) || '\u2014');
      if (data && data.settings) applySettings(data.settings);
      renderDocList();
    } catch (e) {
      if (dot) dot.className = 'status-dot offline';
      var list = $('rag-doc-list');
      if (list) list.innerHTML = '<p class="empty-state">Knowledge base unavailable.</p>';
    }
  }

  function applySettings(s) {
    if ($('rag-chunk-size') && s.chunk_size != null) $('rag-chunk-size').value = s.chunk_size;
    if ($('rag-chunk-overlap') && s.chunk_overlap != null) $('rag-chunk-overlap').value = s.chunk_overlap;
    if ($('rag-top-k') && s.top_k != null) $('rag-top-k').value = s.top_k;
    if ($('rag-min-relevance') && s.min_relevance != null) $('rag-min-relevance').value = s.min_relevance;
  }

  function renderDocList() {
    var list = $('rag-doc-list');
    if (!list) return;
    if (documents.length === 0) {
      list.innerHTML = '<p class="empty-state">No documents indexed yet. Add some knowledge above.</p>';
      return;
    }
    list.innerHTML = documents.map(function (d) {
      var name = d.filename || d.name || 'unknown';
      var safe = escapeHTML(name);
      return '' +
        '<div class="rag-doc-row glass">' +
        '  <div class="doc-info">' +
        '    <span class="doc-name">' + (window.nxIcon ? nxIcon('doc', { size: 15 }) + ' ' : '') + safe + '</span>' +
        '    <span class="doc-chunks">' + escapeHTML(d.chunks != null ? d.chunks : '?') + ' chunks</span>' +
        '    <span class="doc-size">' + escapeHTML(formatBytes(d.size_bytes || d.size)) + '</span>' +
        '    <span class="doc-modified">' + escapeHTML(formatTime(d.modified || d.mtime)) + '</span>' +
        '  </div>' +
        '  <div class="doc-actions">' +
        '    <button class="btn-ghost rag-doc-memory" data-name="' + safe + '" aria-expanded="false">Show memory</button>' +
        '    <button class="btn-secondary rag-doc-edit" data-name="' + safe + '">View / Edit</button>' +
        '    <button class="btn-danger rag-doc-delete" data-name="' + safe + '" aria-label="Delete ' + safe + '">Delete</button>' +
        '  </div>' +
        '  <div class="rag-doc-memory-panel hidden" data-name="' + safe + '"></div>' +
        '</div>';
    }).join('');
    bindDocButtons(list);
  }

  function bindDocButtons(list) {
    var edits = list.querySelectorAll('.rag-doc-edit');
    for (var i = 0; i < edits.length; i++) {
      (function (btn) { btn.addEventListener('click', function () { openDoc(btn.dataset.name); }); })(edits[i]);
    }
    var mems = list.querySelectorAll('.rag-doc-memory');
    for (var m = 0; m < mems.length; m++) {
      (function (btn) {
        btn.addEventListener('click', function () { toggleMemory(btn); });
      })(mems[m]);
    }
    var dels = list.querySelectorAll('.rag-doc-delete');
    for (var j = 0; j < dels.length; j++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          if (!window.confirm('Delete "' + btn.dataset.name + '" from the knowledge base?')) return;
          try {
            await API.deleteRAGDocument(btn.dataset.name);
            toast('Document deleted', 'success');
            var ed = $('kb-editor');
            if (ed && ed.dataset.name === btn.dataset.name) hide(ed);
            await loadRAGStats();
          } catch (e) { toast('Delete failed', 'error'); }
        });
      })(dels[j]);
    }
  }

  /* ---- Inline "everything ARIA remembers" viewer ---- */
  async function toggleMemory(btn) {
    var row = btn.closest('.rag-doc-row');
    if (!row) return;
    var panel = row.querySelector('.rag-doc-memory-panel');
    if (!panel) return;
    if (!panel.classList.contains('hidden')) {
      panel.classList.add('hidden');
      btn.setAttribute('aria-expanded', 'false');
      btn.textContent = 'Show memory';
      return;
    }
    btn.setAttribute('aria-expanded', 'true');
    btn.textContent = 'Hide memory';
    panel.classList.remove('hidden');
    panel.innerHTML = '<p class="empty-state">Loading stored memory\u2026</p>';
    try {
      var data = await API.getRAGDocument(btn.dataset.name);
      var text = (data && (data.text || data.content)) || '';
      panel.innerHTML =
        '<div class="memory-head">Exactly what ARIA stored for this entry</div>' +
        '<pre class="memory-text">' + escapeHTML(text || '(empty)') + '</pre>';
    } catch (e) {
      panel.innerHTML = '<p class="empty-state">Could not load stored memory.</p>';
    }
  }

  /* ---- Add knowledge (paste text) ---- */
  async function addKnowledge() {
    var titleEl = $('kb-add-title');
    var textEl = $('kb-add-text');
    if (!textEl) return;
    var title = titleEl ? titleEl.value.trim() : '';
    var text = textEl.value.trim();
    if (!text) { toast('Paste some text first', 'warning'); return; }
    var btn = $('kb-add-btn');
    if (btn) btn.disabled = true;
    try {
      var res = await API.addRAGDocument(title, text);
      toast('Added to knowledge base', 'success');
      if (titleEl) titleEl.value = '';
      textEl.value = '';
      if (res && res.filename && $('kb-add-feedback')) {
        var fb = $('kb-add-feedback');
        show(fb); fb.style.color = '';
        fb.innerHTML = (window.nxIcon ? nxIcon('check', { size: 13 }) + ' ' : '') + 'Saved as ' + escapeHTML(res.filename);
      }
      await loadRAGStats();
    } catch (e) {
      toast('Could not add document', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ---- View / edit an existing document ---- */
  async function openDoc(name) {
    var editor = $('kb-editor');
    if (!editor) return;
    try {
      var d = await API.getRAGDocument(name);
      setText('kb-edit-name', name);
      if ($('kb-edit-text')) $('kb-edit-text').value = (d && d.text) || '';
      editor.dataset.name = name;
      renderPreview();
      show(editor);
      editor.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      toast('Could not open document', 'error');
    }
  }

  function renderPreview() {
    var prev = $('kb-edit-preview');
    var ta = $('kb-edit-text');
    if (prev && ta) prev.innerHTML = md(ta.value);
  }

  async function saveDoc() {
    var editor = $('kb-editor');
    if (!editor) return;
    var name = editor.dataset.name;
    var text = $('kb-edit-text') ? $('kb-edit-text').value : '';
    var btn = $('kb-edit-save');
    if (btn) btn.disabled = true;
    try {
      await API.updateRAGDocument(name, text);
      toast('Changes saved', 'success');
      hide(editor);
      await loadRAGStats();
    } catch (e) {
      toast('Save failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function testQuery() {
    var input = $('rag-query-input');
    var results = $('rag-query-results');
    if (!input || !results) return;
    var q = input.value.trim();
    if (!q) { toast('Enter a query first', 'warning'); return; }
    show(results);
    results.innerHTML = '<p class="empty-state">Searching\u2026</p>';
    try {
      var data = await API.queryRAG(q);
      var items = (data && data.results) || [];
      if (items.length === 0) {
        results.innerHTML = '<p class="empty-state">No matching chunks.</p>';
        return;
      }
      results.innerHTML = items.map(function (r) {
        var score = (typeof r.score === 'number') ? r.score.toFixed(3) : escapeHTML(r.score);
        return '' +
          '<div class="rag-result-item">' +
          '  <span class="rag-result-score">score ' + score + '</span>' +
          '  <div class="rag-result-source">' + escapeHTML(r.source || 'unknown') + '</div>' +
          '  <div class="rag-result-text nxmd">' + md(r.text || '') + '</div>' +
          '</div>';
      }).join('');
    } catch (e) {
      results.innerHTML = '<p class="empty-state">Query failed.</p>';
      toast('Query failed', 'error');
    }
  }

  async function saveSettings() {
    var cs = Number($('rag-chunk-size') && $('rag-chunk-size').value);
    var co = Number($('rag-chunk-overlap') && $('rag-chunk-overlap').value);
    var tk = Number($('rag-top-k') && $('rag-top-k').value);
    var mr = Number($('rag-min-relevance') && $('rag-min-relevance').value);
    var feedback = $('rag-settings-feedback');
    try {
      await API.saveRAGSettings(cs, co, tk, mr);
      if (feedback) { show(feedback); feedback.style.color = ''; feedback.innerHTML = (window.nxIcon ? nxIcon('check', { size: 13 }) + ' ' : '') + 'Settings saved'; }
      toast('RAG settings saved', 'success');
    } catch (e) {
      if (feedback) { show(feedback); feedback.textContent = 'Failed to save'; feedback.style.color = 'var(--nexus-danger)'; }
      toast('Could not save settings', 'error');
    }
  }

  async function reindex() {
    var btn = $('rag-reindex-btn');
    if (btn) btn.disabled = true;
    toast('Reindexing started\u2026', 'info');
    try {
      await API.reindexRAG();
      toast('Reindex complete', 'success');
      await loadRAGStats();
    } catch (e) {
      toast('Reindex failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function wire() {
    var addBtn = $('kb-add-btn');
    if (addBtn) addBtn.addEventListener('click', addKnowledge);
    var saveDocBtn = $('kb-edit-save');
    if (saveDocBtn) saveDocBtn.addEventListener('click', saveDoc);
    var cancelBtn = $('kb-edit-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', function () { hide($('kb-editor')); });
    var closeBtn = $('kb-edit-close');
    if (closeBtn) closeBtn.addEventListener('click', function () { hide($('kb-editor')); });
    var editText = $('kb-edit-text');
    if (editText) editText.addEventListener('input', renderPreview);

    var queryBtn = $('rag-query-btn');
    if (queryBtn) queryBtn.addEventListener('click', testQuery);
    var queryInput = $('rag-query-input');
    if (queryInput) queryInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); testQuery(); }
    });
    var saveBtn = $('rag-save-settings-btn');
    if (saveBtn) saveBtn.addEventListener('click', saveSettings);
    var reindexBtn = $('rag-reindex-btn');
    if (reindexBtn) reindexBtn.addEventListener('click', reindex);
    var refreshBtn = $('rag-refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', loadRAGStats);
  }

  function init() {
    if (!initialized) { initialized = true; wire(); }
    loadRAGStats();
  }

  window.KnowledgePage = { init: init };
})();
