╔══════════════════════════════════════════════════════════════════════╗
║             ARIA NEXUS — دليل ملفات الفحص والاختبارات               ║
║             ARIA NEXUS — Test & Benchmark Files Guide               ║
╚══════════════════════════════════════════════════════════════════════╝

التاريخ: 2026-06-11
المشروع: ARIA NEXUS Command Center
الموقع: backend/


══════════════════════════════════════════════════════════════════════
  ملفات الفحص الأساسية (Unit Tests)
══════════════════════════════════════════════════════════════════════

1. test_smoke.py
   ─────────────
   الهدف: فحص سريع للتأكد من سلامة البنية التحتية الأساسية
   يفحص:
     • إنشاء Flask App Factory
     • مسار /api/launcher/health يستجيب HTTP 200
     • مسار /api/config يرجع VAD + Wake word settings
     • إعدادات config.py (Whisper multilingual, Piper voices, VAD, Wake)
     • Piper TTS Pool يشتغل أو يتراجع بأمان
     • كشف النص العربي (_is_arabic_text)
   التشغيل: python test_smoke.py
   المدة: ~30 ثانية
   ✅ 6/6 PASS

2. test_wakeword.py
   ─────────────────
   الهدف: فحص سريع لتكامل wake word مع الـ backend
   يفحص:
     • وجود ملف aarya.onnx
     • تحميل الموديل بـ openWakeWord
     • توفر مكتبة sounddevice والأجهزة الصوتية
   التشغيل: python test_wakeword.py
   المدة: ~3 ثوانٍ
   ✅ PASS

3. test_model.py (في مجلد aarya_wakeword/)
   ─────────────────────────────────────────
   الهدف: فحص سلامة ملف ONNX مباشرة بدون openWakeWord
   يفحص:
     • وجود الملف وحجمه
     • تحميل بـ onnxruntime
     • أبعاد المدخلات والمخرجات
     • تشغيل inference وهمي
   التشغيل: cd aarya_wakeword && python test_model.py
   المدة: ~1 ثانية
   ✅ PASS


══════════════════════════════════════════════════════════════════════
  ملفات قياس الأداء (Benchmarks)
══════════════════════════════════════════════════════════════════════

4. test_benchmark.py  ← الملف الرئيسي الشامل
   ──────────────────
   الهدف: قياس أداء شامل لجميع مكونات ARIA NEXUS
   يقيس (بالثانية):
     • وقت استيراد كل مكتبة (config, flask, rag, piper, iot, onnx, numpy)
     • وقت تحميل config.py + التحقق من كل إعداد
     • وقت إنشاء Flask App Factory
     • سرعة استجابة المسارات (health, config, redirect) — 10 تكرارات
     • وقت تهيئة RAG Engine (embeddings + ChromaDB)
     • سرعة الاستعلام RAG (بارد + من الكاش) — 3 استعلامات
     • وقت تهيئة Piper TTS Pool
     • سرعة التوليد الصوتي (بارد + دافئ) — إنجليزي + عربي
     • تحميل موديل wake word + سرعة inference (100 تكرار)
     • سرعة كشف اللغة العربية (1000 × 5 نصوص)
     • تهيئة IoT Controller + فحص اتصال HA
     • تهيئة WakeWordListener + سرعة feed()
   الناتج: يطبع تقرير كامل + يحفظه في benchmark_results.txt
   التشغيل: python test_benchmark.py
   المدة: ~60-120 ثانية

5. test_rag_bench.py
   ──────────────────
   الهدف: قياس أداء محرك RAG بالتفصيل
   يقيس:
     • وقت تهيئة المحرك (embeddings + vector store)
     • سرعة استعلام بارد (5 استعلامات مختلفة)
     • سرعة استعلام من الكاش
     • نسبة التسريع (cache speedup)
     • 50 استعلام متتالي (1 بارد + 49 كاش)
   التشغيل: python test_rag_bench.py
   المدة: ~15-30 ثانية

6. test_tts_bench.py
   ──────────────────
   الهدف: قياس أداء Piper TTS بالتفصيل
   يقيس:
     • تهيئة PiperVoicePool
     • توليد صوتي لنصوص قصيرة/متوسطة/طويلة
     • مقارنة بين الصوت الإنجليزي والعربي
     • cold synthesis vs warm synthesis
     • overhead تبديل اللغات (EN↔AR)
     • حجم ملف WAV الناتج
     • إحصائيات Pool الداخلية
   التشغيل: python test_tts_bench.py
   المدة: ~30-60 ثانية

7. test_wakeword_bench.py
   ───────────────────────
   الهدف: قياس أداء wake word بعمق
   يقيس:
     • تحميل ONNX model (onnxruntime مباشر)
     • سرعة inference مباشر (1000 تكرار مع avg/min/max/P95)
     • throughput (frames/sec)
     • فحص real-time capability (<80ms per frame)
     • تحميل openWakeWord pipeline
     • سرعة predict() الكاملة (500 تكرار)
     • نسبة false positives مع ضوضاء عشوائية
     • سرعة nexus_wakeword feed() path (200 تكرار)
   التشغيل: python test_wakeword_bench.py
   المدة: ~15-30 ثانية


══════════════════════════════════════════════════════════════════════
  ملف إصلاح (Utility)
══════════════════════════════════════════════════════════════════════

8. fix_onnx_model.py (في مجلد aarya_wakeword/)
   ──────────────────────────────────────────────
   الهدف: دمج ملف aarya.onnx.data في aarya.onnx ليصبح ملفاً واحداً
   التشغيل: cd aarya_wakeword && python fix_onnx_model.py
   ✅ تم التنفيذ بنجاح — الموديل الآن 210KB ملف واحد


══════════════════════════════════════════════════════════════════════
  كيفية التشغيل
══════════════════════════════════════════════════════════════════════

  # الفحوصات السريعة (لا تحتاج خدمات شغالة):
  cd backend
  source venv/bin/activate
  python test_smoke.py
  python test_wakeword.py

  # البنشمارك الشامل (يحتاج وقت):
  python test_benchmark.py

  # بنشماركات مفصّلة:
  python test_rag_bench.py
  python test_tts_bench.py
  python test_wakeword_bench.py

  # النتائج تُحفظ في:
  benchmark_results.txt


══════════════════════════════════════════════════════════════════════
  الإصلاحات التي تمت
══════════════════════════════════════════════════════════════════════

  1. ✅ إضافة jsonify إلى Flask imports في server.py
     المشكلة: NameError: name 'jsonify' is not defined
     الحل: from flask import ..., jsonify

  2. ✅ دمج aarya.onnx.data في aarya.onnx
     المشكلة: aarya.onnx.data مفقود — الموديل external data format
     الحل: سكربت fix_onnx_model.py دمج الـ weights (14KB → 210KB)

  3. ✅ إضافة HA_TOKEN loading في run.bash
     المشكلة: IoT-WS Auth failed: Invalid access token
     الحل: run.bash يقرأ من .env + export HA_TOKEN للـ Flask

  4. ✅ تثبيت libportaudio2
     المشكلة: sounddevice error: PortAudio library not found
     الحل: sudo apt install -y libportaudio2
