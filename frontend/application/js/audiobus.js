/* =====================================================================
   ARIA NEXUS - audiobus.js   (window.NexusAudio)
   ---------------------------------------------------------------------
   ONE shared Web Audio AudioContext for the whole single-page app.

   Why this exists (root-cause fix):
     Browsers cap the number of concurrent AudioContext objects per tab
     (Chrome/Chromium allow ~6). The app used to create a *new* AudioContext
     in mic.js (every recording), in the wake listener, in the barge-in
     monitors, in the call screen, in the robot-face screen and in the wake
     chime. Several of those were never closed. After a few turns the tab hit
     the ceiling, `new AudioContext()` started THROWING, the VAD analyser
     silently became null, and capture could no longer detect speech -> the
     mic "went deaf after the first turn".

     Reusing a single long-lived AudioContext is also the approach the Web
     Audio spec and every major browser explicitly recommend.

   API:
     NexusAudio.ctx()      -> the shared AudioContext (created lazily), or
                              null if Web Audio is unavailable. Always resumed.
     NexusAudio.resume()   -> resume the context (call from a user gesture).
     NexusAudio.analyser(stream)
                           -> { analyser, source } wired to the shared ctx,
                              or null on failure. Caller MUST call
                              source.disconnect() when done (never close ctx).
     NexusAudio.available  -> bool, Web Audio supported.
   ===================================================================== */
(function () {
  'use strict';

  var AC = window.AudioContext || window.webkitAudioContext;
  var _ctx = null;

  function ctx() {
    if (!AC) return null;
    if (!_ctx) {
      try { _ctx = new AC(); }
      catch (e) { _ctx = null; return null; }
    }
    // A context can be auto-suspended by the browser until a user gesture, or
    // after the device sleeps. Always try to bring it back.
    if (_ctx && _ctx.state === 'suspended') {
      try { _ctx.resume(); } catch (e) {}
    }
    return _ctx;
  }

  function resume() {
    var c = ctx();
    if (c && c.state === 'suspended') {
      try { return c.resume(); } catch (e) {}
    }
    return null;
  }

  function analyser(stream) {
    var c = ctx();
    if (!c) return null;
    try {
      var source = c.createMediaStreamSource(stream);
      var an = c.createAnalyser();
      an.fftSize = 512;
      source.connect(an);
      return { analyser: an, source: source };
    } catch (e) {
      return null;
    }
  }

  // Best-effort: resume the shared context on the first user interaction so
  // autoplay/AudioContext gesture policies never leave us suspended.
  try {
    var kick = function () {
      resume();
      window.removeEventListener('pointerdown', kick, true);
      window.removeEventListener('keydown', kick, true);
    };
    window.addEventListener('pointerdown', kick, true);
    window.addEventListener('keydown', kick, true);
  } catch (e) {}

  window.NexusAudio = {
    ctx: ctx,
    resume: resume,
    analyser: analyser,
    available: !!AC
  };
})();
