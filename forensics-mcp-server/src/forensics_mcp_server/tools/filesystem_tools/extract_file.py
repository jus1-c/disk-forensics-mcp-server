"""Tool for extracting files from a partition to disk."""

import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from ...utils.image_detector import ImageDetector
from ...models.schemas import ErrorOutput


class ExtractFileInput(BaseModel):
    """Input for extract_file tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    file_path: str = Field(..., description="Path to the file within the partition")
    output_path: str = Field(..., description="Path to save the extracted file")


class ExtractFileOutput(BaseModel):
    """Output for extract_file tool."""
    success: bool = Field(..., description="Whether extraction succeeded")
    source_path: str = Field(..., description="Source file path in image")
    output_path: str = Field(..., description="Output file path")
    size: int = Field(..., description="Size of extracted file in bytes")
    message: str = Field(..., description="Status message")


async def extract_file(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a file from a partition to disk.
    
    This tool uses pytsk3 to read file content from the filesystem
    and saves it to the specified output path.
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'file_path', 'output_path'
        
    Returns:
        Dictionary with extraction result or error
    """
    try:
        # Validate input
        input_model = ExtractFileInput(**input_data)
        
        # Get handler
        handler = ImageDetector.get_handler(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Read file using handler's method
        with handler:
            content = handler.read_file(
                partition_offset=input_model.partition_offset,
                file_path=input_model.file_path
            )
        
        if content is None:
            return ErrorOutput(
                message=f"File not found or is a directory: {input_model.file_path}",
                code="FILE_NOT_FOUND"
            ).model_dump()
        
        # Create output directory if needed
        output_dir = os.path.dirname(input_model.output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # Write file to disk
        with open(input_model.output_path, 'wb') as f:
            f.write(content)
        
        # Build output
        output = ExtractFileOutput(
            success=True,
            source_path=input_model.file_path,
            output_path=input_model.output_path,
            size=len(content),
            message=f"Successfully extracted {len(content)} bytes to {input_model.output_path}"
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except PermissionError as e:
        return ErrorOutput(
            message=f"Permission denied writing to output path: {str(e)}",
            code="PERMISSION_DENIED"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error extracting file: {str(e)}",
            code="EXTRACTION_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "extract_file",
    "description": "Extract a file from a partition to disk. Saves the file content to the specified output path.",
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
                "description": "Path to the file within the partition (e.g., /Windows/System32/config/SAM)"
            },
            "output_path": {
                "type": "string",
                "description": "Path to save the extracted file (e.g., C:\\extracted\\SAM)"
            }
        },
        "required": ["image_path", "partition_offset", "file_path", "output_path"]
    }
}
