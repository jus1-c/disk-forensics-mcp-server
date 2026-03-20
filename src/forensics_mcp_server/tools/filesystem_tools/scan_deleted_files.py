"""Tool for scanning deleted files in a partition."""

import pytsk3
from typing import Dict, Any, List
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    ErrorOutput,
)


async def scan_deleted_files(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Scan for deleted files in a partition.
    
    This tool attempts to find and recover information about deleted files
    using the filesystem's deleted entries (MFT unallocated entries in NTFS).
    Note: Content recovery depends on whether clusters have been overwritten.
    
    Args:
        input_data: Dictionary containing:
            - image_path: Path to disk image
            - partition_offset: Partition offset
            - path: Starting path (default: /)
            - max_results: Maximum results to return (default: 100)
        
    Returns:
        Dictionary with deleted files info or error
    """
    try:
        # Parse input
        image_path = input_data.get('image_path')
        partition_offset = input_data.get('partition_offset', 0)
        path = input_data.get('path', '/')
        max_results = input_data.get('max_results', 100)
        
        if not image_path:
            return ErrorOutput(
                message="image_path is required",
                code="MISSING_PARAMETER"
            ).model_dump()
        
        # Get handler
        handler = ImageDetector.get_handler(image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Scan for deleted files
        with handler:
            deleted_files = await _scan_deleted(
                handler,
                partition_offset,
                path,
                max_results
            )
        
        # Build output
        output = {
            "deleted_files": [
                {
                    "name": f.get('name', 'UNKNOWN'),
                    "path": f.get('path', ''),
                    "size": f.get('size', 0),
                    "inode": f.get('inode'),
                    "created": f.get('created'),
                    "modified": f.get('modified'),
                    "accessed": f.get('accessed'),
                    "recoverable": f.get('recoverable', False),
                    "notes": f.get('notes', '')
                }
                for f in deleted_files
            ],
            "count": len(deleted_files),
            "path": path,
            "warning": "Deleted file recovery depends on whether data clusters have been overwritten. Some files may not be fully recoverable."
        }
        
        return output
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error scanning deleted files: {str(e)}",
            code="SCAN_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


async def _scan_deleted(
    handler,
    partition_offset: int,
    path: str,
    max_results: int
) -> List[Dict[str, Any]]:
    """Scan for deleted files using pytsk3."""
    deleted_files = []
    
    try:
        # Get filesystem
        fs = handler.get_filesystem(partition_offset)
        if not fs:
            return deleted_files
        
        # Open directory
        dir_obj = fs.open_dir(path=path)
        
        for entry in dir_obj:
            if len(deleted_files) >= max_results:
                break
            
            try:
                # Check if this is a deleted entry
                meta = entry.info.meta
                name = entry.info.name.name.decode('utf-8', errors='replace')
                
                # Skip . and ..
                if name in ['.', '..']:
                    continue
                
                # Check for deleted flag
                is_deleted = False
                if meta and hasattr(meta, 'flags'):
                    # Check TSK_FS_META_FLAG_UNALLOC flag
                    if meta.flags & pytsk3.TSK_FS_META_FLAG_UNALLOC:
                        is_deleted = True
                
                # Also check if entry is in $OrphanFiles or $Deleted
                if not is_deleted and '$' in name:
                    # Check if this might be a deleted entry
                    if name.startswith('$Orphan') or 'Deleted' in path:
                        is_deleted = True
                
                if is_deleted or (meta and meta.type == pytsk3.TSK_FS_META_TYPE_UNDEF):
                    # This is a deleted or unallocated entry
                    file_info = {
                        'name': name if name else f"DELETED_{entry.info.name.meta_addr}",
                        'path': f"{path}/{name}" if path != '/' else f"/{name}",
                        'size': meta.size if meta else 0,
                        'inode': entry.info.name.meta_addr if hasattr(entry.info.name, 'meta_addr') else None,
                        'created': None,
                        'modified': None,
                        'accessed': None,
                        'recoverable': False,
                        'notes': 'Deleted file entry found'
                    }
                    
                    # Try to get timestamps
                    if meta:
                        if hasattr(meta, 'crtime') and meta.crtime:
                            from datetime import datetime
                            file_info['created'] = datetime.fromtimestamp(meta.crtime).isoformat()
                        if hasattr(meta, 'mtime') and meta.mtime:
                            from datetime import datetime
                            file_info['modified'] = datetime.fromtimestamp(meta.mtime).isoformat()
                        if hasattr(meta, 'atime') and meta.atime:
                            from datetime import datetime
                            file_info['accessed'] = datetime.fromtimestamp(meta.atime).isoformat()
                    
                    # Check if potentially recoverable
                    # (has size > 0 and some metadata)
                    if file_info['size'] > 0 and file_info['inode']:
                        file_info['recoverable'] = True
                        file_info['notes'] = 'Potentially recoverable - data may still exist'
                    
                    deleted_files.append(file_info)
                
                # Recursively scan subdirectories
                elif meta and meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                    if name not in ['.', '..']:
                        try:
                            sub_path = f"{path}/{name}" if path != '/' else f"/{name}"
                            sub_files = await _scan_deleted(
                                handler, partition_offset, sub_path, max_results - len(deleted_files)
                            )
                            deleted_files.extend(sub_files)
                        except Exception:
                            pass
            
            except Exception:
                # Skip entries we can't process
                continue
    
    except Exception as e:
        print(f"Error scanning directory: {e}")
    
    return deleted_files


# Tool definition for MCP
tool_definition = {
    "name": "scan_deleted_files",
    "description": "Scan for deleted files in the filesystem. Attempts to find unallocated MFT entries and deleted file records. Note: Recovery success depends on whether data clusters have been overwritten.",
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
                "description": "Directory path to start scan (default: /)",
                "default": "/"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of deleted files to return (default: 100)",
                "default": 100
            }
        },
        "required": ["image_path", "partition_offset"]
    }
}
