/* =====================================================================
   ARIA NEXUS — i18n.js   (window.I18N)
   ---------------------------------------------------------------------
   Lightweight, dependency-free localization for the whole UI.

   • Two languages: English ('en') and Arabic ('ar').
   • Picking a language instantly:
       - swaps every translatable string,
       - flips the document between LTR and RTL (dir/lang on <html>),
       - and broadcasts a 'nexus:langchange' event so dynamic pages can
         re-render their own strings.
   • Choice is remembered in localStorage ('nexus_lang').

   Markup usage (declarative — no JS needed per element):
       <span data-i18n="nav.launcher">Launcher</span>
       <input data-i18n-ph="search.placeholder">
       <button data-i18n-aria="settings.title" data-i18n-title="settings.title">

   Programmatic usage (for JS-rendered content):
       I18N.t('nav.launcher')         -> localized string
       I18N.setLang('ar')             -> switch language
       I18N.getLang()                 -> 'en' | 'ar'
       document.addEventListener('nexus:langchange', fn)
   ===================================================================== */
(function () {
  'use strict';

  var DICT = {
    en: {
      /* splash */
      'splash.tagline': 'Unified Command Center',
      'splash.enter': 'ENTER FULL EXPERIENCE',
      'splash.hint': 'Click to activate fullscreen mode',
      /* navigation */
      'nav.launcher': 'Launcher',
      'nav.chatbot': 'Chatbot',
      'nav.face': 'Robot Face',
      'nav.iot': 'IoT',
      'nav.assistant': 'Assistant',
      'nav.monitor': 'Monitor',
      'nav.tts': 'TTS',
      'nav.knowledge': 'Knowledge',
      'nav.exporter': 'Exporter',
      /* launcher overview */
      'page.launcher.title': 'Command Center',
      'page.launcher.subtitle': 'Select a module to begin',
      'ov.servicesOnline': 'Services online',
      'ov.knowledgeDocs': 'Knowledge docs',
      'ov.iotDevices': 'IoT devices',
      'ov.ttsVoices': 'TTS voices',
      'ov.systemVitals': 'System Vitals',
      'ov.serviceHealth': 'Service Health',
      'ov.connecting': 'Connecting\u2026',
      /* page titles */
      'page.chatbot.title': 'ARIA Chatbot',
      'page.face.title': 'Robot Face',
      'page.iot.title': 'IoT Control',
      'page.iot.subtitle': '3 connection modes',
      'page.monitor.title': 'System Monitor',
      'page.tts.title': 'TTS Studio',
      'page.knowledge.title': 'Knowledge Base',
      'page.assistant.title': 'Assistant',
      'page.exporter.title': 'System Exporter',
      'page.exporter.subtitle': 'Export or import full ARIA configuration',
      /* settings shell */
      'settings.title': 'Customize',
      'settings.reset': 'Reset to defaults',
      'tab.appearance': 'Appearance',
      'tab.mic': 'Mic & Wake',
      'tab.voice': 'Voice',
      'tab.assistant': 'Assistant',
      'tab.sound': 'Sound',
      /* settings — appearance */
      'set.accentTheme': 'Accent theme',
      'set.accentHue': 'Custom accent hue',
      'set.glassBlur': 'Glass blur',
      'set.uiScale': 'Interface scale',
      'set.ambientGlow': 'Ambient glow',
      'set.gridOverlay': 'Grid overlay',
      'set.filmGrain': 'Film grain',
      'set.reduceMotion': 'Reduce motion',
      'set.language': 'Language',
      'set.langHint': 'Switches the whole interface and text direction (LTR / RTL).',
      'opt.lang.en': 'English',
      'opt.lang.ar': 'Arabic · العربية',
      /* settings — mic & wake */
      'set.wakeWord': 'Wake word',
      'set.wakeHint': 'Say “aria” to open the assistant. The mic runs quietly in the background and shows nothing until it hears the word.',
      'set.alwaysOn': 'Always-on wake word',
      'set.wakeSource': 'Wake source',
      'set.deviceMode': 'Device mode',
      'set.micDeviceTitle': 'Microphone device',
      'set.thisDeviceMic': 'This device mic',
      'set.jetsonInput': 'Jetson input',
      'set.micHint': 'If it can\u2019t hear you, pick the right microphone here.',
      'set.sensitivity': 'Sensitivity',
      'set.sensitivityHint': 'Higher = wakes faster (but more false triggers).',
      'set.confirmChime': 'Confirmation chime',
      'set.listeningDot': 'Show listening dot',
      'set.wakeOpens': 'Wake opens',
      'set.deviceModeStreamHint': 'Streams the mic to the Jetson so openWakeWord runs locally — works with no internet (same network).',
      'set.deviceModeSpeechHint': 'Uses the browser speech engine — needs internet.',
      'opt.source.device': 'This device',
      'opt.source.jetson': 'Jetson mic',
      'opt.mode.stream': 'Stream to Jetson · offline (LAN)',
      'opt.mode.speech': 'Browser speech · needs internet',
      'opt.wakeui.call': 'Assistant call',
      'opt.wakeui.face': 'Robot face',
      'opt.default': 'Default',
      'opt.systemDefault': 'System default',
      'opt.jetsonUnreachable': 'Jetson not reachable',
      /* settings — voice */
      'set.tts': 'Text-to-speech',
      'set.speakReplies': 'Speak chatbot replies',
      'set.arabicVoice': 'Arabic voice',
      'set.englishVoice': 'English voice',
      'set.voiceHint': 'Picks the voice automatically based on the reply language (Arabic / English).',
      /* settings — assistant / llm */
      'set.modelBehaviour': 'Model behaviour',
      'set.temperature': 'Temperature',
      'set.tempHint': 'Low = precise and consistent, high = creative and varied.',
      'set.topP': 'Top-p',
      'set.maxReply': 'Max reply length',
      'set.maxReplyHint': '0 = unlimited (the model decides).',
      /* settings — sound */
      'set.soundVolume': 'Sound volume',
      'set.soundEffects': 'Sound effects',
      'set.hoverSounds': 'Hover sounds',
      'set.ambientMusic': 'Ambient music'
    },
    ar: {
      /* splash */
      'splash.tagline': 'مركز التحكم الموحّد',
      'splash.enter': 'ادخل التجربة الكاملة',
      'splash.hint': 'اضغط لتفعيل وضع ملء الشاشة',
      /* navigation */
      'nav.launcher': 'الرئيسية',
      'nav.chatbot': 'المحادثة',
      'nav.face': 'وجه الروبوت',
      'nav.iot': 'الأجهزة',
      'nav.assistant': 'المساعد',
      'nav.monitor': 'المراقبة',
      'nav.tts': 'النطق',
      'nav.knowledge': 'المعرفة',
      'nav.exporter': 'التصدير',
      /* launcher overview */
      'page.launcher.title': 'مركز التحكم',
      'page.launcher.subtitle': 'اختر وحدة للبدء',
      'ov.servicesOnline': 'الخدمات المتصلة',
      'ov.knowledgeDocs': 'مستندات المعرفة',
      'ov.iotDevices': 'أجهزة IoT',
      'ov.ttsVoices': 'أصوات النطق',
      'ov.systemVitals': 'حالة النظام',
      'ov.serviceHealth': 'صحة الخدمات',
      'ov.connecting': 'جارٍ الاتصال…',
      /* page titles */
      'page.chatbot.title': 'محادثة ARIA',
      'page.face.title': 'وجه الروبوت',
      'page.iot.title': 'تحكم الأجهزة',
      'page.iot.subtitle': '3 أوضاع اتصال',
      'page.monitor.title': 'مراقبة النظام',
      'page.tts.title': 'استوديو النطق',
      'page.knowledge.title': 'قاعدة المعرفة',
      'page.assistant.title': 'المساعد',
      'page.exporter.title': 'مصدّر النظام',
      'page.exporter.subtitle': 'تصدير أو استيراد إعدادات ARIA الكاملة',
      /* settings shell */
      'settings.title': 'تخصيص',
      'settings.reset': 'إعادة الضبط الافتراضي',
      'tab.appearance': 'المظهر',
      'tab.mic': 'المايك',
      'tab.voice': 'الصوت',
      'tab.assistant': 'المساعد',
      'tab.sound': 'الأصوات',
      /* settings — appearance */
      'set.accentTheme': 'لون الواجهة',
      'set.accentHue': 'درجة اللون المخصصة',
      'set.glassBlur': 'ضبابية الزجاج',
      'set.uiScale': 'حجم الواجهة',
      'set.ambientGlow': 'توهّج محيط',
      'set.gridOverlay': 'شبكة خلفية',
      'set.filmGrain': 'حبيبات الفيلم',
      'set.reduceMotion': 'تقليل الحركة',
      'set.language': 'اللغة',
      'set.langHint': 'يغيّر الواجهة بالكامل واتجاه النص (يسار/يمين).',
      'opt.lang.en': 'English · الإنكليزية',
      'opt.lang.ar': 'العربية',
      /* settings — mic & wake */
      'set.wakeWord': 'كلمة الإيقاظ',
      'set.wakeHint': 'قل “aria” لفتح المساعد. المايك يشتغل بالخلفية وما يبين شي حتى يسمع الكلمة.',
      'set.alwaysOn': 'السماع الدائم',
      'set.wakeSource': 'مصدر المايك',
      'set.deviceMode': 'وضع الجهاز',
      'set.micDeviceTitle': 'جهاز المايك',
      'set.thisDeviceMic': 'مايك المتصفح',
      'set.jetsonInput': 'مدخل جاستن',
      'set.micHint': 'إذا ما يلتقط الصوت، اختر جهاز المايك الصحيح من القائمة.',
      'set.sensitivity': 'الحساسية',
      'set.sensitivityHint': 'أعلى = يلتقط أسرع (لكن احتمال إطلاق خاطئ أكثر).',
      'set.confirmChime': 'صوت تأكيد',
      'set.listeningDot': 'نقطة الاستماع',
      'set.wakeOpens': 'عند المناداة',
      'set.deviceModeStreamHint': 'يرسل صوت المايك إلى جاستن ليشتغل openWakeWord محلياً — يشتغل بدون انترنت (على نفس الشبكة).',
      'set.deviceModeSpeechHint': 'يستخدم تعرف المتصفح على الكلام — يحتاج انترنت.',
      'opt.source.device': 'هذا الجهاز',
      'opt.source.jetson': 'مايك جاستن',
      'opt.mode.stream': 'إرسال إلى جاستن · أوفلاين (LAN)',
      'opt.mode.speech': 'تعرف المتصفح · يحتاج نت',
      'opt.wakeui.call': 'قائمة المساعد',
      'opt.wakeui.face': 'وجه الروبوت',
      'opt.default': 'افتراضي',
      'opt.systemDefault': 'افتراضي النظام',
      'opt.jetsonUnreachable': 'جاستن غير متصل',
      /* settings — voice */
      'set.tts': 'النطق (تحويل النص لصوت)',
      'set.speakReplies': 'نطق ردود الشات',
      'set.arabicVoice': 'الصوت العربي',
      'set.englishVoice': 'الصوت الإنكليزي',
      'set.voiceHint': 'يختار الصوت تلقائياً حسب لغة الرد (عربي/إنكليزي).',
      /* settings — assistant / llm */
      'set.modelBehaviour': 'سلوك النموذج',
      'set.temperature': 'العشوائية (Temperature)',
      'set.tempHint': 'واطئ = إجابات دقيقة وثابتة، عالي = إبداعية ومتنوعة.',
      'set.topP': 'تنوع الكلمات (Top-p)',
      'set.maxReply': 'أقصى طول للرد',
      'set.maxReplyHint': '0 = بدون حد (النموذج يقرر).',
      /* settings — sound */
      'set.soundVolume': 'مستوى الصوت',
      'set.soundEffects': 'مؤثرات صوتية',
      'set.hoverSounds': 'أصوات التمرير',
      'set.ambientMusic': 'موسيقى خلفية'
    }
  };

  var lang = 'en';
  try { lang = localStorage.getItem('nexus_lang') || 'en'; } catch (e) {}
  if (lang !== 'ar') lang = 'en';

  function t(key, fallback) {
    var d = DICT[lang] || DICT.en;
    if (d && d[key] != null) return d[key];
    if (DICT.en[key] != null) return DICT.en[key];
    return (fallback != null) ? fallback : key;
  }

  function translateEl(el) {
    var k = el.getAttribute('data-i18n');
    if (k) el.textContent = t(k);
    var ph = el.getAttribute('data-i18n-ph');
    if (ph) el.setAttribute('placeholder', t(ph));
    var ti = el.getAttribute('data-i18n-title');
    if (ti) el.setAttribute('title', t(ti));
    var ar = el.getAttribute('data-i18n-aria');
    if (ar) el.setAttribute('aria-label', t(ar));
  }

  function apply(root) {
    var scope = root || document;
    var nodes = scope.querySelectorAll(
      '[data-i18n],[data-i18n-ph],[data-i18n-title],[data-i18n-aria]'
    );
    for (var i = 0; i < nodes.length; i++) translateEl(nodes[i]);
  }

  function applyDir() {
    var html = document.documentElement;
    html.setAttribute('lang', lang);
    html.setAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
  }

  function setLang(l) {
    l = (l === 'ar') ? 'ar' : 'en';
    if (l === lang) { applyDir(); apply(document); return; }
    lang = l;
    try { localStorage.setItem('nexus_lang', l); } catch (e) {}
    applyDir();
    apply(document);
    try {
      document.dispatchEvent(new CustomEvent('nexus:langchange', { detail: { lang: l } }));
    } catch (e) {
      var ev = document.createEvent('CustomEvent');
      ev.initCustomEvent('nexus:langchange', false, false, { lang: l });
      document.dispatchEvent(ev);
    }
  }

  function getLang() { return lang; }

  /* Set direction immediately (before paint) to avoid an LTR→RTL flash. */
  applyDir();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { apply(document); });
  } else {
    apply(document);
  }

  window.I18N = { t: t, apply: apply, setLang: setLang, getLang: getLang };
})();
