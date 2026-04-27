"""AD1 (AccessData Format) handler with full tool integration.

AD1 is a logical image format used by AccessData FTK Imager.
This handler supports all MCP tools for browsing and extracting files.

Reference: Based on pyad1 from https://github.com/pcbje/pyad1
"""

import os
import struct
import threading
import zlib
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Iterator
from .base_handler import BaseImageHandler, ImageInfo, FileInfo, PartitionInfo
from datetime import datetime


AD1_INDEX_CACHE_VERSION = 1
AD1_INDEX_CACHE_MAX_IMAGES = 2


@dataclass
class AD1Index:
    """Process-local parsed AD1 index."""

    version: int
    zlib_chunk_size: int
    image_header_length: int
    image_header_length_2: int
    logical_image_path: bytes
    items: Dict[str, Dict[str, Any]]
    children_by_parent: Dict[str, List[Dict[str, Any]]]
    file_count: int
    folder_count: int


_ad1_index_cache: OrderedDict[tuple[str, int, int, int], AD1Index] = OrderedDict()
_ad1_index_cache_lock = threading.Lock()
_ad1_index_cache_hits = 0
_ad1_index_cache_misses = 0


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
        self._children_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        self._version = 0
        self._zlib_chunk_size = 65536
        self._image_header_length = 0
        self._image_header_length_2 = 0
        self._logical_image_path = b""
        self._file_count = 0
        self._folder_count = 0
        self._index_cache_key: Optional[tuple[str, int, int, int]] = None
        self._index_cache_hit = False
        
    @property
    def format_name(self) -> str:
        return self._format_name
    
    def open(self) -> None:
        """Open and parse the AD1 file."""
        try:
            self._file_handle = open(self.image_path, 'rb')
            self._index_cache_key = self._get_index_cache_key()

            cached_index = self._get_cached_index(self._index_cache_key)
            if cached_index is not None:
                self._load_index(cached_index)
                self._index_cache_hit = True
                return

            self._index_cache_hit = False
            self._items = {}
            self._children_by_parent = {}
            self._parse_ad1()
            self._store_cached_index(self._index_cache_key, self._build_index())
        except Exception as e:
            raise IOError(f"Failed to open AD1 image: {e}")

    def _get_index_cache_key(self) -> tuple[str, int, int, int]:
        """Build a cache key that invalidates when the AD1 file changes."""
        image_path = os.path.abspath(self.image_path)
        stat_result = os.stat(image_path)
        return (
            image_path,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            AD1_INDEX_CACHE_VERSION,
        )

    @classmethod
    def _get_cached_index(cls, cache_key: tuple[str, int, int, int]) -> Optional[AD1Index]:
        """Return a process-local cached AD1 index if present."""
        global _ad1_index_cache_hits, _ad1_index_cache_misses

        with _ad1_index_cache_lock:
            index = _ad1_index_cache.get(cache_key)
            if index is None:
                _ad1_index_cache_misses += 1
                return None

            _ad1_index_cache_hits += 1
            _ad1_index_cache.move_to_end(cache_key)
            return index

    @classmethod
    def _store_cached_index(cls, cache_key: tuple[str, int, int, int], index: AD1Index) -> None:
        """Store a parsed AD1 index in process memory."""
        with _ad1_index_cache_lock:
            _ad1_index_cache[cache_key] = index
            _ad1_index_cache.move_to_end(cache_key)
            while len(_ad1_index_cache) > AD1_INDEX_CACHE_MAX_IMAGES:
                _ad1_index_cache.popitem(last=False)

    @classmethod
    def clear_index_cache(cls) -> None:
        """Clear all process-local AD1 indexes."""
        global _ad1_index_cache_hits, _ad1_index_cache_misses

        with _ad1_index_cache_lock:
            _ad1_index_cache.clear()
            _ad1_index_cache_hits = 0
            _ad1_index_cache_misses = 0

    @classmethod
    def get_index_cache_stats(cls) -> Dict[str, Any]:
        """Return process-local AD1 index cache stats."""
        with _ad1_index_cache_lock:
            total_items = sum(len(index.items) for index in _ad1_index_cache.values())
            return {
                "entries": len(_ad1_index_cache),
                "max_entries": AD1_INDEX_CACHE_MAX_IMAGES,
                "hits": _ad1_index_cache_hits,
                "misses": _ad1_index_cache_misses,
                "total_items": total_items,
            }

    def _build_index(self) -> AD1Index:
        """Build a cacheable index from the parsed handler state."""
        self._file_count = sum(1 for item in self._items.values() if item['type'] == 0)
        self._folder_count = sum(1 for item in self._items.values() if item['type'] == 5)
        return AD1Index(
            version=self._version,
            zlib_chunk_size=self._zlib_chunk_size,
            image_header_length=self._image_header_length,
            image_header_length_2=self._image_header_length_2,
            logical_image_path=self._logical_image_path,
            items=self._items,
            children_by_parent=self._children_by_parent,
            file_count=self._file_count,
            folder_count=self._folder_count,
        )

    def _load_index(self, index: AD1Index) -> None:
        """Attach a cached AD1 index to this handler."""
        self._version = index.version
        self._zlib_chunk_size = index.zlib_chunk_size
        self._image_header_length = index.image_header_length
        self._image_header_length_2 = index.image_header_length_2
        self._logical_image_path = index.logical_image_path
        self._items = index.items
        self._children_by_parent = index.children_by_parent
        self._file_count = index.file_count
        self._folder_count = index.folder_count
    
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
        # Use deque as FIFO queue for breadth-first traversal.
        stack = deque([(start_offset, "")])
        processed_offsets = set()  # Track processed offsets to avoid loops

        while stack:
            offset, expected_parent = stack.popleft()
            
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
                self._children_by_parent.setdefault(item['parent'], []).append(item)
                
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
        
        # Store content location for lazy loading. The chunk table is read only
        # when file content is actually requested; browsing/extract planning does
        # not need it.
        content_info = None
        if decompressed_size > 0:
            content_info = {
                'decompressed_size': decompressed_size,
                'start_of_data': start_of_data + self.MARGIN if start_of_data > 0 else 0,
                'chunk_count': None,
                'chunk_arr': None,
            }

        metadata_offset = next_block + self.MARGIN if next_block > 0 else 0

        return {
            'type': item_type,  # 0=file, 5=folder
            'path': full_path,
            'parent': parent_path,
            'name': filename,
            'next_group': next_group,
            'next_in_group': next_in_group,
            'content_info': content_info,
            'metadata': {},
            'metadata_offset': metadata_offset,
            'metadata_loaded': False,
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

        content = bytearray()
        for chunk in self._iter_content_chunks(content_info):
            content.extend(chunk)
        return bytes(content)

    def _load_content_chunk_table(self, content_info: Dict[str, Any]) -> tuple[int, tuple[int, ...]]:
        """Load and cache AD1 content chunk table for a file."""
        chunk_count = content_info.get('chunk_count')
        chunk_arr = content_info.get('chunk_arr')
        if chunk_count is not None and chunk_arr is not None:
            return chunk_count, chunk_arr

        original_pos = self._file_handle.tell()
        try:
            self._file_handle.seek(content_info['start_of_data'])
            chunk_count_data = self._file_handle.read(8)
            if len(chunk_count_data) < 8:
                return 0, ()

            chunk_count = struct.unpack('<q', chunk_count_data)[0] + 1
            chunk_arr_data = self._file_handle.read(8 * chunk_count)
            if len(chunk_arr_data) < 8 * chunk_count:
                return 0, ()

            chunk_arr = struct.unpack(f'<{chunk_count}q', chunk_arr_data)
            content_info['chunk_count'] = chunk_count
            content_info['chunk_arr'] = chunk_arr
            return chunk_count, chunk_arr
        except Exception:
            return 0, ()
        finally:
            self._file_handle.seek(original_pos)

    def _iter_content_chunks(
        self,
        content_info: Dict[str, Any],
        offset: int = 0,
        size: Optional[int] = None,
    ) -> Iterator[bytes]:
        """Yield decompressed AD1 content without buffering the full file."""
        if not content_info:
            return

        chunk_count, chunk_arr = self._load_content_chunk_table(content_info)
        if chunk_count <= 1 or not chunk_arr:
            return

        table_size = 8 + (8 * chunk_count)
        compressed_offset = content_info['start_of_data'] + table_size
        skip_remaining = max(offset, 0)
        emit_remaining = size
        original_pos = self._file_handle.tell()

        try:
            for index in range(1, len(chunk_arr)):
                compressed_size = chunk_arr[index] - chunk_arr[index - 1]
                if compressed_size <= 0:
                    continue

                self._file_handle.seek(compressed_offset)
                compressed = self._file_handle.read(compressed_size)
                compressed_offset += compressed_size
                if not compressed:
                    break

                try:
                    decompressed = zlib.decompress(compressed)
                except zlib.error:
                    continue

                if skip_remaining >= len(decompressed):
                    skip_remaining -= len(decompressed)
                    continue

                if skip_remaining:
                    decompressed = decompressed[skip_remaining:]
                    skip_remaining = 0

                if emit_remaining is not None:
                    if emit_remaining <= 0:
                        break
                    decompressed = decompressed[:emit_remaining]
                    emit_remaining -= len(decompressed)

                if decompressed:
                    yield decompressed

                if emit_remaining == 0:
                    break
        finally:
            self._file_handle.seek(original_pos)
    
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
        file_count = self._file_count
        folder_count = self._folder_count
        
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

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get handler and process-local AD1 index cache statistics."""
        stats = super().get_cache_stats()
        stats.update({
            "ad1_index_cache_hit": self._index_cache_hit,
            "ad1_items": len(self._items),
            "ad1_file_count": self._file_count,
            "ad1_folder_count": self._folder_count,
            "ad1_index_cache": self.get_index_cache_stats(),
        })
        return stats

    def get_partitions(self) -> List[PartitionInfo]:
        """Return the logical AD1 container as a single pseudo-partition."""
        if self._partitions_cache is None:
            self._partitions_cache = [
                PartitionInfo(
                    index=1,
                    offset=0,
                    size=self.get_size(),
                    type="Logical Image",
                    filesystem="AD1",
                    label="AD1 Logical Image",
                )
            ]
        return self._partitions_cache
    
    def list_files(self, partition_offset: int = 0, path: str = "/") -> List[FileInfo]:
        """List files in a directory (with caching).
        
        Note: partition_offset is ignored for AD1 (logical image).
        """
        cache_key = f"{partition_offset}:{path}"
        if cache_key in self._file_cache:
            self._cache_hits += 1
            self._file_cache.move_to_end(cache_key)
            return self._file_cache[cache_key]
        self._cache_misses += 1

        # Normalize path
        if path == "/":
            search_path = ""
        else:
            search_path = path.lstrip("/")

        files = [
            self._item_to_fileinfo(item)
            for item in self._children_by_parent.get(search_path, [])
        ]
        self._add_to_file_cache(cache_key, files)
        return files

    def list_files_for_extraction(self, partition_offset: int = 0, path: str = "/") -> List[FileInfo]:
        """List directory entries without loading timestamps or extra metadata."""
        if path == "/":
            search_path = ""
        else:
            search_path = path.lstrip("/")

        return [
            self._item_to_fileinfo_fast(item)
            for item in self._children_by_parent.get(search_path, [])
        ]
    
    def _item_to_fileinfo(self, item: Dict[str, Any]) -> FileInfo:
        """Convert AD1 item to FileInfo."""
        # Parse timestamps from metadata
        created = None
        modified = None
        accessed = None
        
        metadata = self._get_item_metadata(item)
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

    def _item_to_fileinfo_fast(self, item: Dict[str, Any]) -> FileInfo:
        """Convert AD1 item to FileInfo without parsing optional metadata."""
        size = 0
        if item.get('content_info'):
            size = item['content_info']['decompressed_size']

        return FileInfo(
            name=item['name'],
            path=item['path'],
            size=size,
            is_directory=(item['type'] == 5),
            is_deleted=False,
            inode=None,
        )

    def _get_item_metadata(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Load AD1 metadata for an item only when it is needed."""
        if not item.get('metadata_loaded'):
            item['metadata'] = self._parse_metadata(item.get('metadata_offset', 0))
            item['metadata_loaded'] = True
        return item.get('metadata', {})
    
    def get_file_metadata(self, partition_offset: int, file_path: str) -> Optional[FileInfo]:
        """Get metadata for a specific file (with caching)."""
        cache_key = f"{partition_offset}:{file_path}"
        if cache_key in self._metadata_cache:
            self._cache_hits += 1
            self._metadata_cache.move_to_end(cache_key)
            return self._metadata_cache[cache_key]
        self._cache_misses += 1
        
        # Normalize path
        normalized_path = file_path.lstrip("/")
        
        if normalized_path in self._items:
            result = self._item_to_fileinfo(self._items[normalized_path])
            # Cache the result
            self._add_to_metadata_cache(cache_key, result)
            return result

        return None

    def read_file(
        self,
        partition_offset: int,
        file_path: str,
        offset: int = 0,
        max_size: Optional[int] = None,
        chunk_size: int = BaseImageHandler.DEFAULT_READ_CHUNK_SIZE,
    ) -> Optional[bytes]:
        """Read content of a specific file."""
        # Normalize path
        normalized_path = file_path.lstrip("/")

        if normalized_path not in self._items:
            return None

        item = self._items[normalized_path]

        # Check if it's a directory
        if item['type'] == 5:
            return None

        read_offset = max(offset, 0)

        content_info = item.get('content_info')
        if not content_info:
            return b''

        read_size = max_size

        # Return cached content or load lazily
        if item.get('content') is not None:
            content = item['content']
            end = len(content) if read_size is None else min(
                len(content), read_offset + read_size
            )
            return content[read_offset:end]

        content = bytearray()
        for chunk in self._iter_content_chunks(content_info, offset=read_offset, size=read_size):
            content.extend(chunk)

        result = bytes(content)
        if read_offset == 0 and read_size is None and len(result) <= 16 * 1024 * 1024:
            item['content'] = result
        return result

    def iter_file_chunks(
        self,
        partition_offset: int,
        file_path: str,
        offset: int = 0,
        size: Optional[int] = None,
        chunk_size: int = BaseImageHandler.DEFAULT_READ_CHUNK_SIZE,
    ) -> Iterator[bytes]:
        """Yield AD1 file content chunks."""
        # Normalize path
        normalized_path = file_path.lstrip("/")

        if normalized_path not in self._items:
            return

        item = self._items[normalized_path]
        if item['type'] == 5:
            return

        if item.get('content') is not None:
            content = item['content']
            read_offset = max(offset, 0)
            end = len(content) if size is None else min(len(content), read_offset + size)
            current = read_offset
            while current < end:
                chunk = content[current:current + chunk_size]
                if not chunk:
                    break
                yield chunk
                current += len(chunk)
            return

        content_info = item.get('content_info')
        if not content_info:
            return

        for chunk in self._iter_content_chunks(content_info, offset=offset, size=size):
            yield chunk
    
    def get_image_handle(self):
        """Get image handle - not applicable for AD1."""
        raise NotImplementedError("AD1 does not support pytsk3 image handle")
