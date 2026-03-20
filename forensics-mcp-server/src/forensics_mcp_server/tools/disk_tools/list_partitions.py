"""Tool for listing partitions in a disk image using pytsk3."""

import pytsk3
from typing import Dict, Any, List
from ...utils.image_detector import ImageDetector
from ...models.schemas import (
    ListPartitionsInput,
    PartitionsOutput,
    Partition,
    ErrorOutput,
)


def _get_partition_type_str(part_type: int) -> str:
    """Convert partition type to string."""
    partition_types = {
        0x00: "Empty",
        0x01: "FAT12",
        0x04: "FAT16 (< 32MB)",
        0x05: "Extended",
        0x06: "FAT16 (>= 32MB)",
        0x07: "NTFS / exFAT / HPFS",
        0x0B: "FAT32 (CHS)",
        0x0C: "FAT32 (LBA)",
        0x0E: "FAT16 (LBA)",
        0x0F: "Extended (LBA)",
        0x82: "Linux swap",
        0x83: "Linux",
        0x85: "Linux Extended",
        0x8E: "Linux LVM",
        0xA5: "FreeBSD",
        0xA6: "OpenBSD",
        0xA8: "Mac OS X",
        0xA9: "NetBSD",
        0xAB: "Mac OS X Boot",
        0xAF: "Mac OS X HFS+",
        0xEE: "GPT Protective",
        0xEF: "EFI System",
    }
    return partition_types.get(part_type, f"Unknown (0x{part_type:02X})")


def _detect_filesystem_with_tsk(handler, offset: int) -> str:
    """Detect filesystem type using pytsk3."""
    try:
        img_handle = handler.get_image_handle()
        fs = pytsk3.FS_Info(img_handle, offset=offset)
        fs_type = fs.info.ftype
        
        fs_types = {
            pytsk3.TSK_FS_TYPE_NTFS: "NTFS",
            pytsk3.TSK_FS_TYPE_FAT12: "FAT12",
            pytsk3.TSK_FS_TYPE_FAT16: "FAT16",
            pytsk3.TSK_FS_TYPE_FAT32: "FAT32",
            pytsk3.TSK_FS_TYPE_EXT2: "ext2",
            pytsk3.TSK_FS_TYPE_EXT3: "ext3",
            pytsk3.TSK_FS_TYPE_EXT4: "ext4",
            pytsk3.TSK_FS_TYPE_HFS: "HFS",
            pytsk3.TSK_FS_TYPE_ISO9660: "ISO9660",
            pytsk3.TSK_FS_TYPE_EXFAT: "exFAT",
        }
        
        return fs_types.get(fs_type, f"Unknown ({fs_type})")
    except Exception:
        return "Unknown"


def _read_partitions_with_tsk(handler) -> List[Partition]:
    """Read partitions using pytsk3."""
    partitions = []
    
    try:
        img_handle = handler.get_image_handle()
        
        # Try to get volume info (partition table)
        try:
            vol_info = pytsk3.Volume_Info(img_handle)
            
            for i, part in enumerate(vol_info):
                if part.len == 0:
                    continue
                
                offset = part.start * 512  # Assuming 512-byte sectors
                size = part.len * 512
                
                # Detect filesystem
                fs_type = _detect_filesystem_with_tsk(handler, offset)
                
                partitions.append(Partition(
                    offset=offset,
                    size=size,
                    type=_get_partition_type_str(part.desc),
                    label=None,
                    filesystem=fs_type,
                    index=i
                ))
            
            vol_info.close()
            
        except Exception as e:
            # No partition table found, treat entire image as single partition
            size = handler.get_size()
            fs_type = _detect_filesystem_with_tsk(handler, 0)
            
            partitions.append(Partition(
                offset=0,
                size=size,
                type="Raw / No partition table",
                label=None,
                filesystem=fs_type,
                index=0
            ))
        
    except Exception as e:
        print(f"Error reading partitions with TSK: {e}")
    
    return partitions


async def list_partitions(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """List partitions in a disk image.
    
    This tool reads the partition table using pytsk3 from the image
    and returns information about each partition.
    
    Args:
        input_data: Dictionary containing 'image_path'
        
    Returns:
        Dictionary with partition list or error
    """
    try:
        # Validate input
        input_model = ListPartitionsInput(**input_data)
        
        # Get handler
        handler = ImageDetector.get_handler(input_model.image_path)
        
        if not handler:
            return ErrorOutput(
                message=f"Unsupported image format or file not found: {input_model.image_path}",
                code="UNSUPPORTED_FORMAT"
            ).model_dump()
        
        # Read partitions using pytsk3
        with handler:
            partitions = _read_partitions_with_tsk(handler)
        
        # Build output
        output = PartitionsOutput(
            partitions=partitions,
            count=len(partitions)
        )
        
        return output.model_dump()
        
    except FileNotFoundError as e:
        return ErrorOutput(
            message=f"Image file not found: {str(e)}",
            code="FILE_NOT_FOUND"
        ).model_dump()
    except Exception as e:
        return ErrorOutput(
            message=f"Error reading partitions: {str(e)}",
            code="PARTITION_ERROR",
            details={"exception": type(e).__name__}
        ).model_dump()


# Tool definition for MCP
tool_definition = {
    "name": "list_partitions",
    "description": "List partitions in a disk image using The Sleuth Kit (pytsk3). Supports MBR, GPT, and other partition tables.",
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
