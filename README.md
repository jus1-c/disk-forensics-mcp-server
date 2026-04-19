# MCP Disk Forensics

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

A high-performance MCP Server for Disk Forensics that enables AI agents to analyze disk images through the Model Context Protocol. Built with pytsk3 integration and intelligent caching for maximum speed.

## Features

- **High Performance**: Global handler caching with 279-235,000x speedup for repeated operations
- **Multi-Format Support**: RAW, E01, VMDK, VHD/VHDX, AD1 formats
- **Deep File Inspection**: Access to all filesystem structures (NTFS, FAT, ext, etc.)
- **Advanced Filtering**: Search by extension, timestamp, and deleted files
- **Security First**: Path validation, size limits, input sanitization
- **Memory Efficient**: LRU cache with 500,000 entries for large images
- **Parallel Processing**: Multi-threaded directory traversal

## Performance Benchmarks

Tested on a 3.7GB AD1 image with 1,587 directories and 19,882 files:

| Operation | Cold | Warm | Speedup |
|-----------|------|------|---------|
| List root | 7.2s | 0.000s | 235,877x |
| Full traversal | 29.0s | 0.104s | 279x |
| Repeated access | 7.2s | 0.000s | 235,877x |
| Deep path (5 levels) | 7.1s | 0.000s | 173,631x |

## Requirements

- Python 3.10+
- pytsk3 and forensic libraries installed
- MCP-compatible client (Claude Desktop, VSCode, Cline, etc.)

## Installation

### 1. Install Dependencies

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install python3-dev libtsk-dev
```

**macOS:**
```bash
brew install sleuthkit
```

**Windows:**
Install Python 3.10+ from [python.org](https://www.python.org/downloads/)

### 2. Install MCP Server

```bash
# Clone repository
git clone https://github.com/jus1-c/disk-forensics-mcp-server.git
cd disk-forensics-mcp-server

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install package
pip install -e ".[forensics]"
```

## Configuration

### Claude Desktop

Edit `claude_desktop_config.json`:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "disk-forensics": {
      "command": "disk-forensics-mcp-server",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### VSCode (with Cline extension)

Add to your settings:

```json
{
  "mcpServers": {
    "disk-forensics": {
      "command": "disk-forensics-mcp-server",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### OpenCode

Add to `~/.opencode/opencode.json`:

```json
{
  "mcp": {
    "disk-forensics": {
      "type": "local",
      "command": ["disk-forensics-mcp-server"],
      "enabled": true,
      "timeout": 150000
    }
  }
}
```

## Available Tools

### 1. analyze_disk_image
Analyze a disk image and return information about its format, size, and structure.

**Parameters:**
- `image_path`: Absolute path to disk image (required)

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw"
}
```

### 2. list_partitions
List partitions in a disk image. Supports MBR and GPT partition tables.

**Parameters:**
- `image_path`: Absolute path to disk image

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw"
}
```

### 3. list_files
List files in a directory with caching support.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `path`: Directory path to list (default: "/")

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "path": "/Windows/System32"
}
```

### 4. get_file_metadata
Get metadata for a specific file.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `file_path`: Path to the file within the partition

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "file_path": "/Windows/System32/config/SAM"
}
```

### 5. read_file
Read content of a specific file.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `file_path`: Path to the file within the partition
- `max_size`: Maximum bytes to read (default: 1MB)

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "file_path": "/Windows/System32/config/SAM",
  "max_size": 1048576
}
```

### 6. extract_file
Extract a file from the image to a destination path.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `file_path`: Path to the file within the partition
- `output_path`: Path to save the extracted file

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "file_path": "/Windows/System32/config/SAM",
  "output_path": "/home/user/extracted/SAM"
}
```

### 7. extract_directory
Extract a directory from the image to a destination path while preserving relative paths.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `directory_path`: Path to the directory within the partition
- `output_path`: Path to save the extracted directory

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "directory_path": "/Windows/System32/config",
  "output_path": "/home/user/extracted/config"
}
```

### 8. get_directory_tree
Get complete directory tree structure.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `path`: Starting path (default: "/")
- `max_depth`: Maximum recursion depth (default: 10)

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "path": "/Windows",
  "max_depth": 3
}
```

### 9. search_by_extension
Search files by extension.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `extension`: File extension to search for (e.g., "exe", "txt")
- `path`: Starting path (default: "/")

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "extension": "exe",
  "path": "/Windows"
}
```

### 10. search_by_timestamp
Search files by date range.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `start_time`: Start time (ISO format)
- `end_time`: End time (ISO format)
- `timestamp_type`: Type to check - "created", "modified", "accessed", or "any"
- `path`: Starting path (default: "/")

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "start_time": "2024-01-01T00:00:00",
  "end_time": "2024-12-31T23:59:59",
  "timestamp_type": "modified",
  "path": "/Windows"
}
```

### 11. scan_deleted_files
Scan for deleted files.

**Parameters:**
- `image_path`: Absolute path to disk image
- `partition_offset`: Offset of the partition in bytes
- `path`: Starting path (default: "/")
- `max_results`: Maximum results to return (default: 100)

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "partition_offset": 1048576,
  "path": "/",
  "max_results": 100
}
```

### 12. calculate_hash
Calculate hash (MD5, SHA1, or SHA256) of a disk image.

**Parameters:**
- `image_path`: Absolute path to disk image
- `algorithm`: Hash algorithm - "md5", "sha1", or "sha256" (default: "sha256")

**Example:**
```json
{
  "image_path": "/home/user/evidence/image.raw",
  "algorithm": "sha256"
}
```

## Usage Examples

### Basic Analysis
```
Please analyze this disk image and show me the partition layout.
Image: /home/user/evidence/image.raw
```

### File Extraction
```
Extract the SAM file from this Windows image.
Image: /home/user/evidence/windows.raw
Partition offset: 1048576
```

### Timeline Analysis
```
Find all files modified between January 1, 2024 and March 1, 2024.
Image: /home/user/evidence/image.raw
Partition offset: 1048576
```

### Malware Hunting
```
Search for all executable files in the Windows directory.
Image: /home/user/evidence/suspicious.raw
Extension: exe
Path: /Windows
```

### Deleted File Recovery
```
Scan for deleted files in the root directory.
Image: /home/user/evidence/image.raw
Partition offset: 1048576
```

## Security Features

- **Path Validation**: Only absolute paths allowed, no directory traversal
- **File Size Limits**: Configurable max file size (default: 1MB per read)
- **Cache Limits**: LRU cache with 500,000 entries
- **Timeout Protection**: Request timeout configuration (default: 150s)
- **Graceful Shutdown**: Proper resource cleanup on exit

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│   MCP Client    │────▶│  MCP Server      │────▶│   pytsk3    │
│ (Claude/VSCode) │     │  (Python/MCP)    │     │  (The Sleuth│
└─────────────────┘     └──────────────────┘     │   Kit)      │
                               │                 └─────────────┘
                               ▼                          │
                        ┌─────────────────┐               │
                        │  Global Cache   │               │
                        │  (500K entries) │               │
                        └─────────────────┘               │
                               │                          ▼
                               ▼                  ┌──────────────┐
                        ┌──────────────┐          │  Disk Image  │
                        │ Partition FS │          │  (RAW/E01/   │
                        │   Handles    │          │  VMDK/AD1)   │
                        └──────────────┘          └──────────────┘
```

## Project Structure

```
disk-forensics-mcp-server/
├── src/
│   ├── handlers/           # Image format handlers
│   │   ├── base_handler.py
│   │   ├── raw_handler.py
│   │   ├── e01_handler.py
│   │   ├── vmdk_handler.py
│   │   ├── vhd_handler.py
│   │   └── ad1_handler.py
│   ├── models/             # Pydantic schemas
│   │   └── schemas.py
│   ├── server/             # MCP server implementation
│   │   └── mcp_server.py
│   ├── tools/              # Forensics tools
│   │   ├── disk_tools/
│   │   │   ├── analyze_image.py
│   │   │   └── list_partitions.py
│   │   ├── filesystem_tools/
│   │   │   ├── list_files.py
│   │   │   ├── read_file.py
│   │   │   ├── extract_file.py
│   │   │   ├── get_directory_tree.py
│   │   │   ├── get_file_metadata.py
│   │   │   ├── search_by_extension.py
│   │   │   ├── search_by_timestamp.py
│   │   │   └── scan_deleted_files.py
│   │   └── hash_tools/
│   │       └── calculate_hash.py
│   └── utils/              # Utilities
│       ├── image_detector.py
│       └── parallel_utils.py
├── pyproject.toml
└── README.md
```

## Development

### Setup Development Environment
```bash
pip install -e ".[forensics,dev]"
```

### Code Quality
```bash
black src
isort src
flake8 src
mypy src
```

## Troubleshooting

### pytsk3 not found
```bash
# Install forensics dependencies
pip install ".[forensics]"

# On Ubuntu/Debian
sudo apt-get install python3-dev libtsk-dev

# On macOS
brew install sleuthkit
```

### Permission denied when accessing disk images
```bash
# Run with appropriate permissions
sudo disk-forensics-mcp-server

# Or copy image to user directory
cp /path/to/image.raw ~/evidence/
```

### Slow performance on first access
This is expected. First access reads from disk, subsequent accesses use cache.
- Cold: ~7-29s for full traversal
- Warm: ~0.000s from cache

## Changelog

### v0.2.0 - Major Performance Improvements
- Global handler caching with 279x - 235,000x speedup
- Increased cache capacity to 500,000 entries with LRU eviction
- Parallel processing with ThreadPoolExecutor
- Cache statistics monitoring
- Graceful shutdown with signal handling

### v0.1.0 - Initial Release
- Support for RAW, E01, VMDK, VHD/VHDX, AD1 formats
- Disk analysis: analyze_disk_image, list_partitions, calculate_hash
- Filesystem tools: list_files, get_file_metadata, read_file, extract_file
- Directory tree traversal and search tools
- Deleted file scanning
- Basic caching with 187x speedup

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- [The Sleuth Kit](https://www.sleuthkit.org/) - Forensic toolkit
- [pytsk3](https://github.com/py4n6/pytsk) - Python bindings for TSK
- [pyad1](https://github.com/pcbje/pyad1) - AD1 (AccessData Format) parser - Used as reference for AD1 handler implementation
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
- [python-mcp](https://github.com/modelcontextprotocol/python-sdk) - Python MCP SDK

## Support

For issues and feature requests, please use the [GitHub issue tracker](https://github.com/jus1-c/disk-forensics-mcp-server/issues).
