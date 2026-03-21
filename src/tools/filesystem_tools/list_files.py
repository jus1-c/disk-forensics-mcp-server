"""Tool for listing files in a partition."""

import base64
from typing import Dict, Any, List
from src.utils.image_detector import ImageDetector
from src.models.schemas import (
    ListFilesInput,
    FilesOutput,
    FileEntry,
    ErrorOutput,
)


async def list_files(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """List files in a directory within a partition.
    
    This tool uses pytsk3 to browse the filesystem and list files
    in the specified directory. Uses persistent caching for improved performance.
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'path'
        
    Returns:
        Dictionary with file list or error
    """
    try:
        # Validate input
        input_model = ListFilesInput(**input_data)
        
        # Get handler from cache (creates new if not exists)
        handler = ImageDetector.get_handler_cached(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # List files using handler's method (cached internally)
        files = handler.list_files(
            partition_offset=input_model.partition_offset,
            path=input_model.path
        )
        
        # Convert to output format
        file_entries = []
        for f in files:
            entry = FileEntry(
                name=f.name,
                path=f.path,
                size=f.size,
                is_directory=f.is_directory,
                is_deleted=f.is_deleted,
                created=f.created,
                modified=f.modified,
                accessed=f.accessed,
                inode=f.inode
            )
            file_entries.append(entry)
        
        # Build output
        output = FilesOutput(
            files=file_entries,
            count=len(file_entries),
            path=input_model.path
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error listing files: {str(e)}",
            code="FILESYSTEM_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "list_files",
    "description": "List files and directories in a partition. Uses pytsk3 to browse NTFS, FAT, ext2/3/4, and other filesystems with persistent caching for improved performance.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the disk image file"
            },
            "partition_offset": {
                "type": "integer",
                "description": "Offset of the partition in bytes (from list_partitions)"
            },
            "path": {
                "type": "string",
                "description": "Directory path to list (default: /)",
                "default": "/"
            }
        },
        "required": ["image_path", "partition_offset"]
    }
}
