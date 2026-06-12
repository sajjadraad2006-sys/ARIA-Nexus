/* =====================================================================
   ARIA NEXUS — voice.js   (window.VoiceManager)
   ---------------------------------------------------------------------
   ONE place that owns spoken output, so the whole app can:
     • BARGE-IN / مقاطعة — stop ARIA mid-sentence and ask something new.
         - VoiceManager.stop() kills current playback + aborts the
           in-flight TTS fetch.
         - Pressing Escape, clicking a Stop button, sending a new chat
           message, or starting the mic all call stop() first.
     • MULTI-LANGUAGE VOICES — auto-detect Arabic vs English in the reply
         and speak it with the matching Piper voice. Per-language voices
         persist in localStorage ('nexus_voice_ar' / 'nexus_voice_en');
         falls back to the single 'nexus_tts_voice'.

   Public API:
     speak(text, opts) -> Promise   opts: { voice, onAudio(el), lang }
     stop()            -> bool       (true if something was stopped)
     isSpeaking()      -> bool
     detectLang(text)  -> 'ar' | 'en'
     voiceForText(text)-> voice id string
     onChange(cb)      -> subscribe to speaking-state changes (bool)
   ===================================================================== */
(function () {
  'use strict';

  var cur = { audio: null, url: null, ctrl: null, token: 0 };
  var seq = 0;
  var listeners = [];

  function notify(speaking) {
    for (var i = 0; i < listeners.length; i++) {
      try { listeners[i](speaking); } catch (e) {}
    }
  }

  function ttsEnabled() {
    return localStorage.getItem('nexus_chat_tts') !== '0';
  }

  /* ---- language detection + per-language Piper voice ---- */
  function detectLang(text) {
    return /[\u0600-\u06FF]/.test(String(text || '')) ? 'ar' : 'en';
  }

  /* Cache of installed voices (from the TTS server) so we can auto-match a
     voice to the detected language even when the user never picked a
     per-language voice in Settings. */
  var _voicesCache = null;
  var _voicesPromise = null;
  function ensureVoices() {
    if (_voicesCache) return Promise.resolve(_voicesCache);
    if (_voicesPromise) return _voicesPromise;
    if (!window.API || !API.getTTSVoices) return Promise.resolve([]);
    _voicesPromise = API.getTTSVoices().then(function (data) {
      var list = (data && (data.voices || data.list)) || [];
      _voicesCache = Array.isArray(list) ? list : [];
      return _voicesCache;
    }).catch(function () { _voicesCache = []; return _voicesCache; });
    return _voicesPromise;
  }
  function refreshVoices() { _voicesCache = null; _voicesPromise = null; return ensureVoices(); }

  function _vid(v) { return (v && (v.voice_id || v.id)) || ''; }
  function _matchesLang(v, lang) {
    var id = _vid(v).toLowerCase();
    var meta = ((v && v.language) || '').toString().toLowerCase();
    if (lang === 'ar') {
      return id.indexOf('ar_') === 0 || id.indexOf('ar-') === 0 ||
             /(^|[_\-\/])ar([_\-]|$)/.test(id) ||
             meta.indexOf('arab') !== -1 || meta === 'ar' || /[\u0600-\u06FF]/.test(meta);
    }
    return id.indexOf('en_') === 0 || id.indexOf('en-') === 0 ||
           /(^|[_\-\/])en([_\-]|$)/.test(id) ||
           meta.indexOf('english') !== -1 || meta === 'en';
  }
  /* Pick a voice id for a language: manual Settings choice wins, then an
     auto-match from the installed voices, then the single saved voice,
     then the first available voice. */
  function pickVoiceForLang(lang, voices) {
    var manual = localStorage.getItem('nexus_voice_' + lang);
    voices = voices || _voicesCache || [];
    var ids = voices.map(_vid);
    if (manual && (ids.length === 0 || ids.indexOf(manual) !== -1)) return manual;
    for (var i = 0; i < voices.length; i++) {
      if (_matchesLang(voices[i], lang)) return _vid(voices[i]);
    }
    return localStorage.getItem('nexus_tts_voice') || (voices[0] ? _vid(voices[0]) : '');
  }
  /* Synchronous best-effort (uses cache if already loaded). */
  function voiceForText(text) {
    return pickVoiceForLang(detectLang(text), _voicesCache || []);
  }
  /* Async: guarantees the voices list is loaded before choosing, so the
     correct Arabic/English voice is used even on the first utterance. */
  function resolveVoiceForText(text, explicit) {
    if (explicit) return Promise.resolve(explicit);
    var lang = detectLang(text);
    return ensureVoices().then(function (voices) { return pickVoiceForLang(lang, voices); });
  }

  /* ---- barge-in: stop everything currently speaking ---- */
  function stop() {
    var had = !!(cur.audio || cur.ctrl);
    cur.token = ++seq; // invalidate any in-flight speak() resolution path
    try { if (cur.ctrl) cur.ctrl.abort(); } catch (e) {}
    if (cur.audio) {
      try {
        cur.audio.onended = null;
        cur.audio.onerror = null;
        cur.audio.pause();
        cur.audio.src = '';
      } catch (e) {}
    }
    if (cur.url) { try { URL.revokeObjectURL(cur.url); } catch (e) {} }
    cur.audio = null; cur.url = null; cur.ctrl = null;
    if (had) notify(false);
    return had;
  }

  function isSpeaking() { return !!cur.audio; }

  /* ---- speak text (auto language voice, abortable) ---- */
  function speak(text, opts) {
    opts = opts || {};
    stop(); // any new utterance interrupts the previous one
    var myToken = ++seq;
    cur.token = myToken;

    return new Promise(function (resolve) {
      if (!ttsEnabled()) { resolve({ skipped: true }); return; }
      if (!text || !window.API || !API.previewTTSVoice) { resolve({ skipped: true }); return; }

      var ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      cur.ctrl = ctrl;

      resolveVoiceForText(text, opts.voice).then(function (voice) {
        if (cur.token !== myToken) { resolve({ aborted: true }); return; }

        var p;
        try { p = API.previewTTSVoice(voice, text, ctrl ? ctrl.signal : undefined); }
        catch (e) { cur.ctrl = null; resolve({ error: true }); return; }

        p.then(function (blob) {
        // superseded by a newer speak()/stop()? bail quietly.
        if (cur.token !== myToken) { resolve({ aborted: true }); return; }
        cur.ctrl = null;
        if (!blob || !blob.size) { resolve({ empty: true }); return; }

        var url = URL.createObjectURL(blob);
        var audio = new Audio();
        audio.src = url;
        cur.audio = audio; cur.url = url;

        if (opts.onAudio) { try { opts.onAudio(audio); } catch (e) {} }

        var done = false;
        function finish(res) {
          if (done) return; done = true;
          if (cur.audio === audio) {
            if (cur.url) { try { URL.revokeObjectURL(cur.url); } catch (e) {} }
            cur.audio = null; cur.url = null;
            notify(false);
          }
          resolve(res || { ok: true });
        }
        audio.onended = function () { finish({ ok: true }); };
        audio.onerror = function () { finish({ error: true }); };
        notify(true);
        audio.play().catch(function () { finish({ error: true }); });
      }).catch(function () {
        if (cur.token === myToken) cur.ctrl = null;
        resolve({ error: true }); // network error or aborted fetch
      });
      });
    });
  }

  function onChange(cb) { if (typeof cb === 'function') listeners.push(cb); }

  window.VoiceManager = {
    speak: speak,
    stop: stop,
    isSpeaking: isSpeaking,
    detectLang: detectLang,
    voiceForText: voiceForText,
    refreshVoices: refreshVoices,
    onChange: onChange
  };

  // Warm the voices cache so the first reply already picks the right language voice.
  try { ensureVoices(); } catch (e) {}

  /* ---- global barge-in key: Escape stops speech anywhere ---- */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isSpeaking()) { stop(); }
  });
})();
