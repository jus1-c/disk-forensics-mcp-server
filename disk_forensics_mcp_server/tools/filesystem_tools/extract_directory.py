"""Tool for extracting directories from a partition to disk."""

import os
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ...models.schemas import ErrorOutput
from ...utils.image_detector import ImageDetector


PATH_SAMPLE_LIMIT = 200


class ExtractDirectoryInput(BaseModel):
    """Input for extract_directory tool."""

    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    directory_path: str = Field(..., description="Path to the directory within the partition")
    output_path: str = Field(..., description="Path to save the extracted directory")
    max_files: Optional[int] = Field(None, description="Optional maximum number of files to extract")
    max_bytes: Optional[int] = Field(None, description="Optional maximum number of bytes to write")


class ExtractDirectoryOutput(BaseModel):
    """Output for extract_directory tool."""

    success: bool = Field(..., description="Whether extraction completed without read/write failures")
    source_path: str = Field(..., description="Source directory path in image")
    output_path: str = Field(..., description="Output directory path")
    files_extracted: int = Field(..., description="Number of files extracted")
    directories_created: int = Field(..., description="Number of directories created on disk")
    files_skipped: int = Field(..., description="Number of existing files skipped")
    files_failed: int = Field(..., description="Number of files that failed to extract")
    bytes_written: int = Field(..., description="Total bytes written to disk")
    skipped_paths: list[str] = Field(default_factory=list, description="Source paths skipped because output already existed")
    failed_paths: list[str] = Field(default_factory=list, description="Source paths that could not be extracted")
    skipped_paths_truncated: bool = Field(default=False, description="Whether skipped_paths was truncated")
    failed_paths_truncated: bool = Field(default=False, description="Whether failed_paths was truncated")
    limited_by: Optional[str] = Field(None, description="Limit that stopped extraction, if any")
    message: str = Field(..., description="Status message")


def _normalize_directory_path(path: str) -> str:
    """Normalize image directory paths while preserving root."""
    if path == "/":
        return path
    return path.rstrip("/") or "/"


def _relative_image_path(source_dir: str, image_path: str) -> str:
    """Compute a stable relative path within the source directory."""
    if image_path == source_dir:
        return ""

    if source_dir == "/":
        return image_path.lstrip("/")

    prefix = f"{source_dir}/"
    if image_path.startswith(prefix):
        return image_path[len(prefix):]

    raise ValueError(f"Path '{image_path}' is outside source directory '{source_dir}'")


def _build_output_path(output_root: str, source_dir: str, image_path: str) -> str:
    """Map an image path to its local output path."""
    relative_path = _relative_image_path(source_dir, image_path)
    if not relative_path:
        return output_root

    parts = [part for part in relative_path.split("/") if part]
    return os.path.join(output_root, *parts)


def _append_limited_path(stats: Dict[str, Any], key: str, truncated_key: str, path: str) -> None:
    """Append path samples without letting MCP responses grow without bound."""
    if len(stats[key]) < PATH_SAMPLE_LIMIT:
        stats[key].append(path)
    else:
        stats[truncated_key] = True


def _ensure_directory(path: str, known_dirs: set[str]) -> bool:
    """Ensure a local directory exists and return whether it was created."""
    if path in known_dirs:
        return False

    if os.path.isdir(path):
        known_dirs.add(path)
        return False

    if os.path.exists(path):
        raise FileExistsError(f"Output path exists and is not a directory: {path}")

    os.makedirs(path, exist_ok=False)
    known_dirs.add(path)
    return True


def _should_stop_before_file(entry_size: int, stats: Dict[str, Any]) -> bool:
    """Return whether extraction limits prevent extracting the next file."""
    max_files = stats.get("max_files")
    if max_files is not None and stats["files_extracted"] >= max_files:
        stats["limited_by"] = "max_files"
        return True

    max_bytes = stats.get("max_bytes")
    if max_bytes is not None and stats["bytes_written"] + entry_size > max_bytes:
        stats["limited_by"] = "max_bytes"
        return True

    return False


def _extract_directory_recursive(
    handler,
    partition_offset: int,
    source_dir: str,
    current_dir: str,
    output_root: str,
    stats: Dict[str, Any],
) -> None:
    """Extract directory contents recursively using handler list/read APIs."""
    if stats.get("limited_by"):
        return

    current_output_dir = _build_output_path(output_root, source_dir, current_dir)
    if _ensure_directory(current_output_dir, stats["known_dirs"]):
        stats["directories_created"] += 1

    for entry in handler.list_files_for_extraction(partition_offset, current_dir):
        if stats.get("limited_by"):
            return

        output_path = _build_output_path(output_root, source_dir, entry.path)

        if entry.is_directory:
            if _ensure_directory(output_path, stats["known_dirs"]):
                stats["directories_created"] += 1
            _extract_directory_recursive(
                handler,
                partition_offset,
                source_dir,
                entry.path,
                output_root,
                stats,
            )
            continue

        if _should_stop_before_file(entry.size, stats):
            return

        if os.path.exists(output_path):
            stats["files_skipped"] += 1
            _append_limited_path(stats, "skipped_paths", "skipped_paths_truncated", entry.path)
            continue

        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            _ensure_directory(parent_dir, stats["known_dirs"])

        try:
            with open(output_path, "wb") as output_file:
                file_bytes = 0
                for chunk in handler.iter_file_chunks(partition_offset, entry.path):
                    output_file.write(chunk)
                    file_bytes += len(chunk)
        except Exception:
            stats["files_failed"] += 1
            _append_limited_path(stats, "failed_paths", "failed_paths_truncated", entry.path)
            continue

        stats["files_extracted"] += 1
        stats["bytes_written"] += file_bytes


async def extract_directory(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a directory from a partition to disk."""
    try:
        input_model = ExtractDirectoryInput(**input_data)
        source_dir = _normalize_directory_path(input_model.directory_path)

        handler = ImageDetector.get_handler_cached(input_model.image_path)
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT",
            ).model_dump()

        source_metadata = handler.get_file_metadata(input_model.partition_offset, source_dir)
        if source_metadata is None:
            return ErrorOutput(
                message=f"Directory not found: {source_dir}",
                code="DIRECTORY_NOT_FOUND",
            ).model_dump()

        if not source_metadata.is_directory:
            return ErrorOutput(
                message=f"Path is not a directory: {source_dir}",
                code="NOT_A_DIRECTORY",
            ).model_dump()

        if os.path.exists(input_model.output_path) and not os.path.isdir(input_model.output_path):
            return ErrorOutput(
                message=f"Output path exists and is not a directory: {input_model.output_path}",
                code="INVALID_OUTPUT_PATH",
            ).model_dump()

        stats = {
            "files_extracted": 0,
            "directories_created": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "bytes_written": 0,
            "skipped_paths": [],
            "failed_paths": [],
            "skipped_paths_truncated": False,
            "failed_paths_truncated": False,
            "limited_by": None,
            "max_files": input_model.max_files,
            "max_bytes": input_model.max_bytes,
            "known_dirs": set(),
        }

        _extract_directory_recursive(
            handler,
            input_model.partition_offset,
            source_dir,
            source_dir,
            input_model.output_path,
            stats,
        )

        success = stats["files_failed"] == 0
        if stats["limited_by"]:
            message = (
                f"Partially extracted {stats['files_extracted']} files to {input_model.output_path} "
                f"before reaching {stats['limited_by']}"
            )
        elif success:
            message = (
                f"Successfully extracted {stats['files_extracted']} files to "
                f"{input_model.output_path} with {stats['files_skipped']} skipped existing files"
            )
        else:
            message = (
                f"Extracted {stats['files_extracted']} files to {input_model.output_path} "
                f"with {stats['files_failed']} failures and {stats['files_skipped']} skipped existing files"
            )

        output = ExtractDirectoryOutput(
            success=success,
            source_path=source_dir,
            output_path=input_model.output_path,
            files_extracted=stats["files_extracted"],
            directories_created=stats["directories_created"],
            files_skipped=stats["files_skipped"],
            files_failed=stats["files_failed"],
            bytes_written=stats["bytes_written"],
            skipped_paths=stats["skipped_paths"],
            failed_paths=stats["failed_paths"],
            skipped_paths_truncated=stats["skipped_paths_truncated"],
            failed_paths_truncated=stats["failed_paths_truncated"],
            limited_by=stats["limited_by"],
            message=message,
        )
        return output.model_dump()

    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND",
        ).model_dump()
    except PermissionError as e:
        return ErrorOutput(
            message=f"Permission denied writing to output path: {str(e)}",
            code="PERMISSION_DENIED",
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error extracting directory: {str(e)}",
            code="EXTRACTION_ERROR",
            details={"exception": type(e).__name__},
        ).model_dump()


tool_definition = {
    "name": "extract_directory",
    "description": "Extract a directory from a partition to disk. Preserves relative paths, creates empty directories, and skips existing files by default.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the disk image file"
            },
            "partition_offset": {
                "type": "integer",
                "description": "Offset of the partition in bytes"
            },
            "directory_path": {
                "type": "string",
                "description": "Path to the directory within the partition"
            },
            "output_path": {
                "type": "string",
                "description": "Path to save the extracted directory"
            },
            "max_files": {
                "type": "integer",
                "description": "Optional maximum number of files to extract"
            },
            "max_bytes": {
                "type": "integer",
                "description": "Optional maximum number of bytes to write"
            }
        },
        "required": ["image_path", "partition_offset", "directory_path", "output_path"]
    }
}
