# ARIA NEXUS — "Could not hear you" deep root-cause fix

> Scope: why the assistant hears you **once and then goes deaf**, why it works
> *sometimes* and not others, and the exact code changes that fix it across
> the wake word, Robot Face, the call screen and the normal chatbot mic.

---

## TL;DR (English)

The microphone was almost always capturing audio. The problem was **before**
and **after** capture, not the mic itself — exactly the hunch you had
("it hears me but doesn't send to Whisper"). Four independent bugs stacked on
top of each other and all produced the same symptom: a blank Whisper result →
the `Could not hear you — please try again` toast → the voice loop ending.

1. **VAD calibration poisoning (primary, the "hears once then deaf" cause).**
   `mic.js` measured the room's noise floor from the **first ~300 ms** of the
   recording and set the speech threshold to `max(0.030, floor × 2.2)`. If you
   started talking immediately (which everyone does after the UI pops open),
   your own voice inflated that "noise floor", so the speech threshold was set
   *above your speaking volume*. The detector then **never** saw speech, never
   triggered the silence-stop, recorded the full 20 s of near-silence, and
   Whisper returned blank. Two blanks in a row end the call / face loop — so it
   felt like "it heard me once, then stopped hearing me." Whether it worked
   depended entirely on whether you paused before talking.

2. **AudioContext exhaustion.** Browsers allow only ~6 live `AudioContext`s per
   tab. `face.js` and `call.js` each created a **persistent** context that was
   never closed, `mic.js` made one **per capture**, and `wakelistener.js` made
   a **new context for every wake-word chime**. After a handful of turns the
   browser refused to create another context, every `createAnalyser()` threw,
   the analyser became `null`, VAD went dead, and again → blank → deaf.

3. **Microphone contention on the chatbot mic.** The always-on wake listener
   holds an open `getUserMedia` stream. When you pressed the normal chatbot
   mic, a *second* `getUserMedia` opened while the wake listener still owned
   the device. On single-capture devices (the Jetson) the second stream comes
   back **silent**, so the recording was empty → blank → "Could not hear you."

4. **Self-terminating loops.** `call.js` ends the conversation after 2 blank
   rounds and `face.js` ends after the first blank. With bugs 1–3 producing
   blanks, the loops shut themselves down after the first good turn.

---

## ما هي المشكلة؟ (بالعربي)

المايك كان **يسمعك فعلاً** بأغلب الأحيان. المشكلة لم تكن في المايك نفسه، بل في
ما يحدث **قبل** الإرسال و**بعده** — تماماً مثل ما توقعت: "يسمعني بس ما يرسل لل
Whisper". كانت هناك أربع مشاكل منفصلة تتراكم وكلها تنتج نفس العَرَض: نتيجة فارغة
من Whisper ← رسالة `Could not hear you — please try again` ← توقف دورة الصوت.

1. **تسميم معايرة الـ VAD (السبب الأساسي لـ «يسمعني مرة وحدة بس»).**
   كان `mic.js` يقيس مستوى ضجيج الغرفة من **أول ٣٠٠ مللي ثانية** من التسجيل
   ويضبط عتبة الكلام على `max(0.030, floor × 2.2)`. إذا بدأت الكلام مباشرة بعد
   ظهور الواجهة، صوتك نفسه يرفع قيمة «الضجيج»، فتُضبط العتبة **أعلى من صوتك**.
   عندها لا يكتشف الكلام أبداً، ولا يوقف التسجيل عند الصمت، فيسجل ٢٠ ثانية شبه
   صامتة وتُرجع Whisper نصاً فارغاً. فراغان متتاليان يُنهيان دورة المكالمة/الوجه
   — ولهذا تحس أنه «سمعني مرة ثم توقف». نجاحه كان يعتمد فقط على إن كنت سكتّ
   لحظة قبل أن تتكلم.

2. **استنفاد الـ AudioContext.** المتصفح يسمح بحوالي ٦ سياقات صوت فقط لكل تبويب.
   كان `face.js` و`call.js` ينشئان سياقاً **دائماً** لا يُغلق، و`mic.js` ينشئ
   واحداً **لكل تسجيل**، و`wakelistener.js` ينشئ سياقاً **جديداً لكل نغمة تنبيه**.
   بعد عدة محاولات يرفض المتصفح إنشاء سياق جديد، فيفشل `createAnalyser()`،
   ويصبح المحلل `null`، ويتعطل الـ VAD ← فراغ ← صمم.

3. **تنازع على المايك في شات بوت.** مستمع كلمة التنبيه يبقى ممسكاً بالمايك. عند
   ضغط مايك الشات العادي يُفتح طلب `getUserMedia` ثانٍ بينما المستمع ما زال
   يملك الجهاز. على الأجهزة ذات مايك واحد (Jetson) يرجع التيار الثاني **صامتاً**،
   فيكون التسجيل فارغاً ← «Could not hear you».

4. **دورات تُنهي نفسها.** `call.js` ينهي بعد فراغين و`face.js` بعد أول فراغ. مع
   المشاكل ١–٣ التي تُنتج فراغات، تُغلق الدورات نفسها بعد أول دور ناجح.

---

## What changed (file by file)

### `frontend/application/js/audiobus.js` *(new)*
A single shared audio bus, `window.NexusAudio`:
- `ctx()` — one lazily-created, auto-resumed `AudioContext` for the whole app.
- `analyser(stream)` — returns `{ analyser, source }` wired on the shared ctx.
- `available`, `resume()` — auto-resumes on first pointer/key interaction.
This removes the per-tab context ceiling problem (bug 2) at the source.

Loaded in `nexus_app.html` **before** `js/mic.js` so every later module can use it.

### `frontend/application/js/mic.js` *(VAD rewrite — bug 1)*
- Replaced the one-shot "mean of first 300 ms" calibration with an **adaptive
  running-minimum noise floor**: the floor snaps *down* to true silence and
  only creeps up very slowly, so talking early can no longer poison it.
- The speech threshold is now hard-clamped to `[startThreshold, maxThreshold]`
  (default `0.030 … 0.080`) so it can never rise above a normal speaking voice.
- VAD is active from the **first frame**; silence-stop is gated by a short warmup
  so it can't end before you start.
- Analyser is wired through `NexusAudio` (private-context fallback retained);
  teardown disconnects nodes and only closes a *private* context, never the
  shared one.
- Added `console.info('[mic] captured …')` diagnostics plus warnings when no
  chunks or no analyser are produced, so this class of bug is visible next time.

### `frontend/application/js/pages/chatbot.js` *(bug 3 + bug 2)*
- `toggleMic()` now calls `WakeManager.suspend()` **before** opening its own
  mic and `WakeManager.resume()` once the mic is released — no more two streams
  fighting over one device.
- Capture now requests `echoCancellation / noiseSuppression / autoGainControl`.
- Sends a **language hint** (`nexus_stt_lang` → UI language) to Whisper, matching
  `api.js`; far more reliable than auto-detect on the small model.
- Barge-in monitor routed through the shared `NexusAudio` context.
- Added capture-size and transcription diagnostics.

### `frontend/application/js/pages/call.js` & `pages/face.js` *(bug 2)*
- The persistent speaking-analyser context and the barge-in monitor now reuse
  the shared `NexusAudio` context instead of creating/leaking their own.

### `frontend/application/js/wakelistener.js` *(bug 2)*
- The wake **chime** reuses the shared context and disconnects its nodes
  instead of creating-then-closing a fresh context on every detection.
- The offline **stream** path reuses the shared context; `stopStream()` now only
  closes a *private* context and never the shared one (a `sCtxShared` flag
  guards this).

---

## Why this fixes every symptom you described

| Symptom | Cause | Fix |
|---|---|---|
| Hears me once, then deaf (Robot Face & call) | VAD poisoned → blank → loop ends after 1–2 blanks | Adaptive noise floor + clamp (bug 1); loops no longer fed blanks |
| Sometimes hears me, sometimes not | Depended on pausing before talking | VAD no longer depends on a clean calibration window |
| Normal chatbot mic also goes deaf | 2nd getUserMedia silent vs. wake listener | Wake suspend/resume around capture (bug 3) |
| Gets worse the longer the app is open | AudioContext leak hitting the ~6 ceiling | One shared context for the whole app (bug 2) |

---

## Verified
- `node --check` passes on: `audiobus.js`, `mic.js`, `wakelistener.js`,
  `pages/chatbot.js`, `pages/call.js`, `pages/face.js`.
- No shared context is ever closed by a screen teardown.
- Script load order: `api.js` → **`audiobus.js`** → `mic.js` → … (so
  `window.NexusAudio` exists before any consumer runs).

## How to confirm on the device
Open the browser console and watch for `[mic] captured <N> bytes` on each turn.
If you see a healthy byte count followed by a non-empty `[chatbot] whisper text`,
the full path is working. A `0`-byte capture or a missing analyser warning now
tells you exactly where to look instead of a generic "Could not hear you."
