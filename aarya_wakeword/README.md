# Aarya Wake Word — كاشف كلمة التنبيه "AARYA"

موديل صغير (14KB) مُدرّب بـ **openWakeWord** يكشف كلمة التنبيه **"AARYA"** (تُلفظ AR-ee-ah) من المايك في الوقت الحقيقي.

A tiny (14KB) custom **openWakeWord** model that detects the wake word **"AARYA"** (pronounced AR-ee-ah) from the microphone in real time.

---

## 📦 محتويات الحزمة / Package contents

| File | الوصف / Description |
|------|---------------------|
| `aarya.onnx` | الموديل المُدرّب / the trained model (the only file you really need) |
| `aarya_wakeword.py` | سكربت الاستماع الحي بالمايك / live microphone detector |
| `test_model.py` | فحص سريع للموديل بدون مايك / quick model sanity check (no mic) |
| `requirements.txt` | المكتبات المطلوبة / Python dependencies |
| `setup.sh` | تثبيت تلقائي / automated setup |
| `README.md` | هذا الملف / this file |

---

## ⚙️ المتطلبات / Requirements

- Python 3.9+ (تم اختباره على 3.12 / tested on 3.12)
- مايكروفون / a microphone
- نظام لينكس/ويندوز/ماك / Linux, Windows, or macOS
- إنترنت **مرة وحدة فقط** لتنزيل ملفات المعالجة / internet **once** to download the preprocessing models

---

## 🚀 التثبيت السريع / Quick install

### الطريقة الأوتوماتيكية (لينكس/ماك) / Automated (Linux/macOS)
```bash
chmod +x setup.sh
./setup.sh
```

### الطريقة اليدوية / Manual
```bash
# 1) أنشئ بيئة افتراضية (اختياري لكن مفضّل) / create a virtual env (recommended)
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2) ثبّت المكتبات / install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 3) نزّل ملفات المعالجة مرة وحدة / download preprocessing models once
python3 -c "import openwakeword.utils; openwakeword.utils.download_models()"
```

> **لينكس / Linux:** لو طلع خطأ PortAudio وقت التشغيل، ثبّت مكتبة النظام:
> ```bash
> sudo apt install -y libportaudio2      # Debian / Ubuntu / Kubuntu
> sudo dnf install -y portaudio           # Fedora / RHEL
> ```

---

## ▶️ التشغيل / Run

### 1) فحص الموديل (بدون مايك) / test the model (no mic)
```bash
python3 test_model.py
```
المتوقع / expected:
```
exists: True | size: 14.1 KB
inputs : [('x', [1, 16, 96])]
outputs: [('sigmoid', [1, 1])]
dummy output: [...] -> model runs OK
```

### 2) الكشف الحي بالمايك / live microphone detection
```bash
python3 aarya_wakeword.py
```
قُل **"AARYA"** — راح يطلع شريط بالدرجة، ولما تتجاوز العتبة يطبع كشف.
Say **"AARYA"** — you'll see a live score bar, and a detection message when it crosses the threshold.

---

## 🎚️ الضبط / Tuning

عدّل الثوابت بأعلى `aarya_wakeword.py`:
Edit the constants at the top of `aarya_wakeword.py`:

| الإعداد / Setting | الافتراضي / Default | الوصف / Description |
|---|---|---|
| `THRESHOLD` | `0.1` | عتبة الكشف. أقل = أحسّاس (كشف أسهل لكن إنذارات كاذبة أكثر) / detection threshold. lower = more sensitive |
| `COOLDOWN` | `1.5` | ثواني تجاهل بعد كل كشف (يمنع التكرار) / seconds to ignore after a hit |

**نصيحة / Tip:** لو صار كشف خاطئ كثير، ارفع `THRESHOLD` لـ`0.3`–`0.5`. لو ما يكشف بسهولة، قلّلها.
If you get false positives, raise `THRESHOLD` to `0.3`–`0.5`. If it misses, lower it.

---

## 🔌 الدمج بمشروعك / Integrate into your project

افتح `aarya_wakeword.py` وحُط الكود حقك داخل الدالة `on_wakeword()`:
Open `aarya_wakeword.py` and put your code inside `on_wakeword()`:

```python
def on_wakeword(score):
    # مثال: شغّل أمر / example: run a command
    import os
    os.system("notify-send 'Aarya' 'wake word detected'")
    # أو: ابدأ مساعد صوتي، شغّل تسجيل، أرسل إشارة، إلخ.
```

أو استورد الموديل مباشرة بأي كود بايثون / or use the model directly in any Python code:
```python
import numpy as np
from openwakeword.model import Model

oww = Model(wakeword_models=["aarya.onnx"], inference_framework="onnx")
# audio = numpy int16 array @ 16kHz, ~1280 samples (80ms) per chunk
score = oww.predict(audio)["aarya"]
if score > 0.1:
    print("detected!")
```

---

## 📴 التشغيل بدون إنترنت / Offline use

ملفات المعالجة (`melspectrogram.onnx`, `embedding_model.onnx`) تنزّل مرة وحدة وتنحفظ داخل مكتبة openwakeword. مكانها:
The preprocessing models download once and live inside the openwakeword package. Find them with:
```bash
python3 -c "import openwakeword, os; print(os.path.join(os.path.dirname(openwakeword.__file__),'resources','models'))"
```
انسخهم بجنب `aarya.onnx` لو تريد حزمة مستقلة تماماً.
Copy them next to `aarya.onnx` for a fully self-contained bundle.

---

## 🧠 عن الموديل / About the model

- **النوع / Type:** شبكة عصبية عميقة صغيرة (DNN) لتصنيف الصوت — **مو نموذج لغوي (LLM)** / a small Deep Neural Network audio classifier — **not an LLM**.
- **المدخل / Input:** ميزات صوت `[1, 16, 96]` (16 إطار × 96 ميزة) / audio features.
- **المخرج / Output:** احتمال واحد عبر sigmoid `[1, 1]` (0..1) / a single sigmoid probability.
- **التدريب / Training:** openWakeWord، نوع `dnn`، 50,000 خطوة على GPU / openWakeWord, `dnn`, 50k steps on GPU.
- **مقاييس / Metrics:** Accuracy ≈ 0.74 · Recall ≈ 0.48 · False positives/hour ≈ 0.18.

السلسلة الكاملة / Full pipeline:
```
mic audio (16kHz) -> melspectrogram -> embeddings (pretrained) -> aarya DNN -> sigmoid -> probability
```

---

## 🛠️ حل المشاكل / Troubleshooting

| المشكلة / Problem | الحل / Fix |
|---|---|
| `Invalid sample rate [-9997]` | السكربت يعالجها تلقائياً (يلتقط بتردد المايك الأصلي ويحوّل لـ16kHz) / handled automatically by the script |
| `PortAudioError` / no PortAudio | `sudo apt install -y libportaudio2` (أو `dnf install portaudio`) |
| ما يلقى مايك / no input device | `python3 -c "import sounddevice as sd; print(sd.query_devices())"` لاختيار الجهاز |
| كشف خاطئ كثير / too many false hits | ارفع `THRESHOLD` / raise `THRESHOLD` |
| ما يكشف / misses the word | قلّل `THRESHOLD` / lower `THRESHOLD` |

---

*Wake word: "AARYA" (AR-ee-ah) · Model: aarya.onnx · Built with openWakeWord.*
