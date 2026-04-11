#!/usr/bin/env python3
"""MCP Server for Disk Forensics Analysis with persistent handler caching."""

import asyncio
import sys
import signal
import atexit
from typing import Dict, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Import disk tools
from ..tools.disk_tools.analyze_image import analyze_disk_image, tool_definition as analyze_tool
from ..tools.disk_tools.list_partitions import list_partitions, tool_definition as partitions_tool

# Import filesystem tools
from ..tools.filesystem_tools.list_files import list_files, tool_definition as list_files_tool
from ..tools.filesystem_tools.read_file import read_file_content, tool_definition as read_file_tool
from ..tools.filesystem_tools.extract_file import extract_file, tool_definition as extract_file_tool
from ..tools.filesystem_tools.get_directory_tree import get_directory_tree, tool_definition as tree_tool
from ..tools.filesystem_tools.get_file_metadata import get_file_metadata, tool_definition as metadata_tool
from ..tools.filesystem_tools.search_by_extension import search_by_extension, tool_definition as ext_search_tool
from ..tools.filesystem_tools.search_by_timestamp import search_by_timestamp, tool_definition as time_search_tool
from ..tools.filesystem_tools.scan_deleted_files import scan_deleted_files, tool_definition as deleted_tool

# Import hash tools
from ..tools.hash_tools.calculate_hash import calculate_hash, tool_definition as hash_tool

# Import cache utilities
from ..utils.image_detector import ImageDetector
from ..utils.parallel_utils import cleanup_parallel_processing


# Tool registry
TOOLS: Dict[str, Dict[str, Any]] = {
    # Disk tools
    "analyze_disk_image": {
        "definition": analyze_tool,
        "handler": analyze_disk_image,
    },
    "list_partitions": {
        "definition": partitions_tool,
        "handler": list_partitions,
    },
    # Filesystem tools
    "list_files": {
        "definition": list_files_tool,
        "handler": list_files,
    },
    "read_file_content": {
        "definition": read_file_tool,
        "handler": read_file_content,
    },
    "extract_file": {
        "definition": extract_file_tool,
        "handler": extract_file,
    },
    "get_directory_tree": {
        "definition": tree_tool,
        "handler": get_directory_tree,
    },
    "get_file_metadata": {
        "definition": metadata_tool,
        "handler": get_file_metadata,
    },
    "search_by_extension": {
        "definition": ext_search_tool,
        "handler": search_by_extension,
    },
    "search_by_timestamp": {
        "definition": time_search_tool,
        "handler": search_by_timestamp,
    },
    "scan_deleted_files": {
        "definition": deleted_tool,
        "handler": scan_deleted_files,
    },
    # Hash tools
    "calculate_hash": {
        "definition": hash_tool,
        "handler": calculate_hash,
    },
}


class ForensicsMCPServer:
    """MCP Server for disk forensics with persistent handler caching."""

    def __init__(self):
        self.server = Server(
            "disk-forensics",
            "0.2.0",
        )
        self._setup_handlers()
        self._setup_shutdown_handler()

    def _setup_handlers(self) -> None:
        """Setup MCP request handlers."""
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            tools = []
            for tool_info in TOOLS.values():
                tool_def = tool_info["definition"]
                tools.append(Tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    inputSchema=tool_def["inputSchema"],
                ))
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool calls."""
            if name not in TOOLS:
                return [
                    TextContent(
                        type="text",
                        text=f"Error: Unknown tool '{name}'"
                    )
                ]
            
            try:
                # Get the tool handler
                handler = TOOLS[name]["handler"]
                
                # Call the handler
                result = await handler(arguments)
                
                # Format result as JSON
                import json
                result_text = json.dumps(result, indent=2, default=str)
                
                return [
                    TextContent(
                        type="text",
                        text=result_text
                    )
                ]
                
            except Exception as e:
                import traceback
                error_text = f"Error executing tool '{name}': {str(e)}\n{traceback.format_exc()}"
                return [
                    TextContent(
                        type="text",
                        text=error_text
                    )
                ]

    def _setup_shutdown_handler(self) -> None:
        """Setup cleanup on server shutdown."""
        # Register atexit handler
        atexit.register(self._cleanup)
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # On Windows, also handle these signals
        if sys.platform == "win32":
            signal.signal(signal.SIGBREAK, self._signal_handler)  # Ctrl+Break

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        import signal
        signal_name = signal.Signals(signum).name
        print(f"\nReceived {signal_name}, shutting down gracefully...")
        self._cleanup()
        sys.exit(0)

    def _cleanup(self) -> None:
        """Cleanup all cached handlers and parallel resources on shutdown."""
        try:
            ImageDetector.invalidate_handler()
            cleanup_parallel_processing()
            print("All handlers and resources cleaned up successfully")
        except Exception as e:
            print(f"Error during cleanup: {e}")

    async def run(self) -> None:
        """Run the server."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


def main() -> None:
    """Main entry point."""
    server = ForensicsMCPServer()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
