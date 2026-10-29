"""Wrapper script to run MCP server without module conflicts."""
import asyncio
import sys
import os

# Ensure this directory is in the path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.mcp_server import main

if __name__ == "__main__":
    asyncio.run(main())
