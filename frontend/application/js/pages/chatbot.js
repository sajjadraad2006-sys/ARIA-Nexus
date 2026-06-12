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

    try {
      var data = await (API.assistantCommand ? API.assistantCommand(text, conversationHistory) : API.chat(text, conversationHistory));
      isThinking = false;
      if (thinking) thinking.classList.add('hidden');
      var reply = (data && data.response) ? data.response : '(empty response)';
      appendBubble('aria', reply);
      conversationHistory.push({ role: 'assistant', content: reply });
      speakReply(reply);
      if (data) updateContextCounter(data.context_used, data.context_max);
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
  var _mediaRec  = null;
  var _audioChunks = [];
  var _stream    = null;

  function _whisperURL() {
    // Use Flask HTTPS proxy → no mixed-content issue
    return window.location.origin + '/api/stt/inference';
  }

  async function toggleMic() {
    var btn = $('chat-mic-btn');
    if (!btn) return;

    if (!recording) {
      // ── START recording ─────────────────────────────────
      stopSpeaking();
      try {
        _stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        toast('Microphone access denied', 'error');
        return;
      }
      _audioChunks = [];
      var mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      _mediaRec = new MediaRecorder(_stream, { mimeType: mimeType });
      _mediaRec.ondataavailable = function (e) {
        if (e.data && e.data.size > 0) _audioChunks.push(e.data);
      };
      _mediaRec.start(250); // collect chunks every 250ms
      recording = true;
      btn.classList.add('recording');
      btn.setAttribute('aria-label', 'Stop voice input');
      toast('🎤 Listening…', 'info');

    } else {
      // ── STOP recording & transcribe ──────────────────────
      recording = false;
      btn.classList.remove('recording');
      btn.setAttribute('aria-label', 'Start voice input');
      btn.disabled = true;

      // Stop media tracks
      if (_stream) { _stream.getTracks().forEach(function (t) { t.stop(); }); _stream = null; }

      _mediaRec.stop();
      _mediaRec.onstop = async function () {
        btn.disabled = false;
        if (_audioChunks.length === 0) { toast('No audio captured', 'warning'); return; }
        var blob = new Blob(_audioChunks, { type: _mediaRec.mimeType || 'audio/webm' });
        _audioChunks = [];

        // Send to Whisper /inference
        try {
          var form = new FormData();
          form.append('file', blob, 'recording.webm');
          form.append('response_format', 'json');
          // language hint: detect Arabic from previous messages or leave blank for auto
          var resp = await fetch(_whisperURL(), { method: 'POST', body: form });
          if (!resp.ok) throw new Error('Whisper HTTP ' + resp.status);
          var json = await resp.json();
          var text = (json.text || json.transcription || '').trim();
          if (!text || text === '[BLANK_AUDIO]' || text.length < 2) {
            toast('Could not hear you — please try again', 'warning');
            return;
          }
          var ta = $('chat-input');
          if (ta) { ta.value = text; resizeChatInput(); ta.focus(); }
          toast('✅ Transcribed', 'success');
          // Auto-send after 600ms
          setTimeout(sendMessage, 600);
        } catch (e) {
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
    // Show the Stop button only while ARIA is actually speaking.
    if (window.VoiceManager && VoiceManager.onChange) {
      VoiceManager.onChange(function (speaking) {
        var b = $('chat-stop-btn');
        if (b) b.classList.toggle('hidden', !speaking);
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
  }

  window.ChatbotPage = { init: init };
})();
