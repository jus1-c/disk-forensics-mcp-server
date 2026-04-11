"""Parallel processing utilities for filesystem operations."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Any, Optional

# Optimal workers = min(4, CPU cores) to avoid overwhelming the disk I/O
MAX_WORKERS = min(4, os.cpu_count() or 4)

# Global thread pool executor
_executor: Optional[ThreadPoolExecutor] = None


def get_executor() -> ThreadPoolExecutor:
    """Get or create the global thread pool executor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    return _executor


def shutdown_executor():
    """Shutdown the global thread pool executor."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


async def parallel_map(
    func: Callable,
    items: List[Any],
    max_workers: int = MAX_WORKERS
) -> List[Any]:
    """Execute function in parallel across items using thread pool.
    
    Args:
        func: Function to execute (must be thread-safe)
        items: List of items to process
        max_workers: Maximum number of parallel workers
        
    Returns:
        List of results in the same order as items
    """
    if not items:
        return []
    
    # For small lists, process sequentially to avoid overhead
    if len(items) <= 2:
        return [func(item) for item in items]
    
    loop = asyncio.get_event_loop()
    executor = get_executor()
    
    # Create futures for all items
    futures = [
        loop.run_in_executor(executor, func, item)
        for item in items
    ]
    
    # Wait for all to complete
    return await asyncio.gather(*futures, return_exceptions=True)


async def parallel_map_with_results(
    func: Callable,
    items: List[Any],
    max_workers: int = MAX_WORKERS
) -> tuple[List[Any], List[Exception]]:
    """Execute function in parallel and separate results from exceptions.
    
    Args:
        func: Function to execute
        items: List of items to process
        max_workers: Maximum number of parallel workers
        
    Returns:
        Tuple of (successful_results, exceptions)
    """
    if not items:
        return [], []
    
    results = await parallel_map(func, items, max_workers)
    
    successful = []
    exceptions = []
    
    for result in results:
        if isinstance(result, Exception):
            exceptions.append(result)
        else:
            successful.append(result)
    
    return successful, exceptions


async def parallel_recursive_search(
    handler,
    partition_offset: int,
    dirs: List[Any],
    search_func: Callable,
    *args
) -> List[Any]:
    """Search multiple directories in parallel.
    
    This is optimized for filesystem operations where multiple directories
    can be searched concurrently without interfering with each other.
    
    Args:
        handler: Image handler instance
        partition_offset: Partition offset
        dirs: List of directory entries to search
        search_func: Search function to call for each directory
        *args: Additional arguments to pass to search_func
        
    Returns:
        Flattened list of all matches
    """
    if not dirs:
        return []
    
    async def search_single_dir(d):
        """Search a single directory."""
        try:
            if hasattr(d, 'name') and d.name in ['.', '..']:
                return []
            path = d.path if hasattr(d, 'path') else str(d)
            return await search_func(handler, partition_offset, path, *args)
        except Exception:
            return []
    
    # Run searches in parallel
    tasks = [search_single_dir(d) for d in dirs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Flatten and filter out exceptions
    all_matches = []
    for result in results:
        if isinstance(result, list):
            all_matches.extend(result)
    
    return all_matches


class ParallelProcessor:
    """Context manager for parallel processing with automatic cleanup."""
    
    def __init__(self, max_workers: int = MAX_WORKERS):
        self.max_workers = max_workers
        self._local_executor: Optional[ThreadPoolExecutor] = None
    
    def __enter__(self):
        """Enter context."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and cleanup."""
        if self._local_executor:
            self._local_executor.shutdown(wait=False)
        return False
    
    async def map(self, func: Callable, items: List[Any]) -> List[Any]:
        """Process items in parallel."""
        return await parallel_map(func, items, self.max_workers)


# Cache for parallel operations to avoid recreating executors
def setup_parallel_processing():
    """Initialize parallel processing infrastructure."""
    get_executor()


def cleanup_parallel_processing():
    """Cleanup parallel processing infrastructure."""
    shutdown_executor()
