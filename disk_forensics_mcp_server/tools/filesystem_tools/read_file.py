"""Tool for reading file content from a partition."""

import base64
from typing import Dict, Any
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    ReadFileContentInput,
    FileContentOutput,
    ErrorOutput,
)


def _is_binary_content(content: bytes) -> bool:
    """Check if content is binary."""
    # Check for null bytes
    if b'\x00' in content[:1024]:
        return True
    
    # Check for non-printable characters
    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
    if bool(content.translate(None, text_chars)):
        return True
    
    return False


async def read_file_content(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Read content of a file from a partition.
    
    This tool uses pytsk3 to read file content from the filesystem.
    Returns text content or base64-encoded binary content.
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'file_path', 'max_size'
        
    Returns:
        Dictionary with file content or error
    """
    try:
        # Validate input
        input_model = ReadFileContentInput(**input_data)
        
        # Get handler from cache
        handler = ImageDetector.get_handler_cached(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()

        metadata = handler.get_file_metadata(
            partition_offset=input_model.partition_offset,
            file_path=input_model.file_path,
        )
        if metadata is not None and metadata.is_directory:
            return ErrorOutput(
                message=f"File not found or is a directory: {input_model.file_path}",
                code="FILE_NOT_FOUND"
            ).model_dump()

        # Read at most max_size instead of buffering the whole file first.
        content = handler.read_file(
            partition_offset=input_model.partition_offset,
            file_path=input_model.file_path,
            max_size=input_model.max_size,
        )
        
        if content is None:
            return ErrorOutput(
                message=f"File not found or is a directory: {input_model.file_path}",
                code="FILE_NOT_FOUND"
            ).model_dump()
        
        truncated = metadata is not None and metadata.size > input_model.max_size
        
        # Check if binary
        is_binary = _is_binary_content(content)
        
        if is_binary:
            # Return base64 encoded
            result_content = base64.b64encode(content).decode('utf-8')
            encoding = "base64"
        else:
            # Return as text
            try:
                result_content = content.decode('utf-8')
                encoding = "utf-8"
            except UnicodeDecodeError:
                # Try other encodings
                try:
                    result_content = content.decode('latin-1')
                    encoding = "latin-1"
                except:
                    result_content = base64.b64encode(content).decode('utf-8')
                    encoding = "base64"
        
        # Build output
        output = FileContentOutput(
            content=result_content,
            size=len(content),
            is_binary=is_binary,
            encoding=encoding
        )
        
        result = output.model_dump()
        if truncated:
            result["truncated"] = True
            result["note"] = f"Content truncated to {input_model.max_size} bytes"
        
        return result
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error reading file: {str(e)}",
            code="FILESYSTEM_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "read_file_content",
    "description": "Read content of a file from a partition. Returns text content or base64-encoded binary data. Automatically detects binary files. Uses caching for improved performance.",
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
            },
            "max_size": {
                "type": "integer",
                "description": "Maximum bytes to read (default 1MB)",
                "default": 1048576
            }
        },
        "required": ["image_path", "partition_offset", "file_path"]
    }
}
