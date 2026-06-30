import asyncio
import os
import time
import httpx

async def worker(sem, client, url, stats):
    async with sem:
        start = time.time()
        try:
            resp = await client.post(
                'http://localhost:8000/api/process_video',
                data={'url': url, 'fps': 1},
                timeout=30.0
            )
            duration = time.time() - start
            if resp.status_code == 200:
                stats["durations"].append(duration)
                stats["success"] += 1
            else:
                stats["failures"] += 1
        except Exception:
            stats["failures"] += 1

async def run_test(urls, concurrency):
    sem = asyncio.Semaphore(concurrency)
    stats = {"success": 0, "failures": 0, "durations": []}
    
    limits = httpx.Limits(max_keepalive_connections=concurrency, max_connections=concurrency * 2)
    start_total = time.time()
    
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = [worker(sem, client, url, stats) for url in urls]
        await asyncio.gather(*tasks)
        
    total_time = time.time() - start_total
    avg_time = sum(stats["durations"]) / len(stats["durations"]) if stats["durations"] else 0
    throughput = len(urls) / total_time if total_time > 0 else 0
    return {
        "concurrency": concurrency,
        "total_time": total_time,
        "avg_time": avg_time,
        "throughput": throughput,
        "success": stats["success"],
        "failures": stats["failures"]
    }

async def main():
    links_file = "/home/twoseepeakay/VideoProcessing/stream_links.txt"
    if not os.path.exists(links_file):
        print(f"Error: {links_file} not found.")
        return

    with open(links_file, "r") as f:
        urls = [line.strip() for line in f if line.strip()]
        
    # Use first 120 URLs for a fast but statistically significant test
    test_urls = urls[:120]
    
    concurrency_levels = [2, 4, 8, 12, 16, 20]
    results = []
    
    print(f"Starting sweep across concurrency levels {concurrency_levels} using {len(test_urls)} videos...")
    for c in concurrency_levels:
        print(f"Testing concurrency: {c}...")
        res = await run_test(test_urls, c)
        results.append(res)
        # Short cooldown to let socket connections close down
        await asyncio.sleep(2.0)
        
    print("\n" + "="*80)
    print(f"{'Concurrency':<12} | {'Total Time (s)':<15} | {'Avg Time (s)':<12} | {'Throughput (v/s)':<18} | {'Successes':<10} | {'Failures':<10}")
    print("-"*80)
    for r in results:
        print(f"{r['concurrency']:<12} | {r['total_time']:<15.3f} | {r['avg_time']:<12.3f} | {r['throughput']:<18.3f} | {r['success']:<10} | {r['failures']:<10}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(main())
