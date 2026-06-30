import os
import sys
import base64
sys.path.insert(0, '/home/twoseepeakay/VideoProcessing/.venv/lib/python3.12/site-packages')

from batch_extractor import extract_single_video

def main():
    video_dir = "/home/twoseepeakay/VideoProcessing/videos"
    output_dir = "/home/twoseepeakay/VideoProcessing/batch_verification"
    os.makedirs(output_dir, exist_ok=True)

    # Grab the first 10 available video files
    video_files = sorted([f for f in os.listdir(video_dir) if f.endswith(".mp4")])
    if not video_files:
        print(f"Error: No video files found in {video_dir}")
        return

    selected_files = video_files[:10]
    print(f"Running extraction on {len(selected_files)} sample videos and saving results to disk...")

    for v_idx, v_name in enumerate(selected_files):
        video_path = os.path.join(video_dir, v_name)
        video_uuid = os.path.splitext(v_name)[0]
        video_out_dir = os.path.join(output_dir, video_uuid)
        os.makedirs(video_out_dir, exist_ok=True)
        
        print(f"\n[{v_idx+1}/{len(selected_files)}] Processing: {v_name}")
        
        try:
            result = extract_single_video(video_path)
            frames = result.get("frames", [])
            
            success_frames = 0
            success_audio = 0
            
            for idx, f in enumerate(frames):
                # Save JPG
                img_b64 = f["base64"].split(",")[1] if "," in f["base64"] else f["base64"]
                img_path = os.path.join(video_out_dir, f"frame_{idx}_at_{f['t2']:.1f}s.jpg")
                with open(img_path, "wb") as img_file:
                    img_file.write(base64.b64decode(img_b64))
                success_frames += 1

                # Save WAV
                if f.get("audio"):
                    aud_b64 = f["audio"].split(",")[1] if "," in f["audio"] else f["audio"]
                    aud_path = os.path.join(video_out_dir, f"audio_{idx}_at_{f['t2']:.1f}s.wav")
                    with open(aud_path, "wb") as aud_file:
                        aud_file.write(base64.b64decode(aud_b64))
                    success_audio += 1
            
            print(f" -> Success: saved {success_frames} JPEGs and {success_audio} WAVs to {video_out_dir}")
        except Exception as e:
            print(f" -> FAILED to process {v_name}: {e}")

    print(f"\nAll verification files written to: {output_dir}")

if __name__ == "__main__":
    main()
