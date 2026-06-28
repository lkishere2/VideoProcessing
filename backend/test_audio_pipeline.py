import os
import numpy as np
import soundfile as sf
from audio_pipeline import process_audio

SR = 16000
# 6 seconds: silence, then a 0.5s burst at 1s and another at 3.2s
t = np.linspace(0, 6, int(6 * SR), endpoint=False)
# base silence
audio = np.zeros_like(t)
# burst 1: 440 Hz sine from 1.0s to 1.5s
b1_start, b1_end = int(1.0 * SR), int(1.5 * SR)
audio[b1_start:b1_end] += 0.5 * np.sin(2 * np.pi * 440 * t[: b1_end - b1_start])
# burst 2: higher energy noise from 3.2s to 3.7s
b2_start, b2_end = int(3.2 * SR), int(3.7 * SR)
audio[b2_start:b2_end] += 0.8 * np.random.randn(b2_end - b2_start)

out_wav = "test_synthetic.wav"
sf.write(out_wav, audio, SR)

print(f"Wrote test WAV: {out_wav}")

res = process_audio(out_wav, output_dir="test_output")
print("Pipeline result:")
import json
print(json.dumps(res, indent=2))

print("Contents of test_output:")
for root, dirs, files in os.walk('test_output'):
    for f in files:
        print(os.path.join(root, f))
