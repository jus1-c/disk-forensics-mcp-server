# Disk Forensics MCP Server

MCP Server for disk forensics analysis, supporting multiple image formats including RAW, E01, VMDK, VHD/VHDX, and AD1.

## 🚀 Features

### Supported Image Formats
- ✅ **RAW/DD** - Single and split images
- ✅ **E01/EnCase** - Expert Witness Format
- ✅ **VMDK** - VMware Virtual Disk
- ✅ **VHD/VHDX** - Microsoft Virtual Hard Disk (fixed & dynamic)
- ✅ **AD1** - AccessData FTK Image

### Disk Tools
- ✅ **analyze_disk_image** - Detect format, size, segments
- ✅ **list_partitions** - MBR and GPT partition tables
- ✅ **calculate_hash** - MD5, SHA1, SHA256

### Filesystem Tools (via pytsk3)
- ✅ **list_files** - Browse directories with caching
- ✅ **get_file_metadata** - File details with timestamps
- ✅ **read_file** - Read file content
- ✅ **extract_file** - Extract files from image
- ✅ **get_directory_tree** - Get complete directory structure
- ✅ **search_by_extension** - Find files by extension
- ✅ **search_by_timestamp** - Find files by date range
- ✅ **scan_deleted_files** - Recover deleted files

### Performance Features
- ✅ **Intelligent Caching** - 187x speedup for repeated operations
- ✅ **Partition Caching** - Filesystem handles cached per partition
- ✅ **File Listing Cache** - Directory listings cached
- ✅ **Metadata Cache** - File metadata cached

## 📦 Installation

### Prerequisites
- Python 3.10+
- pip

### Install from source

```bash
cd forensics-mcp-server
pip install -e .
```

### Install with forensics libraries

```bash
pip install -e ".[forensics]"
```

### Install with development tools

```bash
pip install -e ".[forensics,dev]"
```

## 🔧 MCP Configuration

Add to your MCP settings file:

**Cline:**
```json
{
  "mcpServers": {
    "disk-forensics": {
      "command": "python",
      "args": ["-m", "forensics_mcp_server.server.mcp_server"],
      "cwd": "C:\\Users\\Administrator\\Documents\\Python\\Forensics_Tools\\forensics-mcp-server",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

**Claude Desktop:**
```json
{
  "mcpServers": {
    "disk-forensics": {
      "command": "python",
      "args": ["-m", "forensics_mcp_server.server.mcp_server"],
      "cwd": "C:\\Users\\Administrator\\Documents\\Python\\Forensics_Tools\\forensics-mcp-server"
    }
  }
}
```

## 🛠️ Available Tools

### Disk Tools

#### analyze_disk_image
Analyze a disk image and return information about its format, size, and structure.

**Input:**
```json
{
  "image_path": "path/to/image.raw"
}
```

**Output:**
```json
{
  "format": "RAW",
  "size": 1073741824,
  "sectors": 2097152,
  "sector_size": 512,
  "is_split": false,
  "segments": ["path/to/image.raw"],
  "metadata": {}
}
```

#### list_partitions
List partitions in a disk image. Supports MBR and GPT partition tables.

**Input:**
```json
{
  "image_path": "path/to/image.raw"
}
```

**Output:**
```json
{
  "partitions": [
    {
      "offset": 1048576,
      "size": 536870912,
      "type": "NTFS / exFAT / HPFS",
      "label": null,
      "filesystem": "NTFS"
    }
  ],
  "count": 1
}
```

#### calculate_hash
Calculate hash (MD5, SHA1, or SHA256) of a disk image.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "algorithm": "sha256"
}
```

**Output:**
```json
{
  "algorithm": "SHA256",
  "hash_value": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "image_path": "path/to/image.raw"
}
```

### Filesystem Tools

#### list_files
List files in a directory with caching support.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "path": "/"
}
```

**Output:**
```json
{
  "files": [
    {
      "name": "file.txt",
      "path": "/file.txt",
      "size": 1024,
      "is_directory": false,
      "is_deleted": false,
      "created": "2024-01-01T00:00:00",
      "modified": "2024-01-01T00:00:00",
      "accessed": "2024-01-01T00:00:00",
      "inode": 12345
    }
  ],
  "count": 1
}
```

#### get_file_metadata
Get metadata for a specific file.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "file_path": "/file.txt"
}
```

#### read_file
Read content of a specific file.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "file_path": "/file.txt"
}
```

#### extract_file
Extract a file from the image to a destination path.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "file_path": "/file.txt",
  "destination_path": "/tmp/extracted.txt"
}
```

#### get_directory_tree
Get complete directory tree structure.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "path": "/"
}
```

#### search_by_extension
Search files by extension.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "extension": ".txt",
  "path": "/"
}
```

#### search_by_timestamp
Search files by date range.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "timestamp_type": "modified",
  "path": "/"
}
```

#### scan_deleted_files
Scan for deleted files.

**Input:**
```json
{
  "image_path": "path/to/image.raw",
  "partition_offset": 1048576,
  "path": "/"
}
```

## 📁 Project Structure

```
forensics-mcp-server/
├── src/
│   └── forensics_mcp_server/
│       ├── handlers/       # Image format handlers (RAW, E01, VMDK, VHD, AD1)
│       ├── models/         # Pydantic schemas
│       ├── server/         # MCP server implementation
│       ├── tools/          # Forensics tools
│       │   ├── disk_tools/     # Disk analysis tools
│       │   ├── filesystem_tools/  # Filesystem browsing tools
│       │   └── hash_tools/     # Hash calculation tools
│       └── utils/          # Utilities (image detector)
├── pyproject.toml          # Project configuration
└── README.md              # This file
```

## 🧪 Testing

### Create a test image
```bash
# Create a 10MB test image
dd if=/dev/zero of=test.raw bs=1M count=10

# Or on Windows
fsutil file createnew test.raw 10485760
```

### Run tests
```bash
pytest tests/
```

## 📚 Dependencies

### Core Dependencies
- mcp>=1.0.0
- pydantic>=2.0.0
- python-magic>=0.4.27
- python-dateutil>=2.8.2

### Forensics Libraries (Optional)
- pytsk3>=20231007 - Filesystem analysis
- pyewf>=20231123 - E01 support
- libvhdi-python>=20231123 - VHD/VHDX support
- libvmdk-python>=20231123 - VMDK support
- pyfsntfs>=20231123 - NTFS support
- pyfsfat>=20231123 - FAT support

## 📝 License

MIT License - See LICENSE file

## 🤝 Contributing

Contributions are welcome! Please follow the vertical slice approach when adding new features.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 🐛 Troubleshooting

### Common Issues

**Issue:** `ImportError: No module named 'pytsk3'`
**Solution:** Install forensics dependencies: `pip install ".[forensics]"`

**Issue:** `Permission denied` when accessing disk images
**Solution:** Run with appropriate permissions or copy image to user directory

**Issue:** Slow performance on large images
**Solution:** The server uses intelligent caching. First access may be slow, subsequent accesses will be much faster (up to 187x speedup).

## 📞 Support

For issues and feature requests, please use the GitHub issue tracker.

---

**Note:** This tool is for forensic analysis and investigation purposes. Always ensure you have proper authorization before analyzing disk images.
