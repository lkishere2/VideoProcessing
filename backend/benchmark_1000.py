import asyncio
import os
import time
import httpx

async def worker(sem, client, url, stats, idx):
    async with sem:
        start = time.time()
        try:
            # Send HTTP POST request to the local FastAPI server
            resp = await client.post(
                'http://localhost:8000/api/process_video',
                data={'url': url, 'fps': 1},
                timeout=60.0
            )
            duration = time.time() - start
            if resp.status_code == 200:
                stats["durations"].append(duration)
                stats["success"] += 1
            else:
                stats["failures"] += 1
                stats["errors"].append(f"HTTP {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            duration = time.time() - start
            stats["failures"] += 1
            stats["errors"].append(str(e))
            
        stats["processed"] += 1
        if stats["processed"] % 50 == 0 or stats["processed"] == stats["total"]:
            avg_time = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
            print(f"[Benchmark] Progress: {stats['processed']}/{stats['total']} URLs processed. "
                  f"Avg Time: {avg_time:.3f}s. Successes: {stats['success']}. Failures: {stats['failures']}.")

async def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()]

    total_urls = len(urls)
    print(f"[Benchmark] Loaded {total_urls} URLs from stream_links.txt. Starting concurrent execution...")
    
    # Use semaphore to control concurrency (e.g. 8 concurrent requests to match system cores)
    concurrency_limit = 8
    sem = asyncio.Semaphore(concurrency_limit)
    
    stats = {
        "processed": 0,
        "total": total_urls,
        "success": 0,
        "failures": 0,
        "durations": [],
        "errors": []
    }
    
    start_total = time.time()
    
    # Configure httpx Client with pooling enabled for high concurrency
    limits = httpx.Limits(max_keepalive_connections=concurrency_limit, max_connections=concurrency_limit * 2)
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [worker(sem, client, url, stats, i) for i, url in enumerate(urls)]
        await asyncio.gather(*tasks)
    
    total_time = time.time() - start_total
    avg_time = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
    throughput = total_urls / total_time if total_time > 0 else 0
    
    print("\n" + "="*50)
    print("BENCHMARK RESULTS")
    print("="*50)
    print(f"Total Videos Processed : {total_urls}")
    print(f"Total Execution Time   : {total_time:.3f} seconds ({total_time/60:.2f} minutes)")
    print(f"Average Time per Video : {avg_time:.3f} seconds")
    print(f"System Throughput      : {throughput:.3f} videos/second")
    print(f"Success Rate           : {(stats['success']/total_urls)*100:.2f}% ({stats['success']} successes, {stats['failures']} failures)")
    if stats["errors"]:
        print(f"Unique errors: {list(set(stats['errors']))[:10]}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(main())
