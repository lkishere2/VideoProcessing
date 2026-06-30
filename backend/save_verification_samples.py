import os
import sys
import base64
sys.path.insert(0, '/home/twoseepeakay/VideoProcessing/.venv/lib/python3.12/site-packages')

from batch_extractor import extract_single_video

def main():
    video_dir = "/home/twoseepeakay/VideoProcessing/videos"
    output_dir = "/home/twoseepeakay/VideoProcessing/verification_samples"
    os.makedirs(output_dir, exist_ok=True)

    # Grab the first available video file
    video_files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
    if not video_files:
        print(f"Error: No video files found in {video_dir}")
        return

    sample_video = os.path.join(video_dir, video_files[0])
    print(f"Extracting sample video: {sample_video}")

    result = extract_single_video(sample_video)
    frames = result.get("frames", [])

    print(f"Extracted {len(frames)} segments. Saving to disk...")

    for idx, f in enumerate(frames):
        # 1. Save frame image
        img_b64 = f["base64"].split(",")[1] if "," in f["base64"] else f["base64"]
        img_path = os.path.join(output_dir, f"segment_{idx}_time_{f['t2']:.1f}s.jpg")
        with open(img_path, "wb") as img_file:
            img_file.write(base64.b64decode(img_b64))

        # 2. Save audio WAV (if present)
        if f.get("audio"):
            aud_b64 = f["audio"].split(",")[1] if "," in f["audio"] else f["audio"]
            aud_path = os.path.join(output_dir, f"segment_{idx}_time_{f['t2']:.1f}s.wav")
            with open(aud_path, "wb") as aud_file:
                aud_file.write(base64.b64decode(aud_b64))
            print(f" -> Saved segment {idx}: JPG + WAV (Timestamp: {f['t1']:.1f}s - {f['t2']:.1f}s)")
        else:
            print(f" -> Saved segment {idx}: JPG only (Silent segment) (Timestamp: {f['t1']:.1f}s - {f['t2']:.1f}s)")

    print(f"\nVerification samples written successfully to: {output_dir}")

if __name__ == "__main__":
    main()
