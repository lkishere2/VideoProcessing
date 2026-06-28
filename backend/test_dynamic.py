import subprocess
import re

video_path = "test_video.mp4" # Let's create a dummy video first
subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10", "-y", video_path], capture_output=True)

command = [
    "ffmpeg", "-i", video_path,
    "-vf", "scdet=s=1,metadata=print:file=-",
    "-f", "null", "-"
]
process = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
stdout, stderr = process.communicate()

for line in stdout.splitlines()[:20]:
    print("OUT:", line)
for line in stderr.splitlines()[-20:]:
    print("ERR:", line)
