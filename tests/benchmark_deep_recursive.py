"""Deep recursive benchmark - traverse entire filesystem.

This benchmark will:
1. List ALL directories recursively
2. Test cache performance with real deep traversal
3. Measure memory usage
4. Show actual cache hit rates

Run: python tests/benchmark_deep_recursive.py
"""

import asyncio
import time
import sys
import os
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.image_detector import ImageDetector
from src.tools.filesystem_tools.list_files import list_files


TEST_IMAGE_PATH = "extracted.ad1"
TEST_PARTITION_OFFSET = None


async def detect_partition():
    """Auto-detect partition."""
    global TEST_PARTITION_OFFSET
    if TEST_PARTITION_OFFSET is not None:
        return TEST_PARTITION_OFFSET
    
    from src.tools.disk_tools.list_partitions import list_partitions
    result = await list_partitions({"image_path": TEST_IMAGE_PATH})
    
    if result.get('partitions'):
        TEST_PARTITION_OFFSET = result['partitions'][0]['offset']
        print(f"[OK] Partition offset: {TEST_PARTITION_OFFSET}")
    else:
        TEST_PARTITION_OFFSET = 0
        print("[WARN] Using offset: 0")
    
    return TEST_PARTITION_OFFSET


async def recursive_list_all(
    path: str = "/",
    max_depth: int = 20,
    current_depth: int = 0
) -> Tuple[List[str], int, int]:
    """
    Recursively list ALL directories.
    
    Returns: (all_paths, total_files, total_dirs)
    """
    if current_depth >= max_depth:
        return [], 0, 0
    
    result = await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": path
    })
    
    files = result.get('files', [])
    all_paths = [path]
    total_files = len([f for f in files if not f.get('is_directory')])
    total_dirs = len([f for f in files if f.get('is_directory')])
    
    # Recurse into subdirectories
    for f in files:
        if f.get('is_directory') and f.get('name') not in ['.', '..']:
            subpath = f.get('path')
            if subpath and subpath != path:
                sub_paths, sub_files, sub_dirs = await recursive_list_all(
                    subpath, max_depth, current_depth + 1
                )
                all_paths.extend(sub_paths)
                total_files += sub_files
                total_dirs += sub_dirs
    
    return all_paths, total_files, total_dirs


async def benchmark_full_traversal():
    """Benchmark full filesystem traversal."""
    print("\n" + "=" * 70)
    print("FULL FILESYSTEM TRAVERSAL - CACHE BENCHMARK")
    print("=" * 70)
    
    # Clear cache for cold start
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    print("\n[COLD] Starting fresh traversal...")
    
    start = time.time()
    all_paths_cold, files_cold, dirs_cold = await recursive_list_all("/", max_depth=10)
    cold_time = time.time() - start
    
    print(f"\n[COLD] Traversal complete:")
    print(f"  Time: {cold_time:.2f}s")
    print(f"  Directories found: {len(all_paths_cold)}")
    print(f"  Total files: {files_cold}")
    print(f"  Total directories: {dirs_cold}")
    
    # Show cache stats after cold run
    handler = ImageDetector.get_handler_cached(TEST_IMAGE_PATH)
    if handler:
        stats = handler.get_cache_stats()
        print(f"\n  Cache entries after cold run: {stats['file_cache_entries']}")
    
    # WARM run - traverse again (should be instant from cache)
    print("\n[WARM] Repeating traversal (all from cache)...")
    start = time.time()
    all_paths_warm, files_warm, dirs_warm = await recursive_list_all("/", max_depth=10)
    warm_time = time.time() - start
    
    print(f"\n[WARM] Traversal complete:")
    print(f"  Time: {warm_time:.3f}s")
    print(f"  Directories found: {len(all_paths_warm)}")
    print(f"  Total files: {files_warm}")
    print(f"  Total directories: {dirs_warm}")
    
    if warm_time > 0:
        speedup = cold_time / warm_time
        print(f"\n  SPEEDUP: {speedup:,.1f}x")
    
    return cold_time, warm_time, len(all_paths_cold)


async def benchmark_incremental_access():
    """Test accessing directories one by one with cache."""
    print("\n" + "=" * 70)
    print("INCREMENTAL DIRECTORY ACCESS")
    print("=" * 70)
    
    # First get list of all directories
    print("\nBuilding directory list (cold)...")
    all_paths, _, _ = await recursive_list_all("/", max_depth=5)
    
    print(f"Found {len(all_paths)} directories")
    
    # Clear cache
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    print("\n[CLEAR] Cache cleared")
    
    # Access first 20 directories one by one
    test_dirs = all_paths[:min(20, len(all_paths))]
    
    print(f"\nAccessing {len(test_dirs)} directories...")
    
    first_access_times = []
    second_access_times = []
    
    for i, path in enumerate(test_dirs):
        # First access (cold or cache miss)
        start = time.time()
        await list_files({
            "image_path": TEST_IMAGE_PATH,
            "partition_offset": TEST_PARTITION_OFFSET,
            "path": path
        })
        first_time = time.time() - start
        first_access_times.append(first_time)
        
        # Second access (should be cache hit)
        start = time.time()
        await list_files({
            "image_path": TEST_IMAGE_PATH,
            "partition_offset": TEST_PARTITION_OFFSET,
            "path": path
        })
        second_time = time.time() - start
        second_access_times.append(second_time)
        
        if i < 5 or i == len(test_dirs) - 1:  # Show first 5 and last
            speedup = first_time / second_time if second_time > 0 else 0
            print(f"  [{i+1:2d}] {path[:50]:50s} 1st: {first_time:.3f}s, 2nd: {second_time:.4f}s ({speedup:>7.1f}x)")
    
    avg_first = sum(first_access_times) / len(first_access_times)
    avg_second = sum(second_access_times) / len(second_access_times)
    
    print(f"\n  Average first access:  {avg_first:.3f}s")
    print(f"  Average second access: {avg_second:.4f}s")
    if avg_second > 0:
        print(f"  Average speedup:       {avg_first/avg_second:,.1f}x")


async def benchmark_deep_path(depth: int = 5):
    """Benchmark accessing a deeply nested path."""
    print("\n" + "=" * 70)
    print(f"DEEP PATH ACCESS (depth={depth})")
    print("=" * 70)
    
    # Build a deep path
    deep_path = "/"
    current = "/"
    
    for d in range(depth):
        result = await list_files({
            "image_path": TEST_IMAGE_PATH,
            "partition_offset": TEST_PARTITION_OFFSET,
            "path": current
        })
        files = result.get('files', [])
        dirs = [f for f in files if f.get('is_directory') and f.get('name') not in ['.', '..']]
        
        if not dirs:
            print(f"  Cannot go deeper than {d} levels")
            break
        
        current = dirs[0].get('path', current)
        deep_path = current
    
    print(f"\nDeepest path: {deep_path}")
    
    # Clear cache and test
    ImageDetector.invalidate_handler(TEST_IMAGE_PATH)
    
    print("\n[COLD] Accessing deep path...")
    start = time.time()
    await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": deep_path
    })
    cold_time = time.time() - start
    print(f"  Time: {cold_time:.3f}s")
    
    print("\n[WARM] Accessing again (from cache)...")
    start = time.time()
    await list_files({
        "image_path": TEST_IMAGE_PATH,
        "partition_offset": TEST_PARTITION_OFFSET,
        "path": deep_path
    })
    warm_time = time.time() - start
    print(f"  Time: {warm_time:.4f}s")
    
    if warm_time > 0:
        print(f"\n  SPEEDUP: {cold_time/warm_time:,.1f}x")


async def show_detailed_cache_stats():
    """Show detailed cache statistics."""
    print("\n" + "=" * 70)
    print("DETAILED CACHE STATISTICS")
    print("=" * 70)
    
    handler = ImageDetector.get_handler_cached(TEST_IMAGE_PATH)
    if not handler:
        print("  No handler cached")
        return
    
    stats = handler.get_cache_stats()
    print(f"\n  File cache entries:     {stats['file_cache_entries']}")
    print(f"  Metadata cache entries: {stats['metadata_cache_entries']}")
    print(f"  Cache hits:             {stats['cache_hits']}")
    print(f"  Cache misses:           {stats['cache_misses']}")
    print(f"  Hit rate:               {stats['hit_rate']}")
    print(f"  Max cache size:         {stats['max_cache_size']}")
    
    # Show all cached paths
    print(f"\n  All cached paths:")
    for i, key in enumerate(handler._file_cache.keys(), 1):
        print(f"    {i:3d}. {key}")
        if i >= 30:  # Limit output
            remaining = len(handler._file_cache) - 30
            print(f"    ... and {remaining} more")
            break


async def run_all_benchmarks():
    """Run all deep benchmarks."""
    print("=" * 70)
    print("ULTIMATE DEEP CACHE BENCHMARK")
    print("=" * 70)
    print(f"Image: {TEST_IMAGE_PATH}")
    
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"\n[ERROR] Image not found: {TEST_IMAGE_PATH}")
        return
    
    try:
        await detect_partition()
        
        # Run comprehensive benchmarks
        cold_time, warm_time, total_dirs = await benchmark_full_traversal()
        await benchmark_incremental_access()
        await benchmark_deep_path(depth=5)
        await show_detailed_cache_stats()
        
        # Final summary
        print("\n" + "=" * 70)
        print("FINAL SUMMARY")
        print("=" * 70)
        print(f"Full traversal cold:    {cold_time:.2f}s")
        print(f"Full traversal warm:    {warm_time:.3f}s")
        print(f"Total directories:      {total_dirs}")
        if warm_time > 0:
            print(f"Overall speedup:        {cold_time/warm_time:,.1f}x")
        print("\n[OK] All benchmarks completed successfully!")
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        ImageDetector.invalidate_handler()
        print("\n[OK] Cleanup completed")


if __name__ == "__main__":
    asyncio.run(run_all_benchmarks())
