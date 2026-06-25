import os
import subprocess
import base64
import re

def frame_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def extract_frames(video_path: str, temp_dir: str, max_frames: int = 50):
    pattern = os.path.join(temp_dir, "frame_%04d.jpg")
    
    # We use subprocess directly to capture stderr which contains the 'showinfo' logs
    command = [
        "ffmpeg",
        "-i", video_path,
        "-vf", "select='gt(scene,0.2)',showinfo",
        "-vsync", "vfr",
        "-qscale:v", "2",
        pattern
    ]
    
    # Run FFmpeg and capture stderr
    process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    _, stderr_output = process.communicate()
        
    # Parse timestamps from stderr output
    # Example line: [Parsed_showinfo_1 @ 0x...] n:   0 pts: 1234 pts_time:1.23456 pos: ...
    timestamps = []
    for line in stderr_output.splitlines():
        if "showinfo" in line and "pts_time:" in line:
            match = re.search(r"pts_time:([0-9.]+)", line)
            if match:
                timestamps.append(float(match.group(1)))
                
    frame_files = sorted(f for f in os.listdir(temp_dir) if f.startswith("frame_") and f.endswith(".jpg"))
    
    # Map files to their precise chronological timestamps
    results = []
    for i, file in enumerate(frame_files):
        ts = timestamps[i] if i < len(timestamps) else 0.0
        results.append((os.path.join(temp_dir, file), ts))
        
    # Fallback: If no scene changes detected (e.g. completely static video), extract the very first frame
    if not results:
        fallback_command = ["ffmpeg", "-i", video_path, "-vframes", "1", "-qscale:v", "2", pattern]
        subprocess.run(fallback_command, capture_output=True)
        frame_files = sorted(f for f in os.listdir(temp_dir) if f.startswith("frame_") and f.endswith(".jpg"))
        if frame_files:
            results.append((os.path.join(temp_dir, frame_files[0]), 0.0))
            
    # Cap the absolute maximum number of frames sent to Claude
    if len(results) > max_frames:
        step = len(results) / max_frames
        sampled_results = [results[int(i * step)] for i in range(max_frames)]
        return sampled_results
        
    return results
