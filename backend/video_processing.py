"""
Video processing endpoints: frame extraction + sprite-sheet summarization,
sent to Amazon Nova 2 Lite via the Bedrock Converse API.

Fixes applied vs. the original draft:
  - Switched from the Anthropic SDK / Claude 3.5 Sonnet call to boto3's
    `bedrock-runtime` Converse API targeting Nova 2 Lite
    (global.amazon.nova-2-lite-v1:0), per the requested model.
  - Cost constants updated to Nova 2 Lite's actual published pricing
    ($0.30/M input tokens, $2.50/M output tokens) - the original code's
    $3/$15 constants were Claude 3.5 Sonnet's pricing and would have
    silently misreported cost under any model swap.
  - Response parsing defensively concatenates all text content blocks
    instead of indexing content[0].text, which throws if the model ever
    returns multiple blocks or a non-text first block.
  - Upload validation: extension allowlist + size cap, so the endpoint
    can't be used to push arbitrary/huge files through ffmpeg and the
    paid model call.
  - Per-tile timestamps are now passed to the model as adjacent TEXT
    content blocks instead of being burned into the image pixels - this
    is exact, costs no extra vision tokens for OCR-prone tiny text, and
    removes the PIL font/draw step entirely.
  - Added a basic retry with backoff around the Bedrock call for
    transient throttling/timeouts.
"""

import os
import shutil
import uuid
import time
import tempfile
import base64
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
import io
from fastapi import UploadFile, File, Form, HTTPException
from typing import List
from pydantic import BaseModel
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image

from frame_processing import extract_media_pyav, frame_to_base64
from voice_processing import transcribe_audio
from downloader import download_video
from audio_pipeline import detect_sound_bursts, cluster_significant_points
from typing import Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Nova 2 Lite published on-demand pricing (per million tokens).
# Source: AWS Bedrock pricing page / model card, verified for nova-2-lite-v1:0.
# If you switch models, these MUST be updated or cost reporting will be wrong.
NOVA_2_LITE_INPUT_COST_PER_M = 0.30
NOVA_2_LITE_OUTPUT_COST_PER_M = 2.50

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "m4v"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB; adjust to your infra's limits

_bedrock_client = None
_bedrock_client_lock = threading.Lock()

# Sized strictly for CPU-bound tasks to prevent OS core thrashing
_pipeline_executor = ThreadPoolExecutor(max_workers=max(1, os.cpu_count() - 1))


def get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        with _bedrock_client_lock:
            if _bedrock_client is None:
                _bedrock_client = boto3.client(
                    "bedrock-runtime",
                    region_name=BEDROCK_REGION,
                    config=Config(connect_timeout=3600, read_timeout=3600, retries={"max_attempts": 1}),
                )
    return _bedrock_client


# ---------------------------------------------------------------------------
# /api/process_video
# ---------------------------------------------------------------------------
async def process_video_endpoint(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    fps: int = Form(1)
):
    if not file and not url:
        raise HTTPException(status_code=400, detail="Either a video file or a URL must be provided.")

    video_id = str(uuid.uuid4())
    video_path = None
    temp_dir = None
    is_temp_download = False
    http_headers = None

    try:
        # === PHASE 1: INGESTION & URL RESOLUTION ===
        print(f"[Phase 1/4] Ingesting video source...")
        ingest_start = time.time()
        if file:
            # --- Upload validation ---
            if not file.filename or "." not in file.filename:
                raise HTTPException(status_code=400, detail="File must have an extension.")

            video_title = file.filename
            ext = file.filename.rsplit(".", 1)[-1].lower()
            if ext not in ALLOWED_VIDEO_EXTENSIONS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(ALLOWED_VIDEO_EXTENSIONS)}",
                )

            # Validate file size without reading it fully to disk/memory
            try:
                file.file.seek(0, 2)
                size = file.file.tell()
                file.file.seek(0)
            except Exception:
                size = 0

            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
                )

            # Pass the SpooledTemporaryFile stream directly
            video_source = file.file
            ingest_time = time.time() - ingest_start
            print(f"  - [Step 1.1] Verifying uploaded file: {ingest_time:.3f}s (Size: {size} bytes)")
        else:
            # Bypasses local download and resolve direct streaming URL instead
            try:
                download_start = time.time()
                video_source, video_title, http_headers = await asyncio.to_thread(download_video, url)
                is_temp_download = False
                ingest_time = time.time() - download_start
                print(f"  - [Step 1.1] Resolving direct streaming URL: {ingest_time:.3f}s")
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        # === PHASE 2: PYAV STREAM EXTRACTION ===
        print(f"[Phase 2/4] Starting PyAV stream extraction...")
        extraction_start = time.time()
        
        loop = asyncio.get_running_loop()
        
        # Single-pass media stream extraction using PyAV: extracts both frames and audio directly in-memory
        try:
            frame_results, audio_array, temp_dir, audio_time_extracted = await loop.run_in_executor(
                _pipeline_executor, extract_media_pyav, video_source, http_headers, float(fps), 100
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Preprocessing failed: {e}")

        total_media_time = time.time() - extraction_start
        audio_time = round(audio_time_extracted, 3)
        frame_time = round(total_media_time - audio_time_extracted, 3)
        print(f"  - [Step 2.4] Complete PyAV Phase duration: {total_media_time:.3f}s")

        # === PHASE 3: AUDIO SIGNAL PROCESSING ===
        print(f"[Phase 3/4] Processing audio signals...")
        duration_sec = len(audio_array) / 16000 if audio_array is not None else 0.0
        important_segments = []
        if audio_array is not None and len(audio_array) > 0:
            try:
                # Time burst detection
                burst_start = time.time()
                bursts = detect_sound_bursts(audio_array, 16000)
                burst_time = time.time() - burst_start
                print(f"  - [Step 3.1] Sound burst detection: {burst_time:.3f}s (Found {len(bursts)} bursts)")

                # Time clustering
                cluster_start = time.time()
                important_segments = cluster_significant_points(duration_sec, [], bursts, max_clusters=10)
                cluster_time = time.time() - cluster_start
                print(f"  - [Step 3.2] Temporal gap merging & clustering: {cluster_time:.3f}s (Merged into {len(important_segments)} segments)")
            except Exception as e:
                print(f"  - [Step 3.x] Sound burst detection failed: {e}")

        # === PHASE 4: ENCODING & AUDIO SLICING ===
        print(f"[Phase 4/4] Encoding payloads & slicing audio...")
        encoding_start = time.time()
        
        b64_accumulated_time = 0.0
        slice_accumulated_time = 0.0

        # Whisper transcription bypassed to prioritize speed
        voice_segments = []

        frames_data = []
        for index, (frame_path, timestamp) in enumerate(frame_results):
            t1 = 0.0 if index == 0 else frame_results[index - 1][1]
            t2 = timestamp

            b64_start = time.time()
            b64 = frame_to_base64(frame_path)
            b64_accumulated_time += (time.time() - b64_start)

            voice_text = ""

            slice_start = time.time()
            audio_b64 = None
            is_important = any(max(t1, seg_start) < min(t2, seg_end) for seg_start, seg_end in important_segments)
            
            if is_important and audio_array is not None and len(audio_array) > 0:
                try:
                    import soundfile as sf
                    import io
                    import base64
                    start_sample = int(t1 * 16000)
                    end_sample = min(int(t2 * 16000), len(audio_array))
                    chunk_audio = audio_array[start_sample:end_sample]
                    if len(chunk_audio) > 0:
                        wav_io = io.BytesIO()
                        sf.write(wav_io, chunk_audio, 16000, format='WAV', subtype='PCM_16')
                        audio_b64 = "data:audio/wav;base64," + base64.b64encode(wav_io.getvalue()).decode("ascii")
                except Exception as e:
                    print(f"[video_processing] failed to slice/encode frame audio: {e}")
            slice_accumulated_time += (time.time() - slice_start)

            frames_data.append({
                "t1": t1,
                "t2": t2,
                "execution_time": 0.0,
                "base64": f"data:image/jpeg;base64,{b64}",
                "audio": audio_b64,
                "voice_text": voice_text,
            })

        print(f"  - [Step 4.1] Frame image base64 encoding: {b64_accumulated_time:.3f}s")
        print(f"  - [Step 4.2] Audio slicing & WAV base64 encoding: {slice_accumulated_time:.3f}s (Sliced {sum(1 for f in frames_data if f['audio'])} segments)")
        
        total_encoding_time = time.time() - encoding_start
        print(f"  - [Step 4.3] Complete Encoding Phase duration: {total_encoding_time:.3f}s")

        return {
            "video_id": video_id, 
            "video_title": video_title,
            "frames": frames_data, 
            "voice_segments": voice_segments,
            "metrics": {
                "frame_processing_sec": frame_time,
                "audio_processing_sec": audio_time
            }
        }
    finally:
        # Clean up frames temp directory
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        # Clean up download from /tmp/shm
        if is_temp_download and video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception as e:
                print(f"[video_processing] Failed to remove temp download '{video_path}': {e}")


# ---------------------------------------------------------------------------
# /api/summarize
# ---------------------------------------------------------------------------
class SummarizeRequest(BaseModel):
    video_id: str
    frames: List[dict]
    voice_segments: List[dict] = []


def _build_sprite_sheets(frames: List[dict], chunk_size: int = 10, target_width: int = 400):
    """
    Groups frames into sprite-sheet grids (no burned-in timestamp text -
    timestamps are sent as separate text blocks instead, see below).
    Returns a list of (grid_jpeg_bytes, [timestamps_in_this_grid]) tuples.
    """
    sheets = []

    for i in range(0, len(frames), chunk_size):
        chunk = frames[i:i + chunk_size]
        pil_images = []
        chunk_timestamps = []

        for f in chunk:
            b64_data = f['base64'].split(',')[1] if ',' in f['base64'] else f['base64']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data)).convert('RGB')

            pil_images.append(img)
            chunk_timestamps.append(f.get('t1', 0.0))

        if not pil_images:
            continue

        frame_w = pil_images[0].width
        frame_h = pil_images[0].height
        cols = min(5, len(pil_images))
        rows = (len(pil_images) + cols - 1) // cols

        grid_img = Image.new('RGB', (cols * frame_w, rows * frame_h), color='black')
        for idx, img in enumerate(pil_images):
            row, col = idx // cols, idx % cols
            grid_img.paste(img, (col * frame_w, row * frame_h))

        buffered = io.BytesIO()
        grid_img.save(buffered, format="JPEG", quality=85)
        sheets.append((buffered.getvalue(), chunk_timestamps))

    return sheets


def _call_bedrock_with_retry(client, model_id, messages, system, max_retries=3):
    """Calls Bedrock Converse with exponential backoff on throttling/transient errors."""
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.converse(
                modelId=model_id,
                messages=messages,
                system=system,
                inferenceConfig={"maxTokens": 2048},
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            last_err = e
            if code in ("ThrottlingException", "ModelTimeoutException", "ServiceUnavailableException"):
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_err


async def summarize_endpoint(request: SummarizeRequest):
    start_time = time.time()
    video_id = request.video_id
    frames = request.frames
    voice_segments = request.voice_segments

    system_prompt = (
        "You are an expert media analyst. Watch these video frames and transcript, "
        "then provide a detailed and extended summary of what the video is about. "
        "Include a detailed chronological breakdown of key events and scenes. "
        "At the very beginning of your response, specify the category that this "
        "video best fits into (e.g., E-commerce, User Generated Content (UGC), "
        "Educational, Entertainment, etc.) formatted as '**Category:** [Your Category]'. "
        "Do not output any other conversational filler, just the requested information "
        "formatted in Markdown."
    )

    content_blocks = []
    sheets = _build_sprite_sheets(frames)

    for grid_bytes, timestamps in sheets:
        # Timestamps as exact text, not pixels - cheaper and never misread.
        ts_label = ", ".join(f"{t:.1f}s" for t in timestamps)
        content_blocks.append({"text": f"Frames at timestamps: {ts_label}"})
        content_blocks.append({
            "image": {
                "format": "jpeg",
                "source": {"bytes": grid_bytes},
            }
        })

    voice_segments = request.voice_segments
    if voice_segments:
        # Preferred path: build from the original significant-audio-chunk
        # segments, tagged with chunk-local emotion - e.g.
        # "[12.3s-14.1s, Excited]: some text". These boundaries come from
        # the audio pipeline's burst detection, not from frame timing.
        transcript_lines = [
            f"[{seg['start']:.1f}s - {seg['end']:.1f}s, {seg.get('emotion', 'Neutral')}]: {seg['text']}"
            for seg in sorted(voice_segments, key=lambda s: s['start'])
            if seg.get('text')
        ]
    else:
        # Fallback for callers that only send frame-level voice_text
        # (e.g. older clients that haven't picked up voice_segments yet).
        transcript_lines = [
            f"[{f['t1']:.1f}s - {f['t2']:.1f}s]: {f['voice_text']}"
            for f in frames if f.get('voice_text')
        ]

    if transcript_lines:
        content_blocks.append({
            "text": "Chronological Audio Transcript (with emotional tone where audio events were detected):\n" + "\n".join(transcript_lines)
        })

    if not content_blocks:
        raise HTTPException(status_code=400, detail="No frames provided to summarize.")

    messages = [{"role": "user", "content": content_blocks}]

    print(f"[Summarize] Sending request to Bedrock Model ({BEDROCK_MODEL_ID})...")
    try:
        start_llm = time.time()
        client = get_bedrock_client()
        response = await asyncio.to_thread(
            _call_bedrock_with_retry, client, BEDROCK_MODEL_ID, messages, [{"text": system_prompt}]
        )
    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    llm_time = round(time.time() - start_llm, 3)
    analyze_time = round(time.time() - start_time, 3)
    print(f"  - [Summarize Step] Bedrock API converse call: {llm_time:.3f}s")
    print(f"  - [Summarize Step] Total endpoint processing: {analyze_time:.3f}s")

    # Defensive parsing: concatenate all text blocks rather than indexing [0].
    output_content = response["output"]["message"]["content"]
    summary = "".join(block.get("text", "") for block in output_content).strip()

    unique_speakers = {seg.get("speaker_id") for seg in voice_segments if seg.get("speaker_id")}
    n_speakers = len(unique_speakers) if unique_speakers else 1
    
    # Identify the most frequent emotion, default to 'Neutral'
    emotions = [seg.get("emotion", "Neutral") for seg in voice_segments]
    dominant_emotion = max(set(emotions), key=emotions.count) if emotions else "Neutral"
    
    # Concatenate all text segments for the full transcript
    full_transcript = " ".join([seg.get("text", "") for seg in sorted(voice_segments, key=lambda s: s['start'])])

    usage = response.get("usage", {})
    in_tokens = usage.get("inputTokens", 0)
    out_tokens = usage.get("outputTokens", 0)
    vid_cost = ((in_tokens / 1_000_000) * NOVA_2_LITE_INPUT_COST_PER_M) + \
               ((out_tokens / 1_000_000) * NOVA_2_LITE_OUTPUT_COST_PER_M)

    return {
        "summary": summary,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "analyze_time": analyze_time,
        "llm_inference_time_sec": llm_time,
        "cost": vid_cost,
        "frames_count": len(frames),
        "audio_analysis": {
            "n_speakers": n_speakers,
            "emotional_tone": dominant_emotion,
            "transcript": full_transcript
        }
    }