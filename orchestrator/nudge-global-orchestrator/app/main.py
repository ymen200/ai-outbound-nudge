from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

from app import __version__
from app.api import router as campaigns_router
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
# Module MCP servers already log to stderr; quiet noisy HTTP libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

app = FastAPI(
    title="Nudge Global Orchestrator",
    version=__version__,
    description="Phase A orchestrator — inject_collect_project ↔ nudge-qualifier-engine via MCP",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns_router)


@app.get("/")
async def root():
    return {
        "service": "nudge-global-orchestrator",
        "version": __version__,
        "phase": "A",
        "mock": settings.orchestrator_mock,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "mock": settings.orchestrator_mock}


@app.get("/ui/save-campaign")
async def ui_save_campaign():
    # Serve the simple test HTML page located at project_root/frontend/save_campaign.html
    p = Path(__file__).resolve().parent.parent / "frontend" / "save_campaign.html"
    if not p.exists():
        return {"error": "UI file not found", "path": str(p)}
    return FileResponse(str(p), media_type="text/html")
