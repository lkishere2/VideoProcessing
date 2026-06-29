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

def extract_media_pyav(video_source, headers=None, fps: float = 1.0, max_frames: int = 100) -> tuple[list[tuple[str, float]], np.ndarray, str, float]:
    import av
    import numpy as np
    import io
    import time
    import tempfile
    
    total_start = time.time()
    
    # 1. Open the video container
    open_start = time.time()
    if isinstance(video_source, str) and (video_source.startswith("http://") or video_source.startswith("https://")):
        headers_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items()) if headers else ""
        container = av.open(video_source, options={'headers': headers_str})
    else:
        # Uploaded file or local file
        container = av.open(video_source)
    open_time = time.time() - open_start
    print(f"[PyAV Profile] Opening media source took {open_time:.3f} seconds.")
        
    # 2. Find video and audio streams
    video_stream = None
    audio_stream = None
    
    for stream in container.streams:
        if stream.type == 'video' and video_stream is None:
            video_stream = stream
        elif stream.type == 'audio' and audio_stream is None:
            audio_stream = stream
            
    if video_stream is None:
        raise RuntimeError("No video stream found in the source container.")
        
    # Enable multi-threaded decoding
    video_stream.thread_type = 'AUTO'
    
    # Calculate duration
    duration = 0.0
    if container.duration:
        duration = float(container.duration) / av.time_base
        
    # 3. Decode audio in-memory if present
    audio_start = time.time()
    audio_array = np.array([], dtype=np.float32)
    if audio_stream is not None:
        try:
            resampler = av.AudioResampler(
                format='flt', # float32
                layout='mono',
                rate=16000
            )
            audio_data = []
            for frame in container.decode(audio_stream):
                resampled = resampler.resample(frame)
                if resampled:
                    for f in resampled:
                        audio_data.append(f.to_ndarray())
                        
            # Flush the resampler
            flushed = resampler.resample(None)
            if flushed:
                for f in flushed:
                    audio_data.append(f.to_ndarray())
                    
            if audio_data:
                audio_array = np.concatenate(audio_data, axis=1).flatten()
        except Exception as e:
            print(f"[PyAV] Audio extraction failed: {e}")
    audio_time = time.time() - audio_start
    print(f"[PyAV Profile] Audio decoding & resampling took {audio_time:.3f} seconds.")
            
    # Seek back to beginning to decode video frames
    container.seek(0)
    
    # 4. Decode video frames
    video_start = time.time()
    frames_in_memory = []
    
    time_base = float(video_stream.time_base)
    next_target_time = 0.0
    interval = 1.0 / fps
    
    for frame in container.decode(video_stream):
        ts = float(frame.pts * time_base) if frame.pts is not None else frame.time
        if ts >= next_target_time:
            img = frame.to_image()
            w, h = img.size
            new_w = 400
            new_h = int(h * (400 / w))
            img_resized = img.resize((new_w, new_h))
            
            frames_in_memory.append({
                "image": img_resized,
                "timestamp": ts,
                "index": len(frames_in_memory)
            })
            next_target_time += interval
            
    container.close()
    video_time_spent = time.time() - video_start
    print(f"[PyAV Profile] Video decoding & resizing took {video_time_spent:.3f} seconds. Decoded {len(frames_in_memory)} raw target frames.")
    
    if not frames_in_memory:
        return [], audio_array, ""
        
    if duration == 0.0:
        duration = frames_in_memory[-1]["timestamp"]
        
    # 5. Score frames using grayscale differences
    scoring_start = time.time()
    category, min_frames = _duration_tier(duration)
    
    scored_frames = []
    prev_img = None
    for item in frames_in_memory:
        img = item["image"]
        ts = item["timestamp"]
        idx = item["index"]
        
        img_gray = img.convert('L').resize((32, 32))
        img_arr = np.array(img_gray, dtype=np.float32)
        
        if prev_img is not None:
            score = float(np.mean(np.abs(prev_img - img_arr)))
        else:
            score = 0.0
            
        prev_img = img_arr
        scored_frames.append((idx, item, ts, score))
        
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
        extra_frames_count = int(avg_mvp_diff * 4.0)
        target_count = min(max_frames, min_frames + extra_frames_count)
    else:
        target_count = min_frames
        
    # Chronological Interval Selection
    valid_candidates.sort(key=lambda x: x[2])
    target_count = min(target_count, len(valid_candidates))
    
    selected_items = []
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
                best = max(candidates, key=lambda x: x[3])
                selected_items.append(best[1])
            else:
                center = (interval_start + interval_end) / 2
                closest = min(valid_candidates, key=lambda x: abs(x[2] - center))
                selected_items.append(closest[1])
                
    # Deduplicate selected items
    unique_selected = []
    seen_indices = set()
    for item in selected_items:
        if item["index"] not in seen_indices:
            unique_selected.append(item)
            seen_indices.add(item["index"])
    selected_items = unique_selected
    
    # Sort chronologically
    selected_items = sorted(selected_items, key=lambda x: x["timestamp"])
    
    # Save selected frames to temp directory for frontend static serving
    temp_dir = tempfile.mkdtemp()
    results = []
    for idx, item in enumerate(selected_items):
        frame_path = os.path.join(temp_dir, f"frame_{idx:04d}.jpg")
        item["image"].save(frame_path, "JPEG", quality=90)
        results.append((frame_path, item["timestamp"]))
        
    scoring_time = time.time() - scoring_start
    print(f"[PyAV Profile] Scoring, interval selection & disk save took {scoring_time:.3f} seconds. Kept {len(results)} frames.")
    
    total_time = time.time() - total_start
    print(f"[PyAV Profile] TOTAL processing time: {total_time:.3f} seconds.")
    
    return sorted(results, key=lambda x: x[1]), audio_array, temp_dir, audio_time