"""Tool for extracting directories from a partition to disk."""

import os
from typing import Any, Dict

from pydantic import BaseModel, Field

from ...models.schemas import ErrorOutput
from ...utils.image_detector import ImageDetector


class ExtractDirectoryInput(BaseModel):
    """Input for extract_directory tool."""

    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    directory_path: str = Field(..., description="Path to the directory within the partition")
    output_path: str = Field(..., description="Path to save the extracted directory")


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


def _ensure_directory(path: str) -> bool:
    """Ensure a local directory exists and return whether it was created."""
    if os.path.isdir(path):
        return False

    if os.path.exists(path):
        raise FileExistsError(f"Output path exists and is not a directory: {path}")

    os.makedirs(path, exist_ok=False)
    return True


def _extract_directory_recursive(
    handler,
    partition_offset: int,
    source_dir: str,
    current_dir: str,
    output_root: str,
    stats: Dict[str, Any],
) -> None:
    """Extract directory contents recursively using handler list/read APIs."""
    current_output_dir = _build_output_path(output_root, source_dir, current_dir)
    if _ensure_directory(current_output_dir):
        stats["directories_created"] += 1

    for entry in handler.list_files(partition_offset, current_dir):
        output_path = _build_output_path(output_root, source_dir, entry.path)

        if entry.is_directory:
            if _ensure_directory(output_path):
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

        if os.path.exists(output_path):
            stats["files_skipped"] += 1
            stats["skipped_paths"].append(entry.path)
            continue

        parent_dir = os.path.dirname(output_path)
        if parent_dir:
            _ensure_directory(parent_dir)

        content = handler.read_file(partition_offset, entry.path)
        if content is None:
            stats["files_failed"] += 1
            stats["failed_paths"].append(entry.path)
            continue

        try:
            with open(output_path, "wb") as output_file:
                output_file.write(content)
        except Exception:
            stats["files_failed"] += 1
            stats["failed_paths"].append(entry.path)
            continue

        stats["files_extracted"] += 1
        stats["bytes_written"] += len(content)


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
        if success:
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
            }
        },
        "required": ["image_path", "partition_offset", "directory_path", "output_path"]
    }
}
