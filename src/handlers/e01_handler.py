"""E01/EnCase Evidence File Format handler with libewf support."""

import os
import pytsk3
from typing import Optional, List
from .base_handler import BaseImageHandler, ImageInfo


class E01ImageHandle(pytsk3.Img_Info):
    """Custom image handle that wraps libewf for E01 support."""
    
    def __init__(self, ewf_handle):
        self._ewf_handle = ewf_handle
        self._size = ewf_handle.get_media_size()
        # Initialize with RAW type but we'll override read method
        super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_RAW)
    
    def get_size(self):
        return self._size
    
    def read(self, offset, size):
        """Read data from E01 via libewf."""
        self._ewf_handle.seek_offset(offset, os.SEEK_SET)
        return self._ewf_handle.read_buffer(size)
    
    def close(self):
        """Close the EWF handle."""
        if self._ewf_handle:
            self._ewf_handle.close()
            self._ewf_handle = None


class E01Handler(BaseImageHandler):
    """Handler for E01 (EnCase Evidence File Format) images.
    
    E01 files use the Expert Witness Compression Format (EWF) with
    zlib compression. This handler uses libewf-python for reading
    and provides a pytsk3-compatible interface.
    """
    
    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._format_name = "E01"
        self._ewf_handle = None
        self._image_handle = None
        
    @property
    def format_name(self) -> str:
        return self._format_name
    
    def open(self) -> None:
        """Open the E01 image using libewf."""
        try:
            import pyewf
            
            # Check for split files
            filenames = self._get_segment_files()
            
            # Normalize paths for Windows (libewf needs absolute paths with backslashes)
            filenames = [os.path.abspath(f) for f in filenames]
            
            # Open E01 file(s)
            self._ewf_handle = pyewf.handle()
            self._ewf_handle.open(filenames)
            
        except ImportError:
            raise IOError("libewf-python (pyewf) is required for E01 support")
        except Exception as e:
            raise IOError(f"Failed to open E01 image: {e}")
    
    def _get_segment_files(self) -> List[str]:
        """Get list of all segment files for this E01 image."""
        base = os.path.splitext(self.image_path)[0]
        ext = os.path.splitext(self.image_path)[1].lower()
        
        if ext != '.e01':
            return [self.image_path]
        
        # Start with E01
        files = [self.image_path]
        
        # Check for E02, E03, etc.
        for i in range(2, 1000):
            # Try uppercase
            next_file = f"{base}.E{i:02d}"
            if os.path.exists(next_file):
                files.append(next_file)
                continue
            
            # Try lowercase
            next_file_lower = f"{base}.e{i:02d}"
            if os.path.exists(next_file_lower):
                files.append(next_file_lower)
                continue
            
            # No more segments
            break
        
        return files
    
    def close(self) -> None:
        """Close the E01 image."""
        # Call base handler close to clear caches
        super().close()
        
        if self._image_handle:
            self._image_handle.close()
            self._image_handle = None
        if self._ewf_handle:
            self._ewf_handle.close()
            self._ewf_handle = None
    
    def read(self, offset: int, size: int) -> bytes:
        """Read data from the E01 image."""
        if not self._ewf_handle:
            raise IOError("E01 image not opened")
        
        try:
            self._ewf_handle.seek_offset(offset, os.SEEK_SET)
            return self._ewf_handle.read_buffer(size)
        except Exception as e:
            raise IOError(f"Failed to read from E01 image: {e}")
    
    def get_size(self) -> int:
        """Get the total size of the E01 image in bytes."""
        if not self._ewf_handle:
            raise IOError("E01 image not opened")
        
        try:
            return self._ewf_handle.get_media_size()
        except Exception as e:
            raise IOError(f"Failed to get E01 image size: {e}")
    
    def get_info(self) -> ImageInfo:
        """Get information about the E01 image."""
        size = self.get_size()
        
        # Get sector size from EWF
        try:
            sector_size = self._ewf_handle.get_bytes_per_sector()
        except:
            sector_size = 512  # Default
        
        sectors = size // sector_size
        
        return ImageInfo(
            format=self._format_name,
            size=size,
            sectors=sectors,
            sector_size=sector_size,
            checksum=None,  # E01 has internal checksums
            metadata={
                "image_path": self.image_path,
                "segment_files": self._get_segment_files(),
                "has_split_files": len(self._get_segment_files()) > 1
            }
        )
    
    def get_image_handle(self):
        """Get pytsk3-compatible image handle for E01."""
        if not self._ewf_handle:
            self.open()
        
        if self._image_handle is None:
            self._image_handle = E01ImageHandle(self._ewf_handle)
        
        return self._image_handle
