#!/usr/bin/env python3
"""
fix_onnx_model.py — يدمج ملف aarya.onnx.data في aarya.onnx ليصبح ملفاً واحداً.

المشكلة: aarya.onnx مُصدَّر بـ "external data" فيحتاج ملف aarya.onnx.data
الحل:    نُعيد كتابته بـ save_as_external_data=False (كل الـ weights مضمّنة)

تشغيل:
    cd /home/mecha/Desktop/مسابقة\ وطنية/ARIA_NEXUS_FULL
    source backend/venv/bin/activate
    python3 aarya_wakeword/fix_onnx_model.py
"""
import os
import shutil
import sys

try:
    import onnx
except ImportError:
    print("❌ onnx not installed. Run: pip install onnx")
    sys.exit(1)

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH   = os.path.join(SCRIPT_DIR, "aarya.onnx")
BACKUP_PATH  = os.path.join(SCRIPT_DIR, "aarya.onnx.bak")

print(f"Model : {MODEL_PATH}")
print(f"Size  : {os.path.getsize(MODEL_PATH) / 1024:.1f} KB")

# ── Check if .data file already exists alongside the model ──────────────────
data_path = MODEL_PATH + ".data"
if not os.path.exists(data_path):
    # Maybe the model is already self-contained — try loading it directly
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
        print("✅ Model loads fine without external data — nothing to fix!")
        sys.exit(0)
    except Exception as e:
        print(f"⚠️  Model fails to load: {e}")
        print("    The .data file is missing and cannot be regenerated without the original weights.")
        print("    You need to retrain or re-export the model.")
        sys.exit(1)

print(f"\nFound external data file: {data_path}")
print(f"Data  : {os.path.getsize(data_path) / 1024:.1f} KB")
print("\nMerging external data into a single self-contained ONNX file…")

# Backup original
shutil.copy2(MODEL_PATH, BACKUP_PATH)
print(f"Backed up original → {BACKUP_PATH}")

# Load model with external data (must be in the same directory)
os.chdir(SCRIPT_DIR)
model = onnx.load(MODEL_PATH, load_external_data=True)

# Save as a single file (no external data)
FIXED_PATH = MODEL_PATH + ".fixed"
onnx.save_model(
    model,
    FIXED_PATH,
    save_as_external_data=False,
)

# Replace original with the fixed version
os.replace(FIXED_PATH, MODEL_PATH)
print(f"\n✅ Done! New size: {os.path.getsize(MODEL_PATH) / 1024:.1f} KB")
print(f"   (external data file can now be deleted: {data_path})")

# Verify it loads correctly with onnxruntime
try:
    import onnxruntime as ort
    import numpy as np
    sess = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])
    inp  = sess.get_inputs()[0]
    shape = [d if isinstance(d, int) else 1 for d in inp.shape]
    dummy = np.random.rand(*shape).astype(np.float32)
    out   = sess.run(None, {inp.name: dummy})
    print(f"✅ Verified: model runs OK  →  output shape {np.array(out[0]).shape}")
except Exception as e:
    print(f"❌ Post-fix verification failed: {e}")
    # Restore backup
    shutil.copy2(BACKUP_PATH, MODEL_PATH)
    print("   Restored original from backup.")
    sys.exit(1)
