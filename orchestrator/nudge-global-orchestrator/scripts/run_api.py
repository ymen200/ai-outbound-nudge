"""Run the orchestrator API.

Usage:
    cd nudge-global-orchestrator
    python scripts/run_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the orchestrator root is on sys.path so 'app' is importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn

from app.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
