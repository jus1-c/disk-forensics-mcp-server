"""Pydantic models for MCP tool inputs and outputs."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================================
# Input Schemas
# ============================================================================

class AnalyzeDiskImageInput(BaseModel):
    """Input for analyze_disk_image tool."""
    image_path: str = Field(..., description="Path to the disk image file")


class ListPartitionsInput(BaseModel):
    """Input for list_partitions tool."""
    image_path: str = Field(..., description="Path to the disk image file")


class ListFilesInput(BaseModel):
    """Input for list_files tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    path: str = Field(default="/", description="Directory path to list")
    max_depth: int = Field(default=10, description="Maximum recursion depth for tree view")


class GetFileMetadataInput(BaseModel):
    """Input for get_file_metadata tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    file_path: str = Field(..., description="Path to the file")


class ReadFileContentInput(BaseModel):
    """Input for read_file_content tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    file_path: str = Field(..., description="Path to the file")
    max_size: int = Field(default=1048576, description="Maximum bytes to read (default 1MB)")


class CalculateHashInput(BaseModel):
    """Input for calculate_hash tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    algorithm: str = Field(default="sha256", description="Hash algorithm (md5, sha1, sha256)")


class SearchByExtensionInput(BaseModel):
    """Input for search_by_extension tool."""
    image_path: str = Field(..., description="Path to the disk image file")
    partition_offset: int = Field(..., description="Offset of the partition in bytes")
    extension: str = Field(..., description="File extension to search for (e.g., 'txt')")
    path: str = Field(default="/", description="Directory path to start search")


# ============================================================================
# Output Schemas
# ============================================================================

class DiskImageInfo(BaseModel):
    """Information about a disk image."""
    format: str = Field(..., description="Image format (RAW, E01, etc.)")
    size: int = Field(..., description="Total size in bytes")
    sectors: int = Field(..., description="Number of sectors")
    sector_size: int = Field(..., description="Sector size in bytes")
    is_split: bool = Field(default=False, description="Whether image is split")
    segments: List[str] = Field(default=[], description="List of segment files")
    metadata: Dict[str, Any] = Field(default={}, description="Additional metadata")


class Partition(BaseModel):
    """Partition information."""
    offset: int = Field(..., description="Partition offset in bytes")
    size: int = Field(..., description="Partition size in bytes")
    type: str = Field(..., description="Partition type")
    label: Optional[str] = Field(None, description="Partition label")
    filesystem: Optional[str] = Field(None, description="Filesystem type")


class PartitionsOutput(BaseModel):
    """Output for list_partitions."""
    partitions: List[Partition] = Field(..., description="List of partitions")
    count: int = Field(..., description="Number of partitions")


class FileEntry(BaseModel):
    """File or directory entry."""
    name: str = Field(..., description="File name")
    path: str = Field(..., description="Full path")
    size: int = Field(..., description="File size in bytes")
    is_directory: bool = Field(..., description="Whether this is a directory")
    is_deleted: bool = Field(default=False, description="Whether file is deleted")
    created: Optional[datetime] = Field(None, description="Creation timestamp")
    modified: Optional[datetime] = Field(None, description="Modification timestamp")
    accessed: Optional[datetime] = Field(None, description="Access timestamp")
    inode: Optional[int] = Field(None, description="Inode number")


class FilesOutput(BaseModel):
    """Output for list_files."""
    files: List[FileEntry] = Field(..., description="List of files")
    count: int = Field(..., description="Number of files")
    path: str = Field(..., description="Directory path")


class FileMetadataOutput(BaseModel):
    """Output for get_file_metadata."""
    file: FileEntry = Field(..., description="File metadata")


class FileContentOutput(BaseModel):
    """Output for read_file_content."""
    content: str = Field(..., description="File content (base64 encoded if binary)")
    size: int = Field(..., description="Size of content in bytes")
    is_binary: bool = Field(..., description="Whether content is binary")
    encoding: str = Field(default="utf-8", description="Text encoding if applicable")


class HashOutput(BaseModel):
    """Output for calculate_hash."""
    algorithm: str = Field(..., description="Hash algorithm used")
    hash_value: str = Field(..., description="Computed hash value")
    image_path: str = Field(..., description="Path to the image")


class SearchResultsOutput(BaseModel):
    """Output for search operations."""
    files: List[FileEntry] = Field(..., description="Matching files")
    count: int = Field(..., description="Number of matches")
    search_term: str = Field(..., description="Search term used")


class DirectoryTreeOutput(BaseModel):
    """Output for get_directory_tree."""
    tree: Dict[str, Any] = Field(..., description="Hierarchical tree structure")
    total_files: int = Field(..., description="Total number of files")
    total_dirs: int = Field(..., description="Total number of directories")


# ============================================================================
# Error Schemas
# ============================================================================

class ErrorOutput(BaseModel):
    """Error output."""
    error: bool = Field(default=True, description="Indicates an error occurred")
    message: str = Field(..., description="Error message")
    code: Optional[str] = Field(None, description="Error code")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
