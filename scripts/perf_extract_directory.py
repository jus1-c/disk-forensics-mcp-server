#!/usr/bin/env python3
"""Benchmark extract_directory planning and extraction.

Dry-run is read-only and measures the directory walk that extraction would do.
Use --extract to write files, defaulting to /tmp/disk-forensics-extract-test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from disk_forensics_mcp_server.tools.filesystem_tools.extract_directory import extract_directory
from disk_forensics_mcp_server.utils.image_detector import ImageDetector


def dry_run_extract(
    image_path: str,
    partition_offset: int,
    directory_path: str,
    max_dirs: int | None,
) -> dict[str, Any]:
    ImageDetector.invalidate_handler(image_path)

    started = time.perf_counter()
    handler = ImageDetector.get_handler_cached(image_path)
    open_seconds = time.perf_counter() - started
    if not handler:
        return {"error": True, "message": "handler not found"}

    queue: deque[str] = deque([directory_path])
    visited: set[str] = set()
    dirs = 0
    files = 0
    bytes_total = 0
    list_calls = 0
    list_seconds = 0.0
    first_files: list[dict[str, Any]] = []

    walk_started = time.perf_counter()
    while queue:
        if max_dirs is not None and list_calls >= max_dirs:
            break

        current_dir = queue.popleft()
        if current_dir in visited:
            continue
        visited.add(current_dir)

        list_started = time.perf_counter()
        entries = handler.list_files_for_extraction(partition_offset, current_dir)
        list_seconds += time.perf_counter() - list_started
        list_calls += 1

        for entry in entries:
            if entry.is_directory:
                dirs += 1
                queue.append(entry.path)
            else:
                files += 1
                bytes_total += entry.size
                if len(first_files) < 10:
                    first_files.append({"path": entry.path, "size": entry.size})

    return {
        "image_path": image_path,
        "partition_offset": partition_offset,
        "directory_path": directory_path,
        "open_seconds": round(open_seconds, 3),
        "walk_seconds": round(time.perf_counter() - walk_started, 3),
        "list_seconds": round(list_seconds, 3),
        "list_calls": list_calls,
        "dirs": dirs,
        "files": files,
        "bytes": bytes_total,
        "truncated": bool(queue),
        "first_files": first_files,
    }


async def run_extract(args: argparse.Namespace) -> dict[str, Any]:
    output_path = args.output_path
    if output_path is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        output_path = f"/tmp/disk-forensics-extract-test/{stamp}"

    input_data: dict[str, Any] = {
        "image_path": args.image_path,
        "partition_offset": args.partition_offset,
        "directory_path": args.directory_path,
        "output_path": output_path,
    }
    if args.max_files is not None:
        input_data["max_files"] = args.max_files
    if args.max_bytes is not None:
        input_data["max_bytes"] = args.max_bytes

    started = time.perf_counter()
    result = await extract_directory(input_data)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_path", help="Disk image path")
    parser.add_argument("directory_path", help="Directory path inside the image")
    parser.add_argument("--partition-offset", type=int, default=0)
    parser.add_argument("--max-dirs", type=int, default=None, help="Dry-run max directory list calls")
    parser.add_argument("--extract", action="store_true", help="Actually extract files")
    parser.add_argument("--output-path", default=None, help="Output path for --extract")
    parser.add_argument("--max-files", type=int, default=None, help="Maximum files to extract")
    parser.add_argument("--max-bytes", type=int, default=None, help="Maximum bytes to write")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.image_path = str(Path(args.image_path).resolve())

    if args.extract:
        result = asyncio.run(run_extract(args))
    else:
        result = dry_run_extract(
            args.image_path,
            args.partition_offset,
            args.directory_path,
            args.max_dirs,
        )

    print(json.dumps(result, indent=2, default=str))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
