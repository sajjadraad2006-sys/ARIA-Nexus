/* =====================================================================
   ARIA NEXUS - mic.js   (window.MicRecorder)
   ---------------------------------------------------------------------
   ONE place that records microphone audio in the browser and (optionally)
   AUTO-STOPS when the speaker goes silent (VAD - voice activity detect).

   Why it exists:
     The backend /api/stt/start and /api/stt/stop endpoints are no-ops
     (whisper.cpp has no record loop). The ONLY working speech path is:
        browser MediaRecorder  ->  POST /api/stt/inference  ->  whisper.cpp
     This module captures a clean webm blob ready for that endpoint and
     stops by itself the moment the user stops talking.

   ENDPOINTING (Phase 3 - fixes "drops words / ends too early"):
     * PRE-ROLL: MediaRecorder.start() is called BEFORE the VAD loop arms, so
       the very first phoneme is always inside the blob (never clipped).
     * NOISE-FLOOR CALIBRATION: the first calibrateMs of audio measures the
       ambient room level; the speech threshold becomes
       max(startThreshold, noiseFloor * noiseMult) so a noisy room does not
       look like constant speech (and a quiet room stays sensitive).
     * MIN-SPEECH GATE: a turn only ends on silence after at least minSpeechMs
       of *actual speech* has been seen, so a short cough/click cannot end the
       turn before the user really spoke.
     * SILENCE HANGOVER: silenceMs of trailing silence (default long enough to
       ride over natural mid-sentence pauses) is required before we stop.

   capture(opts) -> Promise<Blob|null>
     opts (all optional; sensible config-driven defaults):
       vad            (bool,  default true)   auto-stop on silence
       maxMs          (num,   default 20000)  hard cap on a single utterance
       silenceMs      (num,   default 1500)   trailing silence => stop
       minMs          (num,   default 500)    ignore stops before this
       minSpeechMs    (num,   default 300)    speech needed before silence-stop
       startThreshold (num,   default 0.030)  RMS floor that counts as speech
       calibrateMs    (num,   default 300)    ambient-noise calibration window
       noiseMult      (num,   default 2.2)    speech thr = noiseFloor*noiseMult
       onLevel(level0to1)   live mic loudness (for waveform UI)
       onState('listening'|'calibrating'|'stopping')
       onController(ctrl)   ctrl.stop() = stop now, ctrl.cancel() = abort
     Resolves with the recorded Blob, or null if nothing was captured /
     it was cancelled. Rejects only if the mic could not be opened.
   ===================================================================== */
(function () {
  'use strict';

  // Capture defaults. Overridable per-call AND globally via
  // window.NEXUS_VAD (the backend pushes config.VAD_CONFIG into that global).
  var DEFAULTS = {
    vad: true,
    maxMs: 20000,
    silenceMs: 900,   // trailing silence before auto-stop (lowered from 1500 to cut the reply lag)
    minMs: 500,
    minSpeechMs: 300,
    startThreshold: 0.030,
    calibrateMs: 300,
    noiseMult: 2.2
  };

  function cfg(opts, key) {
    if (opts && opts[key] != null) return opts[key];
    var g = window.NEXUS_VAD || {};
    if (g[key] != null) return g[key];
    return DEFAULTS[key];
  }

  function capture(opts) {
    opts = opts || {};
    var maxMs = cfg(opts, 'maxMs');
    var silenceMs = cfg(opts, 'silenceMs');
    var minMs = cfg(opts, 'minMs');
    var minSpeechMs = cfg(opts, 'minSpeechMs');
    var startThreshold = cfg(opts, 'startThreshold');
    var calibrateMs = cfg(opts, 'calibrateMs');
    var noiseMult = cfg(opts, 'noiseMult');
    var onLevel = opts.onLevel, onState = opts.onState, onController = opts.onController;

    return new Promise(function (resolve, reject) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
        reject(new Error('Microphone not supported in this browser'));
        return;
      }
      // echoCancellation + noiseSuppression help a lot for barge-in / open mic.
      var constraints = { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } };
      navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
        var chunks = [];
        var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
        var rec;
        try { rec = new MediaRecorder(stream, { mimeType: mime }); }
        catch (e) { rec = new MediaRecorder(stream); }
        rec.ondataavailable = function (e) { if (e.data && e.data.size > 0) chunks.push(e.data); };

        /* analyser for VAD + live level */
        var AC = window.AudioContext || window.webkitAudioContext;
        var ac = null, analyser = null, data = null, src = null;
        if (AC) {
          try {
            ac = new AC();
            if (ac.state === 'suspended') { try { ac.resume(); } catch (e) {} }
            src = ac.createMediaStreamSource(stream);
            analyser = ac.createAnalyser();
            analyser.fftSize = 512;
            data = new Uint8Array(analyser.fftSize);
            src.connect(analyser);
          } catch (e) { analyser = null; }
        }

        var started = Date.now(), lastVoice = started;
        var sawSpeech = false, speechMs = 0, lastTick = started;
        var raf = null, stopped = false, settled = false;
        // Noise-floor calibration state.
        var calibrating = (calibrateMs > 0 && analyser);
        var noiseSum = 0, noiseN = 0, speechThr = startThreshold;

        function rms() {
          if (!analyser) return 0;
          analyser.getByteTimeDomainData(data);
          var sum = 0;
          for (var i = 0; i < data.length; i++) { var v = (data[i] - 128) / 128; sum += v * v; }
          return Math.sqrt(sum / data.length);
        }
        function teardown() {
          if (raf) { cancelAnimationFrame(raf); raf = null; }
          try { if (src) src.disconnect(); } catch (e) {}
          try { if (ac) ac.close(); } catch (e) {}
          try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        }
        function stopNow() {
          if (stopped) return;
          stopped = true;
          if (onState) { try { onState('stopping'); } catch (e) {} }
          try { rec.stop(); } catch (e) { teardown(); if (!settled) { settled = true; resolve(null); } }
        }
        function cancel() {
          if (settled) return;
          stopped = true;
          try { rec.ondataavailable = null; rec.stop(); } catch (e) {}
          teardown();
          settled = true;
          resolve(null);
        }

        rec.onstop = function () {
          teardown();
          if (settled) return;
          settled = true;
          if (!chunks.length) { resolve(null); return; }
          resolve(new Blob(chunks, { type: rec.mimeType || 'audio/webm' }));
        };

        if (onController) { try { onController({ stop: stopNow, cancel: cancel }); } catch (e) {} }

        // PRE-ROLL: start recording immediately, BEFORE VAD arms, so the start
        // of speech is captured even while we are still calibrating noise.
        try { rec.start(200); } catch (e) { teardown(); reject(e); return; }
        if (onState) { try { onState(calibrating ? 'calibrating' : 'listening'); } catch (e) {} }

        function loop() {
          if (stopped) return;
          var now = Date.now();
          var dt = now - lastTick; lastTick = now;
          var lvl = rms();
          if (onLevel) { try { onLevel(Math.min(1, lvl * 3.2)); } catch (e) {} }

          // --- Phase 1: ambient noise-floor calibration ---
          if (calibrating) {
            noiseSum += lvl; noiseN++;
            if ((now - started) >= calibrateMs) {
              var floor = noiseN ? (noiseSum / noiseN) : 0;
              speechThr = Math.max(startThreshold, floor * noiseMult);
              calibrating = false;
              if (onState) { try { onState('listening'); } catch (e) {} }
            }
            raf = requestAnimationFrame(loop);
            return;
          }

          // --- Phase 2: voice activity detection ---
          if (lvl >= speechThr) {
            sawSpeech = true;
            speechMs += dt;
            lastVoice = now;
          }
          var elapsed = now - started;
          // Only end on silence once we have heard enough real speech AND the
          // trailing silence + min-length conditions are all satisfied.
          if (opts.vad !== false && sawSpeech && speechMs >= minSpeechMs &&
              (now - lastVoice) >= silenceMs && elapsed >= minMs) {
            stopNow(); return;
          }
          if (elapsed >= maxMs) { stopNow(); return; }
          raf = requestAnimationFrame(loop);
        }
        raf = requestAnimationFrame(loop);
      }).catch(function (err) {
        reject(err || new Error('Microphone access denied'));
      });
    });
  }

  window.MicRecorder = { capture: capture };
})();
