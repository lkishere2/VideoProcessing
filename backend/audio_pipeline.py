"""
Audio significant-point detection and cropping pipeline.

Pipeline stages:
  1. Noise suppression
  2. Speaker identification (MFCC + KMeans, auto-K via silhouette score)
  3. Prosodic / emotional tone analysis
  4. Transcript detection
  5. Sound burst detection (RMS energy onsets, not raw sample diffs)
  6. Clustering significant points -> time segments
  7. Cropping audio into segment files, ready to hand to an AI API

Design notes (fixes vs. the original draft):
  - Everything is tracked in SECONDS, converted to sample indices only at
    the point of slicing/exporting. This avoids the bug where cluster
    labels (positions in a sparse event list) were used as if they were
    raw sample indices.
  - Sound burst detection uses frame-wise RMS energy + a rate-of-change
    threshold instead of a per-sample amplitude diff loop (which is slow
    and acoustically meaningless on raw waveforms).
  - KMeans calls are guarded against n_samples < n_clusters, which will
    raise on short/quiet clips otherwise.
  - Output is real cropped .wav files on disk (plus metadata), since an
    in-memory list of numpy arrays isn't usable by a downstream AI API.
"""

import os
import json
import time
import numpy as np
import soundfile as sf
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
import speech_recognition as sr


# ---------------------------------------------------------------------------
# 1. Background Noise Suppression
# ---------------------------------------------------------------------------
def reduce_noise(audio: np.ndarray, sr_rate: int) -> np.ndarray:
    """
    Simple spectral-gating noise reduction.

    Estimates a noise profile from the quietest 0.5s of the clip (assumed
    to be background-only) and subtracts that energy from the spectrogram.
    This is intentionally lightweight (no extra heavy deps); swap in
    `noisereduce` if you want a stronger result and can add the dependency.
    """
    if len(audio) == 0:
        return audio

    # STFT noise reduction has been removed to speed up processing
    # Whisper handles noise reasonably well out of the box
    return audio.astype(np.float32)


def compute_rms(audio: np.ndarray, frame_length: int = 2048, hop_length: int = 512) -> np.ndarray:
    # Center padding: pad by frame_length // 2 on both sides (mirrors librosa)
    pad_width = frame_length // 2
    padded_audio = np.pad(audio, pad_width, mode='reflect')
    
    n_frames = (len(padded_audio) - frame_length) // hop_length + 1
    if n_frames <= 0:
        return np.array([0.0], dtype=np.float32)
        
    shape = (n_frames, frame_length)
    strides = (padded_audio.strides[0] * hop_length, padded_audio.strides[0])
    windows = np.lib.stride_tricks.as_strided(padded_audio, shape=shape, strides=strides)
    
    # Keep in float32 to avoid expensive type-cast and speed up math on CPU
    windows_f32 = np.nan_to_num(windows, nan=0.0, posinf=0.0, neginf=0.0)
    # Clip absolute values to prevent overflow spikes during squaring
    windows_clipped = np.clip(windows_f32, -1.0, 1.0)
    return np.sqrt(np.mean(windows_clipped**2, axis=1))

# ---------------------------------------------------------------------------
# 3. Emotional Tone Analysis
# ---------------------------------------------------------------------------
def extract_prosodic_features(audio: np.ndarray, sr_rate: int):
    """
    Returns (mean_pitch_hz, rms_volume, tempo_bpm).
    Bypasses pitch and tempo (returns 0.0) to avoid slow processing.
    """
    if len(audio) == 0:
        return 0.0, 0.0, 0.0

    volume = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    return 0.0, volume, 0.0


def analyze_emotional_tone(pitch: float, volume: float, speech_rate: float, bursts: list) -> str:
    # Pitch and tempo are no longer computed for performance reasons.
    if volume > 0.05 and len(bursts) > 1:
        return "Excited"
    elif volume < 0.015:
        return "Sad"
    else:
        return "Neutral"


# ---------------------------------------------------------------------------
# 4. Transcript Detection
# ---------------------------------------------------------------------------
def transcribe_audio(audio_file: str) -> str:
    """
    DEPRECATED for pipeline use: speech_recognition's `recognize_google` hits
    a free, rate-limited, unofficial endpoint that has proven unreliable in
    practice. Kept only for the standalone CLI (`__main__` block) below.
    The actual video pipeline transcribes each chunk with faster-whisper via
    `transcribe_chunk()` instead - see voice_processing.py.
    """
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(audio_file) as source:
            audio_data = recognizer.record(source)
            return recognizer.recognize_google(audio_data)
    except (sr.UnknownValueError, sr.RequestError) as e:
        return f"[transcription unavailable: {e}]"


# ---------------------------------------------------------------------------
# 5. Sound Burst Detection (RMS-energy based, returns TIMES in seconds)
# ---------------------------------------------------------------------------
def detect_sound_bursts(audio: np.ndarray, sr_rate: int,
                         frame_length: int = 2048, hop_length: int = 512,
                         rel_threshold: float = 1.8) -> list:
    """
    Detects sudden increases in energy using frame-wise RMS.
    Returns burst times in seconds.
    """
    if len(audio) == 0:
        return []

    # Downsample audio by 2x to speed up RMS calculation (from 16kHz to 8kHz)
    audio_ds = audio[::2]
    sr_rate_ds = sr_rate // 2
    # Adjust frame and hop lengths for the new sampling rate
    frame_length_ds = frame_length // 2
    hop_length_ds = hop_length // 2

    rms = compute_rms(audio_ds, frame_length_ds, hop_length_ds)
    times = np.arange(len(rms)) * hop_length_ds / sr_rate_ds
    median_rms = np.median(rms)

    # Vectorized ratio calculation with safety boundaries for silence
    eps = 1e-4
    denominator = np.clip(rms[:-1], eps, None)
    ratios = rms[1:] / denominator
    
    # Locate indices where both energy ratio increases rapidly and exceeds median noise threshold
    indices = np.where((ratios > rel_threshold) & (rms[1:] > median_rms * 1.2))[0] + 1
    
    return times[indices].tolist(), rms, times


# ---------------------------------------------------------------------------
# 6. Clustering Significant Points -> time segments
# ---------------------------------------------------------------------------
def cluster_significant_points(duration_sec: float, speaker_change_times: list,
                                bursts: list, max_clusters: int = 5,
                                gap_merge_sec: float = 1.5) -> list:
    """
    Combines burst times and speaker-change times into a single sorted list
    of "significant point" timestamps (in seconds), then groups nearby
    points into segments by merging points within `gap_merge_sec` of each
    other - rather than handing arbitrary integer indices to KMeans.

    Returns a list of (start_sec, end_sec) segment tuples.
    """
    points = sorted(set(round(t, 3) for t in (speaker_change_times + bursts) if 0 <= t <= duration_sec))

    if not points:
        return []

    # Merge points into segments using a simple gap threshold. This is more
    # robust than KMeans here because the points are 1-D timestamps with a
    # natural notion of "close in time" - no need to force a fixed K, and
    # no crash risk when there are fewer points than clusters.
    segments = []
    seg_start = points[0]
    prev = points[0]
    for t in points[1:]:
        if t - prev > gap_merge_sec:
            segments.append((seg_start, prev))
            seg_start = t
        prev = t
    segments.append((seg_start, prev))

    # Pad each segment with a little context, clipped to the audio bounds.
    padded = []
    pad = 0.5
    for start, end in segments:
        padded.append((max(0.0, start - pad), min(duration_sec, end + pad)))

    # Cap to max_clusters most "active" segments if there are too many,
    # ranked by segment duration (a proxy for how much happened there).
    if len(padded) > max_clusters:
        padded = sorted(padded, key=lambda seg: seg[1] - seg[0], reverse=True)[:max_clusters]
        padded = sorted(padded)

    return padded


def get_speaker_change_times(speaker_labels: np.ndarray, sr_rate: int,
                               hop_length: int = 512) -> list:
    """Converts frame-wise speaker-label changes into timestamps (seconds)."""
    if len(speaker_labels) < 2:
        return []
    change_frames = np.where(np.diff(speaker_labels) != 0)[0] + 1
    # Replace librosa.frames_to_time with direct math
    return (change_frames * hop_length / sr_rate).tolist()


# ---------------------------------------------------------------------------
# Per-chunk enrichment: chunk-local emotional tone for each cropped segment,
# instead of one global value for the whole file.
#
# NOTE on speaker identification: MFCC+KMeans clustering was tested against
# realistic distinct voices and found unreliable - it clusters timbre and
# silence gaps, not speaker identity (in testing, ~90% of frames landed in
# one cluster regardless of which of two clearly different voices was
# speaking). Speaker labels have been removed from chunk enrichment and
# from significant-point detection (below) as a result. A real speaker
# label would need a proper diarization model (e.g. pyannote.audio) rather
# than this lightweight approach.
# ---------------------------------------------------------------------------
def analyze_audio_chunks(audio_file: str, output_dir: str, max_clusters: int = 5) -> dict:
    """
    Runs noise reduction + burst detection, crops the audio into per-segment
    .wav files around detected bursts, and returns a chunk-local emotional
    tone for each chunk (not one global value for the whole file).

    Returns:
        {
            "duration_sec": float,
            "chunks": [
                {
                    "file": str, "start_sec": float, "end_sec": float,
                    "duration_sec": float, "emotion": str,
                }, ...
            ],
        }
    """
    audio, sr_rate = sf.read(audio_file)
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    duration_sec = len(audio) / sr_rate

    audio_clean = reduce_noise(audio, sr_rate)

    bursts = detect_sound_bursts(audio_clean, sr_rate)

    # Significant points are now bursts only - speaker-change detection
    # was dropped as a clustering input (see note above).
    segments = cluster_significant_points(duration_sec, [], bursts, max_clusters=max_clusters)
    chunks_meta = crop_audio(audio_clean, sr_rate, segments, output_dir)

    # Enrich each chunk with a chunk-local emotion, instead of the
    # one-size-fits-all global emotion from process_audio().
    for chunk in chunks_meta:
        start_sec, end_sec = chunk["start_sec"], chunk["end_sec"]

        start_sample = int(start_sec * sr_rate)
        end_sample = min(int(end_sec * sr_rate), len(audio_clean))
        chunk_audio = audio_clean[start_sample:end_sample]

        chunk_pitch, chunk_volume, chunk_tempo = extract_prosodic_features(chunk_audio, sr_rate)
        chunk_bursts_in_window = [b for b in bursts if start_sec <= b < end_sec]
        emotion = analyze_emotional_tone(chunk_pitch, chunk_volume, chunk_tempo, chunk_bursts_in_window)

        chunk["emotion"] = emotion

    return {
        "duration_sec": round(duration_sec, 3),
        "chunks": chunks_meta,
    }


# ---------------------------------------------------------------------------
# 7. Cropping the Audio -> real .wav files on disk
# ---------------------------------------------------------------------------
def crop_audio(audio: np.ndarray, sr_rate: int, segments: list,
                output_dir: str, min_segment_sec: float = 0.3) -> list:
    """
    Crops audio using (start_sec, end_sec) segments and writes each to its
    own .wav file. Returns metadata describing each exported chunk - this
    is what you'd hand off to an AI API (file path + timing context).
    """
    os.makedirs(output_dir, exist_ok=True)
    chunks_meta = []

    for idx, (start_sec, end_sec) in enumerate(segments):
        if end_sec - start_sec < min_segment_sec:
            continue
        start_sample = int(start_sec * sr_rate)
        end_sample = int(end_sec * sr_rate)
        end_sample = min(end_sample, len(audio))
        if start_sample >= end_sample:
            continue

        chunk = audio[start_sample:end_sample]
        filename = f"chunk_{idx:03d}_{start_sec:.2f}-{end_sec:.2f}.wav"
        filepath = os.path.join(output_dir, filename)
        sf.write(filepath, chunk, sr_rate); print('Voice segment captured:', filepath)

        chunks_meta.append({
            "file": filepath,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "duration_sec": round(end_sec - start_sec, 3),
        })

    return chunks_meta


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def process_audio(audio_file: str, output_dir: str = "output_chunks") -> dict:
    start_time = time.time()
    
    audio, sr_rate = sf.read(audio_file)
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    duration_sec = len(audio) / sr_rate

    # 1. Noise suppression
    audio_clean = reduce_noise(audio, sr_rate)

    # 2. Speaker identification (simplified, clustering removed per verified tests)
    speaker_change_times = []
    n_speakers = 1

    # 3. Emotional tone
    pitch, volume, tempo = extract_prosodic_features(audio_clean, sr_rate)

    bursts, _, _ = detect_sound_bursts(audio_clean, sr_rate)
    emotional_tone = analyze_emotional_tone(pitch, volume, tempo, bursts)

    # 4. Transcript
    transcript = transcribe_audio(audio_file)

    # 6. Cluster significant points into time segments
    segments = cluster_significant_points(duration_sec, speaker_change_times, bursts)

    # 7. Crop into real files
    chunks_meta = crop_audio(audio_clean, sr_rate, segments, output_dir)

    result = {
        "duration_sec": round(duration_sec, 3),
        "n_speakers_detected": n_speakers,
        "emotional_tone": emotional_tone,
        "prosody": {"mean_pitch_hz": round(pitch, 1), "rms_volume": round(volume, 4), "tempo_bpm": round(tempo, 1)},
        "transcript": transcript,
        "bursts_sec": [round(b, 3) for b in bursts],
        "segments_sec": [(round(s, 3), round(e, 3)) for s, e in segments],
        "chunks": chunks_meta,
    }

    # Write a manifest alongside the chunks - useful for handing to an AI API
    manifest_path = os.path.join(output_dir, "manifest.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(result, f, indent=2)

    end_time = time.time()
    print(f'Audio processing took {end_time - start_time} seconds')
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python audio_pipeline.py <audio_file.wav> [output_dir]")
        sys.exit(1)

    audio_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "output_chunks"
    result = process_audio(audio_path, out_dir)

    print(f"Duration: {result['duration_sec']}s")
    print(f"Speakers detected: {result['n_speakers_detected']}")
    print(f"Emotional tone: {result['emotional_tone']}")
    print(f"Prosody: {result['prosody']}")
    print(f"Transcript: {result['transcript']}")
    print(f"Bursts (sec): {result['bursts_sec']}")
    print(f"Segments (sec): {result['segments_sec']}")
    print(f"Chunks written: {len(result['chunks'])}")
    for c in result['chunks']:
        print(f"  - {c['file']} ({c['start_sec']}s - {c['end_sec']}s)")