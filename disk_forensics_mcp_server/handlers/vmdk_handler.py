"""VMDK (VMware Virtual Disk) handler.

VMDK is VMware's virtual disk format. This handler supports both regular
VMDK and streamOptimized VMDK using pyvmdk for decompression.
"""

import os
import struct
import pytsk3
from typing import Optional, List, Dict, Any, Tuple
from .base_handler import BaseImageHandler, ImageInfo, FileInfo, PartitionInfo

# Try to import pyvmdk for streamOptimized support
try:
    import pyvmdk
    HAS_PYVMDK = True
except ImportError:
    HAS_PYVMDK = False


class VMDKImgInfoWrapper(pytsk3.Img_Info):
    """Wrapper for pyvmdk handle to work with pytsk3.
    
    This class wraps pyvmdk handle to provide pytsk3.Img_Info interface,
    enabling streamOptimized VMDK files to work with pytsk3 filesystem
    parsing.
    """
    
    def __init__(self, vmdk_handle):
        self._vmdk = vmdk_handle
        self._size = vmdk_handle.get_media_size()
        # Initialize parent with dummy values, we'll override methods
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_RAW)
    
    def read(self, offset: int, size: int) -> bytes:
        """Read data from VMDK at given offset."""
        self._vmdk.seek_offset(offset, 0)  # SEEK_SET = 0
        return self._vmdk.read_buffer(size)
    
    def get_size(self) -> int:
        """Get virtual size of VMDK."""
        return self._size
    
    def close(self):
        """Close VMDK handle."""
        if self._vmdk:
            self._vmdk.close()
            self._vmdk = None


class VMDKHandler(BaseImageHandler):
    """Handler for VMDK (VMware Virtual Disk) images.
    
    VMDK is a virtual disk format used by VMware. This handler leverages
    pytsk3's built-in VMDK support via Img_Info for regular VMDK files.
    
    For streamOptimized VMDK files (compressed), the handler detects the
    format and provides appropriate error messages or limited access.
    """
    
    # VMDK sparse extent magic number
    VMDK_MAGIC = b'KDMV'
    
    # VMDK flags
    FLAG_VALID_NEWLINE = 0x00000001
    FLAG_USE_REDIRECTION_GRAIN = 0x00000002
    FLAG_ZEROED_GRAIN_GTE = 0x00000004
    FLAG_COMPRESSION_DEFLATE = 0x00010000
    FLAG_COMPRESSION_NONE = 0x00020000
    
    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._format_name = "VMDK"
        self._img_info: Optional[pytsk3.Img_Info] = None
        self._fs_info: Optional[pytsk3.FS_Info] = None
        self._vmdk_info: Optional[Dict[str, Any]] = None
        self._partitions: List[PartitionInfo] = []
        self._current_partition_offset: int = 0
        self._file_objects: List[Any] = []
        
    @property
    def format_name(self) -> str:
        return self._format_name
    
    def _detect_vmdk_type(self) -> Dict[str, Any]:
        """Detect VMDK type and parse header information."""
        info = {
            'is_vmdk': False,
            'version': 0,
            'flags': 0,
            'capacity': 0,
            'grain_size': 0,
            'is_stream_optimized': False,
            'is_compressed': False,
            'descriptor_offset': 0,
            'descriptor_size': 0
        }
        
        try:
            with open(self.image_path, 'rb') as f:
                header = f.read(512)
                
                if len(header) < 512:
                    return info
                
                # Check magic number
                magic = header[0:4]
                if magic != self.VMDK_MAGIC:
                    return info
                
                info['is_vmdk'] = True
                
                # Parse sparse extent header
                info['version'] = struct.unpack('<I', header[4:8])[0]
                info['flags'] = struct.unpack('<I', header[8:12])[0]
                info['capacity'] = struct.unpack('<Q', header[12:20])[0]
                info['grain_size'] = struct.unpack('<I', header[20:24])[0]
                info['descriptor_offset'] = struct.unpack('<Q', header[24:32])[0]
                info['descriptor_size'] = struct.unpack('<I', header[32:36])[0]
                
                # Check for streamOptimized format
                if info['flags'] & self.FLAG_COMPRESSION_DEFLATE:
                    info['is_stream_optimized'] = True
                    info['is_compressed'] = True
                
                return info
                
        except Exception:
            return info
    
    def _detect_partitions(self) -> List[PartitionInfo]:
        """Detect partitions in the VMDK image."""
        if not self._img_info:
            return []

        partitions: List[PartitionInfo] = []

        try:
            vol_info = pytsk3.Volume_Info(self._img_info)
            block_size = getattr(getattr(vol_info, "info", None), "block_size", 512) or 512
            alloc_flag = getattr(pytsk3, "TSK_VS_PART_FLAG_ALLOC", None)

            for index, part in enumerate(vol_info, start=1):
                if part.len == 0:
                    continue

                if alloc_flag is not None and hasattr(part, "flags"):
                    if not (part.flags & alloc_flag):
                        continue

                offset = part.start * block_size
                fs_type = None
                try:
                    fs_type = pytsk3.FS_Info(self._img_info, offset=offset).info.ftype
                except Exception:
                    pass

                filesystem = {
                    pytsk3.TSK_FS_TYPE_NTFS: "NTFS",
                    pytsk3.TSK_FS_TYPE_FAT12: "FAT12",
                    pytsk3.TSK_FS_TYPE_FAT16: "FAT16",
                    pytsk3.TSK_FS_TYPE_FAT32: "FAT32",
                    pytsk3.TSK_FS_TYPE_EXT2: "ext2",
                    pytsk3.TSK_FS_TYPE_EXT3: "ext3",
                    pytsk3.TSK_FS_TYPE_EXT4: "ext4",
                    pytsk3.TSK_FS_TYPE_EXFAT: "exFAT",
                }.get(fs_type)

                part_type = part.desc.decode("utf-8", errors="replace").strip("\x00 ")
                partitions.append(PartitionInfo(
                    index=index,
                    offset=offset,
                    size=part.len * block_size,
                    type=part_type or f"Partition {index}",
                    filesystem=filesystem,
                    label=f"Partition {index}",
                ))

            if partitions:
                return partitions

        except Exception:
            pass

        return super().get_partitions()
    
    def _identify_filesystem(self, offset: int) -> Optional[str]:
        """Try to identify filesystem type at given offset."""
        try:
            data = self._img_info.read(offset, 512)
            
            if len(data) < 512:
                return None
            
            # Check for NTFS
            if data[3:7] == b'NTFS':
                return 'NTFS'
            
            # Check for FAT32
            if data[82:90] == b'FAT32   ':
                return 'FAT32'
            
            # Check for FAT12/16
            if data[54:62] == b'FAT16   ' or data[54:62] == b'FAT12   ':
                return 'FAT'
            
            # Check for ext2/3/4
            if data[56:58] == b'\x53\xef':
                return 'ext'
            
            return None
            
        except Exception:
            return None
    
    def _get_partition_type_name(self, type_code: int) -> str:
        """Get human-readable partition type name."""
        partition_types = {
            0x01: 'FAT12',
            0x04: 'FAT16 (< 32MB)',
            0x06: 'FAT16',
            0x07: 'NTFS/HPFS',
            0x0B: 'FAT32 (CHS)',
            0x0C: 'FAT32 (LBA)',
            0x0E: 'FAT16 (LBA)',
            0x82: 'Linux swap',
            0x83: 'Linux',
            0x85: 'Linux extended',
            0x8E: 'Linux LVM',
            0xA5: 'FreeBSD',
            0xA6: 'OpenBSD',
            0xA8: 'Mac OS X',
            0xEE: 'GPT',
            0xEF: 'EFI System',
        }
        return partition_types.get(type_code, f'0x{type_code:02X}')
    
    def _open_filesystem(self, partition_offset: int) -> bool:
        """Open filesystem at given partition offset."""
        try:
            self._fs_info = pytsk3.FS_Info(self._img_info, offset=partition_offset)
            self._current_partition_offset = partition_offset
            return True
        except Exception:
            self._fs_info = None
            return False
    
    def open(self) -> None:
        """Open the VMDK image.
        
        For streamOptimized VMDK, uses pyvmdk for on-demand decompression.
        For regular VMDK, uses pytsk3's built-in support.
        """
        try:
            # Detect VMDK type first
            self._vmdk_info = self._detect_vmdk_type()
            
            if not self._vmdk_info['is_vmdk']:
                raise IOError("File is not a valid VMDK image")
            
            # Check if streamOptimized and pyvmdk is available
            if self._vmdk_info.get('is_stream_optimized') and HAS_PYVMDK:
                try:
                    # Use pyvmdk for streamOptimized VMDK
                    abs_path = os.path.abspath(self.image_path)
                    file_obj = open(abs_path, 'rb')
                    vmdk_handle = pyvmdk.handle()
                    vmdk_handle.open_file_object(file_obj)
                    vmdk_handle.open_extent_data_files_as_file_objects([file_obj])
                    self._file_objects = [file_obj]
                    
                    # Wrap with our wrapper class
                    self._img_info = VMDKImgInfoWrapper(vmdk_handle)
                except Exception as pyvmdk_error:
                    try:
                        file_obj.close()
                    except Exception:
                        pass
                    # Fallback to pytsk3 if pyvmdk fails
                    # (e.g., extent file name mismatch in streamOptimized VMDK)
                    print(f"Warning: pyvmdk failed to open streamOptimized VMDK")
                    print(f"  Error: {pyvmdk_error}")
                    print(f"  Falling back to pytsk3 (limited functionality)")
                    print(f"  Note: streamOptimized VMDK requires conversion for full access")
                    print(f"  Convert with: qemu-img convert -f vmdk -O raw input.vmdk output.raw")
                    self._img_info = pytsk3.Img_Info(self.image_path)
            else:
                # Use pytsk3's built-in support for regular VMDK
                self._img_info = pytsk3.Img_Info(self.image_path)
            
            # Detect partitions
            self._partitions = self._detect_partitions()
            
            # Try to open first partition's filesystem
            if self._partitions:
                self._open_filesystem(self._partitions[0].offset)
            else:
                # Try offset 0 as fallback
                self._open_filesystem(0)
                
        except Exception as e:
            raise IOError(f"Failed to open VMDK image: {e}")
    
    def close(self) -> None:
        """Close the VMDK image."""
        # Call base handler close to clear caches
        super().close()
        
        self._fs_info = None
        self._img_info = None
        self._partitions = []
        self._current_partition_offset = 0

        for file_obj in self._file_objects:
            try:
                file_obj.close()
            except Exception:
                pass
        self._file_objects = []
    
    def read(self, offset: int, size: int) -> bytes:
        """Read data from the VMDK image."""
        if not self._img_info:
            raise IOError("VMDK image not opened")
        
        return self._img_info.read(offset, size)
    
    def get_size(self) -> int:
        """Get the total size of the VMDK image."""
        if not self._img_info:
            raise IOError("VMDK image not opened")
        
        return self._img_info.get_size()
    
    def get_info(self) -> ImageInfo:
        """Get information about the VMDK image."""
        size = self.get_size()
        
        metadata = {}
        if self._vmdk_info:
            metadata['vmdk_version'] = self._vmdk_info['version']
            metadata['capacity_sectors'] = self._vmdk_info['capacity']
            metadata['grain_size'] = self._vmdk_info['grain_size']
            if self._vmdk_info['is_stream_optimized']:
                metadata['format_subtype'] = 'streamOptimized'
                metadata['compressed'] = True
        
        return ImageInfo(
            format=self._format_name,
            size=size,
            sectors=size // 512,
            sector_size=512,
            checksum=None,
            metadata=metadata
        )
    
    def get_partitions(self) -> List[PartitionInfo]:
        """Get list of partitions in the image."""
        return self._partitions
    
    def select_partition(self, partition_number: int) -> bool:
        """Select a partition for filesystem operations."""
        for part in self._partitions:
            if part.index == partition_number:
                return self._open_filesystem(part.offset)
        return False
    
    def list_files(self, partition_offset: int = 0, path: str = "/") -> List[FileInfo]:
        """List files in a directory using the shared pytsk3 path."""
        return super().list_files(partition_offset, path)
    
    def get_file_metadata(self, partition_offset: int, file_path: str) -> Optional[FileInfo]:
        """Get file metadata using the shared pytsk3 path."""
        return super().get_file_metadata(partition_offset, file_path)
    
    def read_file(
        self,
        partition_offset: int,
        file_path: str,
        offset: int = 0,
        max_size: Optional[int] = None,
        chunk_size: int = BaseImageHandler.DEFAULT_READ_CHUNK_SIZE,
    ) -> Optional[bytes]:
        """Read file content using the shared pytsk3 path."""
        return super().read_file(partition_offset, file_path, offset, max_size, chunk_size)
    
    def get_image_handle(self):
        """Get pytsk3 image handle for filesystem operations."""
        return self._img_info
