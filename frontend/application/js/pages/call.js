/* =====================================================================
   ARIA NEXUS — pages/call.js   (window.AssistantCall)
   ---------------------------------------------------------------------
   The big, full-screen “Assistant Call” UI — a hands-free voice session
   with a large animated waveform, a MUTE button and an END button.

   Flow (say the wake word ‘aria’ anywhere, or call AssistantCall.open()):
     1. The overlay slides up over the whole app.
     2. The mic turns on and listens. The waveform reacts to your voice.
     3. When you STOP talking it AUTO-STOPS (VAD) and transcribes (Whisper).
     4. ARIA thinks (LLM) and replies out loud (Piper, auto AR/EN voice).
     5. It listens again — a continuous conversation — until you press END
        (or stay silent for two rounds, then it ends itself).

   MUTE pauses listening but keeps the call open. END closes it and hands
   the mic back to the always-on wake-word listener.

   Public API:
     init()         wire DOM + keys (auto-runs on load)
     open()         open the call and start a session -> Promise (resolves on close)
     openFromWake() alias used by WakeManager
     close()        end the session
     isOpen()       bool
   ===================================================================== */
(function () {
  'use strict';

  var BARS = 5;

  var opened = false, ended = false, muted = false;
  var mode = 'idle';            // idle | listening | thinking | speaking | error
  var history = [];
  var resolveSession = null;
  var micCtrl = null;
  var silenceRounds = 0;

  var ac = null, speakAnalyser = null, freqData = null, wiredEl = null;
  var raf = null, level = 0;

  // Barge-in (interrupt ARIA while she is speaking). A SEPARATE, lightweight
  // mic stream runs only during 'speaking'; sustained user speech stops TTS
  // and immediately opens a listening turn.
  var bargeStream = null, bargeAC = null, bargeAnalyser = null,
      bargeData = null, bargeSrc = null, bargeRAF = null;

  var els = {};

  function $(id) { return document.getElementById(id); }
  function toast(m, t) { if (window.nexus) nexus.showToast(m, t); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ---- DOM ---- */
  function ensure() {
    els.root = $('assistant-call');
    els.status = $('acall-status');
    els.caption = $('acall-caption');
    els.viz = $('acall-viz');
    els.mute = $('acall-mute');
    els.end = $('acall-end');
    if (els.viz && !els.viz.childElementCount) {
      var h = '';
      for (var i = 0; i < BARS; i++) h += '<span class="acall-bar"></span>';
      els.viz.innerHTML = h;
    }
    els.bars = els.viz ? els.viz.querySelectorAll('.acall-bar') : [];
  }

  function setStatus(txt) { if (els.status) els.status.textContent = txt; }
  function setMode(m) {
    mode = m;
    if (els.root) els.root.setAttribute('data-mode', m);
    setStatus({
      idle: '…',
      listening: 'Listening · أسمعك',
      thinking: 'Thinking · أفكر',
      speaking: 'Speaking · أتكلم',
      error: 'Error · خطأ'
    }[m] || m);
  }
  function caption(role, text) {
    if (!els.caption) return;
    els.caption.innerHTML =
      '<span class="acall-cap-who">' + (role === 'user' ? 'You · أنت' : 'ARIA') + '</span>' +
      '<span class="acall-cap-text">' + esc(text) + '</span>';
  }

  /* ---- audio analyser for speaking waveform ---- */
  function ensureAC() {
    if (ac) return ac;
    // Reuse the ONE shared AudioContext so the call screen never adds to (or
    // leaks from) the browser's per-tab AudioContext ceiling.
    if (window.NexusAudio && window.NexusAudio.available) { ac = window.NexusAudio.ctx(); return ac; }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try { ac = new AC(); } catch (e) { ac = null; }
    return ac;
  }
  function wireSpeak(audio) {
    try {
      var c = ensureAC();
      if (!c) return;
      if (c.state === 'suspended') { try { c.resume(); } catch (e) {} }
      if (wiredEl === audio) return;
      var src = c.createMediaElementSource(audio);
      speakAnalyser = c.createAnalyser();
      speakAnalyser.fftSize = 64;
      speakAnalyser.smoothingTimeConstant = 0.7;
      freqData = new Uint8Array(speakAnalyser.frequencyBinCount);
      src.connect(speakAnalyser);
      speakAnalyser.connect(c.destination);
      wiredEl = audio;
    } catch (e) { speakAnalyser = null; }
  }

  /* ---- waveform render loop ---- */
  function renderLoop() {
    var target;
    if (mode === 'speaking' && speakAnalyser) {
      speakAnalyser.getByteFrequencyData(freqData);
      var s = 0; for (var i = 0; i < freqData.length; i++) s += freqData[i];
      target = (s / freqData.length) / 255;
    } else if (mode === 'listening') {
      target = level;
    } else if (mode === 'thinking') {
      target = 0.18 + 0.12 * Math.abs(Math.sin(Date.now() / 220));
    } else {
      target = 0.06 + 0.05 * Math.abs(Math.sin(Date.now() / 360));
    }
    level += (target - level) * 0.3;
    var L = Math.max(0, Math.min(1, level));
    for (var b = 0; b < els.bars.length; b++) {
      var phase = Math.sin(Date.now() / 130 + b * 0.8) * 0.28 + 0.72;
      var h = 0.12 + L * phase * 0.88;
      els.bars[b].style.transform = 'scaleY(' + h.toFixed(3) + ')';
    }
    raf = requestAnimationFrame(renderLoop);
  }
  function startLoop() { if (!raf) raf = requestAnimationFrame(renderLoop); }
  function stopLoop() { if (raf) { cancelAnimationFrame(raf); raf = null; } }

  /* ---- barge-in monitor (interrupt TTS by talking) ---- */
  function vadCfg(key, dflt) {
    var g = window.NEXUS_VAD || {};
    return (g[key] != null) ? g[key] : dflt;
  }
  function stopBargeMonitor() {
    if (bargeRAF) { cancelAnimationFrame(bargeRAF); bargeRAF = null; }
    try { if (bargeSrc) bargeSrc.disconnect(); } catch (e) {}
    try { if (bargeAC) bargeAC.close(); } catch (e) {}
    try { if (bargeStream) bargeStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    bargeStream = null; bargeAC = null; bargeAnalyser = null; bargeData = null; bargeSrc = null;
  }
  function startBargeMonitor() {
    if (bargeStream) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    var hasAudio = (window.NexusAudio && window.NexusAudio.available) ||
                   window.AudioContext || window.webkitAudioContext;
    if (!hasAudio) return;
    var thr = vadCfg('bargeInThreshold', 0.060);
    var needMs = vadCfg('bargeInMs', 350);
    // echoCancellation is essential here so ARIA's OWN voice from the speakers
    // doesn't look like the user barging in.
    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then(function (stream) {
      if (mode !== 'speaking' || ended || muted) {
        try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        return;
      }
      bargeStream = stream;
      try {
        if (window.NexusAudio && window.NexusAudio.available) {
          var wired = window.NexusAudio.analyser(stream);
          if (!wired) { stopBargeMonitor(); return; }
          bargeSrc = wired.source; bargeAnalyser = wired.analyser;
        } else {
          var AC = window.AudioContext || window.webkitAudioContext;
          bargeAC = new AC();
          if (bargeAC.state === 'suspended') { try { bargeAC.resume(); } catch (e) {} }
          bargeSrc = bargeAC.createMediaStreamSource(stream);
          bargeAnalyser = bargeAC.createAnalyser();
          bargeAnalyser.fftSize = 512;
          bargeSrc.connect(bargeAnalyser);
        }
        bargeData = new Uint8Array(bargeAnalyser.fftSize);
      } catch (e) { stopBargeMonitor(); return; }
      var voiceMs = 0, last = Date.now();
      function tick() {
        if (!bargeStream || mode !== 'speaking' || ended || muted) return;
        var now = Date.now(), dt = now - last; last = now;
        bargeAnalyser.getByteTimeDomainData(bargeData);
        var sum = 0;
        for (var i = 0; i < bargeData.length; i++) { var v = (bargeData[i] - 128) / 128; sum += v * v; }
        var rms = Math.sqrt(sum / bargeData.length);
        if (rms >= thr) { voiceMs += dt; } else { voiceMs = Math.max(0, voiceMs - dt * 0.5); }
        if (voiceMs >= needMs) {
          // Sustained user speech => interrupt. NOTE: VoiceManager.stop() does
          // NOT resolve the in-flight speak() promise, so the old turn's
          // post-speak re-arm never fires; we re-arm here explicitly with no
          // risk of a double mic-open.
          stopBargeMonitor();
          try { if (window.VoiceManager) VoiceManager.stop(); } catch (e) {}
          if (!ended && !muted) { setStatus('Go ahead · تفضل'); listenOnce(); }
          return;
        }
        bargeRAF = requestAnimationFrame(tick);
      }
      bargeRAF = requestAnimationFrame(tick);
    }).catch(function () { /* mic unavailable: barge-in simply stays off */ });
  }

  /* ---- conversation core ---- */
  function speak(text) {
    return new Promise(function (res) {
      setMode('speaking');
      if (!window.VoiceManager) { res(); return; }
      startBargeMonitor();
      VoiceManager.speak(text, { onAudio: wireSpeak }).then(function () {
        stopBargeMonitor();
        speakAnalyser = null; wiredEl = null;
        res();
      });
    });
  }

  function converse(text) {
    setMode('thinking');
    history.push({ role: 'user', content: text });
    var call = (window.API && API.assistantCommand)
      ? API.assistantCommand(text, history)
      : API.chat(text, history);
    return Promise.resolve(call).then(function (data) {
      var reply = (data && data.response) ? data.response : '';
      if (!reply) { setMode('error'); return false; }
      history.push({ role: 'assistant', content: reply });
      caption('aria', reply);
      return speak(reply).then(function () { return true; });
    }).catch(function () {
      setMode('error');
      return false;
    });
  }

  function listenOnce() {
    if (ended || muted) return;
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CALL','listenOnce');
    setMode('listening');
    // VAD timing comes from mic.js defaults / window.NEXUS_VAD (backend config),
    // so endpointing is tuned in ONE place and never clips or cuts off early.
    MicRecorder.capture({
      vad: true,
      onController: function (c) { micCtrl = c; },
      onLevel: function (l) { level = Math.max(level, l); }
    }).then(function (blob) {
      micCtrl = null;
      if (ended || muted) return;
      if (!blob) { silenceRounds++; return loopOrEnd(); }
      setMode('thinking');
      return API.sttInference(blob).then(function (data) {
        if (ended) return;
        var text = (data && (data.text || data.transcription) || '').trim();
        if (!text || text === '[BLANK_AUDIO]' || text.length < 2) { (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CALL','stt.blank',{text:text}); silenceRounds++; return loopOrEnd(); }
        (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CALL','stt.text',{text:text.slice(0,60),len:text.length});
        silenceRounds = 0;
        caption('user', text);
        return converse(text).then(function (ok) {
          if (ended) return;
          if (ok) { setTimeout(function () { if (!ended && !muted) listenOnce(); }, 300); }
          else { loopOrEnd(); }
        });
      });
    }).catch(function (err) {
      if (ended) return;
      micCtrl = null;
      toast('Microphone / STT error — ' + (err && err.message ? err.message : 'offline'), 'error');
      setMode('error');
      setTimeout(closeCall, 1600);
    });
  }

  function loopOrEnd() {
    if (ended || muted) return;
    if (silenceRounds >= 2) { setStatus('No speech — ending · إنهاء'); setTimeout(closeCall, 900); return; }
    setStatus('Didn’t catch that · أعد — listening…');
    setTimeout(function () { if (!ended && !muted) listenOnce(); }, 450);
  }

  function setMuted(m) {
    muted = !!m;
    if (els.mute) {
      els.mute.classList.toggle('muted', muted);
      els.mute.setAttribute('aria-label', muted ? 'Unmute microphone' : 'Mute microphone');
      els.mute.title = muted ? 'Unmute · إلغاء الكتم' : 'Mute · كتم';
    }
    if (muted) {
      if (micCtrl) { try { micCtrl.cancel(); } catch (e) {} micCtrl = null; }
      stopBargeMonitor();   // hard stop: no audio captured at all while muted
      try { if (window.VoiceManager) VoiceManager.stop(); } catch (e) {}
      setMode('idle');
      setStatus('Muted · صامت');
    } else {
      silenceRounds = 0;
      if (!ended) listenOnce();
    }
  }

  /* ---- open / close ---- */
  function openCall() {
    ensure();
    if (opened) return Promise.resolve();
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CALL','open');
    opened = true; ended = false; muted = false; silenceRounds = 0; level = 0;
    history = [];
    if (els.root) { els.root.classList.add('open'); els.root.setAttribute('aria-hidden', 'false'); }
    if (els.mute) els.mute.classList.remove('muted');
    if (els.caption) els.caption.innerHTML = '';
    if (window.WakeManager) WakeManager.suspend();   // free the mic for us
    try { if (window.VoiceManager) VoiceManager.stop(); } catch (e) {}
    if (window.NexusSound) { try { NexusSound.play('startup'); } catch (e) {} }
    startLoop();
    setMode('idle');
    setStatus('Connecting · ربط…');
    setTimeout(function () { if (!ended) listenOnce(); }, 280);
    return new Promise(function (res) { resolveSession = res; });
  }

  function closeCall() {
    if (!opened) { return; }
    (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CALL','close');
    ended = true; opened = false;
    if (micCtrl) { try { micCtrl.cancel(); } catch (e) {} micCtrl = null; }
    stopBargeMonitor();
    try { if (window.VoiceManager) VoiceManager.stop(); } catch (e) {}
    stopLoop();
    level = 0;
    if (els.root) { els.root.classList.remove('open'); els.root.setAttribute('aria-hidden', 'true'); }
    mode = 'idle';
    if (window.WakeManager) WakeManager.resume();    // re-arm wake word
    var r = resolveSession; resolveSession = null;
    if (r) { try { r(); } catch (e) {} }
  }

  /* ---- wiring ---- */
  function wire() {
    ensure();
    if (els.mute && !els.mute._wired) {
      els.mute._wired = 1;
      els.mute.addEventListener('click', function () { setMuted(!muted); });
    }
    if (els.end && !els.end._wired) {
      els.end._wired = 1;
      els.end.addEventListener('click', closeCall);
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && opened) closeCall();
    });
  }

  function init() { wire(); }

  window.AssistantCall = {
    init: init,
    open: openCall,
    openFromWake: openCall,
    close: closeCall,
    isOpen: function () { return opened; }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
