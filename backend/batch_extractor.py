import asyncio
import os
import time
import uuid
import tempfile
import shutil
from concurrent.futures import ProcessPoolExecutor
from .audio_pipeline import detect_sound_bursts, cluster_significant_points

import av as _av
import numpy as _np
from PIL import Image as _Image
import soundfile as _sf
import io as _io
import base64 as _base64
import simplejpeg as _simplejpeg

def _av_open_with_retry(url, options, max_retries=1):
    """Opens a PyAV container directly, failing fast without waiting/sleeping."""
    return _av.open(url, options=options)

def extract_single_video(url: str, fps: float = 1.0) -> dict:
    # Timing instrumentation start
    t_start_total = time.perf_counter()
    timings = {}
    
    # Measure initialization duration (library import validation / metadata checks)
    t_init_end = time.perf_counter()
    timings['initialization'] = t_init_end - t_start_total
    # Phase 1: Container open & stream discovery
    """Optimized two-pass extraction logic running inside a worker process."""


    video_id = str(uuid.uuid4())
    video_title = os.path.basename(url.split("?")[0].split("#")[0]) or "Streaming Video"

    is_network = url.startswith("http://") or url.startswith("https://")
    options = {
        'probesize': '32768',         # 32KB probe size limit
        'analyzeduration': '100000',  # 100ms analysis limit
        'fflags': 'nobuffer',         # Skip packet buffering
        'multiple_requests': '1',     # Tell FFmpeg HTTP protocol to reuse connections (Keep-Alive)
        'http_persistent': '1'        # Force persistent HTTP connection behavior
    } if is_network else None

    audio_array = _np.array([], dtype=_np.float32)
    audio_stream = None
    video_stream = None
    duration_sec = 0.0
    container = None

    # === PASS 1: AUDIO-ONLY INGESTION ===
    try:
        container = _av_open_with_retry(url, options=options)
        # Phase 1 timing: after container open & stream discovery
        t_phase1_end = time.perf_counter()
        timings['container_open'] = t_phase1_end - t_start_total
        for stream in container.streams:
            if stream.type == 'audio' and audio_stream is None:
                audio_stream = stream
            elif stream.type == 'video' and video_stream is None:
                video_stream = stream

        if container.duration:
            duration_sec = float(container.duration) / _av.time_base
        elif video_stream and video_stream.duration:
            duration_sec = float(video_stream.duration * video_stream.time_base)

        # Phase 2 timing: after audio demux
        t_phase2_end = time.perf_counter()
        timings['audio_demux'] = t_phase2_end - t_phase1_end
        if audio_stream is not None:
            resampler = _av.AudioResampler(format='flt', layout='mono', rate=16000)
            chunks = []
            # Demux ONLY audio stream
            for packet in container.demux([audio_stream]):
                for frame in packet.decode():
                    resampled = resampler.resample(frame)
                    if resampled:
                        for f in resampled:
                            chunks.append(_np.frombuffer(f.planes[0], dtype=_np.float32))

            flushed = resampler.resample(None)
            if flushed:
                for f in flushed:
                    chunks.append(_np.frombuffer(f.planes[0], dtype=_np.float32))

            if chunks:
                audio_array = _np.concatenate(chunks)
    except Exception as e:
        pass

    # === BURST DETECTION & SPEECH CLUSTERING ===
    important_segments = []
    rms = None
    times = None
    # Phase 3 timing: after burst detection
    t_phase3_start = time.perf_counter()
    is_silent = True
    if len(audio_array) > 0:
        try:
            bursts, rms, times = detect_sound_bursts(audio_array, 16000)
            t_phase3_end = time.perf_counter()
            timings['burst_detection'] = t_phase3_end - t_phase3_start
            
            # If maximum RMS indicates silence, skip further processing
            if rms is not None and len(rms) > 0:
                if _np.max(rms) > 0.005:
                    is_silent = False
            
            if not is_silent:
                important_segments = cluster_significant_points(duration_sec, [], bursts, max_clusters=10)
        except Exception as e:
            print(f"[batch_extractor] Burst detection failed: {e}")

    # Fast-path early exit if the stream is silent (no speaking)
    if is_silent or not important_segments:
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        t_end_total = time.perf_counter()
        timings['total'] = t_end_total - t_start_total
        return {
            "video_id": video_id,
            "video_title": video_title,
            "frames": [],
            "voice_segments": [],
            "timings": timings,
            "num_frames": 0,
            "num_audio_chunks": 0
        }

    # Phase 4 timing: target timestamps calculation
    t_phase4_start = time.perf_counter()
    # Set up target timestamps to seek
    targets = []
    if important_segments:
        for start, end in important_segments:
            targets.append(start)
            # If segment is long, add middle point as well
            if end - start > 2.0:
                targets.append((start + end) / 2.0)
    else:
        # Fallback: 1 frame every 5 seconds
        t = 0.0
        limit = duration_sec if duration_sec > 0 else 10.0
        while t < limit:
            targets.append(t)
            t += 5.0

    # Ensure unique and sorted targets
    targets = sorted(list(set(targets)))
    t_phase4_end = time.perf_counter()
    timings['target_calc'] = t_phase4_end - t_phase4_start

    frames_data = []

    # === PASS 2: TARGETED VIDEO SEEK (REUSING CONTAINER) ===
    # Phase 5 timing: frame seeking & JPEG encode
    t_phase5_start = time.perf_counter()
    if video_stream is not None and targets and container is not None:
        try:
            v_stream = container.streams.video[0]
            v_stream.thread_type = 'NONE'
            v_stream.skip_frame = 'NONKEY'

            for target in targets:
                try:
                    pts_offset = int(target / float(v_stream.time_base))
                    # any_frame=False forces FFmpeg to stop on I-frames only
                    container.seek(pts_offset, stream=v_stream, backward=True, any_frame=False)

                    frame_found = False
                    for packet in container.demux([v_stream]):
                        for frame in packet.decode():
                            # 1. Calculate new height natively
                            w, h = frame.width, frame.height
                            new_h = int(h * (400 / w))
                            
                            # 2. C-LEVEL BYPASS: Use FFmpeg's libswscale to resize and convert to RGB
                            # before the frame ever reaches Python object memory.
                            # 'FAST_BILINEAR' uses minimal CPU cycles compared to Pillow.
                            frame_resized = frame.reformat(width=400, height=new_h, format='rgb24', interpolation='FAST_BILINEAR')

                            # 3. Zero-copy transfer to a NumPy memory view
                            img_np = frame_resized.to_ndarray()

                            # 4. SIMD AVX2 JPEG compression (libjpeg-turbo)
                            jpeg_bytes = _simplejpeg.encode_jpeg(img_np, quality=75, colorspace='RGB')

                            actual_ts = float(frame.pts * v_stream.time_base) if frame.pts is not None else frame.time
                            frames_data.append((actual_ts, jpeg_bytes))
                            frame_found = True
                            break
                        if frame_found:
                            break
                except Exception as seek_err:
                    pass
        except Exception as e:
            pass

    # End of Phase 5
    t_phase5_end = time.perf_counter()
    timings['frame_seek_encode'] = t_phase5_end - t_phase5_start

    # Ensure container is properly closed
    if container is not None:
        try:
            container.close()
        except Exception:
            pass

    # Deduplicate extracted frames by timestamp to prevent duplicate sends
    unique_frames = []
    seen_ts = set()
    # Phase 6 timing: deduplication
    t_phase6_start = time.perf_counter()
    for ts, jpeg_bytes in sorted(frames_data, key=lambda x: x[0]):
        # Deduplicate timestamps within 0.1s tolerance
        rounded_ts = round(ts, 1)
        if rounded_ts not in seen_ts:
            unique_frames.append((ts, jpeg_bytes))
            seen_ts.add(rounded_ts)

    # End of Phase 6
    t_phase6_end = time.perf_counter()
    timings['deduplication'] = t_phase6_end - t_phase6_start

    # === ALIGN AUDIO CHUNKS WITH KEYFRAMES ===
    frames_payload = []
    t_phase7_start = time.perf_counter()

    for idx, (timestamp, jpeg_bytes) in enumerate(unique_frames):
        t1 = 0.0 if idx == 0 else unique_frames[idx - 1][0]
        t2 = timestamp

        # Slice raw audio (if audio is present and segment is within speaking range or fallback)
        raw_audio_slice = None
        if len(audio_array) > 0:
            start_sample = int(t1 * 16000)
            end_sample = min(int(t2 * 16000), len(audio_array))
            if end_sample > start_sample:
                raw_audio_slice = audio_array[start_sample:end_sample]

        frames_payload.append({
            "t1": t1,
            "t2": t2,
            "jpeg_bytes": jpeg_bytes,
            "raw_audio": raw_audio_slice
        })

    # Final timing total
    t_end_total = time.perf_counter()
    timings['payload_assembly'] = t_end_total - t_phase7_start
    timings['total'] = t_end_total - t_start_total

    # Count chunks inside worker context
    num_frames = len(frames_payload)
    num_audio_chunks = sum(1 for f in frames_payload if f.get("raw_audio") is not None)

    return {
        "video_id": video_id,
        "video_title": video_title,
        "frames": frames_payload,
        "voice_segments": [],
        "timings": timings,
        "num_frames": num_frames,
        "num_audio_chunks": num_audio_chunks
    }

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

def _process_chunk_threaded(urls_chunk: list[str]) -> list[dict]:
    """Runs inside a worker process, executing a ThreadPool to process its assigned chunk."""
    # Scale threads per process to saturate I/O overlap (Optimal sweet spot: 4 threads)
    with ThreadPoolExecutor(max_workers=4) as thread_executor:
        futures = [thread_executor.submit(extract_single_video, url) for url in urls_chunk]
        return [fut.result() for fut in futures]

def process_batch(urls: list[str]) -> list[dict]:
    """Hybrid Process-Thread Pool: distributes URLs across 12 processes (GIL-free) running concurrent threads."""
    num_processes = 12
    # Divide the URL list into 12 chunks
    avg = len(urls) // num_processes
    chunks = []
    last = 0.0
    while last < len(urls):
        chunks.append(urls[int(last):int(last + avg)])
        last += avg
        
    # Ensure remaining URLs are included
    if len(chunks) > num_processes:
        extra = chunks.pop()
        chunks[-1].extend(extra)

    results = []
    with ProcessPoolExecutor(max_workers=num_processes) as process_executor:
        futures = [process_executor.submit(_process_chunk_threaded, chunk) for chunk in chunks if chunk]
        for fut in futures:
            results.extend(fut.result())
            
    return results
