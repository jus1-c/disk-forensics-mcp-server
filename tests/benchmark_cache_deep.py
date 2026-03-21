"""Benchmark tests for cache performance with deep directory traversal.

Run with: python -m pytest tests/benchmark_cache_deep.py -v
Or: python tests/benchmark_cache_deep.py
"""

import asyncio
import time
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.image_detector import ImageDetector
from src.tools.filesystem_tools.list_files import list_files
from src.tools.filesystem_tools.get_directory_tree import get_directory_tree


# Test image path
TEST_IMAGE_PATH = "extracted.ad1"
TEST_PARTITION_OFFSET = None  # Will be auto-detected


async def detect_partition():
    """Auto-detect first partition offset."""
    global TEST_PARTITION_OFFSET
    
    if TEST_PARTITION_OFFSET is not None:
        return TEST_PARTITION_OFFSET
    
    from src.tools.disk_tools.list_partitions import list_partitions
    
    print("Detecting partitions...")
    result = await list_partitions({"image_path": TEST_IMAGE_PATH})
    
    if result.get('partitions') and len(result['partitions']) > 0:
        TEST_PARTITION_OFFSET = result['partitions'][0]['offset']
        print(f"[OK] Using partition offset: {TEST_PARTITION_OFFSET}")
    else:
        TEST_PARTITION_OFFSET = 0
        print(f"[WARN] No partitions found, using offset: 0")
    
    return TEST_PARTITION_OFFSET


async def benchmark_single_folder(path="/", description="Root"):
    """Benchmark listing a single folder."""
    print(f"\n=== {description}: {path} ===")
    
    start = time.time()
    result = await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": path
    })
    elapsed = time.time() - start
    
    file_count = result.get('count', 0)
    print(f"Files: {file_count}, Time: {elapsed:.3f}s")
    
    return elapsed, file_count, result.get('files', [])


async def benchmark_folder_with_subdirs(path="/", depth=2):
    """Benchmark traversing folder and subdirectories."""
    print(f"\n=== Deep Traversal: {path} (depth={depth}) ===")
    
    all_files = []
    start = time.time()
    
    # List root
    result = await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": path
    })
    
    files = result.get('files', [])
    all_files.extend(files)
    
    # List subdirectories
    if depth > 0:
        for f in files:
            if f.get('is_directory') and f.get('name') not in ['.', '..']:
                subpath = f.get('path', path + '/' + f.get('name'))
                subresult = await list_files({
                    "image_path": TEST_IMAGE_PATH,
                    "partition_offset": TEST_PARTITION_OFFSET,
                    "path": subpath
                })
                all_files.extend(subresult.get('files', []))
    
    elapsed = time.time() - start
    print(f"Total items: {len(all_files)}, Time: {elapsed:.3f}s")
    
    return elapsed, len(all_files)


async def benchmark_cold_vs_warm():
    """Compare cold vs warm cache performance."""
    print("\n" + "=" * 60)
    print("COLD vs WARM CACHE COMPARISON")
    print("=" * 60)
    
    # Clear cache
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    print("\n[COLD] Cache cleared")
    
    # Test paths to traverse
    test_paths = [
        "/",
        "/Windows" if os.path.exists(TEST_IMAGE_PATH) else "/",
    ]
    
    cold_times = []
    warm_times = []
    
    for path in test_paths[:1]:  # Just test root for now
        print(f"\nTesting: {path}")
        
        # Cold
        cold_time, count, _ = await benchmark_single_folder(path, "COLD")
        cold_times.append(cold_time)
        
        # Warm
        warm_time, _, _ = await benchmark_single_folder(path, "WARM")
        warm_times.append(warm_time)
        
        if warm_time > 0:
            speedup = cold_time / warm_time
            print(f"Speedup: {speedup:.1f}x")
    
    return cold_times, warm_times


async def benchmark_multiple_folders():
    """Benchmark listing multiple different folders."""
    print("\n" + "=" * 60)
    print("MULTIPLE FOLDERS TRAVERSAL")
    print("=" * 60)
    
    # Clear cache
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    print("\nStarting fresh...")
    
    # First, list root to populate cache
    await benchmark_single_folder("/", "1. Root (COLD)")
    
    # Now test repeated access to different folders
    print("\n--- Testing Repeated Access ---")
    
    times = []
    for i in range(5):
        start = time.time()
        await list_files({
            "image_path": TEST_IMAGE_PATH,
            "partition_offset": TEST_PARTITION_OFFSET,
            "path": "/"
        })
        elapsed = time.time() - start
        times.append(elapsed)
        print(f"  Run {i+1}: {elapsed:.4f}s")
    
    avg = sum(times) / len(times)
    print(f"\nAverage: {avg:.4f}s")
    print(f"Min: {min(times):.4f}s")
    print(f"Max: {max(times):.4f}s")
    
    return times


async def benchmark_deep_traversal():
    """Benchmark deep directory traversal."""
    print("\n" + "=" * 60)
    print("DEEP DIRECTORY TREE")
    print("=" * 60)
    
    # Clear cache
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    print("\nBuilding directory tree (COLD)...")
    
    start = time.time()
    result = await get_directory_tree({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": "/",
        "max_depth": 3
    })
    cold_time = time.time() - start
    
    tree = result.get('tree', {})
    total_files = result.get('total_files', 0)
    total_dirs = result.get('total_dirs', 0)
    
    print(f"COLD: {cold_time:.2f}s")
    print(f"Files: {total_files}, Directories: {total_dirs}")
    
    # Warm
    print("\nRepeating (WARM)...")
    start = time.time()
    result = await get_directory_tree({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": "/",
        "max_depth": 3
    })
    warm_time = time.time() - start
    
    print(f"WARM: {warm_time:.4f}s")
    
    if warm_time > 0:
        speedup = cold_time / warm_time
        print(f"Speedup: {speedup:.1f}x")
    
    return cold_time, warm_time


async def show_cache_stats():
    """Display cache statistics."""
    print("\n" + "=" * 60)
    print("CACHE STATISTICS")
    print("=" * 60)
    
    handler = ImageDetector.get_handler_cached(TEST_IMAGE_PATH)
    if handler:
        stats = handler.get_cache_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        # Show what's in cache
        print(f"\nCached folders: {list(handler._file_cache.keys())[:10]}")
    else:
        print("  No handler cached")


async def run_all_benchmarks():
    """Run comprehensive benchmarks."""
    print("=" * 60)
    print("DEEP CACHE PERFORMANCE BENCHMARK")
    print("=" * 60)
    print(f"Test image: {TEST_IMAGE_PATH}")
    
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"\n[WARN] Test image not found: {TEST_IMAGE_PATH}")
        return
    
    try:
        await detect_partition()
        
        # Run benchmarks
        await benchmark_cold_vs_warm()
        await benchmark_multiple_folders()
        await benchmark_deep_traversal()
        await show_cache_stats()
        
        print("\n" + "=" * 60)
        print("BENCHMARK COMPLETED")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n[ERROR] Error during benchmark: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        ImageDetector.invalidate_handler()
        print("\n[OK] Cleanup completed")


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
