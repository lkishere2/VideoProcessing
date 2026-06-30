import asyncio
import os
import time
import httpx

async def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    dest_folder = "/home/twoseepeakay/VideoProcessing/videos"
    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    # Convert URLs to local SSD filepaths
    local_paths = []
    for url in urls:
        filename = os.path.basename(url.split("?")[0].split("#")[0])
        if filename:
            local_paths.append(os.path.join(dest_folder, filename))

    # Benchmark on the full 1000 local files
    total_files = len(local_paths)
    print(f"[SSD Benchmark] Mapped {total_files} local SSD filepaths.")
    print("Sending batch request to local API...")

    start_total = time.time()
    
    # 180s timeout
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(
                'http://localhost:8000/api/batch_extract',
                json={'urls': local_paths}
            )
            total_time = time.time() - start_total
            if resp.status_code == 200:
                res = resp.json()
                results = res.get("results", [])
                successes = sum(1 for r in results if r and r.get("frames"))
                failures = total_files - successes
                throughput = total_files / total_time if total_time > 0 else 0
                
                print("\n" + "="*50)
                print("LOCAL SSD BATCH BENCHMARK RESULTS")
                print("="*50)
                print(f"Total Videos Processed : {total_files}")
                print(f"Total Execution Time   : {total_time:.3f} seconds")
                print(f"System Throughput      : {throughput:.3f} videos/second")
                print(f"Success Rate           : {(successes/total_files)*100:.2f}% ({successes} successes, {failures} failures)")
                print("="*50)
            else:
                print(f"Failed with HTTP {resp.status_code}: {resp.text[:500]}")
        except Exception as e:
            print(f"Batch request failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
