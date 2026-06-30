import os
from concurrent.futures import ThreadPoolExecutor

# Preload target libs globally inside the main process so threads share them immediately
import av
import numpy
import PIL.Image
import soundfile
import io
import base64
import simplejpeg

_global_executor = None

def get_global_executor():
    global _global_executor
    if _global_executor is None:
        # Scale to 240 workers (20 per core) for maximum network pipe saturation.
        _global_executor = ThreadPoolExecutor(
            max_workers=240
        )
    return _global_executor
