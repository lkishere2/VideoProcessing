import os, sys, time

# Ensure project root is on sys.path (this file lives in the project root)
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.batch_extractor import extract_single_video

links_file = os.path.join(project_root, 'stream_links.txt')
with open(links_file, 'r') as f:
    first_url = next((line.strip() for line in f if line.strip()), None)

if not first_url:
    print('No URL found in stream_links.txt')
    sys.exit(1)

start = time.perf_counter()
result = extract_single_video(first_url)
elapsed = time.perf_counter() - start

print(f'Processed first URL: {first_url}')
print(f'Elapsed time: {elapsed:.3f} seconds')
print('Result keys:', result.keys() if isinstance(result, dict) else type(result))
