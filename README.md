# Video Insight Engine

A full-stack application that analyzes videos by intelligently extracting frames and utilizing the **Claude 3.5 Sonnet Vision API** to generate comprehensive, timestamped summaries of visual action.

## 🏗️ Architecture & Workflow

The architecture is split into a **Vite React Frontend** and a **FastAPI Python Backend**. 

1. **Upload & Queue**: Users drag-and-drop multiple `.mp4` videos into the Frontend.
2. **Parallel Extraction**: The frontend asynchronously streams the files to the Backend via the `/api/process_video` endpoint.
3. **Dynamic FFmpeg Processing**: The Backend uses `ffprobe` to scan the video's exact duration and mathematically scales the extraction framerate. It extracts a mathematically perfect, evenly spaced sequence of pictures up to a strict maximum of **50 frames**, regardless of whether the video is 10 seconds or 10 minutes long.
4. **Base64 Conversion**: The backend instantly encodes these 50 images into raw `Base64` strings and returns them to the frontend so they can be visually verified by the user in the UI.
5. **Sprite Sheet Optimization**: The frontend hits the `/api/summarize` endpoint, passing the 50 Base64 images. To prevent token bloat and save massive API costs, the backend dynamically uses the `Pillow` library to resize the pictures, stamp exact chronological timestamps (e.g., `T: 12.0s`) onto them, and digitally stitch them into **5x2 Image Grids** (Sprite Sheets). 
6. **Result Generation**: Claude only receives 5 stitched pictures instead of 50 individual ones. It generates a chronological summary of the video. The backend saves a persistent markdown copy to the `outputs/output.md` file, while the frontend dynamically displays the summary, total time elapsed, and exact API cost.

*Note: The backend also contains modules for local AI execution (`vision_processing.py` [Moondream2] and `voice_processing.py` [Whisper]). These are currently decoupled and bypassed to prioritize Claude Vision stability and cost optimizations, but are fully intact for future development.*

---

## 🚀 How to Run

### Prerequisites
You must have **FFmpeg** installed on your system.

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS (using Homebrew):**
```bash
brew install ffmpeg
```

**Windows:**
1. Download a pre-built FFmpeg release (e.g., from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)).
2. Extract the archive and copy the `bin` folder contents to a directory (e.g., `C:\ffmpeg\bin`).
3. Add that directory to your System PATH environment variable.

### 1. Start the Backend
The backend runs in an isolated Python virtual environment.

**On macOS and Linux:**
```bash
# From the project root, create a virtual environment (only needed once)
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

cd backend

# Install Python dependencies (only needed once)
pip install -r requirements.txt

# Start the FastAPI Server (binds to all network interfaces for --host testing)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**On Windows:**
```powershell
# From the project root, create a virtual environment (only needed once)
python -m venv venv

# Activate the virtual environment
.\venv\Scripts\activate

cd backend

# Install Python dependencies (only needed once)
pip install -r requirements.txt

# Start the FastAPI Server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
*Make sure you have an `.env` file in the root containing your `ANTHROPIC_API_KEY`!*

### 2. Start the Frontend
Open a new terminal window to run the React development server.
```bash
cd frontend

# Install Node dependencies (only needed once)
npm install

# Start the Vite Server
npm run dev
```

You can now open `http://localhost:5173` in your browser to access the dashboard!

---

## 🔒 Security Notes
- **`.env` Leakage**: Your `ANTHROPIC_API_KEY` is completely safe. It is only read by the Python Backend via `dotenv`. The Vite Frontend completely ignores it because it lacks the `VITE_` prefix, guaranteeing your secret keys are never exposed in the browser's client-side javascript. Furthermore, `.env` is secured inside your `.gitignore`.
- **Ephemeral Storage**: Uploaded videos are heavily secured. They are saved temporarily using Python's `tempfile` module and completely wiped from the disk the exact millisecond extraction finishes, preventing your hard drive from bloating.
