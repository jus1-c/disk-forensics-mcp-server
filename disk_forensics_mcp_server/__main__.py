#!/usr/bin/env python3
"""Entry point for disk-forensics-mcp-server."""

from .server.mcp_server import main as server_main

def main():
    """Main entry point."""
    server_main()

if __name__ == "__main__":
    main()
