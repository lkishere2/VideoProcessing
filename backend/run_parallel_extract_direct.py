import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

# Dynamically locate and prepend active virtual environment's site-packages and local backend path
_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _script_dir)

_venv_base = os.path.join(os.path.dirname(_script_dir), ".venv")
if os.path.exists(os.path.join(_venv_base, "pyvenv.cfg")):
    _site_pkgs = os.path.join(_venv_base, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.exists(_site_pkgs):
        sys.path.insert(0, _site_pkgs)
    else:
        # Fallback to any python version site-packages in the venv (append to the end to let 3.12 native paths take precedence)
        _lib_dir = os.path.join(_venv_base, "lib")
        if os.path.exists(_lib_dir):
            for _py_ver in sorted(os.listdir(_lib_dir), reverse=True):
                _fallback_pkgs = os.path.join(_lib_dir, _py_ver, "site-packages")
                if os.path.exists(_fallback_pkgs):
                    sys.path.append(_fallback_pkgs)
                    break

from batch_extractor import extract_single_video, _preload_libs

def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    dest_folder = "/home/twoseepeakay/VideoProcessing/videos"
    
    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()][:1000]

    # Use the URLs directly (network streams) – no local path conversion
    local_paths = urls

    total_files = len(local_paths)
    print(f"Starting direct SSD extraction on {total_files} videos...")
    print("This bypasses FastAPI/HTTP network and GIL serialization bottleneck completely!\n")

    start_time = time.time()
    max_workers = 11

    # Utilize parallel processes directly on the SSD
    with ProcessPoolExecutor(
        max_workers=max_workers,
        initializer=_preload_libs
    ) as executor:
        futures = [executor.submit(extract_single_video, path) for path in local_paths]
        results = [fut.result() for fut in futures]

    total_time = time.time() - start_time
    successes = sum(1 for r in results if r and r.get("frames"))
    throughput = total_files / total_time if total_time > 0 else 0

    print("\n" + "="*50)
    print("DIRECT LOCAL SSD BENCHMARK RESULTS (FASTAPI BYPASSED)")
    print("="*50)
    print(f"Parallel Processes     : {max_workers}")
    print(f"Total Videos Processed : {total_files}")
    print(f"Done in                : {total_time:.3f} seconds")
    print(f"Direct Throughput      : {throughput:.3f} videos/second")
    print(f"Success Rate           : {(successes/total_files)*100:.2f}% ({successes}/{total_files})")
    print("="*50)

if __name__ == "__main__":
    main()
