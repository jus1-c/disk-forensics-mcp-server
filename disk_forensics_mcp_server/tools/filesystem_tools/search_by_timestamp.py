"""Tool for searching files by timestamp in a partition."""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    ErrorOutput,
)


async def search_by_timestamp(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Search for files based on timestamps.
    
    This tool searches for files modified/created/accessed within
    a specific time range. Useful for timeline analysis.
    
    Args:
        input_data: Dictionary containing:
            - image_path: Path to disk image
            - partition_offset: Partition offset
            - start_time: Start time (ISO format)
            - end_time: End time (ISO format)
            - timestamp_type: 'created', 'modified', 'accessed', or 'any'
            - path: Starting path (default: /)
        
    Returns:
        Dictionary with matching files or error
    """
    try:
        # Parse input
        image_path = input_data.get('image_path')
        partition_offset = input_data.get('partition_offset', 0)
        start_time_str = input_data.get('start_time')
        end_time_str = input_data.get('end_time')
        timestamp_type = input_data.get('timestamp_type', 'any')
        path = input_data.get('path', '/')
        
        if not image_path:
            return ErrorOutput(
                message="image_path is required",
                code="MISSING_PARAMETER"
            ).model_dump()
        
        # Parse timestamps
        start_time = datetime.fromisoformat(start_time_str) if start_time_str else None
        end_time = datetime.fromisoformat(end_time_str) if end_time_str else None
        
        # Get handler from cache
        handler = ImageDetector.get_handler_cached(image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Search recursively
        matches = await _search_by_time(
            handler,
            partition_offset,
            path,
            start_time,
            end_time,
            timestamp_type
        )
        
        # Build output
        output = {
            "files": [
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
            "count": len(matches),
            "search_term": f"timestamp:{timestamp_type}",
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None
        }
        
        return output
        
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


async def _search_by_time(
    handler,
    partition_offset: int,
    path: str,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    timestamp_type: str
) -> List[Any]:
    """Recursively search for files by timestamp."""
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
                    sub_matches = await _search_by_time(
                        handler, partition_offset, f.path,
                        start_time, end_time, timestamp_type
                    )
                    matches.extend(sub_matches)
                except Exception:
                    pass
            else:
                # Check timestamp
                file_time = None
                if timestamp_type == 'created' and f.created:
                    file_time = f.created
                elif timestamp_type == 'modified' and f.modified:
                    file_time = f.modified
                elif timestamp_type == 'accessed' and f.accessed:
                    file_time = f.accessed
                elif timestamp_type == 'any':
                    # Check any timestamp
                    times = [t for t in [f.created, f.modified, f.accessed] if t]
                    if times:
                        file_time = max(times)  # Use most recent
                
                if file_time:
                    # Check if within range
                    in_range = True
                    if start_time and file_time < start_time:
                        in_range = False
                    if end_time and file_time > end_time:
                        in_range = False
                    
                    if in_range:
                        matches.append(f)
    
    except Exception:
        pass
    
    return matches


# Tool definition for MCP
tool_definition = {
    "name": "search_by_timestamp",
    "description": "Search for files based on timestamps (created, modified, accessed). Useful for timeline analysis and finding files from specific time periods.",
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
            "start_time": {
                "type": "string",
                "description": "Start time in ISO format (e.g., '2024-01-01T00:00:00')"
            },
            "end_time": {
                "type": "string",
                "description": "End time in ISO format (e.g., '2024-12-31T23:59:59')"
            },
            "timestamp_type": {
                "type": "string",
                "description": "Which timestamp to check: 'created', 'modified', 'accessed', or 'any'",
                "default": "any"
            },
            "path": {
                "type": "string",
                "description": "Directory path to start search (default: /)",
                "default": "/"
            }
        },
        "required": ["image_path", "partition_offset"]
    }
}
