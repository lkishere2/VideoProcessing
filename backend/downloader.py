import os
import uuid
import yt_dlp

import re

def _extract_url_from_html(text: str) -> str:
    text = text.strip()
    if text.startswith("<"):
        # Match cite="url" or href="url"
        cite_match = re.search(r'cite=["\'](https?://[^"\']+)["\']', text)
        if cite_match:
            return cite_match.group(1)
        href_match = re.search(r'href=["\'](https?://[^"\']+)["\']', text)
        if href_match:
            return href_match.group(1)
    return text

def download_video(url: str) -> str:
    """
    Downloads a video from a URL using the yt_dlp python library directly,
    writing it into /dev/shm (RAM-disk) under a unique name.
    Enforces a maximum resolution of 720p and a max size limit of 100MB to prevent OOM.
    Returns the path to the downloaded file in RAM.
    """
    url = _extract_url_from_html(url)
    shm_dir = "/dev/shm"
    if not os.path.exists(shm_dir):
        # Fallback to standard temp directory if /dev/shm is not available
        import tempfile
        shm_dir = tempfile.gettempdir()

    video_id = str(uuid.uuid4())
    output_template = os.path.join(shm_dir, f"{video_id}.%(ext)s")

    # yt-dlp configurations
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        'merge_output_format': 'mp4',
        'max_filesize': 100 * 1024 * 1024, # 100 MB
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_title = info.get('title', 'Video from URL')
    except Exception as e:
        raise RuntimeError(f"Failed to download video: {e}")

    # Find the downloaded file
    for file in os.listdir(shm_dir):
        if file.startswith(video_id) and file.endswith(".mp4"):
            return os.path.join(shm_dir, file), video_title

    raise RuntimeError("Failed to locate downloaded file in RAM.")
