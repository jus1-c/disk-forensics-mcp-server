"""Handler for RAW/DD disk images."""

import os
import re
from typing import List, Optional, BinaryIO
from .base_handler import BaseImageHandler, ImageInfo, PartitionInfo


class RAWHandler(BaseImageHandler):
    """Handler for RAW/DD disk images, including split images."""

    def __init__(self, image_path: str):
        super().__init__(image_path)
        self._segments: List[str] = []
        self._handles: List[BinaryIO] = []
        self._segment_sizes: List[int] = []
        self._current_segment: int = 0

    @property
    def format_name(self) -> str:
        return "RAW"

    def _detect_split_pattern(self) -> List[str]:
        """Detect split RAW files (.001, .002, .aa, .ab, etc.)."""
        segments = []
        base_path = self.image_path

        # Check if this is already a segment
        # Pattern 1: .001, .002, .003...
        match = re.match(r'^(.*?)(\.\d{3,})$', base_path)
        if match:
            base = match.group(1)
            ext = match.group(2)
            # Find all segments
            counter = 1
            while True:
                seg_path = f"{base}.{counter:03d}"
                if os.path.exists(seg_path):
                    segments.append(seg_path)
                    counter += 1
                else:
                    break
            if segments:
                return segments

        # Pattern 2: .aa, .ab, .ac... (split with letters)
        match = re.match(r'^(.*?)(\.[a-z]{2,})$', base_path, re.IGNORECASE)
        if match:
            base = match.group(1)
            # Find all segments
            for i in range(26 * 26):  # aa to zz
                first = chr(ord('a') + (i // 26))
                second = chr(ord('a') + (i % 26))
                seg_path = f"{base}.{first}{second}"
                if os.path.exists(seg_path):
                    segments.append(seg_path)
                elif i > 0:  # Stop if we've found at least one and next doesn't exist
                    break
            if segments:
                return segments

        # Pattern 3: Check if base file exists with numeric extensions
        base_without_ext = os.path.splitext(base_path)[0]
        counter = 1
        while True:
            seg_path = f"{base_without_ext}.{counter:03d}"
            if os.path.exists(seg_path):
                segments.append(seg_path)
                counter += 1
            else:
                break
        if segments:
            return segments

        # Single file
        if os.path.exists(base_path):
            return [base_path]

        return []

    def open(self) -> None:
        """Open the RAW image (single or split)."""
        self._segments = self._detect_split_pattern()
        
        if not self._segments:
            raise FileNotFoundError(f"Image not found: {self.image_path}")

        self._handles = []
        self._segment_sizes = []
        
        for segment_path in self._segments:
            handle = open(segment_path, 'rb')
            self._handles.append(handle)
            self._segment_sizes.append(os.path.getsize(segment_path))

    def close(self) -> None:
        """Close all segment handles."""
        # Call base handler close to clear caches
        super().close()
        
        for handle in self._handles:
            if handle and not handle.closed:
                handle.close()
        self._handles = []
        self._segment_sizes = []

    def _get_segment_for_offset(self, offset: int) -> tuple[int, int]:
        """Get the segment index and local offset for a global offset."""
        current_offset = 0
        for i, size in enumerate(self._segment_sizes):
            if offset < current_offset + size:
                return i, offset - current_offset
            current_offset += size
        raise ValueError(f"Offset {offset} exceeds image size")

    def read(self, offset: int, size: int) -> bytes:
        """Read data from the image at the specified offset."""
        if not self._handles:
            raise IOError("Image not opened")

        result = bytearray()
        remaining = size
        current_offset = offset

        while remaining > 0:
            try:
                segment_idx, local_offset = self._get_segment_for_offset(current_offset)
            except ValueError:
                # We've reached the end of the image
                break

            handle = self._handles[segment_idx]
            segment_remaining = self._segment_sizes[segment_idx] - local_offset
            to_read = min(remaining, segment_remaining)

            handle.seek(local_offset)
            data = handle.read(to_read)
            if not data:
                break

            result.extend(data)
            remaining -= len(data)
            current_offset += len(data)

        return bytes(result)

    def get_size(self) -> int:
        """Get the total size of the image."""
        if not self._segment_sizes:
            self._segments = self._detect_split_pattern()
            self._segment_sizes = [
                os.path.getsize(seg) for seg in self._segments
            ]
        return sum(self._segment_sizes)

    def get_info(self) -> ImageInfo:
        """Get information about the RAW image."""
        size = self.get_size()
        sector_size = 512  # Standard sector size
        sectors = size // sector_size

        metadata = {
            "segments": len(self._segments),
            "segment_files": self._segments,
        }

        return ImageInfo(
            format=self.format_name,
            size=size,
            sectors=sectors,
            sector_size=sector_size,
            metadata=metadata,
        )

    def is_split(self) -> bool:
        """Check if this is a split image."""
        return len(self._segments) > 1

    def get_segments(self) -> List[str]:
        """Get list of segment file paths."""
        return self._segments.copy()
