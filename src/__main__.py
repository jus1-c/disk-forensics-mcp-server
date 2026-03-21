#!/usr/bin/env python3
"""Entry point for disk-forensics-mcp-server that sets up paths correctly."""

import sys
import os

def main():
    """Main entry point."""
    # Add src to path if not already there
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Import and run
    from src.server.mcp_server import main as server_main
    server_main()

if __name__ == "__main__":
    main()
