"""Tool for getting directory tree structure from a partition."""

from typing import Dict, Any, List
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    ListFilesInput,
    DirectoryTreeOutput,
    ErrorOutput,
)


async def get_directory_tree(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Get directory tree structure from a partition.
    
    This tool recursively traverses the filesystem and returns
    a hierarchical tree structure of directories and files.
    
    Args:
        input_data: Dictionary containing 'image_path', 'partition_offset', 'path', 'max_depth'
        
    Returns:
        Dictionary with tree structure or error
    """
    try:
        # Validate input
        input_model = ListFilesInput(**input_data)
        
        # Get handler
        handler = ImageDetector.get_handler(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Build tree recursively
        with handler:
            tree = await _build_tree(
                handler,
                input_model.partition_offset,
                input_model.path,
                input_model.max_depth,
                0
            )
        
        # Build output
        output = DirectoryTreeOutput(
            tree=tree,
            total_files=tree.get('total_files', 0),
            total_dirs=tree.get('total_dirs', 0)
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error building directory tree: {str(e)}",
            code="FILESYSTEM_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


async def _build_tree(
    handler,
    partition_offset: int,
    path: str,
    max_depth: int,
    current_depth: int
) -> Dict[str, Any]:
    """Recursively build directory tree."""
    
    # Get files in current directory
    files = handler.list_files(partition_offset, path)
    
    # Separate dirs and files
    dirs = [f for f in files if f.is_directory]
    regular_files = [f for f in files if not f.is_directory]
    
    # Build node
    node = {
        "name": path.split('/')[-1] if path != '/' else '/',
        "path": path,
        "type": "directory",
        "size": sum(f.size for f in regular_files),
        "children": [],
        "file_count": len(regular_files),
        "dir_count": len(dirs)
    }
    
    total_files = len(regular_files)
    total_dirs = len(dirs)
    
    # Add files as children
    for f in regular_files:
        child = {
            "name": f.name,
            "path": f.path,
            "type": "file",
            "size": f.size,
            "created": f.created.isoformat() if f.created else None,
            "modified": f.modified.isoformat() if f.modified else None,
            "accessed": f.accessed.isoformat() if f.accessed else None,
        }
        node["children"].append(child)
    
    # Recursively process subdirectories
    if current_depth < max_depth:
        for d in dirs:
            if d.name not in ['.', '..']:
                try:
                    child_tree = await _build_tree(
                        handler,
                        partition_offset,
                        d.path,
                        max_depth,
                        current_depth + 1
                    )
                    node["children"].append(child_tree)
                    total_files += child_tree.get('total_files', 0)
                    total_dirs += child_tree.get('total_dirs', 0)
                except Exception:
                    # Skip directories we can't access
                    pass
    
    node["total_files"] = total_files
    node["total_dirs"] = total_dirs
    
    return node


# Tool definition for MCP
tool_definition = {
    "name": "get_directory_tree",
    "description": "Get hierarchical directory tree structure from a partition. Recursively traverses directories and returns a tree view similar to FTK Imager.",
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
            "path": {
                "type": "string",
                "description": "Starting path for tree (default: /)",
                "default": "/"
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum recursion depth (default: 10)",
                "default": 10
            }
        },
        "required": ["image_path", "partition_offset"]
    }
}
