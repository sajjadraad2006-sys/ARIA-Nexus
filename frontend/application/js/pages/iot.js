/* =====================================================================
   ARIA NEXUS — pages/iot.js
   window.IoTPage = { init }
   Three tabs: Home Assistant | Network Device | Web Automation
   IDs aligned to nexus_app.html.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var activeTab = 'ha';
  var haEntities = [];
  var haDomainFilter = 'all';
  var genericDevices = [];
  var customDevices = [];
  var webActions = [];
  var editingWebActionId = null;
  var scannedDevices = [];
  var selectedBrand = '';

  /* Brand catalog — Home-Assistant-style quick presets. Control is routed
     through the local Tasmota-style HTTP endpoint on the backend; the brand
     mainly drives the setup hints + the “how it was added” recipe shown on
     each saved device. */
  var BRANDS = [
    { id: 'tasmota', name: 'Tasmota', icon: 'chip', proto: 'Tasmota HTTP', keywords: 'esp8266 esp32 diy sonoff',
      types: ['switch', 'multi_channel', 'dimmer', 'fan'],
      cmd: 'http://{ip}/cm?cmnd=Power Toggle', note: 'ESP8266/ESP32 boards flashed with Tasmota firmware.' },
    { id: 'sonoff', name: 'Sonoff', icon: 'plug', proto: 'Tasmota HTTP', keywords: 'sonoff basic mini r2 tasmota',
      types: ['switch', 'multi_channel'],
      cmd: 'http://{ip}/cm?cmnd=Power Toggle', note: 'Sonoff relays flashed with Tasmota.' },
    { id: 'shelly', name: 'Shelly', icon: 'bolt', proto: 'Shelly HTTP', keywords: 'shelly plus gen1 gen2 relay',
      types: ['switch', 'multi_channel'],
      cmd: 'http://{ip}/relay/0?turn=toggle', note: 'Shelly Gen1/Plus relays over local HTTP.' },
    { id: 'esphome', name: 'ESPHome', icon: 'chip', proto: 'ESPHome HTTP', keywords: 'esphome esp custom yaml',
      types: ['switch', 'dimmer', 'fan'],
      cmd: 'http://{ip}/switch/relay/toggle', note: 'ESP devices running ESPHome with the web server enabled.' },
    { id: 'tuya', name: 'Tuya / Smart Life', icon: 'wifi', proto: 'LAN (local key)', keywords: 'tuya smart life smartlife',
      types: ['switch'],
      cmd: 'local Tuya protocol (needs device key)', note: 'Local Tuya devices — requires the device local key.' },
    { id: 'generic', name: 'Generic HTTP', icon: 'globe', proto: 'HTTP', keywords: 'http rest custom other unknown',
      types: ['switch', 'multi_channel', 'dimmer', 'fan'],
      cmd: 'http://{ip}/cm?cmnd=Power Toggle', note: 'Any device controllable via a simple HTTP request.' }
  ];

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }
  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }

  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function domainIcon(domain) {
    var map = {
      switch: 'bolt', light: 'bulb', sensor: 'sensor',
      binary_sensor: 'bell', fan: 'fan', cover: 'cover',
      climate: 'climate', input_boolean: 'toggle'
    };
    return (window.nxIcon ? nxIcon(map[domain] || 'gear', { size: 20 }) : '');
  }

  function typeIcon(type) {
    var map = {
      switch: 'bolt', multi_channel: 'plug', dimmer: 'bulb',
      fan: 'fan', rgb_light: 'bulb', relay: 'plug',
      light: 'bulb', sensor: 'sensor'
    };
    return (window.nxIcon ? nxIcon(map[type] || 'network', { size: 20 }) : '');
  }

  function isValidIP(ip) {
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) return false;
    return ip.split('.').every(function (o) { var n = Number(o); return n >= 0 && n <= 255; });
  }

  function formatTime(ts) {
    if (!ts) return 'never';
    var d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts);
    return d.toLocaleString('en-GB', { hour12: false });
  }

  function entityDomain(entityId) {
    return (entityId && entityId.indexOf('.') !== -1) ? entityId.split('.')[0] : 'unknown';
  }

  /* ===============================================================
     TAB SWITCHING
  =============================================================== */
  function switchTab(tab) {
    activeTab = tab;
    var map = { ha: 'iot-panel-ha', network: 'iot-panel-network', web: 'iot-panel-web' };
    Object.keys(map).forEach(function (t) {
      var panel = $(map[t]);
      if (panel) { panel.classList.toggle('active', t === tab); panel.classList.toggle('hidden', t !== tab); }
    });
    var tabs = document.querySelectorAll('.iot-tab');
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].dataset.tab === tab;
      tabs[i].classList.toggle('active', on);
      tabs[i].setAttribute('aria-selected', on ? 'true' : 'false');
    }
    if (tab === 'ha') loadHAEntities();
    else if (tab === 'network') loadGenericDevices();
    else if (tab === 'web') loadWebActions();
  }

  /* ===============================================================
     TAB 1 — HOME ASSISTANT
  =============================================================== */
  async function loadHAEntities() {
    var container = $('ha-entity-grid');
    var dot = $('ha-status-dot');
    var text = $('ha-status-text');
    if (container) container.innerHTML = '<p class="empty-state">Loading entities\u2026</p>';
    try {
      var data = await API.getHAEntities();
      haEntities = Array.isArray(data) ? data : (data && data.entities) || [];
      if (dot) dot.className = 'status-dot online';
      if (text) text.textContent = 'Connected \u00b7 ' + haEntities.length + ' entities';
      renderHAEntities();
    } catch (e) {
      if (dot) dot.className = 'status-dot offline';
      if (text) text.textContent = 'Home Assistant unavailable (:8123)';
      if (container) container.innerHTML = '<p class="empty-state">Could not reach Home Assistant.</p>';
    }
    // Custom devices are local, so always try to render them regardless of HA.
    loadCustomDevices();
  }

  /* ---- Custom (virtual) devices created inside NEXUS ---- */
  async function loadCustomDevices() {
    var grid = $('ha-custom-grid');
    if (!grid) return;
    try {
      var data = await API.getVirtualDevices();
      customDevices = Array.isArray(data) ? data : (data && data.devices) || [];
    } catch (e) { customDevices = []; }
    renderCustomDevices();
  }

  function renderCustomDevices() {
    var grid = $('ha-custom-grid');
    if (!grid) return;
    if (!customDevices.length) {
      grid.innerHTML = '<p class="empty-state">No custom devices yet. Use \u201c+ Add Device\u201d above.</p>';
      return;
    }
    grid.innerHTML = customDevices.map(function (d) {
      var isOn = !!d.state;
      var type = d.device_type || 'switch';
      var room = d.room ? (' \u00b7 ' + d.room) : '';
      return '' +
        '<div class="entity-card glass' + (isOn ? ' is-on' : '') + '">' +
        '  <div class="entity-header">' +
        '    <span class="entity-icon">' + typeIcon(type) + '</span>' +
        '    <span class="entity-name" title="' + escapeHTML(d.name) + '">' + escapeHTML(d.name) + '</span>' +
        '    <span class="entity-domain-badge">' + escapeHTML(type) + '</span>' +
        '  </div>' +
        '  <div class="entity-state-row">' +
        '    <span class="state-badge ' + (isOn ? 'on' : 'off') + '">' + (isOn ? 'on' : 'off') + '</span>' +
        '    <span class="entity-meta">virtual' + escapeHTML(room) + '</span>' +
        '  </div>' +
        '  <div class="entity-actions">' +
        '    <button class="btn-secondary cd-toggle" data-id="' + escapeHTML(d.id) + '">' + (isOn ? 'Turn off' : 'Turn on') + '</button>' +
        '    <button class="btn-ghost cd-delete" data-id="' + escapeHTML(d.id) + '" aria-label="Delete device">Delete</button>' +
        '  </div>' +
        '</div>';
    }).join('');
    wireCustomControls();
  }

  function wireCustomControls() {
    var grid = $('ha-custom-grid');
    if (!grid) return;
    var toggles = grid.querySelectorAll('.cd-toggle');
    for (var i = 0; i < toggles.length; i++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          btn.disabled = true;
          try { await API.toggleVirtualDevice(btn.dataset.id); await loadCustomDevices(); }
          catch (e) { toast('Could not toggle device', 'error'); btn.disabled = false; }
        });
      })(toggles[i]);
    }
    var dels = grid.querySelectorAll('.cd-delete');
    for (var k = 0; k < dels.length; k++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          btn.disabled = true;
          try { await API.deleteVirtualDevice(btn.dataset.id); toast('Device removed', 'success'); await loadCustomDevices(); }
          catch (e) { toast('Could not delete device', 'error'); btn.disabled = false; }
        });
      })(dels[k]);
    }
  }

  function wireDomainFilters() {
    var row = $('ha-domain-filters');
    if (!row) return;
    var chips = row.querySelectorAll('.chip');
    for (var i = 0; i < chips.length; i++) {
      (function (chip) {
        chip.addEventListener('click', function () {
          haDomainFilter = chip.dataset.domain || 'all';
          for (var j = 0; j < chips.length; j++) chips[j].classList.toggle('active', chips[j] === chip);
          renderHAEntities();
        });
      })(chips[i]);
    }
  }

  function renderHAEntities() {
    var container = $('ha-entity-grid');
    if (!container) return;
    var filtered = haEntities.filter(function (e) {
      return haDomainFilter === 'all' || entityDomain(e.entity_id) === haDomainFilter;
    });
    if (filtered.length === 0) {
      container.innerHTML = '<p class="empty-state">No entities in this domain.</p>';
      return;
    }
    container.innerHTML = filtered.map(function (e) {
      var domain = entityDomain(e.entity_id);
      var state = (e.state == null ? '' : String(e.state));
      var isOn = state === 'on' || state === 'open' || state === 'true';
      var friendly = (e.attributes && e.attributes.friendly_name) || e.entity_id;
      return '' +
        '<div class="entity-card glass' + (isOn ? ' is-on' : '') + '">' +
        '  <div class="entity-header">' +
        '    <span class="entity-icon">' + domainIcon(domain) + '</span>' +
        '    <span class="entity-name" title="' + escapeHTML(friendly) + '">' + escapeHTML(friendly) + '</span>' +
        '    <span class="entity-domain-badge">' + escapeHTML(domain) + '</span>' +
        '  </div>' +
        '  <div class="entity-state-row">' +
        '    <span class="state-badge ' + (isOn ? 'on' : 'off') + '">' + escapeHTML(state || 'unknown') + '</span>' +
        '    <span class="entity-meta">' + escapeHTML(e.entity_id) + '</span>' +
        '  </div>' +
        renderDomainControls(domain, e, isOn) +
        '</div>';
    }).join('');
    wireHAControls();
  }

  function renderDomainControls(domain, e, isOn) {
    if (domain === 'switch' || domain === 'light' || domain === 'fan' ||
        domain === 'input_boolean' || domain === 'cover') {
      var label = domain === 'cover' ? (isOn ? 'Close' : 'Open') : (isOn ? 'Turn off' : 'Turn on');
      var html = '<div class="entity-actions">' +
        '<button class="btn-secondary ha-toggle" data-entity="' + escapeHTML(e.entity_id) +
        '" aria-label="' + label + ' ' + escapeHTML(e.entity_id) + '">' + label + '</button></div>';
      if (domain === 'light' && e.attributes && typeof e.attributes.brightness !== 'undefined') {
        var b = Number(e.attributes.brightness) || 0;
        html += '<input type="range" class="range-slider ha-bright" min="0" max="255" value="' + b +
          '" data-entity="' + escapeHTML(e.entity_id) + '" aria-label="Brightness for ' + escapeHTML(e.entity_id) + '">';
      }
      return html;
    }
    if (domain === 'climate') {
      var temp = (e.attributes && e.attributes.temperature) || 20;
      return '<div class="entity-actions">' +
        '<input type="number" class="nexus-input ha-climate" style="width:90px" value="' + escapeHTML(temp) +
        '" data-entity="' + escapeHTML(e.entity_id) + '" aria-label="Target temperature for ' + escapeHTML(e.entity_id) + '">' +
        '<span class="entity-meta">\u00b0C</span></div>';
    }
    return '';
  }

  function wireHAControls() {
    var grid = $('ha-entity-grid');
    if (!grid) return;
    var toggles = grid.querySelectorAll('.ha-toggle');
    for (var i = 0; i < toggles.length; i++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          btn.disabled = true;
          try {
            await API.toggleHAEntity(btn.dataset.entity);
            toast('Toggled ' + btn.dataset.entity, 'success');
            await loadHAEntities();
          } catch (e) { toast('Failed to toggle entity', 'error'); btn.disabled = false; }
        });
      })(toggles[i]);
    }
    var brights = grid.querySelectorAll('.ha-bright');
    for (var j = 0; j < brights.length; j++) {
      (function (slider) {
        slider.addEventListener('change', async function () {
          try {
            await API.callHAService('light', 'turn_on', slider.dataset.entity, { brightness: Number(slider.value) });
            toast('Brightness set', 'success');
          } catch (e) { toast('Failed to set brightness', 'error'); }
        });
      })(brights[j]);
    }
    var clims = grid.querySelectorAll('.ha-climate');
    for (var k = 0; k < clims.length; k++) {
      (function (input) {
        input.addEventListener('change', async function () {
          try {
            await API.callHAService('climate', 'set_temperature', input.dataset.entity, { temperature: Number(input.value) });
            toast('Temperature set', 'success');
          } catch (e) { toast('Failed to set temperature', 'error'); }
        });
      })(clims[k]);
    }
  }

  function wireVirtualForm() {
    var openBtn = $('ha-create-virtual-btn');
    var form = $('ha-virtual-form');
    var nameInput = $('ha-virtual-name');
    var typeInput = $('ha-virtual-type');
    var roomInput = $('ha-virtual-room');
    var submit = $('ha-virtual-submit');
    var cancel = $('ha-virtual-cancel');
    if (openBtn && form) openBtn.addEventListener('click', function () { show(form); if (nameInput) nameInput.focus(); });
    if (cancel && form) cancel.addEventListener('click', function () {
      hide(form);
      if (nameInput) nameInput.value = '';
      if (roomInput) roomInput.value = '';
    });
    if (submit) submit.addEventListener('click', async function () {
      var name = nameInput ? nameInput.value.trim() : '';
      var type = typeInput ? typeInput.value : 'switch';
      var room = roomInput ? roomInput.value.trim() : '';
      if (!name) { toast('Enter a device name', 'warning'); return; }
      try {
        await API.createVirtualDevice(name, type, room);
        toast('Device added', 'success');
        if (nameInput) nameInput.value = '';
        if (roomInput) roomInput.value = '';
        hide(form);
        await loadCustomDevices();
      } catch (e) { toast('Could not add device', 'error'); }
    });
  }

  /* ===============================================================
     TAB 2 — NETWORK DEVICES
  =============================================================== */
  async function loadGenericDevices() {
    var container = $('net-device-grid');
    if (container) container.innerHTML = '<p class="empty-state">Loading devices\u2026</p>';
    try {
      var data = await API.getGenericDevices();
      genericDevices = Array.isArray(data) ? data : (data && data.devices) || [];
      renderGenericDevices();
    } catch (e) {
      if (container) container.innerHTML = '<p class="empty-state">Could not load network devices.</p>';
    }
  }

  function renderGenericDevices() {
    var container = $('net-device-grid');
    if (!container) return;
    if (genericDevices.length === 0) {
      container.innerHTML = '<p class="empty-state">No network devices yet. Add one above or scan your LAN.</p>';
      return;
    }
    container.innerHTML = genericDevices.map(function (d) {
      var type = d.device_type || d.type || 'switch';
      var online = d.online === true || d.reachable === true;
      return '' +
        '<div class="entity-card glass">' +
        '  <div class="entity-header">' +
        '    <span class="entity-icon">' + typeIcon(type) + '</span>' +
        '    <span class="entity-name" title="' + escapeHTML(d.name) + '">' + escapeHTML(d.name) + '</span>' +
        '    <span class="status-dot ' + (online ? 'online' : 'offline') + '"></span>' +
        '  </div>' +
        '  <div class="entity-meta">' + escapeHTML(d.ip || '') + (d.room ? ' \u00b7 ' + escapeHTML(d.room) : '') + '</div>' +
        renderGenericControls(type, d) +
        renderDeviceRecipe(d, type) +
        '  <div class="entity-actions">' +
        '    <button class="btn-secondary gd-howto" data-id="' + escapeHTML(d.id || d.dev_id) + '" aria-label="Show how this device was added">' + (window.nxIcon ? nxIcon('eye', { size: 14 }) + ' ' : '') + 'How it was added</button>' +
        '    <button class="btn-danger gd-delete" data-id="' + escapeHTML(d.id || d.dev_id) + '" aria-label="Delete ' + escapeHTML(d.name) + '">Delete</button>' +
        '  </div>' +
        '</div>';
    }).join('');
    wireGenericControls();
  }

  function renderGenericControls(type, d) {
    var devId = escapeHTML(d.id || d.dev_id);
    if (type === 'switch' || type === 'multi_channel' || type === 'rgb_light') {
      var channels = Array.isArray(d.channels) && d.channels.length ? d.channels : [{ id: 0, name: 'Power' }];
      return '<div class="chip-row">' + channels.map(function (ch, idx) {
        var chId = (typeof ch === 'object') ? (ch.id != null ? ch.id : idx) : idx;
        var chName = (typeof ch === 'object') ? (ch.name || ('CH' + chId)) : String(ch);
        return '<button class="chip gd-toggle" data-id="' + devId + '" data-channel="' + escapeHTML(chId) +
          '" aria-label="Toggle ' + escapeHTML(chName) + '">' + escapeHTML(chName) + '</button>';
      }).join('') + '</div>';
    }
    if (type === 'dimmer') {
      return '<input type="range" class="range-slider gd-command" min="0" max="100" data-id="' + devId +
        '" data-command="brightness" value="' + escapeHTML(d.brightness || 50) + '" aria-label="Brightness">';
    }
    if (type === 'fan') {
      return '<input type="range" class="range-slider gd-command" min="0" max="3" data-id="' + devId +
        '" data-command="speed" value="' + escapeHTML(d.speed || 0) + '" aria-label="Fan speed">';
    }
    return '';
  }

  function wireGenericControls() {
    var grid = $('net-device-grid');
    if (!grid) return;
    var toggles = grid.querySelectorAll('.gd-toggle');
    for (var i = 0; i < toggles.length; i++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          try {
            await API.toggleGenericDevice(btn.dataset.id, Number(btn.dataset.channel));
            toast('Toggled channel', 'success');
            await loadGenericDevices();
          } catch (e) { toast('Toggle failed', 'error'); }
        });
      })(toggles[i]);
    }
    var cmds = grid.querySelectorAll('.gd-command');
    for (var j = 0; j < cmds.length; j++) {
      (function (input) {
        input.addEventListener('change', async function () {
          try {
            await API.sendGenericCommand(input.dataset.id, input.dataset.command, Number(input.value));
            toast('Command sent', 'success');
          } catch (e) { toast('Command failed', 'error'); }
        });
      })(cmds[j]);
    }
    var howtos = grid.querySelectorAll('.gd-howto');
    for (var h = 0; h < howtos.length; h++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var panel = grid.querySelector('.device-recipe[data-recipe="' + btn.dataset.id + '"]');
          if (panel) panel.classList.toggle('hidden');
        });
      })(howtos[h]);
    }
    var dels = grid.querySelectorAll('.gd-delete');
    for (var k = 0; k < dels.length; k++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          try {
            await API.deleteGenericDevice(btn.dataset.id);
            toast('Device removed', 'success');
            await loadGenericDevices();
          } catch (e) { toast('Delete failed', 'error'); }
        });
      })(dels[k]);
    }
  }

  function toggleChannelsVisibility() {
    var type = $('net-type');
    var wrap = $('net-channels-wrap');
    if (!type || !wrap) return;
    wrap.classList.toggle('hidden', type.value !== 'multi_channel');
  }

  function parseChannels() {
    var input = $('net-channels');
    if (!input || !input.value.trim()) return [];
    return input.value.split(',').map(function (s, i) { return { id: i, name: s.trim() }; })
      .filter(function (c) { return c.name; });
  }

  async function addGenericDevice() {
    var name = $('net-name'), ip = $('net-ip'), room = $('net-room'), type = $('net-type');
    if (!name || !ip) return;
    var nameVal = name.value.trim();
    var ipVal = ip.value.trim();
    if (!nameVal) { toast('Device name is required', 'warning'); return; }
    if (!isValidIP(ipVal)) { toast('Enter a valid IPv4 address (e.g. 192.168.1.50)', 'warning'); return; }
    var via = scannedDevices.some(function (s) { return s.ip === ipVal; }) ? 'scan' : 'manual';
    try {
      await API.addGenericDevice(nameVal, ipVal, room ? room.value.trim() : '',
        type ? type.value : 'switch', parseChannels(), selectedBrand || 'generic', via);
      toast('Device added', 'success');
      name.value = ''; ip.value = ''; if (room) room.value = '';
      if ($('net-channels')) $('net-channels').value = '';
      await loadGenericDevices();
    } catch (e) { toast('Could not add device', 'error'); }
  }

  async function testIP() {
    var ip = $('net-ip');
    var result = $('net-test-result');
    if (!ip || !result) return;
    var ipVal = ip.value.trim();
    show(result);
    if (!isValidIP(ipVal)) { result.className = 'test-result err'; result.textContent = 'Invalid IP format'; return; }
    result.className = 'test-result'; result.textContent = 'Testing\u2026';
    try {
      var data = await API.testGenericIP(ipVal);
      var reachable = data && (data.reachable || data.ok);
      result.className = 'test-result ' + (reachable ? 'ok' : 'err');
      result.innerHTML = (window.nxIcon ? nxIcon(reachable ? 'check' : 'x', { size: 14 }) + ' ' : '') + (reachable ? 'Reachable' : 'No response');
    } catch (e) { result.className = 'test-result err'; result.textContent = 'Test failed'; }
  }

  async function scanLAN() {
    var btn = $('net-scan-btn');
    var results = $('net-scan-results');
    if (btn) btn.disabled = true;
    if (results) { show(results); results.innerHTML = 'Scanning LAN\u2026'; }
    try {
      var data = await API.scanLAN();
      var devices = (data && data.devices) || [];
      scannedDevices = devices;
      if (results) {
        results.innerHTML = devices.length
          ? '<div class="scan-head">' + (window.nxIcon ? nxIcon('radar', { size: 14 }) + ' ' : '') +
              devices.length + ' device(s) on your network</div>' +
            devices.map(function (d) {
              var ip = escapeHTML(d.ip || '');
              var host = escapeHTML(d.hostname || d.name || 'unknown');
              return '<div class="scan-result-row">' +
                '<span class="status-dot online"></span>' +
                '<span class="scan-ip">' + ip + '</span>' +
                '<span class="scan-host">' + host + '</span>' +
                '<span class="scan-badge">Same network</span>' +
                '<button type="button" class="btn-secondary scan-configure" data-ip="' + ip + '" data-host="' + host + '">' +
                (window.nxIcon ? nxIcon('sliders', { size: 13 }) + ' ' : '') + 'Configure</button>' +
                '</div>';
            }).join('')
          : '<p class="empty-state">No devices found on your network.</p>';
        var cfgs = results.querySelectorAll('.scan-configure');
        for (var ci = 0; ci < cfgs.length; ci++) {
          (function (btn) { btn.addEventListener('click', function () { configureFromScan(btn.dataset.ip, btn.dataset.host); }); })(cfgs[ci]);
        }
      }
      toast('Scan complete: ' + devices.length + ' device(s)', 'success');
    } catch (e) {
      if (results) results.innerHTML = '<p class="empty-state">Scan failed.</p>';
      toast('LAN scan failed', 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  /* ===============================================================
     TAB 3 — WEB ACTIONS
  =============================================================== */
  async function loadWebActions() {
    var container = $('web-action-list');
    if (container) container.innerHTML = '<p class="empty-state">Loading web actions\u2026</p>';
    try {
      var data = await API.getWebActions();
      webActions = Array.isArray(data) ? data : (data && data.actions) || [];
      renderWebActions();
    } catch (e) {
      if (container) container.innerHTML = '<p class="empty-state">Could not load web actions.</p>';
    }
  }

  function methodBadge(method) {
    var m = (method || 'GET').toUpperCase();
    return '<span class="method-badge method-' + m.toLowerCase() + '">' + m + '</span>';
  }

  function statusBadge(action) {
    if (action.last_status == null) return '';
    var code = Number(action.last_status);
    var ok = code >= 200 && code < 400;
    return '<span class="code-badge ' + (ok ? 'ok' : 'err') + '">' + escapeHTML(code) + '</span>';
  }

  function renderWebActions() {
    var container = $('web-action-list');
    if (!container) return;
    if (webActions.length === 0) {
      container.innerHTML = '<p class="empty-state">No web actions yet. Create one above.</p>';
      return;
    }
    container.innerHTML = webActions.map(function (a) {
      var id = escapeHTML(a.id);
      return '' +
        '<div class="web-action-card glass">' +
        '  <div class="wac-header">' + methodBadge(a.method) +
        '    <span class="wac-name">' + escapeHTML(a.name) + '</span>' + statusBadge(a) + '</div>' +
        '  <div class="wac-url">' + escapeHTML(a.url) + '</div>' +
        '  <div class="wac-meta">Last triggered: ' + escapeHTML(formatTime(a.last_triggered)) + '</div>' +
        '  <div class="wac-actions">' +
        '    <button class="btn-primary wa-trigger" data-id="' + id + '" aria-label="Trigger ' + escapeHTML(a.name) + '">Trigger</button>' +
        '    <button class="btn-secondary wa-edit" data-id="' + id + '" aria-label="Edit ' + escapeHTML(a.name) + '">Edit</button>' +
        '    <button class="btn-danger wa-delete" data-id="' + id + '" aria-label="Delete ' + escapeHTML(a.name) + '">Delete</button>' +
        '  </div>' +
        '</div>';
    }).join('');
    wireWebActions();
  }

  function wireWebActions() {
    var container = $('web-action-list');
    if (!container) return;
    var trigs = container.querySelectorAll('.wa-trigger');
    for (var i = 0; i < trigs.length; i++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          btn.disabled = true;
          try {
            var res = await API.triggerWebAction(btn.dataset.id);
            if (res && res.ok) toast('Action fired (HTTP ' + (res.status_code || '?') + ')', 'success');
            else toast('Action error: ' + ((res && res.error) || 'unknown'), 'error');
            await loadWebActions();
          } catch (e) { toast('Trigger failed', 'error'); }
          finally { btn.disabled = false; }
        });
      })(trigs[i]);
    }
    var edits = container.querySelectorAll('.wa-edit');
    for (var j = 0; j < edits.length; j++) {
      (function (btn) { btn.addEventListener('click', function () { startEditWebAction(btn.dataset.id); }); })(edits[j]);
    }
    var dels = container.querySelectorAll('.wa-delete');
    for (var k = 0; k < dels.length; k++) {
      (function (btn) {
        btn.addEventListener('click', async function () {
          try {
            await API.deleteWebAction(btn.dataset.id);
            toast('Web action deleted', 'success');
            await loadWebActions();
          } catch (e) { toast('Delete failed', 'error'); }
        });
      })(dels[k]);
    }
  }

  function readWebActionForm() {
    var name = $('web-name'), url = $('web-url'), method = $('web-method'),
        headers = $('web-headers'), body = $('web-body');
    var headersObj = {};
    if (headers && headers.value.trim()) {
      try { headersObj = JSON.parse(headers.value); }
      catch (e) { toast('Headers must be valid JSON', 'warning'); return null; }
    }
    if (!name || !name.value.trim()) { toast('Name is required', 'warning'); return null; }
    if (!url || !url.value.trim()) { toast('URL is required', 'warning'); return null; }
    return {
      name: name.value.trim(),
      url: url.value.trim(),
      method: method ? method.value : 'POST',
      headers: headersObj,
      body: body ? body.value : ''
    };
  }

  function clearWebActionForm() {
    ['web-name', 'web-url', 'web-headers', 'web-body'].forEach(function (id) { var el = $(id); if (el) el.value = ''; });
    var m = $('web-method'); if (m) m.value = 'POST';
    editingWebActionId = null;
    var submit = $('web-save-btn'); if (submit) submit.textContent = 'Save Action';
    hide($('web-cancel-edit-btn'));
  }

  function startEditWebAction(id) {
    var a = webActions.filter(function (x) { return String(x.id) === String(id); })[0];
    if (!a) return;
    editingWebActionId = id;
    if ($('web-name')) $('web-name').value = a.name || '';
    if ($('web-url')) $('web-url').value = a.url || '';
    if ($('web-method')) $('web-method').value = (a.method || 'POST').toUpperCase();
    if ($('web-headers')) $('web-headers').value = a.headers ? JSON.stringify(a.headers, null, 2) : '';
    if ($('web-body')) $('web-body').value = a.body || '';
    var submit = $('web-save-btn'); if (submit) submit.textContent = 'Save Changes';
    show($('web-cancel-edit-btn'));
  }

  async function submitWebAction() {
    var data = readWebActionForm();
    if (!data) return;
    try {
      if (editingWebActionId) {
        await API.updateWebAction(editingWebActionId, data);
        toast('Web action updated', 'success');
      } else {
        await API.addWebAction(data.name, data.url, data.method, data.headers, data.body);
        toast('Web action created', 'success');
      }
      clearWebActionForm();
      await loadWebActions();
    } catch (e) { toast('Could not save web action', 'error'); }
  }

  /* ===============================================================
     BRAND CATALOG + DEVICE RECIPE + SCAN → CONFIGURE
  =============================================================== */
  function brandById(id) {
    for (var i = 0; i < BRANDS.length; i++) if (BRANDS[i].id === id) return BRANDS[i];
    return null;
  }

  function renderBrandChips(filter) {
    var list = $('net-brand-list');
    if (!list) return;
    var q = (filter || '').trim().toLowerCase();
    var matches = BRANDS.filter(function (b) {
      return !q || b.name.toLowerCase().indexOf(q) !== -1 ||
        (b.keywords || '').toLowerCase().indexOf(q) !== -1;
    });
    if (!matches.length) {
      list.innerHTML = '<span class="brand-empty">No matching brand \u2014 use \u201cGeneric HTTP\u201d.</span>';
      return;
    }
    list.innerHTML = matches.map(function (b) {
      var on = b.id === selectedBrand;
      return '<button type="button" class="brand-chip' + (on ? ' active' : '') + '" data-brand="' + b.id + '">' +
        (window.nxIcon ? nxIcon(b.icon || 'tag', { size: 15 }) : '') +
        '<span>' + escapeHTML(b.name) + '</span></button>';
    }).join('');
    var chips = list.querySelectorAll('.brand-chip');
    for (var i = 0; i < chips.length; i++) {
      (function (chip) { chip.addEventListener('click', function () { selectBrand(chip.dataset.brand); }); })(chips[i]);
    }
  }

  function selectBrand(id) {
    var b = brandById(id);
    if (!b) return;
    selectedBrand = id;
    var info = $('net-brand-info');
    if (info) {
      info.classList.remove('hidden');
      info.innerHTML =
        '<div class="brand-info-head">' + (window.nxIcon ? nxIcon(b.icon || 'tag', { size: 16 }) : '') +
        ' <strong>' + escapeHTML(b.name) + '</strong> <span class="brand-proto">' + escapeHTML(b.proto) + '</span></div>' +
        '<p class="brand-note">' + escapeHTML(b.note) + '</p>' +
        '<code class="brand-cmd">' + escapeHTML(b.cmd) + '</code>';
    }
    var typeSel = $('net-type');
    if (typeSel && b.types && b.types.length) { typeSel.value = b.types[0]; toggleChannelsVisibility(); }
    renderBrandChips($('net-brand-search') ? $('net-brand-search').value : '');
  }

  function renderDeviceRecipe(d, type) {
    var b = brandById(d.brand) || brandById('generic');
    var ip = escapeHTML(d.ip || '');
    var cmd = (b && b.cmd ? b.cmd : 'http://{ip}/cm?cmnd=Power Toggle').replace('{ip}', ip || '{ip}');
    var added = d.added_via === 'scan' ? 'Network scan' : 'Manual entry';
    var rows = [
      ['Connection', escapeHTML(b ? (b.name + ' \u00b7 ' + b.proto) : 'Generic HTTP')],
      ['Endpoint', '<code>' + escapeHTML(cmd) + '</code>'],
      ['Type', escapeHTML(type)],
      ['Room', escapeHTML(d.room || '\u2014')],
      ['Added via', escapeHTML(added)]
    ];
    if (Array.isArray(d.channels) && d.channels.length) {
      rows.push(['Channels', escapeHTML(d.channels.map(function (c) {
        return typeof c === 'object' ? (c.name || c.id) : c;
      }).join(', '))]);
    }
    return '<div class="device-recipe hidden" data-recipe="' + escapeHTML(d.id || d.dev_id) + '">' +
      '<div class="recipe-title">' + (window.nxIcon ? nxIcon('sliders', { size: 14 }) + ' ' : '') + 'How it was added</div>' +
      rows.map(function (r) {
        return '<div class="recipe-row"><span class="recipe-k">' + r[0] + '</span><span class="recipe-v">' + r[1] + '</span></div>';
      }).join('') +
      '</div>';
  }

  function configureFromScan(ip, hostname) {
    var nameEl = $('net-name'), ipEl = $('net-ip');
    if (ipEl) ipEl.value = ip || '';
    if (nameEl && !nameEl.value.trim()) {
      nameEl.value = (hostname && hostname !== 'unknown') ? hostname : ('Device ' + String(ip || '').split('.').pop());
    }
    if (!selectedBrand) selectBrand('tasmota');
    toast('Loaded ' + ip + ' \u2014 customize the settings and add', 'success');
    var form = nameEl && nameEl.closest ? nameEl.closest('.glass-form') : null;
    if (form && form.scrollIntoView) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (nameEl) nameEl.focus();
  }

  /* ===============================================================
     WIRING + INIT
  =============================================================== */
  function wire() {
    var tabs = document.querySelectorAll('.iot-tab');
    for (var i = 0; i < tabs.length; i++) {
      (function (btn) { btn.addEventListener('click', function () { switchTab(btn.dataset.tab); }); })(tabs[i]);
    }
    wireDomainFilters();
    wireVirtualForm();
    var haRefresh = $('ha-refresh-btn'); if (haRefresh) haRefresh.addEventListener('click', loadHAEntities);
    var netType = $('net-type'); if (netType) netType.addEventListener('change', toggleChannelsVisibility);
    var netAdd = $('net-add-btn'); if (netAdd) netAdd.addEventListener('click', addGenericDevice);
    var netTest = $('net-test-btn'); if (netTest) netTest.addEventListener('click', testIP);
    var netScan = $('net-scan-btn'); if (netScan) netScan.addEventListener('click', scanLAN);
    var brandSearch = $('net-brand-search');
    if (brandSearch) brandSearch.addEventListener('input', function () { renderBrandChips(brandSearch.value); });
    renderBrandChips('');
    var webSave = $('web-save-btn'); if (webSave) webSave.addEventListener('click', submitWebAction);
    var webCancel = $('web-cancel-edit-btn'); if (webCancel) webCancel.addEventListener('click', clearWebActionForm);
  }

  function init() {
    if (!initialized) { initialized = true; wire(); clearWebActionForm(); toggleChannelsVisibility(); }
    switchTab(activeTab);
  }

  window.IoTPage = { init: init };
})();
