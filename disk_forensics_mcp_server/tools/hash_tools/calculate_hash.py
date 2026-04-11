"""Tool for calculating hash of disk images."""

import hashlib
from typing import Dict, Any
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    CalculateHashInput,
    HashOutput,
    ErrorOutput,
)


# Buffer size for reading (1MB chunks)
BUFFER_SIZE = 1024 * 1024


async def calculate_hash(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate hash of a disk image.
    
    This tool computes the hash (MD5, SHA1, or SHA256) of an entire
    disk image, including all segments for split images.
    
    Args:
        input_data: Dictionary containing 'image_path' and optional 'algorithm'
        
    Returns:
        Dictionary with hash value or error
    """
    try:
        # Validate input
        input_model = CalculateHashInput(**input_data)
        
        # Validate algorithm
        algorithm = input_model.algorithm.lower()
        if algorithm not in ['md5', 'sha1', 'sha256']:
            return ErrorOutput(
                message=f"Unsupported hash algorithm: {algorithm}. Use md5, sha1, or sha256.",
                code="INVALID_ALGORITHM"
            ).model_dump()
        
        # Get handler
        handler = ImageDetector.get_handler(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Create hasher
        if algorithm == 'md5':
            hasher = hashlib.md5()
        elif algorithm == 'sha1':
            hasher = hashlib.sha1()
        else:  # sha256
            hasher = hashlib.sha256()
        
        # Calculate hash
        with handler:
            total_size = handler.get_size()
            offset = 0
            
            while offset < total_size:
                # Read in chunks
                to_read = min(BUFFER_SIZE, total_size - offset)
                data = handler.read(offset, to_read)
                
                if not data:
                    break
                
                hasher.update(data)
                offset += len(data)
        
        # Build output
        output = HashOutput(
            algorithm=algorithm.upper(),
            hash_value=hasher.hexdigest(),
            image_path=input_model.image_path
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error calculating hash: {str(e)}",
            code="HASH_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "calculate_hash",
    "description": "Calculate hash (MD5, SHA1, or SHA256) of a disk image. Supports all image formats including split images.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the disk image file"
            },
            "algorithm": {
                "type": "string",
                "description": "Hash algorithm to use (md5, sha1, sha256)",
                "enum": ["md5", "sha1", "sha256"],
                "default": "sha256"
            }
        },
        "required": ["image_path"]
    }
}
