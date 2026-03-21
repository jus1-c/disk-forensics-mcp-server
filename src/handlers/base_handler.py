"""Base handler for all image formats with pytsk3 support."""

import os
import pytsk3
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Iterator
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PartitionInfo:
    """Information about a partition."""
    offset: int
    size: int
    type: str
    label: Optional[str] = None
    filesystem: Optional[str] = None
    index: int = 0


@dataclass
class FileInfo:
    """Information about a file."""
    name: str
    path: str
    size: int
    is_directory: bool
    is_deleted: bool = False
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    accessed: Optional[datetime] = None
    inode: Optional[int] = None


@dataclass
class ImageInfo:
    """Information about a disk image."""
    format: str
    size: int
    sectors: int
    sector_size: int
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = None


class ImageHandle(pytsk3.Img_Info):
    """Wrapper for image handle that works with pytsk3."""
    
    def __init__(self, handler):
        self._handler = handler
        self._size = handler.get_size()
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_RAW)
    
    def get_size(self):
        return self._size
    
    def read(self, offset, size):
        return self._handler.read(offset, size)
    
    def close(self):
        pass


class BaseImageHandler(ABC):
    """Abstract base class for all image handlers with pytsk3 integration."""

    MAX_CACHE_SIZE = 500000  # Increased: Maximum entries per cache (was 10000)
    CACHE_EVICTION_BATCH = 5000  # Increased: Number of entries to remove when limit reached (was 100)

    def __init__(self, image_path: str):
        self.image_path = image_path
        self._size: Optional[int] = None
        self._image_handle: Optional[ImageHandle] = None
        self._filesystems: Dict[int, pytsk3.FS_Info] = {}
        # Cache for file listings and metadata
        self._file_cache: Dict[str, List[FileInfo]] = {}
        self._metadata_cache: Dict[str, FileInfo] = {}
        # Cache statistics
        self._cache_hits = 0
        self._cache_misses = 0
        # Track access order for LRU eviction
        self._file_cache_access: Dict[str, datetime] = {}
        self._metadata_cache_access: Dict[str, datetime] = {}

    @property
    @abstractmethod
    def format_name(self) -> str:
        """Return the format name (e.g., 'RAW', 'E01', 'VMDK')."""
        pass

    @abstractmethod
    def open(self) -> None:
        """Open the image file(s)."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the image file(s)."""
        # Clear caches
        self._file_cache.clear()
        self._metadata_cache.clear()

    @abstractmethod
    def read(self, offset: int, size: int) -> bytes:
        """Read data from the image at the specified offset."""
        pass

    @abstractmethod
    def get_size(self) -> int:
        """Get the total size of the image in bytes."""
        pass

    @abstractmethod
    def get_info(self) -> ImageInfo:
        """Get information about the image."""
        pass

    def get_image_handle(self) -> ImageHandle:
        """Get pytsk3-compatible image handle."""
        if self._image_handle is None:
            self._image_handle = ImageHandle(self)
        return self._image_handle

    def get_filesystem(self, partition_offset: int) -> Optional[pytsk3.FS_Info]:
        """Get filesystem info for a partition."""
        if partition_offset not in self._filesystems:
            try:
                img_handle = self.get_image_handle()
                fs = pytsk3.FS_Info(img_handle, offset=partition_offset)
                self._filesystems[partition_offset] = fs
            except Exception:
                return None
        return self._filesystems.get(partition_offset)

    def _add_to_file_cache(self, cache_key: str, files: List[FileInfo]) -> None:
        """Add to file cache with LRU eviction."""
        # Check if we need to evict
        if len(self._file_cache) >= self.MAX_CACHE_SIZE:
            # Remove oldest entries
            sorted_keys = sorted(
                self._file_cache_access.keys(),
                key=lambda k: self._file_cache_access[k]
            )
            for key in sorted_keys[:self.CACHE_EVICTION_BATCH]:
                del self._file_cache[key]
                del self._file_cache_access[key]
        
        # Add to cache
        self._file_cache[cache_key] = files
        self._file_cache_access[cache_key] = datetime.now()

    def _add_to_metadata_cache(self, cache_key: str, file_info: FileInfo) -> None:
        """Add to metadata cache with LRU eviction."""
        # Check if we need to evict
        if len(self._metadata_cache) >= self.MAX_CACHE_SIZE:
            # Remove oldest entries
            sorted_keys = sorted(
                self._metadata_cache_access.keys(),
                key=lambda k: self._metadata_cache_access[k]
            )
            for key in sorted_keys[:self.CACHE_EVICTION_BATCH]:
                del self._metadata_cache[key]
                del self._metadata_cache_access[key]
        
        # Add to cache
        self._metadata_cache[cache_key] = file_info
        self._metadata_cache_access[cache_key] = datetime.now()

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0
        return {
            "file_cache_entries": len(self._file_cache),
            "metadata_cache_entries": len(self._metadata_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": f"{hit_rate:.2%}",
            "max_cache_size": self.MAX_CACHE_SIZE,
        }

    def list_files(self, partition_offset: int, path: str = "/") -> List[FileInfo]:
        """List files in a directory using pytsk3 (with caching)."""
        cache_key = f"{partition_offset}:{path}"
        
        # Check cache first
        if cache_key in self._file_cache:
            self._cache_hits += 1
            self._file_cache_access[cache_key] = datetime.now()  # Update access time
            return self._file_cache[cache_key]
        
        self._cache_misses += 1
        
        fs = self.get_filesystem(partition_offset)
        if not fs:
            return []
        
        files = []
        try:
            # Open directory
            dir_obj = fs.open_dir(path=path)
            
            for entry in dir_obj:
                name = entry.info.name.name.decode('utf-8', errors='replace')
                
                # Skip . and ..
                if name in ['.', '..']:
                    continue
                
                # Skip entries with no metadata
                if entry.info.meta is None:
                    continue
                
                # Get file info
                file_path = os.path.join(path, name).replace('\\', '/')
                is_dir = entry.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR
                
                # Get timestamps
                meta = entry.info.meta
                created = None
                modified = None
                accessed = None
                
                if meta:
                    if hasattr(meta, 'crtime') and meta.crtime:
                        created = datetime.fromtimestamp(meta.crtime)
                    if hasattr(meta, 'mtime') and meta.mtime:
                        modified = datetime.fromtimestamp(meta.mtime)
                    if hasattr(meta, 'atime') and meta.atime:
                        accessed = datetime.fromtimestamp(meta.atime)
                
                size = meta.size if meta else 0
                inode = meta.addr if meta else None
                
                files.append(FileInfo(
                    name=name,
                    path=file_path,
                    size=size,
                    is_directory=is_dir,
                    is_deleted=False,  # TODO: Detect deleted files
                    created=created,
                    modified=modified,
                    accessed=accessed,
                    inode=inode
                ))
            
            # pytsk3.Directory doesn't have close() method
            # dir_obj.close()
            
        except Exception as e:
            print(f"Error listing files: {e}")
        
        # Cache the result
        self._add_to_file_cache(cache_key, files)
        return files

    def get_file_metadata(self, partition_offset: int, file_path: str) -> Optional[FileInfo]:
        """Get metadata for a specific file using pytsk3 (with caching)."""
        cache_key = f"{partition_offset}:{file_path}"
        
        # Check cache first
        if cache_key in self._metadata_cache:
            self._cache_hits += 1
            self._metadata_cache_access[cache_key] = datetime.now()  # Update access time
            return self._metadata_cache[cache_key]
        
        self._cache_misses += 1
        
        fs = self.get_filesystem(partition_offset)
        if not fs:
            return None
        
        try:
            # Open file
            file_obj = fs.open(file_path)
            meta = file_obj.info.meta
            
            if not meta:
                return None
            
            name = os.path.basename(file_path)
            is_dir = meta.type == pytsk3.TSK_FS_META_TYPE_DIR
            
            # Get timestamps
            created = None
            modified = None
            accessed = None
            
            if hasattr(meta, 'crtime') and meta.crtime:
                created = datetime.fromtimestamp(meta.crtime)
            if hasattr(meta, 'mtime') and meta.mtime:
                modified = datetime.fromtimestamp(meta.mtime)
            if hasattr(meta, 'atime') and meta.atime:
                accessed = datetime.fromtimestamp(meta.atime)
            
            result = FileInfo(
                name=name,
                path=file_path,
                size=meta.size,
                is_directory=is_dir,
                is_deleted=False,
                created=created,
                modified=modified,
                accessed=accessed,
                inode=meta.addr
            )

            # pytsk3.File doesn't have close() method
            # file_obj.close()
            
            # Cache the result
            self._add_to_metadata_cache(cache_key, result)
            return result
            
        except Exception as e:
            print(f"Error getting file metadata: {e}")
            return None

    def read_file(self, partition_offset: int, file_path: str) -> Optional[bytes]:
        """Read content of a specific file using pytsk3."""
        fs = self.get_filesystem(partition_offset)
        if not fs:
            return None
        
        try:
            # Open file
            file_obj = fs.open(file_path)
            meta = file_obj.info.meta
            
            if not meta or meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                return None
            
            # Read file content
            size = meta.size
            content = b''
            offset = 0
            
            while offset < size:
                to_read = min(1024 * 1024, size - offset)  # 1MB chunks
                data = file_obj.read_random(offset, to_read)
                if not data:
                    break
                content += data
                offset += len(data)
            
            # pytsk3.File doesn't have close() method
            # file_obj.close()
            return content

        except Exception as e:
            print(f"Error reading file: {e}")
            return None

    def get_partitions(self) -> List[PartitionInfo]:
        """Detect partitions in the image. Override in subclass for better detection."""
        partitions = []
        
        try:
            # Try to read MBR from offset 0
            mbr_data = self.read(0, 512)
            
            if len(mbr_data) >= 512 and mbr_data[510:512] == b'\x55\xaa':
                # MBR found, parse partition table
                for i in range(4):
                    offset = 446 + (i * 16)
                    entry = mbr_data[offset:offset+16]
                    
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
                        size=self.get_size(),
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
            data = self.read(offset, 512)
            
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

    def get_directory_tree(self, partition_offset: int, path: str = "/") -> Dict[str, List[str]]:
        """Get directory tree structure."""
        tree = {}
        
        def traverse(current_path):
            files = self.list_files(partition_offset, current_path)
            tree[current_path] = [f.name for f in files]
            
            for f in files:
                if f.is_directory:
                    subdir = os.path.join(current_path, f.name).replace('\\', '/')
                    traverse(subdir)
        
        traverse(path)
        return tree

    def search_by_extension(self, partition_offset: int, extension: str, path: str = "/") -> List[FileInfo]:
        """Search files by extension."""
        results = []
        ext_lower = extension.lower()
        
        def search_in_dir(current_path):
            files = self.list_files(partition_offset, current_path)
            
            for f in files:
                if f.name.lower().endswith(ext_lower):
                    results.append(f)
                
                if f.is_directory:
                    subdir = os.path.join(current_path, f.name).replace('\\', '/')
                    search_in_dir(subdir)
        
        search_in_dir(path)
        return results

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
