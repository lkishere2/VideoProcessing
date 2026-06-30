import asyncio
import os
import time
import httpx

# Concurrency limit to prevent overwhelming the LAN connection
MAX_CONCURRENT_DOWNLOADS = 15

async def download_file(client, url, dest_folder, semaphore, idx, total):
    async with semaphore:
        filename = os.path.basename(url.split("?")[0].split("#")[0])
        if not filename:
            filename = f"video_{idx}.mp4"
        
        dest_path = os.path.join(dest_folder, filename)
        
        # Check if already exists to resume/skip
        if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
            return True

        start = time.time()
        for attempt in range(3):
            try:
                # Direct stream read to write to SSD chunk-by-chunk to save RAM
                async with client.stream("GET", url) as response:
                    if response.status_code == 200:
                        with open(dest_path, "wb") as f:
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                f.write(chunk)
                        
                        elapsed = time.time() - start
                        size = os.path.getsize(dest_path)
                        print(f"[{idx}/{total}] Downloaded {filename} ({size/1024/1024:.2f} MB) in {elapsed:.2f}s")
                        return True
            except Exception as e:
                print(f"[{idx}/{total}] Attempt {attempt+1} failed for {filename}: {e}")
                await asyncio.sleep(1)
        
        # Remove partial file if failed
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except:
                pass
        return False

async def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    dest_folder = "/home/twoseepeakay/VideoProcessing/videos"
    os.makedirs(dest_folder, exist_ok=True)

    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()][:1000]

    total = len(urls)
    print(f"Starting batch download of {total} videos to {dest_folder}...")
    start_time = time.time()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    
    # Use HTTPX client with long timeout and keep-alive pool
    limits = httpx.Limits(max_keepalive_connections=MAX_CONCURRENT_DOWNLOADS, max_connections=MAX_CONCURRENT_DOWNLOADS * 2)
    async with httpx.AsyncClient(limits=limits, timeout=60.0) as client:
        tasks = [
            download_file(client, url, dest_folder, semaphore, idx + 1, total)
            for idx, url in enumerate(urls)
        ]
        results = await asyncio.gather(*tasks)

    successes = sum(1 for r in results if r)
    elapsed_total = time.time() - start_time
    print(f"\nCompleted! Downloaded {successes}/{total} successfully in {elapsed_total:.2f} seconds.")

if __name__ == "__main__":
    asyncio.run(main())
