"""
FastAPI app entrypoint.

Fix applied vs. the original draft:
  - CORS no longer uses allow_origins=["*"] with allow_methods=["*"] on an
    endpoint that accepts file uploads and triggers a paid model call.
    That combination lets any website embed a script that uploads videos
    through this server and runs up your AWS/Bedrock bill. Origins are now
    read from an environment variable allowlist - set ALLOWED_ORIGINS to a
    comma-separated list of your actual frontend origin(s) before deploying.
"""

import os
import sys

# Dynamically locate and prepend active virtual environment's site-packages and local backend path
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

_venv_base = os.path.join(os.path.dirname(_script_dir), ".venv")
if os.path.exists(os.path.join(_venv_base, "pyvenv.cfg")):
    _site_pkgs = os.path.join(_venv_base, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.exists(_site_pkgs):
        sys.path.insert(0, _site_pkgs)
    else:
        # Fallback to any python version site-packages in the venv (append to the end to let native paths take precedence)
        _lib_dir = os.path.join(_venv_base, "lib")
        if os.path.exists(_lib_dir):
            for _py_ver in sorted(os.listdir(_lib_dir), reverse=True):
                _fallback_pkgs = os.path.join(_lib_dir, _py_ver, "site-packages")
                if os.path.exists(_fallback_pkgs):
                    sys.path.append(_fallback_pkgs)
                    break

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

from video_processing import process_video_endpoint, summarize_endpoint

load_dotenv()

app = FastAPI()

# Read allowed origins from environment; default to localhost dev origins
# only. NEVER default to "*" in an app that triggers paid API calls.
_allowed_origins_env = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

from pydantic import BaseModel
from typing import List
import asyncio
from batch_extractor import process_batch

class BatchRequest(BaseModel):
    urls: List[str]

# Register routes
app.post("/api/process_video")(process_video_endpoint)
app.post("/api/summarize")(summarize_endpoint)

_request_semaphore = asyncio.Semaphore(8)

@app.post("/api/batch_extract")
async def batch_extract_endpoint(request: BatchRequest):
    async with _request_semaphore:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, process_batch, request.urls)
        return {"results": results, "total": len(results)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)