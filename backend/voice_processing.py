import os
import ffmpeg
import whisper

# Load model globally
model = None

def get_whisper_model():
    global model
    if model is None:
        print("Loading Whisper Model...")
        model = whisper.load_model("tiny", device="cpu")
    return model

def extract_audio(video_path: str, temp_dir: str) -> str:
    audio_path = os.path.join(temp_dir, "audio.wav")
    try:
        (
            ffmpeg
            .input(video_path)
            .output(audio_path, ac=1, ar=16000)
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error:
        # Video might not have audio
        return None
    return audio_path if os.path.exists(audio_path) else None

def transcribe_audio(audio_path: str):
    if not audio_path:
        return []
    model = get_whisper_model()
    result = model.transcribe(audio_path)
    return result.get("segments", [])
