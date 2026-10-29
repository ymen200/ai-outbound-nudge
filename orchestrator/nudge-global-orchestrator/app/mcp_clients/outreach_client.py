from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.mcp_clients import McpStdioClient

logger = logging.getLogger(__name__)


class OutreachClient:
    """Async stdio MCP client for the Outreach Orchestrator.

    Mirrors the existing QualifierClient / SourcerClient pattern:
    the global orchestrator spawns the Outreach Orchestrator's MCP server
    as a subprocess and calls its exposed tools.
    """

    def __init__(self, client: Optional[McpStdioClient] = None):
        if client is not None:
            self._client = client
            return

        script = settings.resolve_path(settings.outreach_mcp_path)
        # The stdio MCP server is started through run_mcp.py. The wrapper imports
        # app.mcp_server so that the package context is preserved and relative
        # imports work. The wrapper lives at the root of the "outreach orchestrator"
        # directory, so that directory is the correct cwd.
        if not script.exists():
            raise FileNotFoundError(
                f"OUTREACH_MCP_PATH does not exist: {script}. "
                f"Set OUTREACH_MCP_PATH to the Outreach Orchestrator's run_mcp.py wrapper."
            )
        if script.name != "run_mcp.py":
            logger.warning(
                "OUTREACH_MCP_PATH should point to run_mcp.py (got %s). "
                "The legacy app/mcp_server.py cannot be launched as a bare script "
                "because its relative imports fail.",
                script.name,
            )
        cwd = str(script.parent)
        python = str(settings.resolve_path(settings.outreach_python)) if settings.outreach_python else sys.executable

        self._client = McpStdioClient(
            script_path=str(script),
            python_executable=python,
            cwd=cwd,
            timeout=settings.outreach_timeout,
            max_retries=settings.outreach_max_retries,
            retry_backoff_base=settings.outreach_retry_backoff_base,
        )

    async def start_outreach(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Start the outreach pipeline. Returns the full Outreach Orchestrator response."""
        logger.info("Calling run_outreach_pipeline via stdio MCP")
        return await self._client.call_tool("run_outreach_pipeline", payload)

    async def approve_pipeline(
        self,
        thread_id: str,
        approved: bool = True,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve or reject a paused outreach sequence."""
        logger.info("Calling approve_pipeline via stdio MCP for thread %s", thread_id)
        return await self._client.call_tool(
            "approve_pipeline",
            {
                "thread_id": thread_id,
                "approved": approved,
                "feedback": feedback or "",
            },
        )

    async def health(self) -> Dict[str, Any]:
        """Health check of the Outreach Orchestrator and its downstream modules."""
        return await self._client.call_tool("get_outreach_status", {})

    async def observability(self) -> Dict[str, Any]:
        """Aggregated observability from Sequence and Message Generators."""
        return await self._client.call_tool("get_observability", {})

    async def _raw_request(
        self, method: str, path: str, json: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Direct HTTP call to Outreach Orchestrator REST API (not MCP).
        Used for workflow signal endpoints that aren't exposed as MCP tools."""
        url = f"{settings.outreach_orch_url}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            if method == "GET":
                resp = await client.get(url)
            elif method == "POST":
                resp = await client.post(url, json=json)
            else:
                raise ValueError(f"Unsupported method: {method}")
            resp.raise_for_status()
            return resp.json()
