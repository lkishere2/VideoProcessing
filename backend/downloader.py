import os
import re
import yt_dlp

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

def download_video(url: str) -> tuple[str, str, dict]:
    """
    Resolves the direct streaming URL, video title, and HTTP headers using yt_dlp.
    Returns:
        (stream_url, video_title, http_headers)
    """
    url = _extract_url_from_html(url)
    
    ydl_opts = {
        'format': 'best[height<=720]/best',
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': ['android']}},
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            stream_url = info.get('url')
            video_title = info.get('title')
            http_headers = info.get('http_headers', {})
            
            if not stream_url:
                stream_url = url
            if not video_title:
                parsed_url = url.split("?")[0].split("#")[0]
                video_title = os.path.basename(parsed_url) or "Streaming Video"
                
            if not video_title or "." not in video_title:
                video_title = "Streaming Video"
                
            return stream_url, video_title, http_headers
    except Exception as e:
        parsed_url = url.split("?")[0].split("#")[0]
        video_title = os.path.basename(parsed_url) or "Streaming Video"
        return url, video_title, {}
