"""
Audio extraction + transcription for the video summarization pipeline.

This module provides the functions video_processing.py imports:
    - extract_audio(video_path, temp_dir) -> str (path to a .wav file)
    - transcribe_audio(audio_path) -> list[dict] with
      "start", "end", "text", "emotion"

Strategy: rather than transcribing the entire audio track, this uses the
audio_pipeline's significant-point detection (noise reduction + RMS burst
detection) to crop out only the meaningful windows first, then runs
faster-whisper on each cropped chunk individually. This is faster for long
recordings with dead air, and each resulting segment carries a chunk-local
emotional tone tag (derived from chunk-local pitch/volume/burst signals)
so the transcript can read like "[12.3s-14.1s, Excited]: ...".

NOTE: speaker identification was evaluated (MFCC+KMeans) and dropped after
testing showed it doesn't reliably separate distinct voices - it clusters
timbre/silence, not speaker identity. Only emotion + burst-based timing
are used here; see audio_pipeline.py's analyze_audio_chunks() docstring.

Uses faster-whisper (CTranslate2-based Whisper) for local, offline
transcription - no per-call API cost, no network dependency, no rate
limits.

Model loading is lazy and cached at module level (mirrors the Bedrock
client pattern in video_processing.py) so the model is loaded once per
process, not once per request.
"""

import os
import subprocess
import threading
import base64

from faster_whisper import WhisperModel

from audio_pipeline import analyze_audio_chunks

FFMPEG_THREADS = os.environ.get("FFMPEG_THREADS", "2")
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "4"))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Model size: tiny/base/small/medium/large-v3. "base" is a good default
# balance of speed vs. accuracy on CPU.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")

# "cpu" works everywhere with no extra setup. Set WHISPER_DEVICE=cuda if you
# have a working CUDA + cuDNN setup and want faster transcription.
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

# int8 is fast and low-memory on CPU; float16 is the typical choice on GPU.
WHISPER_COMPUTE_TYPE = os.environ.get(
    "WHISPER_COMPUTE_TYPE", "int8" if WHISPER_DEVICE == "cpu" else "float16"
)

_model = None
_model_lock = threading.Lock()


def get_whisper_model() -> WhisperModel:
    """Lazily loads and caches the Whisper model (thread-safe singleton)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # re-check inside the lock
                _model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                    cpu_threads=WHISPER_CPU_THREADS,
                )
    return _model


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------
def extract_audio(video_path: str, temp_dir: str) -> str:
    """
    Extracts the audio track from a video file as a 16kHz mono WAV file
    (the format Whisper expects). Returns the path to the extracted file.

    Raises RuntimeError with ffmpeg's stderr if extraction fails (e.g. the
    video has no audio track at all).
    """
    audio_path = os.path.join(temp_dir, "audio.wav")
    cmd = [
        "ffmpeg", "-y",
        "-threads", FFMPEG_THREADS,
        "-i", video_path,
        "-vn",                 # no video
        "-acodec", "pcm_s16le",
        "-ar", "16000",        # 16kHz - what Whisper expects
        "-ac", "1",            # mono
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0 or not os.path.exists(audio_path):
        raise RuntimeError(f"Failed to extract audio from '{video_path}': {result.stderr.strip()}")

    return audio_path


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
def _transcribe_chunk_file(chunk_path: str) -> str:
    """Transcribes a single short audio chunk and returns the joined text."""
    model = get_whisper_model()
    segments, _info = model.transcribe(chunk_path, vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


def transcribe_audio(audio_data):
    import time
    import io
    import soundfile as sf
    import numpy as np
    from audio_pipeline import detect_sound_bursts, analyze_emotional_tone, extract_prosodic_features
    
    start_time = time.time()
    sr_rate = 16000
    
    if isinstance(audio_data, str):
        # Fallback if audio_path is passed
        audio_path = audio_data
        if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            return []
        try:
            audio, sr_rate = sf.read(audio_path)
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
        except Exception as e:
            print(f"[voice_processing] failed to load audio file '{audio_path}': {e}")
            return []
    else:
        # NumPy array passed directly
        audio = audio_data
        if audio is None or len(audio) == 0:
            return []
            
    # Run Whisper in a single pass over the array directly (in-memory)
    try:
        model = get_whisper_model()
        # model.transcribe accepts the numpy array of float32
        segments, _info = model.transcribe(audio, vad_filter=True)
        segments_list = list(segments)
    except Exception as e:
        print(f"[voice_processing] single-pass Whisper transcription failed: {e}")
        return []

    # Calculate global features/bursts to avoid computing them repeatedly
    bursts = detect_sound_bursts(audio, sr_rate)

    results = []
    for idx, seg in enumerate(segments_list):
        start_sec = float(seg.start)
        end_sec = float(seg.end)
        text = seg.text.strip()
        
        if not text:
            continue

        # Slice the segment array in-memory for emotion classification
        start_sample = int(start_sec * sr_rate)
        end_sample = min(int(end_sec * sr_rate), len(audio))
        chunk_audio = audio[start_sample:end_sample]

        # Calculate chunk emotional tone using RMS volume and burst counts in-memory
        _, chunk_volume, _ = extract_prosodic_features(chunk_audio, sr_rate)
        chunk_bursts = [b for b in bursts if start_sec <= b < end_sec]
        emotion = analyze_emotional_tone(0.0, chunk_volume, 0.0, chunk_bursts)

        # Convert the audio segment slice directly to WAV bytes in-memory for base64
        audio_b64 = None
        try:
            if len(chunk_audio) > 0:
                wav_io = io.BytesIO()
                sf.write(wav_io, chunk_audio, sr_rate, format='WAV', subtype='PCM_16')
                audio_b64 = "data:audio/wav;base64," + base64.b64encode(wav_io.getvalue()).decode("ascii")
        except Exception as e:
            print(f"[voice_processing] failed to encode segment {idx} to base64: {e}")

        results.append({
            "start": round(start_sec, 3),
            "end": round(end_sec, 3),
            "text": text,
            "emotion": emotion,
            "audio_b64": audio_b64,
            "file": f"in_memory_chunk_{idx}.wav",
        })

    end_time = time.time()
    print(f'Audio transcription completed in {end_time - start_time:.3f} seconds for {len(results)} segments.')
    return results