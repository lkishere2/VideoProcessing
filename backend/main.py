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

# Register routes
app.post("/api/process_video")(process_video_endpoint)
app.post("/api/summarize")(summarize_endpoint)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)