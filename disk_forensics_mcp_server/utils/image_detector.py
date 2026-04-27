"""Image format detection utilities with global handler caching."""

import os
import re
import threading
from typing import Optional, Type, Dict, Any
from ..handlers.base_handler import BaseImageHandler
from ..handlers.raw_handler import RAWHandler
from ..handlers.e01_handler import E01Handler
from ..handlers.ad1_handler import AD1Handler
from ..handlers.vmdk_handler import VMDKHandler
from ..handlers.vhd_handler import VHDHandler


# Global registry - persistent across tool calls
_handler_cache: Dict[str, BaseImageHandler] = {}
_cache_lock = threading.Lock()


class ImageDetector:
    """Detect and instantiate appropriate image handlers with caching support."""

    # Registry of handlers
    HANDLERS: dict[str, Type[BaseImageHandler]] = {
        "raw": RAWHandler,
        "e01": E01Handler,
        "ad1": AD1Handler,
        "vmdk": VMDKHandler,
        "vhd": VHDHandler,
    }

    @classmethod
    def detect_format(cls, image_path: str) -> Optional[str]:
        """Detect the format of an image file.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Format name (lowercase) or None if unknown
        """
        if not os.path.exists(image_path):
            # Check if split image exists
            if not cls._check_split_exists(image_path):
                return None

        ext = os.path.splitext(image_path)[1].lower()
        basename = os.path.basename(image_path).lower()

        # Check by extension
        format_map = {
            ".raw": "raw",
            ".dd": "raw",
            ".img": "raw",
            ".bin": "raw",
            ".e01": "e01",
            ".e02": "e01",
            ".s01": "e01",
            ".vmdk": "vmdk",
            ".vhd": "vhd",
            ".vhdx": "vhd",
            ".ad1": "ad1",
            ".ad2": "ad1",
        }

        if ext in format_map:
            return format_map[ext]

        # Check for split patterns
        if cls._is_split_raw(image_path):
            return "raw"

        # Try to detect by content (for files without extension)
        if cls._is_raw_by_content(image_path):
            return "raw"

        return None

    @classmethod
    def _check_split_exists(cls, image_path: str) -> bool:
        """Check if any split segments exist."""
        base = os.path.splitext(image_path)[0]
        
        # Check numeric splits
        for i in range(1, 1000):
            if os.path.exists(f"{base}.{i:03d}"):
                return True
            if i > 1 and not os.path.exists(f"{base}.{i:03d}"):
                break
        
        # Check letter splits
        for i in range(26 * 26):
            first = chr(ord('a') + (i // 26))
            second = chr(ord('a') + (i % 26))
            if os.path.exists(f"{base}.{first}{second}"):
                return True
        
        return False

    @classmethod
    def _is_split_raw(cls, image_path: str) -> bool:
        """Check if this is a split RAW image."""
        # Check for numeric pattern (.001, .002, etc.)
        match = re.match(r'^(.*?)(\.\d{3})$', image_path)
        if match:
            # If file has .XXX pattern (001-999), it's a split segment
            # No need to check if other files exist - the extension itself indicates split format
            return True
        
        # Check for letter pattern (.aa, .ab, etc.)
        match = re.match(r'^(.*?)(\.[a-z]{2})$', image_path, re.IGNORECASE)
        if match:
            base = match.group(1)
            ext = match.group(2).lower()
            # Check if it's a valid letter split pattern (aa-zz)
            if len(ext) == 3 and ext[1:] >= 'aa' and ext[1:] <= 'zz':
                return True
        
        return False

    @classmethod
    def _is_raw_by_content(cls, image_path: str) -> bool:
        """Try to detect RAW format by content analysis."""
        try:
            # Check if it's a valid file and has reasonable size
            size = os.path.getsize(image_path)
            if size < 512:  # Too small to be a disk image
                return False
            
            # Check for common filesystem signatures at offset 0
            with open(image_path, 'rb') as f:
                header = f.read(512)
                if len(header) < 512:
                    return False
                
                # Check for boot sector signature
                if header[510:512] == b'\x55\xaa':
                    return True
                
                # Check for partition table
                if header[446:510] != b'\x00' * 64:
                    return True
                
                # Check for GPT signature
                if header[512:520] == b'EFI PART':
                    return True
                
                # Check for common filesystem signatures
                fs_signatures = [
                    (b'\xeb\x52\x90', 0),      # NTFS
                    (b'\xe9\xd0\x01', 0),      # FAT32
                    (b'\xeb\x3c\x90', 0),      # FAT12/16
                    (b'\x53\xef', 0x38),       # ext2/3/4
                    (b'\x19\x01', 0x438),      # HFS+
                ]
                
                for sig, offset in fs_signatures:
                    if len(header) >= offset + len(sig):
                        if header[offset:offset + len(sig)] == sig:
                            return True
            
        except (IOError, OSError):
            pass
        
        return False

    @classmethod
    def get_handler(cls, image_path: str) -> Optional[BaseImageHandler]:
        """Get the appropriate handler for an image file (non-cached).
        
        Use get_handler_cached() for caching support.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Instance of appropriate handler or None
        """
        image_path = os.path.abspath(image_path)
        format_name = cls.detect_format(image_path)
        
        if format_name and format_name in cls.HANDLERS:
            handler_class = cls.HANDLERS[format_name]
            return handler_class(image_path)
        
        return None

    @classmethod
    def get_handler_cached(cls, image_path: str) -> Optional[BaseImageHandler]:
        """Get handler from global cache or create new one.
        
        This method maintains a global cache of handlers that persists
        across tool calls, significantly improving performance for
        repeated operations on the same image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Instance of appropriate handler or None
        """
        global _handler_cache
        
        cache_key = os.path.abspath(image_path)

        with _cache_lock:
            if cache_key not in _handler_cache:
                handler = cls.get_handler(cache_key)
                if handler:
                    handler.open()
                    _handler_cache[cache_key] = handler
            return _handler_cache.get(cache_key)

    @classmethod
    def invalidate_handler(cls, image_path: str = None) -> None:
        """Close and remove handler(s) from cache.
        
        Args:
            image_path: Path to specific image, or None to clear all
        """
        global _handler_cache
        
        with _cache_lock:
            if image_path:
                cache_key = os.path.abspath(image_path)
                if cache_key in _handler_cache:
                    try:
                        _handler_cache[cache_key].close()
                    except Exception:
                        pass
                    del _handler_cache[cache_key]
            else:
                # Clear all handlers
                for handler in list(_handler_cache.values()):
                    try:
                        handler.close()
                    except Exception:
                        pass
                _handler_cache.clear()

    @classmethod
    def get_cached_handlers_info(cls) -> Dict[str, Any]:
        """Get info about cached handlers for monitoring.
        
        Returns:
            Dictionary with cache statistics
        """
        global _handler_cache
        
        with _cache_lock:
            info = {}
            for path, handler in _handler_cache.items():
                try:
                    info[path] = {
                        "format": handler.format_name,
                        "file_cache_size": len(handler._file_cache),
                        "metadata_cache_size": len(handler._metadata_cache),
                    }
                except Exception:
                    info[path] = {"error": "Failed to get info"}
            return info

    @classmethod
    def register_handler(cls, format_name: str, handler_class: Type[BaseImageHandler]) -> None:
        """Register a new handler for a format.
        
        Args:
            format_name: Name of the format (lowercase)
            handler_class: Handler class
        """
        cls.HANDLERS[format_name.lower()] = handler_class

    @classmethod
    def get_supported_formats(cls) -> list[str]:
        """Get list of supported formats."""
        return list(cls.HANDLERS.keys())
