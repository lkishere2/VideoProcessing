import os
import re
import subprocess
import time
import numpy as np
from PIL import Image

FFMPEG_THREADS = os.environ.get("FFMPEG_THREADS", "2")


def _is_blurry(filepath: str, threshold: float = 30.0) -> bool:
    try:
        img = Image.open(filepath).convert('L')
        img_arr = np.array(img, dtype=np.float32)
        h_grad = np.diff(img_arr, axis=1)
        v_grad = np.diff(img_arr, axis=0)
        variance = np.var(h_grad) + np.var(v_grad)
        return float(variance) < threshold
    except Exception:
        return False

def _get_grayscale_thumbnail(filepath: str) -> np.ndarray:
    try:
        img = Image.open(filepath).convert('L').resize((32, 32))
        return np.array(img, dtype=np.float32)
    except Exception:
        return np.zeros((32, 32), dtype=np.float32)

def _get_similarity(img1: np.ndarray, img2: np.ndarray) -> float:
    # Returns the average absolute pixel difference (0.0 to 255.0)
    return float(np.mean(np.abs(img1 - img2)))

def frame_to_base64(path: str) -> str:
    import base64
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def get_video_duration(video_path: str) -> float:
    try:
        output = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            stderr=subprocess.STDOUT,
        ).decode().strip()
        return float(output)
    except (subprocess.CalledProcessError, ValueError) as e:
        raise RuntimeError(f"Could not determine duration for '{video_path}': {e}")

def _duration_tier(duration: float) -> tuple[str, int]:
    if duration <= 60:
        return "short", 20
    elif duration <= 180:
        return "medium", 30
    else:
        return "long", 40

def extract_frames(video_path: str, temp_dir: str, max_frames: int = 100) -> list[tuple[str, float]]:
    """
    Optimized Single-Pass Frame Extraction.
    FFmpeg is invoked exactly once to extract a fixed density of frames (1.0 to 2.0 fps)
    into RAM, directly resizing them to 400px width.
    Python then performs chronological scene scoring and interval-based maxima selection
    entirely in-memory, deleting the unselected images from disk.
    """
    start_time = time.time()

    duration = get_video_duration(video_path)
    category, min_frames = _duration_tier(duration)
    pattern = os.path.join(temp_dir, "frame_%04d.jpg")

    # Set extraction framerate dynamically
    if duration <= 60:
        fps = 2.0
    elif duration <= 180:
        fps = 1.0
    else:
        fps = 0.5

    # Single-pass FFmpeg command limited to FFMPEG_THREADS to prevent core thrashing
    command = [
        "ffmpeg", "-y", "-threads", FFMPEG_THREADS, "-i", video_path,
        "-vf", f"fps={fps},scale=400:-1",
        "-qscale:v", "2",
        pattern
    ]
    
    try:
        subprocess.run(command, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg single-pass extraction failed: {e.stderr.decode().strip()}")

    # Find the extracted files
    files = sorted(f for f in os.listdir(temp_dir) if f.startswith("frame_") and f.endswith(".jpg"))
    if not files:
        return []

    # Score frames using in-memory grayscale thumbnail differences (representing visual change)
    scored_frames = []
    prev_img = None
    for idx, filename in enumerate(files):
        filepath = os.path.join(temp_dir, filename)
        ts = (idx + 1) / fps

        img_arr = _get_grayscale_thumbnail(filepath)
        if prev_img is not None:
            score = _get_similarity(prev_img, img_arr)
        else:
            score = 0.0
        prev_img = img_arr
        scored_frames.append((idx, filepath, ts, score))

    # Exclude the first 1.5s to bypass intro fade-ins
    valid_candidates = [f for f in scored_frames if f[2] > 1.5]
    if not valid_candidates:
        valid_candidates = scored_frames

    # Determine target_count dynamically based on MVP score
    valid_candidates.sort(key=lambda x: x[3], reverse=True)
    guaranteed = valid_candidates[:min_frames]

    if guaranteed:
        total_mvp_score = sum(s[3] for s in guaranteed)
        avg_mvp_diff = total_mvp_score / len(guaranteed)
        # Average difference of 20 (decent change) adds extra frames up to 100 max
        extra_frames_count = int(avg_mvp_diff * 4.0)
        target_count = min(max_frames, min_frames + extra_frames_count)
    else:
        target_count = min_frames

    # Chronological Interval Selection (guarantees even spreading)
    valid_candidates.sort(key=lambda x: x[2])
    target_count = min(target_count, len(valid_candidates))

    selected_frames = []
    if target_count > 0:
        start_ts = valid_candidates[0][2]
        end_ts = valid_candidates[-1][2]
        video_duration = end_ts - start_ts
        interval_width = video_duration / target_count if video_duration > 0 else 1.0

        for i in range(target_count):
            interval_start = start_ts + i * interval_width
            interval_end = interval_start + interval_width

            candidates = [f for f in valid_candidates if interval_start <= f[2] <= interval_end]
            if candidates:
                # Pick local maximum change frame inside this interval
                best = max(candidates, key=lambda x: x[3])
                selected_frames.append(best)
            else:
                # Fallback to closest frame to the interval center
                center = (interval_start + interval_end) / 2
                closest = min(valid_candidates, key=lambda x: abs(x[2] - center))
                selected_frames.append(closest)

    # Deduplicate selected frames
    unique_selected = []
    seen_indices = set()
    for f in selected_frames:
        if f[0] not in seen_indices:
            unique_selected.append(f)
            seen_indices.add(f[0])
    selected_frames = unique_selected

    # Delete unselected files from disk to keep temp_dir clean
    selected_filepaths = {f[1] for f in selected_frames}
    for filename in files:
        path = os.path.join(temp_dir, filename)
        if path not in selected_filepaths:
            try:
                os.remove(path)
            except OSError:
                pass

    results = [(f[1], f[2]) for f in selected_frames]

    end_time = time.time()
    print(f'Single-pass frame extraction completed in {end_time - start_time:.3f} seconds. Extracted {len(files)} raw, kept {len(results)} frames.')
    
    return sorted(results, key=lambda x: x[1])