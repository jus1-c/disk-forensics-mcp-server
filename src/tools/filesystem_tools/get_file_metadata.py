"""Tool for getting detailed file metadata from a partition."""

from typing import Dict, Any
from src.utils.image_detector import ImageDetector
from src.models.schemas import (
    GetFileMetadataInput,
    FileMetadataOutput,
    FileEntry,
    ErrorOutput,
)


async def get_file_metadata(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Get detailed metadata of a file from a partition.
    
    This tool retrieves comprehensive metadata including:
    - File name, path, size
    - Timestamps (created, modified, accessed)
    - Inode number
    - Directory or file type
    - Deleted status (if supported)
    
    Uses persistent caching for improved performance on repeated calls.
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'file_path'
        
    Returns:
        Dictionary with file metadata or error
    """
    try:
        # Validate input
        input_model = GetFileMetadataInput(**input_data)
        
        # Get handler from cache
        handler = ImageDetector.get_handler_cached(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Get metadata using handler's method (cached internally)
        file_info = handler.get_file_metadata(
            partition_offset=input_model.partition_offset,
            file_path=input_model.file_path
        )
        
        if file_info is None:
            return ErrorOutput(
                message=f"File not found: {input_model.file_path}",
                code="FILE_NOT_FOUND"
            ).model_dump()
        
        # Build output
        file_entry = FileEntry(
            name=file_info.name,
            path=file_info.path,
            size=file_info.size,
            is_directory=file_info.is_directory,
            is_deleted=file_info.is_deleted,
            created=file_info.created,
            modified=file_info.modified,
            accessed=file_info.accessed,
            inode=file_info.inode
        )
        
        output = FileMetadataOutput(file=file_entry)
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error getting file metadata: {str(e)}",
            code="FILESYSTEM_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "get_file_metadata",
    "description": "Get detailed metadata of a specific file including timestamps, size, inode, and type. Useful for forensic timeline analysis. Uses caching for improved performance.",
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
            "file_path": {
                "type": "string",
                "description": "Path to the file within the partition"
            }
        },
        "required": ["image_path", "partition_offset", "file_path"]
    }
}
