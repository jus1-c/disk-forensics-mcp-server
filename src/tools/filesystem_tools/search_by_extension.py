"""Tool for searching files by extension in a partition."""

import os
from typing import Dict, Any, List
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    SearchByExtensionInput,
    SearchResultsOutput,
    ErrorOutput,
)


async def search_by_extension(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Search for files with specific extension in a partition.
    
    This tool recursively searches the filesystem for files
    matching the given extension (e.g., 'txt', 'jpg', 'exe').
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'extension', 'path'
        
    Returns:
        Dictionary with matching files or error
    """
    try:
        # Validate input
        input_model = SearchByExtensionInput(**input_data)
        
        # Get handler from cache
        handler = ImageDetector.get_handler_cached(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Normalize extension
        extension = input_model.extension.lower()
        if extension.startswith('.'):
            extension = extension[1:]
        
        # Search recursively
        matches = await _search_recursive(
            handler,
            input_model.partition_offset,
            input_model.path,
            extension
        )
        
        # Build output
        output = SearchResultsOutput(
            files=[
                {
                    "name": f.name,
                    "path": f.path,
                    "size": f.size,
                    "is_directory": f.is_directory,
                    "is_deleted": f.is_deleted,
                    "created": f.created.isoformat() if f.created else None,
                    "modified": f.modified.isoformat() if f.modified else None,
                    "accessed": f.accessed.isoformat() if f.accessed else None,
                    "inode": f.inode
                }
                for f in matches
            ],
            count=len(matches),
            search_term=f"*.{extension}"
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error searching files: {str(e)}",
            code="SEARCH_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


async def _search_recursive(
    handler,
    partition_offset: int,
    path: str,
    extension: str
) -> List[Any]:
    """Recursively search for files with given extension."""
    matches = []
    
    try:
        # Get files in current directory
        files = handler.list_files(partition_offset, path)
        
        for f in files:
            if f.is_directory:
                # Skip . and ..
                if f.name in ['.', '..']:
                    continue
                
                # Recursively search subdirectories
                try:
                    sub_matches = await _search_recursive(
                        handler, partition_offset, f.path, extension
                    )
                    matches.extend(sub_matches)
                except Exception:
                    # Skip directories we can't access
                    pass
            else:
                # Check extension
                file_ext = os.path.splitext(f.name)[1].lower()
                if file_ext == f'.{extension}':
                    matches.append(f)
    
    except Exception:
        # Skip directories we can't access
        pass
    
    return matches


# Tool definition for MCP
tool_definition = {
    "name": "search_by_extension",
    "description": "Search for files with a specific extension (e.g., 'txt', 'jpg', 'exe'). Recursively searches all subdirectories. Uses caching for improved performance.",
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
            "extension": {
                "type": "string",
                "description": "File extension to search for (e.g., 'txt', 'jpg')"
            },
            "path": {
                "type": "string",
                "description": "Directory path to start search (default: /)",
                "default": "/"
            }
        },
        "required": ["image_path", "partition_offset", "extension"]
    }
}
