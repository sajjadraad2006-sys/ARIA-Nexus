# ARIA Nexus — Merged Build (أفضل نسخة مدموجة)

التاريخ: 2026-06-12

هاي النسخة تجمع أفضل ما بالنسختين:

## الأساس: ARIA_NEXUS_FIXED (1) — النسخة الثانية
انتُخبت كأساس لأنها تصلّح المسارات الحيّة الصحيحة (the live SPA path):
- **STT (المشكلة 5):** الإصلاح بداخل الـ blueprint الفعلي `nexus_routes_additions.py`
  (يمرّر `language` + `temperature` لـ whisper.cpp) — وهو الراوت اللي يفوز بالتوجيه.
- **IoT (المشكلة 6):** الإصلاح بداخل دماغ المساعد الحي `nexus_assistant.py`
  (حقن أجهزة Home Assistant الحيّة + رد صادق حسب النتيجة الفعلية).
- **RAG (المشكلة 1):** `hnsw:space=cosine` + مسح كاش الـ engine المشترك
  وضبط `_available=True` عند الإضافة.
- **Wake offline (المشكلة 2):** `wakelistener.js` يُظهر `available:false` بوضوح
  (نقطة حمرا + رسالة) بدل الفشل الصامت.
- قاعدة `chroma_db/` مبنية ومفهرسة مسبقاً وجاهزة.

## إصلاحات الواجهة المنقولة من النسخة الأولى (V1)
- `frontend/application/js/pages/face.js` — **محادثة مستمرة** بعد كلمة التنبيه:
  ARIA تظل تسمع دور-بعد-دور بدون إعادة قول "aria"، وتنتهي لو سكتّ
  (نص فارغ)، مع حد أقصى `MAX_TURNS = 12` لمنع الحلقة اللانهائية.
- `frontend/application/js/wake.js` — الميك **مطفي افتراضياً** (opt-in):
  يبقى مغلق عند الإقلاع، يُفعّل من زر الوجه/الإعدادات. لإرجاع always-on
  افتراضياً: عيّن `localStorage` `nexus_wake_enabled = '1'`.
- `frontend/application/js/mic.js` — صمت الـ VAD قبل الإيقاف التلقائي
  خُفّض من 1500ms إلى 900ms لتقليل تأخير الرد.

## مُلاحظة مهمة
- تم الإبقاء على `wakelistener.js` مال النسخة الثانية (فيه إصلاح إظهار
  حالة عدم التوفّر)، ولم تُؤخذ نسخة V1 منه لأنها تفتقر لهذا الإصلاح.

## خطوات ما بعد النشر على الجهاز (Jetson)
1. `cd backend && python -m ingest`  (إعادة بناء Chroma بمسافة cosine)
2. `pip install openwakeword sounddevice numpy` ثم تأكد `/api/wake/status` يرجّع `available_feed: true`
3. عيّن `HA_TOKEN` + `HA_URL`؛ تأكد `/api/states` يرجّع الأجهزة
4. (اختياري) نزّل `ggml-medium.bin` وعيّن `NEXUS_WHISPER_MODEL` و/أو `NEXUS_WHISPER_LANGUAGE=ar`
5. أعد تشغيل السيرفر وامسح كاش المتصفح (hard refresh)
