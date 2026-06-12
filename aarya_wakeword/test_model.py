#!/usr/bin/env python3
"""Quick sanity check: confirm aarya.onnx loads and runs (no microphone needed)."""
import os
import numpy as np
import onnxruntime as ort

p = "aarya.onnx"
print("exists:", os.path.exists(p), "| size:", round(os.path.getsize(p) / 1024, 1), "KB")

sess = ort.InferenceSession(p, providers=["CPUExecutionProvider"])
print("inputs :", [(i.name, i.shape) for i in sess.get_inputs()])
print("outputs:", [(o.name, o.shape) for o in sess.get_outputs()])

shape = [d if isinstance(d, int) else 1 for d in sess.get_inputs()[0].shape]
x = np.random.rand(*shape).astype(np.float32)
y = sess.run(None, {sess.get_inputs()[0].name: x})
print("dummy output:", np.ravel(y[0])[:3], "-> model runs OK")
