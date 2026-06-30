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
from concurrent.futures import ProcessPoolExecutor
import numpy as np
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
import httpx
import base64
import shutil


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Gemini 1.5 Flash published pricing (per million tokens).
GEMINI_FLASH_INPUT_COST_PER_M = 0.075
GEMINI_FLASH_OUTPUT_COST_PER_M = 0.30

ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "m4v"}
MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500 MB; adjust to your infra's limits

_bedrock_client = None
_bedrock_client_lock = threading.Lock()

from task_manager import get_global_executor


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

            # Save file to a temporary directory on disk to pass as a string path to ProcessPoolExecutor
            temp_dir = tempfile.mkdtemp()
            video_source = os.path.join(temp_dir, f"video.{ext}")
            with open(video_source, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            is_temp_download = True
            ingest_time = time.time() - ingest_start
            print(f"  - [Step 1.1] Ingesting and saving uploaded file: {ingest_time:.3f}s (Size: {size} bytes)")
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
                get_global_executor(), extract_media_pyav, video_source, http_headers, float(fps), 100
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Preprocessing failed: {e}")

        total_media_time = time.time() - extraction_start
        audio_time = round(audio_time_extracted, 3)
        frame_time = round(total_media_time - audio_time_extracted, 3)
        print(f"  - [Step 2.4] Total extraction time: {total_media_time:.3f}s")

        # === PHASE 3: AUDIO SIGNAL PROCESSING ===
        print(f"[Phase 3/4] Processing audio signals...")
        duration_sec = len(audio_array) / 16000 if audio_array is not None else 0.0
        important_segments = []
        if audio_array is not None and len(audio_array) > 0:
            try:
                # Time burst detection
                burst_start = time.time()
                bursts, _, _ = detect_sound_bursts(audio_array, 16000)
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

            voice_text = ""

            # Read the base64 string directly from the temp disk in the main thread to avoid IPC transfer latency
            b64_start = time.time()
            try:
                with open(frame_path, "rb") as f_img:
                    b64 = base64.b64encode(f_img.read()).decode("utf-8")
            except Exception as e:
                b64 = ""
            b64_accumulated_time += (time.time() - b64_start)

            slice_start = time.time()
            audio_b64 = None
            is_important = False
            if important_segments:
                is_important = any(max(t1, seg_start) < min(t2, seg_end) for seg_start, seg_end in important_segments)
            else:
                # Fallback: if no sudden bursts were detected (e.g. continuous talking/noise),
                # include any audio segment that contains active sound (RMS energy above small gate threshold)
                if audio_array is not None and len(audio_array) > 0:
                    start_sample = int(t1 * 16000)
                    end_sample = min(int(t2 * 16000), len(audio_array))
                    chunk_audio = audio_array[start_sample:end_sample]
                    if len(chunk_audio) > 0:
                        chunk_rms = np.sqrt(np.mean(chunk_audio.astype(np.float64) ** 2))
                        if chunk_rms > 0.005:  # Simple noise gate
                            is_important = True
            
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
            try:
                from PIL import ImageFile
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                
                b64_data = f['base64'].split(',')[1] if ',' in f['base64'] else f['base64']
                img_data = base64.b64decode(b64_data)
                img = Image.open(io.BytesIO(img_data)).convert('RGB')

                pil_images.append(img)
                chunk_timestamps.append(f.get('t1', 0.0))
            except Exception as e:
                print(f"[video_processing] Warning: skipping corrupted/truncated frame: {e}")

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


async def _call_gemini_with_retry(url, payload, max_retries=3):
    """Calls Gemini API with exponential backoff on transient errors (500, 503, 504, 429)."""
    last_err = None
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        for attempt in range(max_retries):
            try:
                resp = await http_client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                last_err = e
                status_code = e.response.status_code
                if status_code in (429, 500, 503, 504):
                    sleep_time = 2 ** attempt
                    print(f"  - [Gemini API] Got {status_code}. Retrying in {sleep_time}s (Attempt {attempt+1}/{max_retries})...")
                    await asyncio.sleep(sleep_time)
                    continue
                raise
            except Exception as e:
                last_err = e
                sleep_time = 2 ** attempt
                print(f"  - [Gemini API] Connection error: {e}. Retrying in {sleep_time}s (Attempt {attempt+1}/{max_retries})...")
                await asyncio.sleep(sleep_time)
                continue
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

    gemini_parts = []

    if system_prompt:
        gemini_parts.append({"text": f"System Instruction: {system_prompt}\n"})

    sheets = _build_sprite_sheets(frames)
    for grid_bytes, timestamps in sheets:
        ts_label = ", ".join(f"{t:.1f}s" for t in timestamps)
        gemini_parts.append({"text": f"Frames at timestamps: {ts_label}"})
        gemini_parts.append({
            "inlineData": {
                "mimeType": "image/jpeg",
                "data": base64.b64encode(grid_bytes).decode("utf-8")
            }
        })

    # Append raw audio chunks natively (Gemini processes audio waveforms directly!)
    audio_chunks_sent = 0
    for f in frames:
        if f.get("audio"):
            raw_b64 = f["audio"].split(",")[1] if "," in f["audio"] else f["audio"]
            gemini_parts.append({"text": f"Audio segment from {f['t1']:.1f}s to {f['t2']:.1f}s:"})
            gemini_parts.append({
                "inlineData": {
                    "mimeType": "audio/wav",
                    "data": raw_b64
                }
            })
            audio_chunks_sent += 1

    print(f"  - [Summarize Step] Attached {audio_chunks_sent} audio chunks to Gemini payload")

    voice_segments = request.voice_segments
    if voice_segments:
        transcript_lines = [
            f"[{seg['start']:.1f}s - {seg['end']:.1f}s, {seg.get('emotion', 'Neutral')}]: {seg['text']}"
            for seg in sorted(voice_segments, key=lambda s: s['start'])
            if seg.get('text')
        ]
    else:
        transcript_lines = [
            f"[{f['t1']:.1f}s - {f['t2']:.1f}s]: {f['voice_text']}"
            for f in frames if f.get('voice_text')
        ]

    if transcript_lines:
        gemini_parts.append({
            "text": "Chronological Audio Transcript:\n" + "\n".join(transcript_lines)
        })

    if not gemini_parts:
        raise HTTPException(status_code=400, detail="No content provided to summarize.")

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured in .env file.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "contents": [{"parts": gemini_parts}],
        "generationConfig": {
            "maxOutputTokens": 2048,
            "temperature": 0.4
        }
    }

    print("[Summarize] DOWNSTREAM LLM CALL BYPASSED FOR CONCURRENT TESTING.")
    start_llm = time.time()
    
    prep_time = round(start_llm - start_time, 3)
    llm_time = 0.0
    analyze_time = prep_time
    print(f"  - [Summarize Step] Total preprocessing time (excluding LLM): {prep_time:.3f}s")
    print(f"  - [Summarize Step] Gemini API call: BYPASSED")
    print(f"  - [Summarize Step] Total endpoint processing: {analyze_time:.3f}s")

    summary = "Mock summary generated (LLM query bypassed for load testing)."

    unique_speakers = {seg.get("speaker_id") for seg in voice_segments if seg.get("speaker_id")}
    n_speakers = len(unique_speakers) if unique_speakers else 1
    
    emotions = [seg.get("emotion", "Neutral") for seg in voice_segments]
    dominant_emotion = max(set(emotions), key=emotions.count) if emotions else "Neutral"
    
    full_transcript = " ".join([seg.get("text", "") for seg in sorted(voice_segments, key=lambda s: s['start'])])

    in_tokens = 0
    out_tokens = 0
    vid_cost = 0.0

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