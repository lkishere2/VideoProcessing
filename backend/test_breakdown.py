import sys
sys.path.insert(0, '/home/twoseepeakay/VideoProcessing/.venv/lib/python3.12/site-packages')
import av
import numpy as np
from PIL import Image
import soundfile as sf
import io
import base64
import time
from audio_pipeline import detect_sound_bursts, cluster_significant_points

def test_breakdown():
    url = 'http://192.168.1.67:3001/videos/fbbb4ac4-9bfb-4ee2-8c51-fcb0924a4d67.mp4'
    options = {
        'probesize': '32768',
        'analyzeduration': '100000',
        'fflags': 'nobuffer'
    }

    print(f"Timing Breakdown for: {url}\n" + "-"*50)

    # 1. Container Open
    start = time.time()
    container = av.open(url, options=options)
    open_time = time.time() - start
    print(f"1. Open Media Container (Handshake & Probing) : {open_time*1000:.1f}ms")

    # Find streams
    audio_stream = None
    video_stream = None
    for s in container.streams:
        if s.type == 'audio':
            audio_stream = s
        elif s.type == 'video':
            video_stream = s

    duration_sec = float(container.duration) / av.time_base if container.duration else 0.0

    # 2. Audio-only demux
    start = time.time()
    audio_array = np.array([], dtype=np.float32)
    if audio_stream:
        resampler = av.AudioResampler(format='flt', layout='mono', rate=16000)
        chunks = []
        for packet in container.demux([audio_stream]):
            for frame in packet.decode():
                resampled = resampler.resample(frame)
                if resampled:
                    for f in resampled:
                        chunks.append(np.frombuffer(f.planes[0], dtype=np.float32).copy())
        flushed = resampler.resample(None)
        if flushed:
            for f in flushed:
                chunks.append(np.frombuffer(f.planes[0], dtype=np.float32).copy())
        if chunks:
            audio_array = np.concatenate(chunks)
    audio_time = time.time() - start
    print(f"2. Pass 1: Audio Demux & Resampling            : {audio_time*1000:.1f}ms (Size: {len(audio_array)} samples)")
    container.close()

    # 3. Burst detection
    start = time.time()
    important_segments = []
    if len(audio_array) > 0:
        bursts, rms, times = detect_sound_bursts(audio_array, 16000)
        important_segments = cluster_significant_points(duration_sec, [], bursts, max_clusters=10)
    burst_time = time.time() - start
    print(f"3. Vectorized Audio Burst & Cluster Detection  : {burst_time*1000:.1f}ms (Found {len(important_segments)} segments)")

    # Define seek targets (fallback here is 1 frame per 5s)
    targets = []
    if important_segments:
        for s, e in important_segments:
            targets.append(s)
            if e - s > 2.0:
                targets.append((s + e) / 2.0)
    else:
        t = 0.0
        while t < (duration_sec if duration_sec > 0 else 10.0):
            targets.append(t)
            t += 5.0
    targets = sorted(list(set(targets)))

    # 4. Pass 2 Container Open
    start = time.time()
    container = av.open(url, options=options)
    v_stream = container.streams.video[0]
    v_stream.thread_type = 'AUTO'
    v_stream.skip_frame = 'NONKEY'
    reopen_time = time.time() - start
    print(f"4. Re-open Container for Video Seek            : {reopen_time*1000:.1f}ms")

    # 5. Targeted video seek & decode
    start = time.time()
    frames_decoded = 0
    for target in targets:
        pts_offset = int(target / float(v_stream.time_base))
        container.seek(pts_offset, stream=v_stream, backward=True)
        frame_found = False
        for packet in container.demux([v_stream]):
            for frame in packet.decode():
                img = frame.to_image()
                w, h = img.size
                new_w = 400
                new_h = int(h * (400 / w))
                img_resized = img.resize((new_w, new_h))
                buffered = io.BytesIO()
                img_resized.save(buffered, format="JPEG", quality=90)
                _ = base64.b64encode(buffered.getvalue())
                frames_decoded += 1
                frame_found = True
                break
            if frame_found:
                break
    seek_time = time.time() - start
    print(f"5. Pass 2: Targeted Seek & Decode {frames_decoded} frames   : {seek_time*1000:.1f}ms")
    container.close()

if __name__ == "__main__":
    test_breakdown()
