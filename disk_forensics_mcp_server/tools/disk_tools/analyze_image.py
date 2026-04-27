"""Tool for analyzing disk images."""

import json
from typing import Dict, Any
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    AnalyzeDiskImageInput,
    DiskImageInfo,
    ErrorOutput,
)


async def analyze_disk_image(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a disk image and return information about it.
    
    This tool detects the image format and returns detailed information
    including size, format type, and whether it's a split image.
    
    Args:
        input_data: Dictionary containing 'image_path'
        
    Returns:
        Dictionary with image information or error
    """
    try:
        # Validate input
        input_model = AnalyzeDiskImageInput(**input_data)
        
        # Detect format and get cached handler so repeated tool calls stay warm.
        handler = ImageDetector.get_handler_cached(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        info = handler.get_info()
        
        # Build output
        output = DiskImageInfo(
            format=info.format,
            size=info.size,
            sectors=info.sectors,
            sector_size=info.sector_size,
            is_split=handler.is_split() if hasattr(handler, 'is_split') else False,
            segments=handler.get_segments() if hasattr(handler, 'get_segments') else [input_model.image_path],
            metadata=info.metadata or {}
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error analyzing image: {str(e)}",
            code="ANALYSIS_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "analyze_disk_image",
    "description": "Analyze a disk image and return information about its format, size, and structure. Supports RAW, split RAW, and other formats.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the disk image file"
            }
        },
        "required": ["image_path"]
    }
}
