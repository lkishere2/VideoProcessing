import asyncio
import os
import time
import httpx

async def send_chunk_request(client, chunk_paths, chunk_id):
    url = 'http://localhost:8000/api/batch_extract'
    start = time.time()
    try:
        resp = await client.post(url, json={'urls': chunk_paths})
        elapsed = time.time() - start
        if resp.status_code == 200:
            res = resp.json()
            results = res.get("results", [])
            successes = sum(1 for r in results if r and r.get("frames"))
            print(f"[Process-{chunk_id}] Completed 100 videos in {elapsed:.2f}s (Success: {successes}/100)")
            return successes
        else:
            print(f"[Process-{chunk_id}] Failed with HTTP {resp.status_code}: {resp.text[:200]}")
            return 0
    except Exception as e:
        print(f"[Process-{chunk_id}] Request failed: {e}")
        return 0

async def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    dest_folder = "/home/twoseepeakay/VideoProcessing/videos"
    
    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()][:1000]

    # Map to local SSD filepaths
    local_paths = []
    for u in urls:
        filename = os.path.basename(u.split("?")[0].split("#")[0])
        if filename:
            local_paths.append(os.path.join(dest_folder, filename))

    total_files = len(local_paths)
    chunk_size = 100
    chunks = [local_paths[i:i + chunk_size] for i in range(0, total_files, chunk_size)]

    print(f"Dividing {total_files} local SSD videos into {len(chunks)} parallel client processes (100 videos per process)...")
    print("Saving extracted frames and WAV audio files directly to SSD under extracted_assets/...\n")

    start_time = time.time()

    # Dispatch 10 requests concurrently
    async with httpx.AsyncClient(timeout=180.0) as client:
        tasks = [
            send_chunk_request(client, chunk, idx + 1)
            for idx, chunk in enumerate(chunks)
        ]
        results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    total_successes = sum(results)
    throughput = total_files / total_time if total_time > 0 else 0

    print("\n" + "="*50)
    print("10-PROCESS PARALLEL BATCH BENCHMARK RESULTS")
    print("="*50)
    print(f"Total Videos Processed : {total_files}")
    print(f"Total Execution Time   : {total_time:.3f} seconds")
    print(f"Average Throughput     : {throughput:.3f} videos/second")
    print(f"Total Successes        : {total_successes}/{total_files} successfully saved to SSD")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
