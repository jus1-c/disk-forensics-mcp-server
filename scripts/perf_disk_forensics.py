#!/usr/bin/env python3
"""Benchmark disk-forensics MCP operations against local source code.

This script is intentionally read-only against evidence images. It imports the
package from the repository root when run from this checkout.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from disk_forensics_mcp_server.tools.disk_tools.analyze_image import analyze_disk_image
from disk_forensics_mcp_server.tools.disk_tools.list_partitions import list_partitions
from disk_forensics_mcp_server.tools.filesystem_tools.get_directory_tree import get_directory_tree
from disk_forensics_mcp_server.tools.filesystem_tools.list_files import list_files
from disk_forensics_mcp_server.tools.filesystem_tools.read_file import read_file_content
from disk_forensics_mcp_server.utils.image_detector import ImageDetector


DEFAULT_IMAGES = [
    REPO_ROOT / "Disk-file" / "2.img",
    REPO_ROOT / "Disk-file" / "ctf-vm-disk1.vmdk",
    REPO_ROOT / "Disk-file" / "extracted.ad1",
    REPO_ROOT / "Disk-file" / "HDFS-Master.E01",
    REPO_ROOT / "Disk-file" / "Windows 10.vhdx",
]


@dataclass
class Measurement:
    image: str
    operation: str
    seconds: float
    ok: bool
    details: dict[str, Any]


def _safe_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except Exception:
        return -1


def _summarize_error(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("error"):
        return {
            "error": True,
            "code": result.get("code"),
            "message": result.get("message"),
        }
    return {}


async def measure_async(
    image_label: str,
    operation: str,
    func: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[Measurement, dict[str, Any]]:
    start = time.perf_counter()
    try:
        result = await func()
        elapsed = time.perf_counter() - start
        ok = not bool(result.get("error"))
        details = _summarize_error(result)
        details["json_bytes"] = _safe_json_size(result)
        return Measurement(image_label, operation, elapsed, ok, details), result
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return (
            Measurement(
                image_label,
                operation,
                elapsed,
                False,
                {"exception": type(exc).__name__, "message": str(exc)},
            ),
            {},
        )


def choose_partition(image_path: Path, partitions_result: dict[str, Any]) -> int:
    if image_path.suffix.lower() in {".ad1", ".ad2"}:
        return 0

    partitions = partitions_result.get("partitions") or []
    for partition in partitions:
        filesystem = str(partition.get("filesystem") or "").lower()
        if filesystem and filesystem != "unknown":
            return int(partition.get("offset") or 0)

    if partitions:
        return int(partitions[0].get("offset") or 0)

    return 0


def find_sample_file(
    image_path: Path,
    partition_offset: int,
    max_dirs: int,
    max_sample_file_size: int,
) -> dict[str, Any] | None:
    handler = ImageDetector.get_handler_cached(str(image_path))
    if not handler:
        return None

    queue: deque[str] = deque(["/"])
    visited: set[str] = set()
    dirs_seen = 0
    fallback: dict[str, Any] | None = None

    while queue and dirs_seen < max_dirs:
        current_path = queue.popleft()
        if current_path in visited:
            continue
        visited.add(current_path)
        dirs_seen += 1

        try:
            entries = handler.list_files(partition_offset, current_path)
        except Exception:
            continue

        for entry in entries:
            if entry.is_directory:
                queue.append(entry.path)
                continue

            sample = {"path": entry.path, "size": entry.size}
            if fallback is None:
                fallback = sample
            if entry.size <= 0:
                continue
            if entry.size <= max_sample_file_size:
                return sample

    return fallback


def print_measurement(measurement: Measurement) -> None:
    status = "ok" if measurement.ok else "fail"
    details = ""
    if measurement.details:
        details = " " + json.dumps(measurement.details, default=str, sort_keys=True)
    print(
        f"{measurement.image:22s} {measurement.operation:34s} "
        f"{measurement.seconds:9.3f}s {status}{details}"
    )


async def benchmark_image(args: argparse.Namespace, image_path: Path) -> list[Measurement]:
    image_label = image_path.name
    measurements: list[Measurement] = []

    if not image_path.exists():
        missing = Measurement(image_label, "exists", 0.0, False, {"message": "file not found"})
        print_measurement(missing)
        return [missing]

    ImageDetector.invalidate_handler(str(image_path))
    gc.collect()

    measurement, _ = await measure_async(
        image_label,
        "tool.analyze_disk_image",
        lambda: analyze_disk_image({"image_path": str(image_path)}),
    )
    measurements.append(measurement)
    print_measurement(measurement)

    measurement, partitions_result = await measure_async(
        image_label,
        "tool.list_partitions",
        lambda: list_partitions({"image_path": str(image_path)}),
    )
    if partitions_result and not partitions_result.get("error"):
        measurement.details["count"] = partitions_result.get("count")
    measurements.append(measurement)
    print_measurement(measurement)

    partition_offset = choose_partition(image_path, partitions_result)
    ImageDetector.invalidate_handler(str(image_path))
    gc.collect()

    list_args = {
        "image_path": str(image_path),
        "partition_offset": partition_offset,
        "path": "/",
    }
    measurement, root_result = await measure_async(
        image_label,
        "tool.list_files root cold",
        lambda: list_files(list_args),
    )
    if root_result and not root_result.get("error"):
        measurement.details["count"] = root_result.get("count")
    measurements.append(measurement)
    print_measurement(measurement)

    measurement, warm_root_result = await measure_async(
        image_label,
        "tool.list_files root warm",
        lambda: list_files(list_args),
    )
    if warm_root_result and not warm_root_result.get("error"):
        measurement.details["count"] = warm_root_result.get("count")
    measurements.append(measurement)
    print_measurement(measurement)

    if args.tree_depth >= 0:
        tree_args = {
            "image_path": str(image_path),
            "partition_offset": partition_offset,
            "path": "/",
            "max_depth": args.tree_depth,
        }
        measurement, tree_result = await measure_async(
            image_label,
            f"tool.get_tree depth {args.tree_depth}",
            lambda: get_directory_tree(tree_args),
        )
        if tree_result and not tree_result.get("error"):
            measurement.details["total_files"] = tree_result.get("total_files")
            measurement.details["total_dirs"] = tree_result.get("total_dirs")
        measurements.append(measurement)
        print_measurement(measurement)

    sample = find_sample_file(
        image_path,
        partition_offset,
        max_dirs=args.sample_dirs,
        max_sample_file_size=args.max_sample_file_size,
    )
    if sample:
        read_args = {
            "image_path": str(image_path),
            "partition_offset": partition_offset,
            "file_path": sample["path"],
            "max_size": args.read_limit,
        }
        measurement, read_result = await measure_async(
            image_label,
            "tool.read_file_content sample",
            lambda: read_file_content(read_args),
        )
        measurement.details["sample_path"] = sample["path"]
        measurement.details["sample_size"] = sample["size"]
        if read_result and not read_result.get("error"):
            measurement.details["returned_size"] = read_result.get("size")
            measurement.details["truncated"] = bool(read_result.get("truncated"))
        measurements.append(measurement)
        print_measurement(measurement)
    else:
        measurement = Measurement(
            image_label,
            "tool.read_file_content sample",
            0.0,
            False,
            {"message": "no sample file found"},
        )
        measurements.append(measurement)
        print_measurement(measurement)

    try:
        handler = ImageDetector.get_handler_cached(str(image_path))
        if handler:
            stats = json.dumps(handler.get_cache_stats(), sort_keys=True)
            print(f"{image_label:22s} cache.stats                         {stats}")
    except Exception:
        pass

    return measurements


def summarize(measurements: list[Measurement]) -> None:
    ok_measurements = [m for m in measurements if m.ok]
    print("\nSummary")
    print(f"  operations: {len(measurements)}")
    print(f"  successful: {len(ok_measurements)}")
    print(f"  failed:     {len(measurements) - len(ok_measurements)}")
    if ok_measurements:
        times = [m.seconds for m in ok_measurements]
        print(f"  total ok:   {sum(times):.3f}s")
        print(f"  median ok:  {statistics.median(times):.3f}s")
        print(f"  max ok:     {max(times):.3f}s")


async def main_async(args: argparse.Namespace) -> int:
    images = [Path(image).resolve() for image in args.images]
    all_measurements: list[Measurement] = []

    for index, image_path in enumerate(images):
        if index:
            print("")
        print(f"Image: {image_path}")
        measurements = await benchmark_image(args, image_path)
        all_measurements.extend(measurements)

    summarize(all_measurements)
    return 0 if all(
        m.ok for m in all_measurements if m.operation != "tool.read_file_content sample"
    ) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        default=[str(path) for path in DEFAULT_IMAGES],
        help="Image paths to benchmark. Defaults to Disk-file images.",
    )
    parser.add_argument(
        "--tree-depth", type=int, default=1, help="Tree max_depth to benchmark; use -1 to skip."
    )
    parser.add_argument(
        "--sample-dirs", type=int, default=25, help="Max directories to scan for a sample file."
    )
    parser.add_argument(
        "--max-sample-file-size",
        type=int,
        default=64 * 1024 * 1024,
        help="Prefer a sample file at or below this size.",
    )
    parser.add_argument("--read-limit", type=int, default=1024 * 1024, help="read_file_content max_size.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
