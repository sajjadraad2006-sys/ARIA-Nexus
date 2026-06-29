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
    silenceMs: 1100,  // trailing silence before auto-stop. Long enough to ride
                      // over natural mid-sentence pauses so the LAST word is not
                      // clipped, but short enough to keep replies snappy.
    minMs: 500,
    minSpeechMs: 300,
    // Mobile mics output lower RMS levels than desktop mics. 0.022 (was 0.030)
    // reliably captures normal-volume speech without triggering on room noise
    // (the adaptive noiseMult floor still guards against that).
    startThreshold: 0.022,
    calibrateMs: 300,    // initial settle window before the first silence-stop
    noiseMult: 2.2,
    // Hard cap on the adaptive threshold. Lowered from 0.080 to 0.065 so a
    // slightly noisy room can never push the bar so high that normal speech
    // registers as silence on a mobile mic.
    maxThreshold: 0.065
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
    var maxThreshold = cfg(opts, 'maxThreshold');
    var onLevel = opts.onLevel, onState = opts.onState, onController = opts.onController;

    return new Promise(function (resolve, reject) {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
        reject(new Error('Microphone not supported in this browser'));
        return;
      }
      // echoCancellation + noiseSuppression help a lot for barge-in / open mic.
      var constraints = { audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } };
      var _micT0 = Date.now();
      navigator.mediaDevices.getUserMedia(constraints).then(function (stream) {
        var _micMs = Date.now() - _micT0;
        (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('MIC','getUserMedia.done',{ms:_micMs});
        var chunks = [];
        var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
        var rec;
        try { rec = new MediaRecorder(stream, { mimeType: mime }); }
        catch (e) { rec = new MediaRecorder(stream); }
        rec.ondataavailable = function (e) { if (e.data && e.data.size > 0) chunks.push(e.data); };

        /* analyser for VAD + live level -- wired to the ONE shared AudioContext
           (window.NexusAudio) so we never exhaust the browser's per-tab
           AudioContext ceiling. Falls back to a private context only if the
           shared bus is somehow unavailable. */
        var analyser = null, data = null, src = null, ownCtx = null;
        try {
          if (window.NexusAudio && window.NexusAudio.available) {
            var wired = window.NexusAudio.analyser(stream);
            if (wired) { analyser = wired.analyser; src = wired.source; }
          } else {
            var AC = window.AudioContext || window.webkitAudioContext;
            if (AC) {
              ownCtx = new AC();
              if (ownCtx.state === 'suspended') { try { ownCtx.resume(); } catch (e) {} }
              src = ownCtx.createMediaStreamSource(stream);
              analyser = ownCtx.createAnalyser();
              analyser.fftSize = 512;
              src.connect(analyser);
            }
          }
          if (analyser) data = new Uint8Array(analyser.fftSize);
        } catch (e) { analyser = null; }
        if (!analyser) { try { console.warn('[mic] Web Audio analyser unavailable - VAD off, falling back to time cap'); } catch (e) {} }

        var started = Date.now(), lastVoice = started;
        var sawSpeech = false, speechMs = 0, lastTick = started;
        var raf = null, stopped = false, settled = false;
        var stopReason = 'maxlen', peakLvl = 0;
        // Adaptive noise-floor VAD state. We follow the running MINIMUM level
        // (true silence), not the mean, so speech in the first frames can never
        // inflate the floor and lock out the rest of the utterance.
        var warmupMs = (calibrateMs > 0 ? calibrateMs : 0);
        var noiseFloor = null, speechThr = startThreshold;

        function rms() {
          if (!analyser) return 0;
          analyser.getByteTimeDomainData(data);
          var sum = 0;
          for (var i = 0; i < data.length; i++) { var v = (data[i] - 128) / 128; sum += v * v; }
          return Math.sqrt(sum / data.length);
        }
        function teardown() {
          if (raf) { cancelAnimationFrame(raf); raf = null; }
          // Disconnect our source node, but NEVER close the shared AudioContext
          // (every other surface reuses it). Only a private fallback is closed.
          try { if (src) src.disconnect(); } catch (e) {}
          try { if (ownCtx) ownCtx.close(); } catch (e) {}
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
          var durMs = Date.now() - started;
          if (!chunks.length) {
            try { console.warn('[mic] capture produced NO audio chunks (dur ' + durMs + 'ms)'); } catch (e) {}
            resolve(null); return;
          }
          var blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
          // One concise diagnostic line per capture so the full path
          // (capture -> POST /api/stt/inference -> Whisper) is traceable.
          try {
            console.info('[mic] captured ' + blob.size + ' bytes in ' + durMs +
              'ms | reason=' + stopReason + ' sawSpeech=' + sawSpeech +
              ' speechMs=' + Math.round(speechMs) + ' peak=' + peakLvl.toFixed(3) +
              ' thr=' + speechThr.toFixed(3));
          } catch (e) {}
          (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('MIC','capture.done',{bytes:blob.size,ms:durMs,reason:stopReason,sawSpeech:sawSpeech,speechMs:Math.round(speechMs),peak:+(peakLvl.toFixed(3)),thr:+(speechThr.toFixed(3))});
          resolve(blob);
        };

        if (onController) { try { onController({ stop: stopNow, cancel: cancel }); } catch (e) {} }

        // PRE-ROLL: start recording immediately, BEFORE VAD arms, so the start
        // of speech is captured even while we are still calibrating noise.
        try { rec.start(200); } catch (e) { teardown(); reject(e); return; }
        if (onState) { try { onState('listening'); } catch (e) {} }
        (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('MIC','capture.start',{vad:opts.vad!==false,maxMs:maxMs,silenceMs:silenceMs});

        function loop() {
          if (stopped) return;
          var now = Date.now();
          var dt = now - lastTick; lastTick = now;
          var lvl = rms();
          if (lvl > peakLvl) peakLvl = lvl;
          if (onLevel) { try { onLevel(Math.min(1, lvl * 3.2)); } catch (e) {} }

          // --- Adaptive noise floor (immune to speech poisoning) ---
          // Seed on the first frame, snap DOWN to any quieter frame (real
          // silence), and creep UP only very slowly. Following the minimum means
          // talking during the first 300ms can never raise the threshold and
          // lock out the rest of the sentence -- the exact defect that made the
          // mic 'go deaf after one turn'.
          if (noiseFloor === null) { noiseFloor = lvl; }
          else if (lvl < noiseFloor) { noiseFloor = lvl; }
          else { noiseFloor = noiseFloor + (lvl - noiseFloor) * 0.0008; }
          var dyn = noiseFloor * noiseMult;
          if (dyn < startThreshold) dyn = startThreshold;
          if (dyn > maxThreshold) dyn = maxThreshold;   // HARD safety cap
          speechThr = dyn;

          // --- Voice activity detection (active from the very first frame) ---
          if (analyser && lvl >= speechThr) {
            sawSpeech = true;
            speechMs += dt;
            lastVoice = now;
          }
          var elapsed = now - started;

          // Silence-stop only after the warm-up / min-length window; speech
          // heard during warm-up still counts (pre-roll already records it).
          var settleMs = (minMs > warmupMs ? minMs : warmupMs);
          if (opts.vad !== false && analyser && sawSpeech && speechMs >= minSpeechMs &&
              (now - lastVoice) >= silenceMs && elapsed >= settleMs) {
            stopReason = 'silence'; stopNow(); return;
          }
          if (elapsed >= maxMs) { stopReason = 'maxlen'; stopNow(); return; }
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
