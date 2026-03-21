"""AD1 (AccessData Format) handler with full tool integration.

AD1 is a logical image format used by AccessData FTK Imager.
This handler supports all MCP tools for browsing and extracting files.

Reference: Based on pyad1 from https://github.com/pcbje/pyad1
"""

import os
import struct
import zlib
from typing import Optional, List, Dict, Any
from .base_handler import BaseImageHandler, ImageInfo, FileInfo
from datetime import datetime


class AD1Handler(BaseImageHandler):
    """Handler for AD1 (AccessData Format) logical images.
    
    AD1 is a logical image format that contains selected files/folders
    rather than a full disk image. It uses zlib compression and has
    its own tree structure with metadata.
    """
    
    # AD1 constants
    MARGIN = 512
    SEGMENT_SIGNATURE = b"ADSEGMENTEDFILE"
    LOGICAL_IMAGE_SIGNATURE = b"ADLOGICALIMAGE"
    
    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._format_name = "AD1"
        self._file_handle: Optional[object] = None
        self._items: Dict[str, Dict[str, Any]] = {}
        self._version = 0
        self._zlib_chunk_size = 65536
        self._image_header_length = 0
        self._image_header_length_2 = 0
        self._logical_image_path = b""
        
    @property
    def format_name(self) -> str:
        return self._format_name
    
    def open(self) -> None:
        """Open and parse the AD1 file."""
        try:
            self._file_handle = open(self.image_path, 'rb')
            self._parse_ad1()
        except Exception as e:
            raise IOError(f"Failed to open AD1 image: {e}")
    
    def _parse_ad1(self) -> None:
        """Parse AD1 file structure."""
        # Read segment header (512 bytes margin)
        self._file_handle.seek(0)
        margin_data = self._file_handle.read(self.MARGIN)
        
        # Check segment signature
        if not margin_data.startswith(self.SEGMENT_SIGNATURE):
            raise IOError("Invalid AD1 file: segment signature not found")
        
        # Read logical image header
        self._parse_logical_image_header()
        
        # Parse all items using tree traversal
        self._parse_items()
    
    def _parse_logical_image_header(self) -> None:
        """Parse logical image header (only in first segment)."""
        # Signature (16 bytes): "ADLOGICALIMAGE" + 2 bytes unknown
        sig_data = self._file_handle.read(16)
        if not sig_data.startswith(self.LOGICAL_IMAGE_SIGNATURE):
            raise IOError("Invalid AD1 file: logical image signature not found")
        
        # Version (4 bytes) = 3 or 4
        self._version = struct.unpack('<I', self._file_handle.read(4))[0]
        if self._version not in [3, 4]:
            raise IOError(f"Unsupported AD1 version: {self._version}")
        
        # Unknown (4 bytes)
        self._file_handle.read(4)
        
        # zlib chunk size (4 bytes) = 65536
        self._zlib_chunk_size = struct.unpack("<I", self._file_handle.read(4))[0]
        
        # Image header length (8 bytes)
        self._image_header_length = struct.unpack("<q", self._file_handle.read(8))[0]
        
        # Image header+info length (8 bytes)
        self._image_header_length_2 = struct.unpack("<q", self._file_handle.read(8))[0]
        
        # Logical image path length (4 bytes)
        path_length = struct.unpack('<I', self._file_handle.read(4))[0]
        
        # Version 4 only: Unknown (44 bytes)
        if self._version == 4:
            self._file_handle.read(44)
        
        # Logical image path
        self._logical_image_path = self._file_handle.read(path_length)
        
        # Seek to end of header if needed
        if self._logical_image_path != b'Custom Content Image([Multi])':
            current_pos = self._file_handle.tell()
            target_pos = self.MARGIN + self._image_header_length_2
            if current_pos < target_pos:
                self._file_handle.seek(target_pos)
    
    def _parse_items(self) -> None:
        """Parse all items in AD1 file using tree traversal.
        
        AD1 uses a tree structure with:
        - next_group: points to first child
        - next_in_group: points to next sibling
        """
        folder_cache: Dict[int, str] = {}
        
        # Start from current position after header
        start_offset = self._file_handle.tell()
        
        # Get file size for bounds checking
        self._file_handle.seek(0, 2)
        file_size = self._file_handle.tell()
        self._file_handle.seek(start_offset)
        
        # Use stack for tree traversal: (offset, expected_parent_path)
        # Use list as FIFO queue for breadth-first traversal
        stack = [(start_offset, "")]
        processed_offsets = set()  # Track processed offsets to avoid loops
        
        while stack:
            offset, expected_parent = stack.pop(0)  # FIFO for breadth-first order
            
            # Skip if already processed or out of bounds
            if offset in processed_offsets or offset >= file_size - 40:
                continue
            
            processed_offsets.add(offset)
            
            try:
                # Seek to item position
                self._file_handle.seek(offset)
                
                # Parse the item
                item = self._parse_item_at_offset(offset, folder_cache, expected_parent)
                if item is None:
                    continue
                
                # Store item
                path = item['path']
                self._items[path] = item
                
                # Add children (next_group) to stack - process after siblings
                next_group = item.get('next_group', 0)
                if next_group > 0:
                    child_offset = next_group + self.MARGIN
                    if child_offset < file_size and child_offset not in processed_offsets:
                        stack.append((child_offset, path))
                
                # Add sibling (next_in_group) to stack - process next
                next_in_group = item.get('next_in_group', 0)
                if next_in_group > 0:
                    sibling_offset = next_in_group + self.MARGIN
                    if sibling_offset < file_size and sibling_offset not in processed_offsets:
                        stack.append((sibling_offset, expected_parent))
                
            except Exception as e:
                # Skip problematic items
                continue
    
    def _parse_item_at_offset(self, offset: int, folder_cache: Dict[int, str], 
                              expected_parent: str) -> Optional[Dict[str, Any]]:
        """Parse a single item from AD1 at specific offset."""
        # Item header (40 bytes)
        header_data = self._file_handle.read(40)
        if len(header_data) < 40:
            return None
        
        next_group, next_in_group, next_block, start_of_data, decompressed_size = \
            struct.unpack('<5q', header_data)
        
        # Item type and filename length (8 bytes)
        item_type_data = self._file_handle.read(8)
        if len(item_type_data) < 8:
            return None
        
        item_type, filename_length = struct.unpack('<2I', item_type_data)
        
        # Sanity check
        if filename_length > 10000 or filename_length <= 0:
            return None
        
        # Filename
        filename_bytes = self._file_handle.read(filename_length)
        if len(filename_bytes) < filename_length:
            return None
        
        try:
            filename = filename_bytes.decode('utf-8')
        except UnicodeDecodeError:
            filename = filename_bytes.decode('latin-1', errors='ignore')
        
        # Group index (8 bytes)
        group_index_data = self._file_handle.read(8)
        if len(group_index_data) < 8:
            return None
        
        folder_index = struct.unpack('<q', group_index_data)[0]
        
        # Build path
        parent_path = folder_cache.get(folder_index + self.MARGIN, expected_parent)
        if parent_path:
            full_path = f"{parent_path}/{filename}"
        else:
            full_path = filename
        
        # Cache folder path with absolute offset
        if item_type == 5:  # Folder
            folder_cache[offset] = full_path
        
        # Store content info for lazy loading
        content_info = None
        if decompressed_size > 0:
            # Read chunk info
            chunk_count_data = self._file_handle.read(8)
            if len(chunk_count_data) == 8:
                chunk_count = struct.unpack('<q', chunk_count_data)[0] + 1
                chunk_arr_data = self._file_handle.read(8 * chunk_count)
                if len(chunk_arr_data) == 8 * chunk_count:
                    chunk_arr = struct.unpack(f'<{chunk_count}q', chunk_arr_data)
                    
                    # Skip compressed data
                    total_compressed = chunk_arr[-1] - chunk_arr[0] if len(chunk_arr) > 1 else 0
                    if total_compressed > 0:
                        self._file_handle.seek(total_compressed, 1)
                    
                    content_info = {
                        'decompressed_size': decompressed_size,
                        'start_of_data': start_of_data + self.MARGIN if start_of_data > 0 else 0,
                        'chunk_count': chunk_count,
                        'chunk_arr': chunk_arr
                    }
        
        # Read metadata
        metadata = self._parse_metadata(next_block + self.MARGIN if next_block > 0 else 0)
        
        return {
            'type': item_type,  # 0=file, 5=folder
            'path': full_path,
            'parent': parent_path,
            'name': filename,
            'next_group': next_group,
            'next_in_group': next_in_group,
            'content_info': content_info,
            'metadata': metadata,
            'content': None  # Lazy loaded
        }
    
    def _parse_metadata(self, meta_offset: int) -> Dict[str, Any]:
        """Parse metadata for an item."""
        metadata: Dict[str, Any] = {}
        
        if meta_offset <= self.MARGIN:
            return metadata
        
        original_pos = self._file_handle.tell()
        processed_offsets = set()  # Avoid infinite loops
        
        try:
            while meta_offset > self.MARGIN:
                if meta_offset in processed_offsets:
                    break
                processed_offsets.add(meta_offset)
                
                self._file_handle.seek(meta_offset)
                
                # Next metadata offset
                next_block_data = self._file_handle.read(8)
                if len(next_block_data) < 8:
                    break
                
                next_block = struct.unpack('<q', next_block_data)[0]
                if next_block == 0:
                    break
                
                # Category, key, value length
                meta_header = self._file_handle.read(12)
                if len(meta_header) < 12:
                    break
                
                category, key, value_length = struct.unpack('<3I', meta_header)
                
                # Value
                value = self._file_handle.read(value_length)
                
                # Store metadata
                if category not in metadata:
                    metadata[category] = {}
                metadata[category][key] = value
                
                meta_offset = next_block + self.MARGIN
        
        except Exception:
            pass
        finally:
            self._file_handle.seek(original_pos)
        
        return metadata
    
    def _read_content(self, content_info: Dict[str, Any]) -> bytes:
        """Read and decompress content."""
        if not content_info:
            return b''
        
        content = b''
        original_pos = self._file_handle.tell()
        
        try:
            self._file_handle.seek(content_info['start_of_data'])
            
            # Read chunk info
            chunk_count_data = self._file_handle.read(8)
            if len(chunk_count_data) < 8:
                return b''
            
            chunk_count = struct.unpack('<q', chunk_count_data)[0] + 1
            chunk_arr_data = self._file_handle.read(8 * chunk_count)
            if len(chunk_arr_data) < 8 * chunk_count:
                return b''
            
            chunk_arr = struct.unpack(f'<{chunk_count}q', chunk_arr_data)
            
            # Decompress each chunk
            for c in range(1, len(chunk_arr)):
                compressed_size = chunk_arr[c] - chunk_arr[c - 1]
                if compressed_size > 0:
                    compressed = self._file_handle.read(compressed_size)
                    if compressed:
                        try:
                            decompressed = zlib.decompress(compressed)
                            content += decompressed
                        except zlib.error:
                            # Skip corrupted chunks
                            pass
        
        except Exception:
            pass
        finally:
            self._file_handle.seek(original_pos)
        
        return content
    
    def close(self) -> None:
        """Close the AD1 file."""
        # Call base handler close to clear caches
        super().close()
        
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
    
    def read(self, offset: int, size: int) -> bytes:
        """Read raw data from AD1 (not typically used for logical images)."""
        if not self._file_handle:
            raise IOError("AD1 file not opened")
        
        self._file_handle.seek(offset)
        return self._file_handle.read(size)
    
    def get_size(self) -> int:
        """Get the total size of the AD1 file."""
        if not self._file_handle:
            raise IOError("AD1 file not opened")
        
        self._file_handle.seek(0, 2)
        return self._file_handle.tell()
    
    def get_info(self) -> ImageInfo:
        """Get information about the AD1 image."""
        file_count = sum(1 for item in self._items.values() if item['type'] == 0)
        folder_count = sum(1 for item in self._items.values() if item['type'] == 5)
        
        return ImageInfo(
            format=self._format_name,
            size=self.get_size(),
            sectors=0,  # Not applicable for logical images
            sector_size=0,
            checksum=None,
            metadata={
                "version": self._version,
                "item_count": len(self._items),
                "file_count": file_count,
                "folder_count": folder_count,
                "logical_image_path": self._logical_image_path.decode('utf-8', errors='ignore')
            }
        )
    
    def list_files(self, partition_offset: int = 0, path: str = "/") -> List[FileInfo]:
        """List files in a directory (with caching).
        
        Note: partition_offset is ignored for AD1 (logical image).
        """
        cache_key = f"{partition_offset}:{path}"
        if cache_key in self._file_cache:
            return self._file_cache[cache_key]
        
        files = []
        
        # Normalize path
        if path == "/":
            search_path = ""
        else:
            search_path = path.lstrip("/")
        
        for item_path, item in self._items.items():
            parent = item['parent']
            
            # Check if this item is in the requested directory
            if search_path == "":
                # Root level - items with no parent
                if parent == "":
                    files.append(self._item_to_fileinfo(item))
            else:
                # Subdirectory
                if parent == search_path:
                    files.append(self._item_to_fileinfo(item))
        
        # Cache the result
        self._file_cache[cache_key] = files
        return files
    
    def _item_to_fileinfo(self, item: Dict[str, Any]) -> FileInfo:
        """Convert AD1 item to FileInfo."""
        # Parse timestamps from metadata
        created = None
        modified = None
        accessed = None
        
        metadata = item.get('metadata', {})
        if 5 in metadata:  # Timestamps category
            ts_meta = metadata[5]
            # Try both integer and hex keys
            for key, var_name in [(7, 'accessed'), (8, 'modified'), (9, 'created')]:
                if key in ts_meta:
                    try:
                        ts_str = ts_meta[key].decode('utf-8')
                        # Parse timestamp with microseconds: 20260307T084127.455813
                        dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%S.%f")
                        if var_name == 'accessed':
                            accessed = dt
                        elif var_name == 'modified':
                            modified = dt
                        else:
                            created = dt
                    except:
                        # Try without microseconds
                        try:
                            ts_str = ts_meta[key].decode('utf-8')
                            dt = datetime.strptime(ts_str, "%Y%m%dT%H%M%S")
                            if var_name == 'accessed':
                                accessed = dt
                            elif var_name == 'modified':
                                modified = dt
                            else:
                                created = dt
                        except:
                            pass
        
        # Get size
        size = 0
        if item.get('content_info'):
            size = item['content_info']['decompressed_size']
        elif 3 in metadata:  # File size category
            size_meta = metadata[3]
            if 0x3 in size_meta:
                try:
                    size = int(size_meta[0x3].decode('utf-8'))
                except:
                    pass
        
        return FileInfo(
            name=item['name'],
            path=item['path'],
            size=size,
            is_directory=(item['type'] == 5),
            is_deleted=False,
            created=created,
            modified=modified,
            accessed=accessed,
            inode=None
        )
    
    def get_file_metadata(self, partition_offset: int, file_path: str) -> Optional[FileInfo]:
        """Get metadata for a specific file (with caching)."""
        cache_key = f"{partition_offset}:{file_path}"
        if cache_key in self._metadata_cache:
            return self._metadata_cache[cache_key]
        
        # Normalize path
        normalized_path = file_path.lstrip("/")
        
        if normalized_path in self._items:
            result = self._item_to_fileinfo(self._items[normalized_path])
            # Cache the result
            self._metadata_cache[cache_key] = result
            return result
        
        return None
    
    def read_file(self, partition_offset: int, file_path: str) -> Optional[bytes]:
        """Read content of a specific file."""
        # Normalize path
        normalized_path = file_path.lstrip("/")
        
        if normalized_path not in self._items:
            return None
        
        item = self._items[normalized_path]
        
        # Check if it's a directory
        if item['type'] == 5:
            return None
        
        # Return cached content or load lazily
        if item.get('content') is not None:
            return item['content']
        
        if item.get('content_info'):
            content = self._read_content(item['content_info'])
            item['content'] = content
            return content
        
        return b''
    
    def get_image_handle(self):
        """Get image handle - not applicable for AD1."""
        raise NotImplementedError("AD1 does not support pytsk3 image handle")
