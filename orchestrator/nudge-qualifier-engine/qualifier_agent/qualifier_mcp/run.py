"""
mcp/run.py
──────────
Entrypoint for the Strategic Qualifier MCP server.

Usage:
    From project root:
        python qualifier_agent/mcp/run.py

    Or with uvicorn for production:
        uvicorn qualifier_agent.mcp.run:app --host 0.0.0.0 --port 8000

Environment variables required:
    DATABASE_URL   — Postgres connection string (direct, non-pooled port)
    GROQ_API_KEY   — Groq API key for LLM calls
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Add qualifier_agent directory to path so we can import its modules
qualifier_agent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(qualifier_agent_dir))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)

# Validate required environment variables before starting
_required_env = ["DATABASE_URL", "GROQ_API_KEY"]
_missing = [k for k in _required_env if not os.environ.get(k)]
if _missing:
    raise RuntimeError(
        f"Missing required environment variables: {_missing}. "
        f"Set them in your .env file or environment before starting the server."
    )

from qualifier_mcp.server import mcp

if __name__ == "__main__":
    mcp.run()