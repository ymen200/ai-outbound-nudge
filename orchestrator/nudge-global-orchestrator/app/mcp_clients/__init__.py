from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

from app.config import settings

logger = logging.getLogger(__name__)


def _to_plain(value: Any) -> Any:
    """Convert Pydantic models / nested structures into plain Python types."""
    if value is None:
        return None

    if isinstance(value, str):
        try:
            return _to_plain(json.loads(value))
        except json.JSONDecodeError:
            return value

    if isinstance(value, (bytes, bytearray)):
        try:
            return _to_plain(value.decode("utf-8"))
        except Exception:
            return value

    # Pydantic v2
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _to_plain(value.model_dump())
        except Exception:
            pass

    # Pydantic v1 / generic
    if hasattr(value, "dict") and callable(value.dict):
        try:
            return _to_plain(value.dict())
        except Exception:
            pass

    if isinstance(value, dict):
        plain = {k: _to_plain(v) for k, v in value.items()}
        return _unwrap_mcp_payload(plain)

    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]

    return value


def _unwrap_mcp_payload(payload: Dict[str, Any]) -> Any:
    """
    FastMCP often wraps JSON-string tool returns as:
      {"result": {"companies": [...], "count": N}}
    or {"output": {...}} / {"data": {...}}.
    Unwrap when the inner object is clearly the real tool payload.
    """
    if not isinstance(payload, dict):
        return payload

    # Already the orchestrator shape
    if "companies" in payload or "intent_by_apollo_id" in payload or "contacts" in payload:
        return payload
    if "sourced_personas_by_company" in payload or "campaign_id" in payload:
        return payload
    if "icp_filters" in payload or "ranked_companies" in payload:
        return payload
    if "usage" in payload and len(payload) == 1:
        return payload

    for key in ("result", "output", "data", "value", "content"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            return _unwrap_mcp_payload(inner)
        if isinstance(inner, str):
            try:
                parsed = json.loads(inner)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, (dict, list)):
                return _to_plain(parsed)

    return payload


def _parse_tool_result(result: Any) -> Any:
    """Normalize FastMCP CallToolResult into plain dict/list/str."""
    if result is None:
        return None

    # Prefer structured .data when present (often a Pydantic output model)
    data = getattr(result, "data", None)
    if data is not None:
        return _to_plain(data)

    content = getattr(result, "content", None)
    if content:
        texts = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                texts.append(text)
            elif isinstance(block, dict) and "text" in block:
                texts.append(block["text"])
        if len(texts) == 1:
            return _to_plain(texts[0])
        if texts:
            return [_to_plain(t) for t in texts]

    return _to_plain(result)


class McpStdioClient:
    """Spawns an MCP server via stdio using a specific Python + working directory."""

    def __init__(
        self,
        script_path: str,
        python_executable: Optional[str] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = 120.0,
        max_retries: int = 0,
        retry_backoff_base: float = 2.0,
    ):
        self.script_path = Path(script_path).resolve()
        self.python_executable = python_executable or sys.executable
        self.cwd = str(Path(cwd).resolve()) if cwd else str(self.script_path.parent)
        self.env = env
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base

    def _transport(self) -> PythonStdioTransport:
        merged_env = dict(os.environ)
        if self.env:
            merged_env.update(self.env)
        return PythonStdioTransport(
            script_path=str(self.script_path),
            python_cmd=self.python_executable,
            cwd=self.cwd,
            env=merged_env,
            keep_alive=False,
        )

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Call an MCP tool with timeout and optional retry + exponential backoff.

        Retries up to ``max_retries`` times on *any* exception. MCP subprocess
        failures are inherently transient (the subprocess may crash, restart, or
        time out) and fastmcp's ``McpError`` is not a subclass of the standard
        connection-error hierarchy, so a broad catch is the pragmatic choice.
        Non-transient errors (logic bugs) will simply fail again on retry and
        exhaust the budget quickly.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self._call_tool_once(name, arguments, attempt)
            except Exception as exc:
                # Retry on any exception — MCP subprocess failures are inherently
                # transient (the subprocess may crash, restart, or time out).
                # Non-transient errors (logic bugs) will simply fail again on
                # retry and exhaust the budget quickly.
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.retry_backoff_base * (2 ** attempt)
                    logger.warning(
                        "MCP tool %s attempt %d/%d failed (%s) — retrying in %.1fs",
                        name,
                        attempt + 1,
                        self.max_retries + 1,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "MCP tool %s exhausted %d attempts — giving up",
                        name,
                        self.max_retries + 1,
                    )
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"MCP tool '{name}' on '{self.script_path.name}' "
            f"produced no result and no exception (max_retries={self.max_retries})"
        )

    async def _call_tool_once(
        self, name: str, arguments: Dict[str, Any], attempt: int
    ) -> Any:
        """Single MCP tool call attempt with timeout."""
        logger.info(
            "MCP call %s (%s) → %s  (attempt=%d, timeout=%.0fs)",
            self.script_path.name,
            Path(self.python_executable).name,
            name,
            attempt + 1,
            self.timeout,
        )
        try:
            async with Client(self._transport()) as client:
                result = await asyncio.wait_for(
                    client.call_tool(name, arguments),
                    timeout=self.timeout,
                )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"MCP tool '{name}' on '{self.script_path.name}' "
                f"timed out after {self.timeout}s"
            )
        parsed = _parse_tool_result(result)
        if isinstance(parsed, dict) and parsed.get("error"):
            logger.error("MCP tool %s error: %s", name, parsed["error"])
        else:
            logger.info("MCP tool %s finished (attempt %d)", name, attempt + 1)
        return parsed


class QualifierClient:
    def __init__(self, client: Optional[McpStdioClient] = None):
        script = settings.resolve_path(settings.qualifier_mcp_path)
        # run.py lives in qualifier_mcp/; imports need qualifier_agent/ on path
        cwd = str(script.parent.parent)
        qualifier_python = str(settings.resolve_path(settings.qualifier_python)) if settings.qualifier_python else None
        self._client = client or McpStdioClient(
            str(script),
            qualifier_python,
            cwd=cwd,
            timeout=settings.qualifier_timeout,
            max_retries=settings.qualifier_max_retries,
            retry_backoff_base=settings.mcp_retry_backoff_base,
        )

    async def start_campaign(
        self,
        *,
        user_id: str,
        icp_description_text: str,
        user_offering: str,
        blacklist: Optional[Dict[str, List[str]]] = None,
        configurable_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "start_campaign",
            {
                "user_id": user_id,
                "icp_description_text": icp_description_text,
                "user_offering": user_offering,
                "blacklist": blacklist or {"companies": [], "personas": []},
                "configurable_weights": configurable_weights or {},
            },
        )

    async def resume_with_companies(
        self, *, campaign_id: str, sourced_companies: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "resume_with_companies",
            {"campaign_id": campaign_id, "sourced_companies": sourced_companies},
        )

    async def rescore_with_intent(
        self, *, campaign_id: str, intent_by_apollo_id: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "rescore_with_intent",
            {"campaign_id": campaign_id, "intent_by_apollo_id": intent_by_apollo_id},
        )

    async def resume_with_approvals(
        self,
        *,
        campaign_id: str,
        approved_apollo_ids: List[str],
        sourced_personas_by_company: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "resume_with_approvals",
            {
                "campaign_id": campaign_id,
                "approved_apollo_ids": approved_apollo_ids,
                "sourced_personas_by_company": sourced_personas_by_company,
            },
        )


class SourcerClient:
    def __init__(self, client: Optional[McpStdioClient] = None):
        script = settings.resolve_path(settings.sourcer_mcp_path)
        cwd = str(script.parent)
        sourcer_python = str(settings.resolve_path(settings.sourcer_python)) if settings.sourcer_python else None
        self._client = client or McpStdioClient(
            str(script),
            sourcer_python,
            cwd=cwd,
            timeout=settings.sourcer_timeout,
            max_retries=settings.sourcer_max_retries,
            retry_backoff_base=settings.mcp_retry_backoff_base,
        )

    async def fetch_companies(
        self,
        *,
        industries: List[str],
        locations: Optional[List[str]] = None,
        continent: Optional[str] = None,
        employee_ranges: Optional[List[str]] = None,
        limit: int = 2,
        limit_per_element: int = 1,
        min_employees: Optional[float] = None,
        max_employees: Optional[float] = None,
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "orchestrator_fetch_companies",
            {
                "industries": industries,
                "locations": locations,
                "continent": continent,
                "employee_ranges": employee_ranges,
                "limit": limit,
                "limit_per_element": limit_per_element,
                "min_employees": min_employees,
                "max_employees": max_employees,
            },
        )

    async def fetch_intent(
        self, *, company_apollo_ids: List[str], target_country: Optional[str] = None
    ) -> Dict[str, Any]:
        return await self._client.call_tool(
            "orchestrator_fetch_intent",
            {
                "company_apollo_ids": company_apollo_ids,
                "target_country": target_country,
            },
        )

    async def fetch_personas_with_signals(
        self,
        *,
        company_apollo_ids: List[str],
        target_country: Optional[str] = None,
        role: Optional[List[str]] = None,
        limit: int = 6,
        limit_per_element: int = 3,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "company_apollo_ids": company_apollo_ids,
            "target_country": target_country,
            "limit": limit,
            "limit_per_element": limit_per_element,
        }
        # ICP target_roles → Apollo person_titles[]. Omit when empty so sourcer
        # keeps its sales preset fallback.
        if role:
            payload["role"] = list(role)
        return await self._client.call_tool(
            "orchestrator_fetch_personas_with_signals",
            payload,
        )

    async def enrich_contacts(self, *, persona_apollo_ids: List[str]) -> Dict[str, Any]:
        return await self._client.call_tool(
            "orchestrator_enrich_contacts",
            {"persona_apollo_ids": persona_apollo_ids},
        )
