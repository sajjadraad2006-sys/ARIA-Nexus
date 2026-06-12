/* =====================================================================
   ARIA NEXUS — pages/exporter.js
   window.ExporterPage = { init }
   Two tabs: Export | Import. IDs aligned to nexus_app.html.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var activeTab = 'export';
  var importedManifest = null;

  // Map HTML checkbox IDs -> manifest section flags.
  var EXPORT_TOGGLES = [
    { id: 'exp-toggle-config', flag: 'include_config', section: 'config' },
    { id: 'exp-toggle-iot', flag: 'include_iot', section: 'iot' },
    { id: 'exp-toggle-webactions', flag: 'include_webactions', section: 'webactions' },
    { id: 'exp-toggle-rag', flag: 'include_rag', section: 'rag' }
  ];

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }
  function show(el) { if (el) el.classList.remove('hidden'); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function switchTab(tab) {
    activeTab = tab;
    ['export', 'import'].forEach(function (t) {
      var panel = $('exp-panel-' + t);
      if (panel) { panel.classList.toggle('active', t === tab); panel.classList.toggle('hidden', t !== tab); }
    });
    var tabs = document.querySelectorAll('.exp-tab');
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle('active', tabs[i].dataset.exptab === tab);
  }

  /* ----- EXPORT ----- */
  function collectFlags() {
    var flags = {};
    EXPORT_TOGGLES.forEach(function (t) {
      var box = $(t.id);
      flags[t.flag] = box ? box.checked : false;
    });
    return flags;
  }

  function selectedSections() {
    return EXPORT_TOGGLES.filter(function (t) { var b = $(t.id); return b && b.checked; })
      .map(function (t) { return t.section; });
  }

  function updatePreview() {
    var pre = $('export-preview');
    if (!pre) return;
    var skeleton = {
      manifest_version: '1.0',
      generated_at: new Date().toISOString(),
      sections: selectedSections(),
      checksum: '<computed server-side: SHA-256>'
    };
    pre.textContent = JSON.stringify(skeleton, null, 2);
  }

  async function doExport() {
    var btn = $('btn-export-download');
    if (btn) btn.disabled = true;
    try {
      var blob = await API.exportManifest(collectFlags());
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = 'aria_export_' + Date.now() + '.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
      toast('Manifest exported', 'success');
    } catch (e) {
      toast('Export failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ----- IMPORT ----- */
  function validateManifest(obj) {
    var out = [];
    if (!obj || typeof obj !== 'object') {
      out.push({ level: 'err', msg: 'File is not a valid JSON object.' });
      return out;
    }
    var version = obj.manifest_version || obj.version;
    if (version === '1.0') out.push({ level: 'ok', msg: 'Manifest version 1.0' });
    else out.push({ level: 'err', msg: 'Unsupported manifest version: ' + (version || 'missing') });

    if (obj.checksum) out.push({ level: 'ok', msg: 'Checksum present (verified on apply)' });
    else out.push({ level: 'warn', msg: 'No checksum field \u2014 integrity cannot be verified.' });

    if (Array.isArray(obj.sections) && obj.sections.length) {
      out.push({ level: 'ok', msg: 'Sections: ' + obj.sections.join(', ') });
    } else if (obj.data && typeof obj.data === 'object') {
      out.push({ level: 'ok', msg: 'Sections: ' + Object.keys(obj.data).join(', ') });
    } else {
      out.push({ level: 'warn', msg: 'No recognizable sections found.' });
    }
    return out;
  }

  function renderValidation(results) {
    var box = $('import-validation');
    if (!box) return;
    show(box);
    box.innerHTML = results.map(function (r) {
      var ic = r.level === 'ok' ? 'check' : r.level === 'warn' ? 'warn' : 'x';
      return '<span class="v-' + r.level + '">' +
        (window.nxIcon ? nxIcon(ic, { size: 13 }) + ' ' : '') +
        escapeHTML(r.msg) + '</span>';
    }).join('');
    var hasErr = results.some(function (r) { return r.level === 'err'; });
    var applyBtn = $('btn-import-apply');
    if (applyBtn) applyBtn.disabled = hasErr || !importedManifest;
  }

  function handleFile(file) {
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        importedManifest = JSON.parse(e.target.result);
        renderValidation(validateManifest(importedManifest));
      } catch (err) {
        importedManifest = null;
        renderValidation([{ level: 'err', msg: 'Could not parse JSON: ' + err.message }]);
      }
    };
    reader.onerror = function () { toast('Could not read file', 'error'); };
    reader.readAsText(file);
  }

  async function applyImport() {
    if (!importedManifest) { toast('Load a manifest first', 'warning'); return; }
    var dryBox = $('import-dry-run');
    var dryRun = dryBox ? dryBox.checked : true;
    var btn = $('btn-import-apply');
    if (btn) btn.disabled = true;
    try {
      var res = await API.importManifest(importedManifest, dryRun);
      if (dryRun) toast('Dry run OK \u2014 ' + ((res && res.message) || 'no conflicts'), 'success');
      else toast('Manifest applied successfully', 'success');
    } catch (e) {
      toast((dryRun ? 'Dry run failed' : 'Import failed'), 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function wireDropzone() {
    var zone = $('import-dropzone');
    var input = $('import-file-input');
    if (!zone) return;
    zone.addEventListener('click', function () { if (input) input.click(); });
    zone.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (input) input.click(); }
    });
    zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', function () { zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      zone.classList.remove('drag-over');
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });
    if (input) input.addEventListener('change', function () { if (input.files && input.files[0]) handleFile(input.files[0]); });
  }

  function wire() {
    var tabs = document.querySelectorAll('.exp-tab');
    for (var i = 0; i < tabs.length; i++) {
      (function (btn) { btn.addEventListener('click', function () { switchTab(btn.dataset.exptab); }); })(tabs[i]);
    }
    EXPORT_TOGGLES.forEach(function (t) {
      var box = $(t.id);
      if (box) box.addEventListener('change', updatePreview);
    });
    var dl = $('btn-export-download'); if (dl) dl.addEventListener('click', doExport);
    var apply = $('btn-import-apply'); if (apply) apply.addEventListener('click', applyImport);
    wireDropzone();
  }

  function init() {
    if (!initialized) { initialized = true; wire(); }
    switchTab(activeTab);
    updatePreview();
  }

  window.ExporterPage = { init: init };
})();
