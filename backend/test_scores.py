import subprocess
import re

subprocess.run(["ffmpeg", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10", "-y", "test_video.mp4"], capture_output=True)

print("--- select gte scene ---")
command1 = ["ffmpeg", "-i", "test_video.mp4", "-vf", "select='gte(scene,0)',showinfo", "-an", "-f", "null", "-"]
p1 = subprocess.run(command1, capture_output=True, text=True)
for line in p1.stderr.splitlines():
    if "scene" in line.lower() or "lavfi" in line.lower() or "showinfo" in line:
        print(line)
        
print("--- scdet ---")
command2 = ["ffmpeg", "-i", "test_video.mp4", "-vf", "scdet=s=0,showinfo", "-an", "-f", "null", "-"]
p2 = subprocess.run(command2, capture_output=True, text=True)
for line in p2.stderr.splitlines():
    if "scd" in line.lower() or "lavfi" in line.lower() or "showinfo" in line:
        print(line)
