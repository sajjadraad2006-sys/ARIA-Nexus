/* =====================================================================
   ARIA NEXUS — pages/chatbot.js
   window.ChatbotPage = { init }
   ===================================================================== */
(function () {
  'use strict';

  var initialized = false;
  var conversationHistory = [];   // [{role:'user'|'assistant', content:str}]
  var isThinking = false;
  var contextMax = 4096;
  var contextUsed = 0;
  var recording = false;

  function $(id) { return document.getElementById(id); }
  function toast(msg, type) { if (window.nexus) nexus.showToast(msg, type); }

  function escapeHTML(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function scrollToBottom() {
    var box = $('chat-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  function appendBubble(role, text) {
    var box = $('chat-messages');
    if (!box) return;
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble ' + (role === 'user' ? 'user' : 'aria');
    var avatar = role === 'user' ? 'U' : 'A';
    var time = new Date().toLocaleTimeString('en-GB', { hour12: false });
    var safe = (role !== 'user' && window.nxMarkdown)
      ? window.nxMarkdown(text)
      : escapeHTML(text).replace(/\n/g, '<br>');
    bubble.innerHTML =
      '<div class="bubble-avatar">' + avatar + '</div>' +
      '<div class="bubble-body">' +
      '  <p class="bubble-text">' + safe + '</p>' +
      '  <span class="bubble-time">' + time + '</span>' +
      '</div>';
    box.appendChild(bubble);
    scrollToBottom();
  }

  // Speak ARIA's reply through Piper TTS (on by default). VoiceManager picks
  // the matching Arabic/English voice automatically and makes it stoppable.
  function speakReply(text) {
    try {
      if (window.VoiceManager) { VoiceManager.speak(text); return; }
      if (localStorage.getItem('nexus_chat_tts') === '0') return;
      if (!text || !window.API || !API.previewTTSVoice) return;
      var voice = localStorage.getItem('nexus_tts_voice') || '';
      API.previewTTSVoice(voice, text).then(function (blob) {
        if (!blob || !blob.size) return;
        var url = URL.createObjectURL(blob);
        var a = new Audio(url);
        a.onended = function () { URL.revokeObjectURL(url); };
        a.play().catch(function () {});
      }).catch(function () {});
    } catch (e) {}
  }

  // Barge-in: stop ARIA speaking right now.
  function stopSpeaking() {
    if (window.VoiceManager) VoiceManager.stop();
    stopBargeMonitor();
  }

  // ── Automatic barge-in monitor ─────────────────────────────
  // While ARIA is speaking, a background mic stream monitors RMS. If the
  // user speaks above the threshold for bargeMs, TTS is interrupted
  // instantly. Uses echoCancellation so ARIA's own voice doesn't trigger it.
  var _bargeStream = null, _bargeAC = null, _bargeSrc = null,
      _bargeAnalyser = null, _bargeData = null, _bargeRAF = null;

  function stopBargeMonitor() {
    if (_bargeRAF) { cancelAnimationFrame(_bargeRAF); _bargeRAF = null; }
    try { if (_bargeSrc) _bargeSrc.disconnect(); } catch (e) {}
    try { if (_bargeAC) _bargeAC.close(); } catch (e) {}
    try { if (_bargeStream) _bargeStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    _bargeStream = null; _bargeAC = null; _bargeSrc = null;
    _bargeAnalyser = null; _bargeData = null;
  }

  function startBargeMonitor() {
    if (_bargeStream) return;   // already running
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return;
    var hasAudio = (window.NexusAudio && window.NexusAudio.available) ||
                   window.AudioContext || window.webkitAudioContext;
    if (!hasAudio) return;
    var vad = window.NEXUS_VAD || {};
    var thr = vad.bargeInThreshold || 0.060;
    var needMs = vad.bargeInMs || 350;
    navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then(function (stream) {
      // Guard: only monitor while ARIA is actually speaking
      if (!window.VoiceManager || !VoiceManager.isSpeaking()) {
        try { stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        return;
      }
      _bargeStream = stream;
      try {
        if (window.NexusAudio && window.NexusAudio.available) {
          // Reuse the ONE shared AudioContext (no per-monitor context leak).
          var wired = window.NexusAudio.analyser(stream);
          if (!wired) { stopBargeMonitor(); return; }
          _bargeSrc = wired.source; _bargeAnalyser = wired.analyser;
        } else {
          var AC = window.AudioContext || window.webkitAudioContext;
          _bargeAC = new AC();
          if (_bargeAC.state === 'suspended') { try { _bargeAC.resume(); } catch (e) {} }
          _bargeSrc = _bargeAC.createMediaStreamSource(stream);
          _bargeAnalyser = _bargeAC.createAnalyser();
          _bargeAnalyser.fftSize = 512;
          _bargeSrc.connect(_bargeAnalyser);
        }
        _bargeData = new Uint8Array(_bargeAnalyser.fftSize);
      } catch (e) { stopBargeMonitor(); return; }
      var voiceMs = 0, last = Date.now();
      function tick() {
        if (!_bargeStream || !window.VoiceManager || !VoiceManager.isSpeaking()) {
          stopBargeMonitor(); return;
        }
        var now = Date.now(), dt = now - last; last = now;
        _bargeAnalyser.getByteTimeDomainData(_bargeData);
        var sum = 0;
        for (var i = 0; i < _bargeData.length; i++) {
          var v = (_bargeData[i] - 128) / 128; sum += v * v;
        }
        var rms = Math.sqrt(sum / _bargeData.length);
        if (rms >= thr) { voiceMs += dt; } else { voiceMs = Math.max(0, voiceMs - dt * 0.5); }
        if (voiceMs >= needMs) {
          // Sustained user speech detected → interrupt ARIA
          stopBargeMonitor();
          try { VoiceManager.stop(); } catch (e) {}
          return;
        }
        _bargeRAF = requestAnimationFrame(tick);
      }
      _bargeRAF = requestAnimationFrame(tick);
    }).catch(function () { /* mic unavailable: barge-in stays off */ });
  }

  function resizeChatInput() {
    var ta = $('chat-input');
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px';
  }

  function updateContextCounter(used, max) {
    if (typeof used === 'number') contextUsed = used;
    if (typeof max === 'number' && max) contextMax = max;
    var c = $('chat-ctx-counter');
    if (c) {
      c.textContent = contextUsed + ' / ' + contextMax;
      c.classList.toggle('ctx-warning', contextUsed > contextMax * 0.9);
    }
  }

  /* ── Streaming chat via /api/chat/stream (SSE) ──────────────────
     Renders tokens as they arrive so the user sees ARIA "typing" in
     real-time instead of waiting for the entire LLM response.
     Falls back to the blocking API.chat if EventSource / fetch streaming
     isn't available (very old browsers).
  ─────────────────────────────────────────────────────────────── */
  async function sendMessageStreaming(text) {
    var thinking = $('chat-thinking');
    // Create an empty ARIA bubble to stream tokens into
    var box = $('chat-messages');
    if (!box) return null;
    var bubble = document.createElement('div');
    bubble.className = 'chat-bubble aria';
    var time = new Date().toLocaleTimeString('en-GB', { hour12: false });
    bubble.innerHTML =
      '<div class="bubble-avatar">A</div>' +
      '<div class="bubble-body">' +
      '  <p class="bubble-text" id="stream-bubble-text"></p>' +
      '  <span class="bubble-time">' + time + '</span>' +
      '</div>';
    box.appendChild(bubble);
    scrollToBottom();

    var textEl = document.getElementById('stream-bubble-text');
    var fullText = '';
    var sentenceBuffer = '';
    var spokenFirst = false;

    // SSE streaming via fetch + ReadableStream
    try {
      var res = await fetch(window.location.origin + '/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: conversationHistory })
      });
      if (!res.ok || !res.body) throw new Error('stream failed');

      if (thinking) thinking.classList.add('hidden');

      var reader = res.body.getReader();
      var decoder = new TextDecoder();
      var lineBuf = '';

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        lineBuf += decoder.decode(chunk.value, { stream: true });
        var lines = lineBuf.split('\n');
        lineBuf = lines.pop(); // keep incomplete line

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line || !line.startsWith('data: ')) continue;
          var raw = line.slice(6);
          if (raw === '[DONE]') break;
          try {
            var obj = JSON.parse(raw);
            var token = (obj.choices && obj.choices[0] &&
                         obj.choices[0].delta && obj.choices[0].delta.content) || '';
            if (!token) continue;
            fullText += token;
            sentenceBuffer += token;
            // Render markdown progressively
            if (textEl) {
              textEl.innerHTML = window.nxMarkdown ? window.nxMarkdown(fullText) : escapeHTML(fullText);
            }
            scrollToBottom();
            // TTS: speak first sentence as soon as it ends (low latency audio)
            if (!spokenFirst && /[.!?؟\n]/.test(token)) {
              var sentence = sentenceBuffer.trim();
              if (sentence.length > 4) {
                spokenFirst = true;
                speakReply(sentence);
                sentenceBuffer = '';
              }
            }
          } catch (e) {}
        }
      }
      // Speak remainder if nothing was spoken yet
      if (!spokenFirst && fullText.trim().length > 0) {
        speakReply(fullText.trim());
      }
      return fullText;
    } catch (e) {
      // Streaming failed → fall back to blocking request
      return null;
    }
  }

  async function sendMessage() {
    var ta = $('chat-input');
    if (!ta) return;
    var text = ta.value.trim();
    if (!text || isThinking) return;

    stopSpeaking();   // a new question interrupts any current speech
    isThinking = true;
    appendBubble('user', text);
    ta.value = '';
    resizeChatInput();
    var thinking = $('chat-thinking');
    if (thinking) thinking.classList.remove('hidden');
    scrollToBottom();
    conversationHistory.push({ role: 'user', content: text });

    // ── IoT / assistant commands (need the full structured response to
    //    execute device tags) go through the blocking assistantCommand.
    //    Pure chatbot messages use the streaming SSE path for low latency.
    var useAssistant = !!(window.API && API.assistantCommand);

    try {
      if (useAssistant) {
        // IoT/assistant path: blocking, returns JSON with action + IoT tags
        var data = await API.assistantCommand(text, conversationHistory);
        isThinking = false;
        if (thinking) thinking.classList.add('hidden');
        var reply = (data && data.response) ? data.response : '(empty response)';
        appendBubble('aria', reply);
        conversationHistory.push({ role: 'assistant', content: reply });
        speakReply(reply);
        if (data) updateContextCounter(data.context_used, data.context_max);
      } else {
        // Pure chatbot: streaming path (low latency)
        var streamReply = await sendMessageStreaming(text);
        isThinking = false;
        if (thinking) thinking.classList.add('hidden');
        if (streamReply !== null) {
          conversationHistory.push({ role: 'assistant', content: streamReply });
        } else {
          // Fallback: blocking /api/chat
          var data2 = await API.chat(text, conversationHistory);
          var reply2 = (data2 && data2.response) ? data2.response : '(empty response)';
          appendBubble('aria', reply2);
          conversationHistory.push({ role: 'assistant', content: reply2 });
          speakReply(reply2);
          if (data2) updateContextCounter(data2.context_used, data2.context_max);
        }
      }
    } catch (err) {
      isThinking = false;
      if (thinking) thinking.classList.add('hidden');
      appendBubble('aria', 'Error connecting to LLM. Is the server running?');
      toast('LLM connection error', 'error');
    }
  }

  function clearConversation() {
    conversationHistory = [];
    contextUsed = 0;
    var box = $('chat-messages');
    if (box) box.innerHTML = '';
    updateContextCounter(0, contextMax);
    appendBubble('aria', 'Conversation cleared. How can I help you?');
  }

  // ── MIC: record in browser → send to Whisper /inference ────────────
  //
  // Architecture: we pre-arm ONE persistent mic stream when the chatbot page
  // loads (_prewarmMic). When the user presses the mic button, the MediaRecorder
  // starts immediately on the already-open stream — no getUserMedia() delay.
  // The stream is only released when the user navigates away.
  //
  // This eliminates ROOT CAUSE 2: the 200-600ms getUserMedia() re-acquisition
  // delay on mobile that was swallowing the user's first syllables.
  //
  var _mediaRec    = null;
  var _audioChunks = [];
  var _stream      = null;     // persisted across recordings
  var _streamBusy  = false;    // true while WakeManager owns the stream

  function _whisperURL() {
    return window.location.origin + '/api/stt/inference';
  }

  // Open the mic stream once and keep it alive so start-of-recording has
  // zero getUserMedia latency. Called when the chatbot page initialises.
  async function _prewarmMic() {
    if (_stream) return;   // already armed
    try {
      _stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      try { console.info('[chatbot] mic pre-armed (stream ready for instant recording)'); } catch (e) {}
    } catch (e) {
      // Permission denied or no mic — OK, we'll try again on first button press
      _stream = null;
    }
  }

  // Release the stream completely (called on page hide / cleanup).
  function _releaseMic() {
    if (_stream) {
      try { _stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
      _stream = null;
    }
  }

  async function toggleMic() {
    var btn = $('chat-mic-btn');
    if (!btn) return;

    if (!recording) {
      // ── START recording ──────────────────────────────────────────────
      (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CHAT','mic.start');
      stopSpeaking();

      // Suspend the always-on wake listener so we get exclusive mic access
      // on single-mic devices (phone, Jetson). We do NOT release _stream yet
      // because we pre-armed it — we just pause the wake listener's processing.
      _streamBusy = true;
      try { if (window.WakeManager) WakeManager.suspend(); } catch (e) {}

      // Ensure we have a live mic stream. The pre-warmed stream is reused
      // directly (zero getUserMedia latency). If it died (page was hidden,
      // browser GC'd it, etc.) we fall back to a fresh getUserMedia call.
      if (!_stream || _stream.getTracks().some(function (t) { return t.readyState === 'ended'; })) {
        try {
          _stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
          });
          try { console.info('[chatbot] mic re-opened (pre-warm stream was stale)'); } catch (e) {}
        } catch (e) {
          _streamBusy = false;
          try { if (window.WakeManager) WakeManager.resume(); } catch (e2) {}
          toast('Microphone access denied', 'error');
          return;
        }
      }

      _audioChunks = [];
      var mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';

      try {
        _mediaRec = new MediaRecorder(_stream, { mimeType: mimeType });
      } catch (e) {
        _mediaRec = new MediaRecorder(_stream);
      }

      _mediaRec.ondataavailable = function (ev) {
        if (ev.data && ev.data.size > 0) _audioChunks.push(ev.data);
      };

      // timeslice=100ms — short enough that we never lose more than 100ms
      // of audio on stop, but not so short it floods the browser with events.
      _mediaRec.start(100);
      recording = true;
      btn.classList.add('recording');
      btn.setAttribute('aria-label', 'Stop voice input');
      toast('🎤 Listening…', 'info');

    } else {
      // ── STOP recording & transcribe ──────────────────────────────────
      recording = false;
      btn.classList.remove('recording');
      btn.setAttribute('aria-label', 'Start voice input');
      btn.disabled = true;

      // ── ROOT CAUSE 1 FIX ─────────────────────────────────────────────
      // requestData() forces the codec to flush the current chunk into
      // ondataavailable BEFORE we call stop(). Without this, the last
      // 100-250ms of audio can be in the codec's internal buffer and is
      // silently discarded when stop() terminates the encoder.
      try { if (_mediaRec && _mediaRec.state === 'recording') _mediaRec.requestData(); } catch (e) {}

      // ── ROOT CAUSE 1 FIX (continued) ────────────────────────────────
      // DO NOT call _stream.getTracks().stop() here.
      // The stream must stay alive until AFTER the codec has fully finalised
      // the WebM container — that happens asynchronously inside onstop.
      // Killing the stream here produces a truncated/invalid WebM that ffmpeg
      // either can't decode or decodes with the last chunk missing.
      _mediaRec.stop();

      _mediaRec.onstop = async function () {
        // NOW it is safe to release the stream — codec has fully flushed.
        // We keep the stream alive for re-use (pre-armed architecture), so
        // we only stop tracks here if they are no longer valid.
        _streamBusy = false;
        // The WakeManager gets the mic back. With the pre-armed architecture
        // we do NOT release _stream — we keep it for the next recording.
        try { if (window.WakeManager) WakeManager.resume(); } catch (e) {}

        btn.disabled = false;

        if (_audioChunks.length === 0) {
          try { console.warn('[chatbot] no audio chunks captured — MediaRecorder produced nothing'); } catch (e) {}
          toast('No audio captured', 'warning');
          return;
        }

        var mime = (_mediaRec && _mediaRec.mimeType) ? _mediaRec.mimeType : 'audio/webm';
        var blob = new Blob(_audioChunks, { type: mime });
        _audioChunks = [];
        try {
          console.info('[chatbot] captured ' + blob.size + ' bytes (' + mime + ') → POST /api/stt/inference');
        } catch (e) {}

        if (blob.size < 2000) {
          // Blob is suspiciously small — MediaRecorder likely started but
          // the user released the button before a full chunk was written.
          // Don't waste a round-trip to Whisper.
          try { console.warn('[chatbot] blob too small (' + blob.size + 'B) — skipping inference'); } catch (e) {}
          (window.NexusDebug&&NexusDebug.log)&&NexusDebug.log('CHAT','mic.tooSmall',{bytes:blob.size});
          toast('Recording too short — hold the button while speaking', 'warning');
          return;
        }

        // Send to Whisper /inference via Flask proxy
        try {
          var form = new FormData();
          form.append('file', blob, 'recording.webm');
          form.append('response_format', 'json');

          // Language hint: stored setting > UI language > let Whisper auto-detect
          var _lang = '';
          try { _lang = (localStorage.getItem('nexus_stt_lang') || '').trim(); } catch (e) {}
          if (!_lang) {
            try { _lang = (window.I18N && I18N.getLang && I18N.getLang()) || ''; } catch (e) {}
          }
          if (_lang && _lang !== 'auto') form.append('language', _lang);

          var _sttEnd = (window.NexusDebug&&NexusDebug.time) ? NexusDebug.time('CHAT','stt',{bytes:blob.size}) : null;
          var resp = await fetch(_whisperURL(), { method: 'POST', body: form });
          if (!resp.ok) throw new Error('Whisper HTTP ' + resp.status);
          var json = await resp.json();
          var text = (json.text || json.transcription || '').trim();
          if (_sttEnd) _sttEnd({text:text.slice(0,40)});

          try { console.info('[chatbot] whisper text: ' + JSON.stringify(text)); } catch (e) {}

          // Filter hallucination artefacts whisper.cpp produces on silence
          var blanks = /^\[.*\]$|^\.+$|^(\s*(thank you|thanks)\.?\s*)$/i;
          if (!text || text === '[BLANK_AUDIO]' || blanks.test(text) || text.length < 2) {
            toast('Could not hear you — please try again', 'warning');
            return;
          }

          var ta = $('chat-input');
          if (ta) { ta.value = text; resizeChatInput(); ta.focus(); }
          toast('✅ Transcribed', 'success');
          // Brief pause so the user can see the transcription before it sends
          setTimeout(sendMessage, 500);

        } catch (e) {
          try { console.error('[chatbot] STT error:', e); } catch (ex) {}
          toast('Whisper error: ' + (e.message || e), 'error');
        }
      };
    }
  }


  async function checkHealth() {
    var dot = $('chatbot-status-dot');
    try {
      await API.health();
      if (dot) dot.className = 'status-dot online';
    } catch (e) {
      if (dot) dot.className = 'status-dot offline';
      toast('LLM server offline', 'warning');
      var mic = $('chat-mic-btn');
      if (mic) mic.disabled = true;
    }
  }

  function wire() {
    var send = $('chat-send-btn');
    if (send) send.addEventListener('click', sendMessage);

    var ta = $('chat-input');
    if (ta) {
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
      });
      ta.addEventListener('input', resizeChatInput);
    }

    var clear = $('chat-clear-btn');
    if (clear) clear.addEventListener('click', clearConversation);

    var mic = $('chat-mic-btn');
    if (mic) mic.addEventListener('click', toggleMic);

    var stopBtn = $('chat-stop-btn');
    if (stopBtn) stopBtn.addEventListener('click', stopSpeaking);
    // Show the Stop button while ARIA speaks, and activate barge-in monitor.
    if (window.VoiceManager && VoiceManager.onChange) {
      VoiceManager.onChange(function (speaking) {
        var b = $('chat-stop-btn');
        if (b) b.classList.toggle('hidden', !speaking);
        // Auto barge-in: monitor user's mic while ARIA talks
        if (speaking) { startBargeMonitor(); }
        else { stopBargeMonitor(); }
      });
    }
  }

  function init() {
    if (initialized) { return; }
    initialized = true;
    wire();
    checkHealth();
    updateContextCounter(0, contextMax);
    if (conversationHistory.length === 0) {
      appendBubble('aria', 'Hello! I am ARIA. How can I assist you today?');
    }
    // Pre-arm the microphone stream so the first button press has zero
    // getUserMedia() latency. Fire-and-forget — never blocks the UI.
    _prewarmMic();
  }

  window.ChatbotPage = { init: init, releaseMic: _releaseMic };
})();
