/* =====================================================================
   ARIA NEXUS — pages/face.js
   window.FacePage = { init, runWakeTurn }

   A simple, cute pair of glowing robot EYES (no literal robot head).
   The eyes float, blink, glance around, and emote per state. While ARIA
   speaks they squash/stretch in time with the Piper audio. No assets.

   States: idle | listening | thinking | speaking | error

   Two ways to talk:
     1. Tap “Talk”  (tap-to-talk)
     2. Wake word — ALWAYS-ON & global, handled by window.WakeManager.
        Just call the wake word anywhere in the app; ARIA jumps to the
        face, listens (Whisper), thinks (LLM) and replies out loud (Piper).
        runWakeTurn() is the per-turn routine WakeManager invokes.
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var state = 'idle';
  var recording = false;
  var busy = false;
  var history = [];
  var continuous = false;

  var WAKE_RECORD_MS = 6000;   // fixed listening window per hands-free turn

  // ---- Eye geometry (viewBox 0 0 320 200) — large & friendly ----
  var EYE_CY = 100, L_CX = 108, R_CX = 212;
  var EYE_W = 86, EYE_H = 120, EYE_RX = 42;

  // ---- Animation state ----
  var raf = null;
  var blinking = false, blinkT0 = 0;
  var nextBlinkAt = 0;
  var smileT0 = 0, nextSmileAt = 0;   // occasional idle “happy squish”
  var speakAmp = 0;
  var t = 0;

  // ---- Audio (drives the talking squash) ----
  var audioCtx = null, analyser = null, freqData = null;
  var wiredEls = new WeakSet();

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }
  function escapeHTML(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ===============================================================
     1. BUILD THE EYES
  =============================================================== */
  function eyeGroup(side, cx) {
    var x = cx - EYE_W / 2, y = EYE_CY - EYE_H / 2;
    return '' +
      '<g id="rf-eye-' + side + '">' +
      '  <rect class="rf-eye" x="' + x + '" y="' + y + '" width="' + EYE_W + '" height="' + EYE_H + '" rx="' + EYE_RX + '" ry="' + EYE_RX + '"></rect>' +
      '  <circle class="rf-shine" cx="' + (cx - 15) + '" cy="' + (EYE_CY - 32) + '" r="11"></circle>' +
      '  <circle class="rf-shine rf-shine-sm" cx="' + (cx + 13) + '" cy="' + (EYE_CY - 6) + '" r="5"></circle>' +
      '</g>';
  }

  function buildFace() {
    var wrap = $('face-render');
    if (!wrap) return;
    wrap.innerHTML =
      '<svg class="robo-eyes" viewBox="0 0 320 200" role="img" aria-label="ARIA eyes">' +
      eyeGroup('l', L_CX) +
      eyeGroup('r', R_CX) +
      '</svg>';
  }

  /* ===============================================================
     2. STATE
  =============================================================== */
  function setState(s) {
    state = s;
    var stage = $('face-stage');
    if (stage) stage.setAttribute('data-state', s);
    var pill = $('face-state-pill');
    if (pill) pill.textContent = stateLabel(s);
  }
  function setPill(txt) { var p = $('face-state-pill'); if (p) p.textContent = txt; }

  function stateLabel(s) {
    return {
      idle: 'Idle · جاهز',
      listening: 'Listening · أسمعك',
      thinking: 'Thinking · أفكر',
      speaking: 'Speaking · أتكلم',
      error: 'Error · خطأ'
    }[s] || s;
  }

  /* ===============================================================
     3. RENDER LOOP (float + blink + glance + emote)
  =============================================================== */
  function mood() {
    switch (state) {
      case 'listening': return { sx: 1.16, sy: 1.20, dy: 0 };
      case 'thinking':  return { sx: 0.92, sy: 0.52, dy: -16 };
      case 'speaking':  return { sx: 1.08, sy: 0.86, dy: 0 };
      case 'error':     return { sx: 1.0, sy: 0.6, dy: 6 };
      default:          return { sx: 1.0, sy: 1.0, dy: 0 };
    }
  }

  function eyeTransform(cx, cy, dx, dy, sx, sy, rot) {
    return 'translate(' + dx.toFixed(2) + ' ' + dy.toFixed(2) + ') ' +
           'rotate(' + rot.toFixed(2) + ' ' + cx + ' ' + cy + ') ' +
           'translate(' + cx + ' ' + cy + ') scale(' + sx.toFixed(3) + ' ' + sy.toFixed(3) + ') ' +
           'translate(' + (-cx) + ' ' + (-cy) + ')';
  }

  function tick(now) {
    t += 0.016;
    if (!nextBlinkAt) nextBlinkAt = now + 1800 + Math.random() * 2600;
    if (!nextSmileAt) nextSmileAt = now + 5000 + Math.random() * 6000;

    // schedule blinks
    if (!blinking && now >= nextBlinkAt) { blinking = true; blinkT0 = now; }
    var blink = 1;
    if (blinking) {
      var bp = (now - blinkT0) / 150;
      if (bp >= 1) { blinking = false; nextBlinkAt = now + 1800 + Math.random() * 2600; }
      else { blink = 1 - Math.sin(bp * Math.PI) * 0.92; }
    }

    // occasional happy squish while idle
    var smile = 0;
    if (state === 'idle') {
      if (now >= nextSmileAt && smileT0 === 0) smileT0 = now;
      if (smileT0) {
        var sp = (now - smileT0) / 600;
        if (sp >= 1) { smileT0 = 0; nextSmileAt = now + 6000 + Math.random() * 7000; }
        else smile = Math.sin(sp * Math.PI);
      }
    } else { smileT0 = 0; }

    // audio-reactive amplitude while speaking
    if (state === 'speaking' && analyser) {
      analyser.getByteFrequencyData(freqData);
      var sum = 0, n = freqData.length;
      for (var i = 0; i < n; i++) sum += freqData[i];
      var avg = (sum / n) / 255;
      speakAmp += (avg - speakAmp) * 0.4;
    } else {
      speakAmp += (0 - speakAmp) * 0.2;
    }

    var m = mood();
    // gentle floating bob + slow glance so the eyes feel alive
    var bobY = Math.sin(t * 0.9) * 3.4;
    var lookX = Math.sin(t * 0.6) * 5;
    var lookY = Math.cos(t * 0.45) * 3 + bobY + m.dy;

    var sx = m.sx, sy = m.sy;
    if (state === 'speaking') {
      sy = 0.86 + speakAmp * 0.55;
      sx = 1.10 - speakAmp * 0.14;
    }
    if (smile > 0) { sy *= (1 - smile * 0.35); sx *= (1 + smile * 0.12); }
    sy *= blink;

    var rotL = 0, rotR = 0;
    if (state === 'error') { rotL = 14; rotR = -14; }

    var gl = $('rf-eye-l'), gr = $('rf-eye-r');
    if (gl) gl.setAttribute('transform', eyeTransform(L_CX, EYE_CY, lookX, lookY, sx, sy, rotL));
    if (gr) gr.setAttribute('transform', eyeTransform(R_CX, EYE_CY, lookX, lookY, sx, sy, rotR));

    raf = requestAnimationFrame(tick);
  }
  function startLoop() { if (!raf) raf = requestAnimationFrame(tick); }

  /* ===============================================================
     4. TRANSCRIPT
  =============================================================== */
  function clearEmpty() {
    var box = $('face-transcript');
    if (box) { var e = box.querySelector('.face-empty'); if (e) e.remove(); }
  }
  function addLine(role, text) {
    var box = $('face-transcript');
    if (!box) return;
    clearEmpty();
    var line = document.createElement('div');
    line.className = 'face-line ' + (role === 'user' ? 'user' : 'aria');
    var who = role === 'user' ? 'You' : 'ARIA';
    var body = (role !== 'user' && window.nxMarkdown)
      ? window.nxMarkdown(text)
      : escapeHTML(text).replace(/\n/g, '<br>');
    line.innerHTML =
      '<span class="face-line-who">' + who + '</span>' +
      '<span class="face-line-text">' + body + '</span>';
    box.appendChild(line);
    while (box.querySelectorAll('.face-line').length > 6) {
      box.removeChild(box.querySelector('.face-line'));
    }
  }

  /* ===============================================================
     5. AUDIO
  =============================================================== */
  function ensureAudioCtx() {
    if (audioCtx) return audioCtx;
    // Reuse the ONE shared AudioContext (no per-page context leak, never hits
    // the browser's per-tab AudioContext ceiling).
    if (window.NexusAudio && window.NexusAudio.available) { audioCtx = window.NexusAudio.ctx(); return audioCtx; }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try { audioCtx = new AC(); } catch (e) { audioCtx = null; }
    return audioCtx;
  }
  function resumeAudio() {
    var ac = ensureAudioCtx();
    if (ac && ac.state === 'suspended') { try { ac.resume(); } catch (e) {} }
  }

  /* ===============================================================
     6. CONVERSATION CORE
  =============================================================== */
  // Wire a fresh <audio> element into the analyser so the eyes pulse with
  // the Piper audio. Safe to call once per element.
  function wireAnalyser(audio) {
    try {
      var ac = ensureAudioCtx();
      if (!ac) { analyser = null; return; }
      if (ac.state === 'suspended') { try { ac.resume(); } catch (e) {} }
      if (wiredEls.has(audio)) return;
      var srcNode = ac.createMediaElementSource(audio);
      analyser = ac.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.7;
      freqData = new Uint8Array(analyser.frequencyBinCount);
      srcNode.connect(analyser);
      analyser.connect(ac.destination);
      wiredEls.add(audio);
    } catch (e) { analyser = null; }
  }

  // Speak through the shared VoiceManager: auto Arabic/English voice +
  // barge-in (Escape / Stop / new turn all interrupt instantly).
  function speak(text) {
    return new Promise(function (resolve) {
      setState('speaking');
      if (!window.VoiceManager) { setState('idle'); resolve(); return; }
      VoiceManager.speak(text, { onAudio: wireAnalyser }).then(function () {
        analyser = null; speakAmp = 0;
        if (state === 'speaking') setState('idle');
        resolve();
      });
    });
  }

  // Send text to the LLM and speak the reply. Resolves when fully done.
  async function converse(text) {
    busy = true;
    setState('thinking');
    history.push({ role: 'user', content: text });
    var reply = '';
    try {
      var data = await (API.assistantCommand ? API.assistantCommand(text, history) : API.chat(text, history));
      reply = (data && data.response) ? data.response : '';
    } catch (e) { reply = ''; toast('LLM connection error', 'error'); }
    if (!reply) { setState('error'); busy = false; return; }
    history.push({ role: 'assistant', content: reply });
    addLine('aria', reply);
    await speak(reply);
    busy = false;
  }

  /* ===============================================================
     7. TAP-TO-TALK
  =============================================================== */
  var faceCtrl = null;   // active MicRecorder controller (for early stop)

  async function onTalk() {
    // Barge-in: tapping while ARIA talks stops it and starts a fresh turn.
    if (!recording && window.VoiceManager && VoiceManager.isSpeaking()) {
      VoiceManager.stop();
      busy = false;
      setState('idle');
    }
    // Tapping again while recording = stop now (instead of waiting for silence).
    if (recording) { if (faceCtrl) { try { faceCtrl.stop(); } catch (e) {} } return; }
    if (busy) return;
    var btn = $('face-talk-btn');
    resumeAudio();
    if (window.WakeManager) WakeManager.suspend();   // free the mic for Whisper
    recording = true;
    setState('listening');
    if (btn) { btn.classList.add('recording'); setBtnLabel('■  Stop'); }
    var blob;
    try {
      // Browser records and AUTO-STOPS when you go quiet (VAD).
      blob = await MicRecorder.capture({
        vad: true, maxMs: 12000, silenceMs: 1200, minMs: 400,
        onController: function (c) { faceCtrl = c; }
      });
    } catch (e) {
      faceCtrl = null; recording = false;
      toast('Could not start microphone', 'error');
      setState('error'); resetBtn();
      if (window.WakeManager) WakeManager.resume();
      return;
    }
    faceCtrl = null; recording = false;
    if (btn) { btn.classList.remove('recording'); btn.disabled = true; }
    setState('thinking');
    var text = await transcribeBlob(blob);
    if (text === null) { resetBtn(); if (window.WakeManager) WakeManager.resume(); return; }
    if (!text) { toast('Didn\u2019t catch that — try again', 'warning'); setState('idle'); resetBtn(); if (window.WakeManager) WakeManager.resume(); return; }
    addLine('user', text);
    await converse(text);
    resetBtn();
    if (continuous && !recording && !busy) {
      setTimeout(function () { if (!busy && !recording) onTalk(); }, 400);
    } else if (window.WakeManager) {
      WakeManager.resume();   // hand the mic back to the always-on listener
    }
  }

  async function transcribeBlob(blob) {
    if (!blob) return '';
    try {
      var data = await API.sttInference(blob);
      var t = data && (data.text || data.transcription);
      return t ? String(t).trim() : '';
    } catch (e) {
      toast('Transcription failed', 'error');
      setState('error');
      return null;
    }
  }

  function setBtnLabel(txt) {
    var btn = $('face-talk-btn');
    if (btn) { var l = btn.querySelector('.face-talk-label'); if (l) l.textContent = txt; }
  }
  function resetBtn() {
    var btn = $('face-talk-btn');
    if (btn) { btn.disabled = false; btn.classList.remove('recording'); }
    setBtnLabel('🎙  Tap to Talk');
  }

  /* ===============================================================
     8. WAKE WORD — one hands-free turn (called by WakeManager)
  =============================================================== */
  function setWakeBadge(txt, cls) {
    var b = $('face-wake-badge');
    if (!b) return;
    b.textContent = txt;
    b.className = 'face-wake-badge' + (cls ? ' ' + cls : '');
  }

  // Reflect the global WakeManager state into the Face page UI.
  function updateWakeUI(st) {
    if (!st) return;
    var cb = $('face-wake');
    if (cb) {
      cb.checked = !!st.enabled;
      cb.disabled = (st.available === false);
      if (st.available === false && st.reason) cb.title = st.reason;
      else cb.title = '';
    }
    switch (st.status) {
      case 'unavailable': setWakeBadge('Wake word unavailable', 'off'); break;
      case 'listening':   setWakeBadge('Listening for wake word…', 'on'); break;
      case 'detected':    setWakeBadge('Wake detected!', 'hit'); break;
      default:            setWakeBadge('Wake word off', ''); break;
    }
  }

  // Run exactly one hands-free turn: listen for a fixed window, then reply.
  // Returns a Promise that resolves when the turn (incl. speaking) is done.
  function runWakeTurn() {
    // Continuous conversation: after the wake word, ARIA keeps listening turn
    // after turn WITHOUT needing the wake word again. It waits for you to stop
    // talking (VAD auto-stop), replies, then listens for a follow-up. If a turn
    // comes back empty (you stayed silent), the conversation ends and the wake
    // listener re-arms. A hard cap prevents an endless loop.
    var MAX_TURNS = 12;
    return new Promise(function (resolve) {
      if (busy || recording) { resolve(); return; }
      resumeAudio();
      // Free the mic so MicRecorder can capture without conflict
      if (window.WakeManager) WakeManager.suspend();
      var turns = 0;
      function finish() {
        busy = false;
        setState('idle');
        // Re-arm the wake word listener so it detects "Aria" again
        if (window.WakeManager) WakeManager.resume();
        resolve();
      }
      function oneTurn() {
        recording = true;
        busy = true;
        setState('listening');
        setPill(turns === 0 ? 'Listening…' : 'Listening (follow-up)…');
        MicRecorder.capture({
          vad: true, maxMs: 12000, silenceMs: 900, minMs: 400,
          onController: function (c) { faceCtrl = c; }
        }).then(function (blob) {
          faceCtrl = null; recording = false;
          setState('thinking');
          return transcribeBlob(blob).then(function (text) {
            // Empty/blank transcript = you went quiet → end the conversation.
            if (!text) { finish(); return; }
            addLine('user', text);
            return converse(text).then(function () {
              turns++;
              if (turns >= MAX_TURNS || busy || recording) { finish(); return; }
              oneTurn();   // keep the conversation going, no wake word needed
            });
          });
        }).catch(function () {
          faceCtrl = null; recording = false;
          toast('Could not start microphone', 'error');
          setState('error');
          finish();
        });
      }
      oneTurn();
    });
  }

  /* ===============================================================
     9. HEALTH + WIRING + INIT
  =============================================================== */
  async function checkHealth() {
    var dot = $('face-status-dot');
    try { await API.health(); if (dot) dot.className = 'status-dot online'; }
    catch (e) { if (dot) dot.className = 'status-dot offline'; }
  }

  function wire() {
    var btn = $('face-talk-btn');
    if (btn) btn.addEventListener('click', onTalk);
    var cont = $('face-continuous');
    if (cont) cont.addEventListener('change', function () { continuous = cont.checked; });
    var wake = $('face-wake');
    if (wake) wake.addEventListener('change', function () {
      if (window.WakeManager) WakeManager.setEnabled(wake.checked);
    });
    var clear = $('face-clear-btn');
    if (clear) clear.addEventListener('click', function () {
      history = [];
      var box = $('face-transcript');
      if (box) box.innerHTML = '<p class="face-empty">Tap “Talk” or say the wake word — ARIA will listen, think, and reply out loud.</p>';
    });
    var stop = $('face-stop-btn');
    if (stop) stop.addEventListener('click', function () {
      if (window.VoiceManager) VoiceManager.stop();
      busy = false;
      if (state === 'speaking') setState('idle');
    });
    // Reveal the Stop button only while ARIA is speaking.
    if (window.VoiceManager && VoiceManager.onChange) {
      VoiceManager.onChange(function (speaking) {
        var b = $('face-stop-btn');
        if (b) b.classList.toggle('hidden', !speaking);
      });
    }
  }

  function init() {
    if (!initialized) {
      initialized = true;
      buildFace();
      wire();
      startLoop();
      if (window.WakeManager && WakeManager.onChange) WakeManager.onChange(updateWakeUI);
    }
    setState('idle');
    resetBtn();
    startLoop();
    checkHealth();
    if (window.WakeManager && WakeManager.getState) updateWakeUI(WakeManager.getState());
  }

  window.FacePage = { init: init, runWakeTurn: runWakeTurn };
})();
