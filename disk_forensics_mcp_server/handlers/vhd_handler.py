"""VHD/VHDX (Virtual Hard Disk) handler.

VHD/VHDX are Microsoft's virtual disk formats. This handler uses pyvhdi (libvhdi-python)
for dynamic/sparse VHD/VHDX files and pytsk3 for filesystem access.

Supports:
- VHD (Virtual Hard Disk) - Legacy format
- VHDX (Virtual Hard Disk v2) - Modern format
- Fixed and Dynamic VHD/VHDX
"""

import struct
import pytsk3
from typing import Optional, List, Dict, Any
from .base_handler import BaseImageHandler, ImageInfo, FileInfo, PartitionInfo


class VHDImgInfo(pytsk3.Img_Info):
    """Custom Img_Info that wraps libvhdi for dynamic VHD/VHDX support."""
    
    def __init__(self, vhdi_file):
        # Store reference to pyvhdi file object
        self._vhdi = vhdi_file
        self._size = vhdi_file.media_size
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)
    
    def get_size(self):
        return self._size
    
    def read(self, offset, size):
        self._vhdi.seek(offset)
        return self._vhdi.read(size)
    
    def close(self):
        if self._vhdi:
            self._vhdi.close()
            self._vhdi = None


class VHDHandler(BaseImageHandler):
    """Handler for VHD/VHDX (Virtual Hard Disk) images.
    
    VHD and VHDX are Microsoft's virtual disk formats used by Hyper-V,
    Windows Virtual PC, and other virtualization platforms.
    
    This handler uses libvhdi-python for reading dynamic VHD/VHDX files
    and pytsk3 for filesystem analysis.
    """
    
    # VHD magic numbers
    VHD_COOKIE = b'conectix'
    VHDX_COOKIE = b'vhdxfile'
    
    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._format_name = "VHD/VHDX"
        self._img_info: Optional[pytsk3.Img_Info] = None
        self._fs_info: Optional[pytsk3.FS_Info] = None
        self._vhd_info: Optional[Dict[str, Any]] = None
        self._partitions: List[PartitionInfo] = []
        self._current_partition_offset: int = 0
        self._vhdi_file = None  # pyvhdi file object
        self._use_libvhdi = False
        
    @property
    def format_name(self) -> str:
        return self._format_name
    
    def _detect_vhd_type(self) -> Dict[str, Any]:
        """Detect VHD/VHDX type and parse header information."""
        info = {
            'is_vhd': False,
            'format': None,
            'version': None,
            'disk_type': None,
            'virtual_size': 0,
            'is_dynamic': False
        }
        
        try:
            with open(self.image_path, 'rb') as f:
                # Check for VHDX first (header at beginning)
                header = f.read(8)
                if header == self.VHDX_COOKIE:
                    info['is_vhd'] = True
                    info['format'] = 'VHDX'
                    
                    # Parse VHDX header
                    f.seek(0)
                    header_data = f.read(64 * 1024)  # First 64KB
                    
                    # VHDX header fields (little endian)
                    info['version'] = struct.unpack('<I', header_data[76:80])[0]
                    info['virtual_size'] = struct.unpack('<Q', header_data[80:88])[0]
                    info['is_dynamic'] = True  # VHDX is always dynamic
                    
                    return info
                
                # Check for VHD (footer at end)
                f.seek(-512, 2)
                footer = f.read(512)
                
                if footer[0:8] == self.VHD_COOKIE:
                    info['is_vhd'] = True
                    info['format'] = 'VHD'
                    
                    # Parse VHD footer (big endian)
                    info['version'] = struct.unpack('>I', footer[12:16])[0]
                    info['virtual_size'] = struct.unpack('>Q', footer[48:56])[0]
                    disk_type = struct.unpack('>I', footer[60:64])[0]
                    info['disk_type'] = disk_type
                    info['is_dynamic'] = (disk_type == 3)  # 3 = Dynamic
                    
                    return info
                
                # Check for VHD header at beginning (dynamic VHD)
                f.seek(0)
                header = f.read(1024)
                if header[0:8] == b'cxsparse':
                    info['is_vhd'] = True
                    info['format'] = 'VHD'
                    info['is_dynamic'] = True
                    return info
                    
        except Exception:
            pass
        
        return info
    
    def _open_with_libvhdi(self) -> bool:
        """Open dynamic VHD/VHDX using libvhdi-python."""
        try:
            import pyvhdi
            import os
            
            # Open the VHD/VHDX file with libvhdi (need absolute path)
            abs_path = os.path.abspath(self.image_path)
            self._vhdi_file = pyvhdi.file()
            self._vhdi_file.open(abs_path)
            
            # Create custom Img_Info wrapper
            self._img_info = VHDImgInfo(self._vhdi_file)
            self._use_libvhdi = True
            
            return True
            
        except ImportError:
            return False
        except Exception as e:
            print(f"libvhdi open error: {e}")
            return False
    
    def _open_with_pytsk3(self) -> bool:
        """Open VHD/VHDX using pytsk3's built-in support."""
        try:
            self._img_info = pytsk3.Img_Info(self.image_path)
            self._use_libvhdi = False
            return True
        except Exception as e:
            print(f"pytsk3 open error: {e}")
            return False
    
    def _detect_partitions(self) -> List[PartitionInfo]:
        """Detect partitions in the VHD/VHDX image."""
        partitions = []
        
        if not self._img_info:
            return partitions
        
        try:
            # Try to read MBR from offset 0
            mbr_data = self._img_info.read(0, 512)
            
            if len(mbr_data) >= 512 and mbr_data[510:512] == b'\x55\xaa':
                # MBR found, parse partition table
                for i in range(4):
                    offset = 446 + (i * 16)
                    entry = mbr_data[offset:offset+16]
                    
                    bootable = entry[0] == 0x80
                    partition_type = entry[4]
                    start_lba = int.from_bytes(entry[8:12], 'little')
                    num_sectors = int.from_bytes(entry[12:16], 'little')
                    
                    if partition_type != 0 and num_sectors > 0:
                        partition_offset = start_lba * 512
                        
                        # Try to identify filesystem type
                        fs_type = self._identify_filesystem(partition_offset)
                        
                        partition = PartitionInfo(
                            index=i + 1,
                            offset=partition_offset,
                            size=num_sectors * 512,
                            type=self._get_partition_type_name(partition_type),
                            filesystem=fs_type,
                            label=f"Partition {i + 1}"
                        )
                        partitions.append(partition)
            
            # If no partitions found, check if there's a filesystem at offset 0
            if not partitions:
                fs_type = self._identify_filesystem(0)
                if fs_type:
                    # Single partition (whole disk is one filesystem)
                    partition = PartitionInfo(
                        index=1,
                        offset=0,
                        size=self._img_info.get_size(),
                        type="Single Volume",
                        filesystem=fs_type,
                        label="Single Volume"
                    )
                    partitions.append(partition)
                    
        except Exception as e:
            print(f"Partition detection error: {e}")
        
        return partitions
    
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
        """Open the VHD/VHDX image."""
        try:
            # Detect VHD/VHDX type
            self._vhd_info = self._detect_vhd_type()
            
            if not self._vhd_info['is_vhd']:
                raise IOError("File is not a valid VHD/VHDX image")
            
            # Choose opening method based on VHD type
            if self._vhd_info.get('is_dynamic'):
                # Dynamic VHD/VHDX - try libvhdi first
                if not self._open_with_libvhdi():
                    # Fallback to pytsk3
                    if not self._open_with_pytsk3():
                        raise IOError("Failed to open dynamic VHD/VHDX image")
            else:
                # Fixed VHD - use pytsk3
                if not self._open_with_pytsk3():
                    raise IOError("Failed to open VHD/VHDX image")
            
            # Detect partitions
            self._partitions = self._detect_partitions()
            
            # Try to open first partition's filesystem
            if self._partitions:
                self._open_filesystem(self._partitions[0].offset)
            else:
                # Try offset 0 as fallback
                self._open_filesystem(0)
                
        except Exception as e:
            raise IOError(f"Failed to open VHD/VHDX image: {e}")
    
    def close(self) -> None:
        """Close the VHD/VHDX image."""
        # Call base handler close to clear caches
        super().close()
        
        self._fs_info = None
        
        if self._vhdi_file:
            try:
                self._vhdi_file.close()
            except:
                pass
            self._vhdi_file = None
        
        self._img_info = None
        self._partitions = []
        self._current_partition_offset = 0
        self._use_libvhdi = False
    
    def read(self, offset: int, size: int) -> bytes:
        """Read data from the VHD/VHDX image."""
        if not self._img_info:
            raise IOError("VHD/VHDX image not opened")
        
        return self._img_info.read(offset, size)
    
    def get_size(self) -> int:
        """Get the total size of the VHD/VHDX image."""
        if not self._img_info:
            raise IOError("VHD/VHDX image not opened")
        
        return self._img_info.get_size()
    
    def get_info(self) -> ImageInfo:
        """Get information about the VHD/VHDX image."""
        size = self.get_size()
        
        metadata = {
            'libvhdi_used': self._use_libvhdi
        }
        if self._vhd_info:
            metadata['format'] = self._vhd_info.get('format')
            metadata['version'] = self._vhd_info.get('version')
            metadata['virtual_size'] = self._vhd_info.get('virtual_size')
            metadata['is_dynamic'] = self._vhd_info.get('is_dynamic')
            if self._vhd_info.get('disk_type'):
                metadata['disk_type'] = self._vhd_info.get('disk_type')
        
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
        """List files in a directory (with caching support from base handler)."""
        # Use base handler's caching implementation
        cache_key = f"{partition_offset}:{path}"
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]
        
        files = []
        
        if not self._fs_info:
            return files
        
        # If partition_offset is specified and different from current, switch
        if partition_offset != self._current_partition_offset:
            if not self._open_filesystem(partition_offset):
                return files
        
        try:
            dir_obj = self._fs_info.open_dir(path)
            
            for entry in dir_obj:
                name = entry.info.name.name.decode('utf-8', errors='ignore')
                
                if name in ['.', '..']:
                    continue
                
                is_dir = False
                size = 0
                inode = None
                
                if entry.info.meta:
                    is_dir = entry.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR
                    size = entry.info.meta.size
                    inode = entry.info.meta.addr
                
                file_info = FileInfo(
                    name=name,
                    path=f"{path}/{name}" if path != "/" else f"/{name}",
                    size=size,
                    is_directory=is_dir,
                    is_deleted=False,
                    created=None,
                    modified=None,
                    accessed=None,
                    inode=inode
                )
                files.append(file_info)
                
        except Exception:
            pass
        
        # Cache the result
        self._file_cache[cache_key] = files
        return files
    
    def get_file_metadata(self, partition_offset: int, file_path: str) -> Optional[FileInfo]:
        """Get metadata for a specific file (with caching support from base handler)."""
        # Use base handler's caching implementation
        cache_key = f"{partition_offset}:{file_path}"
        if cache_key in self._metadata_cache:
            return self._metadata_cache[cache_key]
        
        if not self._fs_info:
            return None
        
        # If partition_offset is specified and different from current, switch
        if partition_offset != self._current_partition_offset:
            if not self._open_filesystem(partition_offset):
                return None
        
        try:
            file_obj = self._fs_info.open(file_path)
            
            if not file_obj.info.meta:
                return None
            
            is_dir = file_obj.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR
            
            result = FileInfo(
                name=file_path.split('/')[-1],
                path=file_path,
                size=file_obj.info.meta.size,
                is_directory=is_dir,
                is_deleted=False,
                created=None,
                modified=None,
                accessed=None,
                inode=file_obj.info.meta.addr
            )
            
            # Cache the result
            self._metadata_cache[cache_key] = result
            return result
            
        except Exception:
            return None
    
    def read_file(self, partition_offset: int, file_path: str) -> Optional[bytes]:
        """Read content of a specific file."""
        if not self._fs_info:
            return None
        
        # If partition_offset is specified and different from current, switch
        if partition_offset != self._current_partition_offset:
            if not self._open_filesystem(partition_offset):
                return None
        
        try:
            file_obj = self._fs_info.open(file_path)
            
            if file_obj.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                return None
            
            size = file_obj.info.meta.size
            content = file_obj.read_random(0, size)
            
            return content
            
        except Exception:
            return None
    
    def get_image_handle(self):
        """Get pytsk3 image handle for filesystem operations."""
        return self._img_info
