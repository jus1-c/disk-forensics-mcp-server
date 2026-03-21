"""Benchmark tests for cache performance.

Run with: python -m pytest tests/benchmark_cache.py -v
Or: python tests/benchmark_cache.py
"""

import asyncio
import time
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.image_detector import ImageDetector
from src.tools.filesystem_tools.list_files import list_files
from src.tools.filesystem_tools.get_file_metadata import get_file_metadata
from src.tools.disk_tools.list_partitions import list_partitions


# Test image path - update this to your test image
TEST_IMAGE_PATH = "extracted.ad1"
TEST_PARTITION_OFFSET = None  # Will be auto-detected
TEST_PATH = "/"


async def detect_partition():
    """Auto-detect first partition offset."""
    global TEST_PARTITION_OFFSET
    
    if TEST_PARTITION_OFFSET is not None:
        return TEST_PARTITION_OFFSET
    
    print("Detecting partitions...")
    result = await list_partitions({"image_path": TEST_IMAGE_PATH})
    
    if result.get('partitions') and len(result['partitions']) > 0:
        TEST_PARTITION_OFFSET = result['partitions'][0]['offset']
        print(f"[OK] Using partition offset: {TEST_PARTITION_OFFSET}")
    else:
        TEST_PARTITION_OFFSET = 0
        print(f"[WARN]  No partitions found, using offset: 0")
    
    return TEST_PARTITION_OFFSET


async def benchmark_list_files_cold():
    """Benchmark first call (cold cache)."""
    print("\n=== Cold Cache Benchmark ===")
    
    # Clear any existing cache
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    
    start = time.time()
    result = await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": TEST_PATH
    })
    cold_time = time.time() - start
    
    print(f"Cold cache time: {cold_time:.2f}s")
    print(f"Files returned: {result.get('count', 0)}")
    
    return cold_time, result


async def benchmark_list_files_warm():
    """Benchmark second call (warm cache)."""
    print("\n=== Warm Cache Benchmark ===")
    
    start = time.time()
    result = await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": TEST_PATH
    })
    warm_time = time.time() - start
    
    print(f"Warm cache time: {warm_time:.2f}s")
    print(f"Files returned: {result.get('count', 0)}")
    
    return warm_time, result


async def benchmark_multiple_calls():
    """Benchmark multiple repeated calls."""
    print("\n=== Multiple Calls Benchmark ===")
    
    times = []
    for i in range(5):
        start = time.time()
        result = await list_files({
            "image_path": TEST_IMAGE_PATH,
            "partition_offset": TEST_PARTITION_OFFSET,
            "path": TEST_PATH
        })
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"Call {i+1}: {elapsed:.3f}s")
    
    avg_time = sum(times) / len(times)
    print(f"\nAverage time: {avg_time:.3f}s")
    print(f"Min time: {min(times):.3f}s")
    print(f"Max time: {max(times):.3f}s")
    
    return times


async def benchmark_cache_stats():
    """Show cache statistics."""
    print("\n=== Cache Statistics ===")
    
    # Get handler to check cache stats
    handler = ImageDetector.get_handler_cached(TEST_IMAGE_PATH)
    if handler:
        stats = handler.get_cache_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
    else:
        print("  No handler cached")


async def run_all_benchmarks():
    """Run all benchmarks."""
    print("=" * 60)
    print("DISK FORENSICS MCP SERVER - CACHE PERFORMANCE BENCHMARK")
    print("=" * 60)
    print(f"Test image: {TEST_IMAGE_PATH}")
    
    # Check if test image exists
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"\n[WARN]  Test image not found: {TEST_IMAGE_PATH}")
        print("Please update TEST_IMAGE_PATH in this file to point to your test image.")
        return
    
    try:
        # Auto-detect partition
        await detect_partition()
        
        # Cold cache
        cold_time, _ = await benchmark_list_files_cold()
        
        # Warm cache
        warm_time, _ = await benchmark_list_files_warm()
        
        # Calculate speedup
        speedup = 0
        if warm_time > 0:
            speedup = cold_time / warm_time
            print(f"\n[SPEEDUP] Cache Speedup: {speedup:.1f}x")
        
        # Multiple calls
        times = await benchmark_multiple_calls()
        
        # Cache stats
        await benchmark_cache_stats()
        
        # Summary
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        print(f"[OK] Cold cache: {cold_time:.2f}s")
        print(f"[OK] Warm cache: {warm_time:.2f}s")
        if times:
            print(f"[OK] Average (5 calls): {sum(times)/len(times):.3f}s")
        if speedup > 0:
            print(f"[OK] Speedup: {speedup:.1f}x")
        
    except Exception as e:
        print(f"\n[ERROR] Error during benchmark: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        ImageDetector.invalidate_handler()
        print("\n[OK] Cleanup completed")


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
