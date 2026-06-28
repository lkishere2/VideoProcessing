import time
import subprocess
import librosa
from voice_processing import get_whisper_model, _transcribe_chunk_file
from audio_pipeline import reduce_noise, detect_sound_bursts, cluster_significant_points

# 1. Create dummy audio 30s long
subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=1000:duration=30", "-ar", "16000", "test_30s.wav"], capture_output=True)

# Profile audio load
t0 = time.time()
audio, sr_rate = librosa.load("test_30s.wav", sr=None)
print("Load audio:", time.time() - t0)

# Profile noise reduction
t0 = time.time()
audio_clean = reduce_noise(audio, sr_rate)
print("Noise reduction:", time.time() - t0)

# Profile sound burst
t0 = time.time()
bursts = detect_sound_bursts(audio_clean, sr_rate)
print("Burst detection:", time.time() - t0)

# Profile clustering
t0 = time.time()
segments = cluster_significant_points(30.0, [], bursts)
print("Clustering:", time.time() - t0)

# Profile whisper load
t0 = time.time()
model = get_whisper_model()
print("Whisper model load:", time.time() - t0)

# Profile whisper transcribe (1s chunk)
subprocess.run(["ffmpeg", "-y", "-i", "test_30s.wav", "-t", "1", "test_1s.wav"], capture_output=True)
t0 = time.time()
segments, _ = model.transcribe("test_1s.wav", vad_filter=True)
list(segments)
print("Whisper transcribe 1s:", time.time() - t0)
