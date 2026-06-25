import os
import shutil
import uuid
import time
import tempfile
import base64
import io
from fastapi import UploadFile, File, Form
from typing import List
from pydantic import BaseModel
import anthropic
from PIL import Image, ImageDraw, ImageFont

from frame_processing import extract_frames, frame_to_base64
from voice_processing import extract_audio, transcribe_audio

async def process_video_endpoint(file: UploadFile = File(...), fps: int = Form(1)):
    video_id = str(uuid.uuid4())
    
    with tempfile.TemporaryDirectory() as temp_dir:
        ext = file.filename.split(".")[-1]
        video_path = os.path.join(temp_dir, f"video.{ext}")
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        frame_results = extract_frames(video_path, temp_dir, max_frames=50)
        
        audio_path = extract_audio(video_path, temp_dir)
        voice_segments = transcribe_audio(audio_path)
        
        frames_data = []
        for index, (frame_path, timestamp) in enumerate(frame_results):
            t1 = 0.0 if index == 0 else frame_results[index - 1][1]
            t2 = timestamp
            
            b64 = frame_to_base64(frame_path)
            
            # Find all audio segments that overlap with the [t1, t2] window
            chunk_voice = []
            for seg in voice_segments:
                seg_start = seg.get("start", 0.0)
                seg_end = seg.get("end", 0.0)
                # Overlap logic: max(t1, start) < min(t2, end)
                if max(t1, seg_start) < min(t2, seg_end):
                    chunk_voice.append(seg.get("text", "").strip())
            
            voice_text = " ".join(chunk_voice).strip()
            
            frames_data.append({
                "t1": t1,
                "t2": t2,
                "execution_time": 0.0,
                "base64": f"data:image/jpeg;base64,{b64}",
                "voice_text": voice_text
            })
            
    return {"video_id": video_id, "frames": frames_data}


class SummarizeRequest(BaseModel):
    video_id: str
    frames: List[dict]

async def summarize_endpoint(request: SummarizeRequest):
    start_time = time.time()
    video_id = request.video_id
    frames = request.frames
    
    content_blocks = [
        {
            "type": "text",
            "text": "Watch these video frames and transcript, then provide a detailed and extended summary of what the video is about. Please include a detailed chronological breakdown of key events and scenes. Also, at the very beginning of your response, specify the category that this video best fits into (e.g., E-commerce, User Generated Content (UGC), Educational, Entertainment, etc.) formatted as '**Category:** [Your Category]'. Do not output any other conversational filler, just the requested information formatted in Markdown."
        }
    ]
    
    # Process frames into 5x2 sprite sheets
    chunk_size = 10
    target_width = 400
    
    for i in range(0, len(frames), chunk_size):
        chunk = frames[i:i + chunk_size]
        pil_images = []
        
        for f in chunk:
            b64_data = f['base64'].split(',')[1] if ',' in f['base64'] else f['base64']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data)).convert('RGB')
            
            # Resize image to save bandwidth
            aspect = img.height / img.width
            new_h = int(target_width * aspect)
            img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            
            # Draw timestamp
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()
            t1 = f.get('t1', 0.0)
            text = f"T: {t1:.1f}s"
            
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            
            # Draw black background for text visibility
            draw.rectangle([0, 0, text_w + 10, text_h + 10], fill="black")
            draw.text((5, 5), text, fill="white", font=font)
            
            pil_images.append(img)
            
        if not pil_images:
            continue
            
        frame_w = pil_images[0].width
        frame_h = pil_images[0].height
        
        # Grid logic: Max 5 columns
        cols = min(5, len(pil_images))
        rows = (len(pil_images) + cols - 1) // cols
        
        grid_w = cols * frame_w
        grid_h = rows * frame_h
        
        grid_img = Image.new('RGB', (grid_w, grid_h), color='black')
        
        for idx, img in enumerate(pil_images):
            row = idx // cols
            col = idx % cols
            grid_img.paste(img, (col * frame_w, row * frame_h))
            
        # Convert back to Base64
        buffered = io.BytesIO()
        grid_img.save(buffered, format="JPEG", quality=85)
        grid_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": grid_b64
            }
        })
        
    # Append the chronological audio transcript timeline
    transcript_lines = []
    for f in frames:
        if f.get('voice_text'):
            transcript_lines.append(f"[{f['t1']:.1f}s - {f['t2']:.1f}s]: {f['voice_text']}")
            
    if transcript_lines:
        transcript_block = "Chronological Audio Transcript:\n" + "\n".join(transcript_lines)
        content_blocks.append({
            "type": "text",
            "text": transcript_block
        })

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": content_blocks
            }],
        )
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=str(e))

    analyze_time = time.time() - start_time
    summary = response.content[0].text.strip()

    in_tokens = response.usage.input_tokens
    out_tokens = response.usage.output_tokens
    vid_cost = ((in_tokens / 1_000_000) * 3.00) + ((out_tokens / 1_000_000) * 15.00)

    return {
        "summary": summary,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "analyze_time": analyze_time,
        "cost": vid_cost,
        "frames_count": len(frames)
    }