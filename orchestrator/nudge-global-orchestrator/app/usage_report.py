"""
Per-campaign token / credit usage aggregation.

Collects `usage` blobs returned by sourcer + qualifier MCP tools and writes a
single JSON report at the end of Phase A.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_APOLLO_KEYS = (
    "lead_credits_consumed",
    "direct_dial_credits_consumed",
    "ai_credits_consumed",
)
_GEMINI_KEYS = (
    "api_calls_consumed",
    "successful_calls",
    "failed_calls",
    "prompt_tokens",
    "candidates_tokens",
    "thoughts_tokens",
    "cached_content_tokens",
    "total_tokens",
)
_GROQ_KEYS = (
    "total_tokens_in",
    "total_tokens_out",
    "total_tokens",
    "total_llm_calls",
)


def _empty_apollo() -> Dict[str, int]:
    return {k: 0 for k in _APOLLO_KEYS}


def _empty_gemini() -> Dict[str, Any]:
    return {k: 0 for k in _GEMINI_KEYS} | {"by_model": {}, "by_operation": {}}


def _empty_groq() -> Dict[str, Any]:
    return {k: 0 for k in _GROQ_KEYS} | {"by_operation": {}, "per_node": []}


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _merge_apollo(dst: Dict[str, int], src: Optional[Dict[str, Any]]) -> None:
    if not isinstance(src, dict):
        return
    for key in _APOLLO_KEYS:
        dst[key] = _as_int(dst.get(key)) + _as_int(src.get(key))


def _merge_gemini(dst: Dict[str, Any], src: Optional[Dict[str, Any]]) -> None:
    if not isinstance(src, dict):
        return
    for key in _GEMINI_KEYS:
        dst[key] = _as_int(dst.get(key)) + _as_int(src.get(key))
    for bucket_name in ("by_model", "by_operation"):
        dst_bucket = dst.setdefault(bucket_name, {})
        src_bucket = src.get(bucket_name) or {}
        if not isinstance(src_bucket, dict):
            continue
        for name, stats in src_bucket.items():
            if not isinstance(stats, dict):
                continue
            entry = dst_bucket.setdefault(
                name, {"calls": 0, "total_tokens": 0, "prompt_tokens": 0, "candidates_tokens": 0}
            )
            for field in ("calls", "total_tokens", "prompt_tokens", "candidates_tokens"):
                entry[field] = _as_int(entry.get(field)) + _as_int(stats.get(field))


def _normalize_groq(src: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Accept sourcer groq shape or qualifier usage_summary shape."""
    out = _empty_groq()
    if not isinstance(src, dict):
        return out

    combined = src.get("combined") if isinstance(src.get("combined"), dict) else None
    if combined:
        out["total_tokens_in"] = _as_int(combined.get("total_tokens_in"))
        out["total_tokens_out"] = _as_int(combined.get("total_tokens_out"))
        out["total_tokens"] = _as_int(combined.get("total_tokens"))
        out["total_llm_calls"] = _as_int(combined.get("total_llm_calls"))
        out["per_node"] = list(src.get("per_node") or [])
        return out

    out["total_tokens_in"] = _as_int(src.get("total_tokens_in"))
    out["total_tokens_out"] = _as_int(src.get("total_tokens_out"))
    out["total_tokens"] = _as_int(src.get("total_tokens"))
    out["total_llm_calls"] = _as_int(src.get("total_llm_calls"))
    out["by_operation"] = dict(src.get("by_operation") or {})
    if src.get("per_node"):
        out["per_node"] = list(src.get("per_node") or [])
    return out


def _merge_groq(dst: Dict[str, Any], src: Optional[Dict[str, Any]]) -> None:
    norm = _normalize_groq(src)
    for key in _GROQ_KEYS:
        dst[key] = _as_int(dst.get(key)) + _as_int(norm.get(key))
    dst_ops = dst.setdefault("by_operation", {})
    for name, stats in (norm.get("by_operation") or {}).items():
        if not isinstance(stats, dict):
            continue
        entry = dst_ops.setdefault(
            name, {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0}
        )
        for field in ("llm_calls", "tokens_in", "tokens_out", "total_tokens"):
            entry[field] = _as_int(entry.get(field)) + _as_int(stats.get(field))
    if norm.get("per_node"):
        dst.setdefault("per_node", []).extend(norm["per_node"])


def _tool_service(tool_name: str) -> str:
    if tool_name.startswith("qualifier."):
        return "qualifier"
    if tool_name.startswith("sourcer."):
        return "sourcer"
    return "other"


class UsageReportBuilder:
    """Accumulates per-tool usage and builds the consolidated campaign report."""

    def __init__(self, campaign_id: str, qualifier_campaign_id: Optional[str] = None):
        self.campaign_id = campaign_id
        self.qualifier_campaign_id = qualifier_campaign_id
        self.tools: Dict[str, Dict[str, Any]] = {}

    def set_qualifier_campaign_id(self, qualifier_campaign_id: str) -> None:
        self.qualifier_campaign_id = qualifier_campaign_id

    def record(self, tool_name: str, usage: Optional[Dict[str, Any]]) -> None:
        if not tool_name:
            return
        if not isinstance(usage, dict):
            usage = {}

        # Qualifier returns usage_summary directly; sourcer returns build_tool_usage.
        if "apollo" in usage or "gemini" in usage or "groq" in usage:
            apollo = usage.get("apollo")
            gemini = usage.get("gemini")
            groq = usage.get("groq")
        else:
            apollo = None
            gemini = None
            groq = usage if usage else None

        entry = {
            "tool": tool_name,
            "apollo": dict(apollo) if isinstance(apollo, dict) else _empty_apollo(),
            "gemini": dict(gemini) if isinstance(gemini, dict) else _empty_gemini(),
            "groq": _normalize_groq(groq),
        }
        if isinstance(usage.get("extra"), dict):
            entry["extra"] = usage["extra"]
        self.tools[tool_name] = entry

    def build(self) -> Dict[str, Any]:
        apollo_total = _empty_apollo()
        gemini_total = _empty_gemini()
        groq_total = _empty_groq()
        groq_by_service = {
            "sourcer": _empty_groq(),
            "qualifier": _empty_groq(),
        }

        for tool_name, entry in self.tools.items():
            _merge_apollo(apollo_total, entry.get("apollo"))
            _merge_gemini(gemini_total, entry.get("gemini"))
            _merge_groq(groq_total, entry.get("groq"))
            service = _tool_service(tool_name)
            if service in groq_by_service:
                _merge_groq(groq_by_service[service], entry.get("groq"))

        groq_total["by_service"] = groq_by_service

        return {
            "campaign_id": self.campaign_id,
            "qualifier_campaign_id": self.qualifier_campaign_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tools": self.tools,
            "totals": {
                "apollo": apollo_total,
                "gemini": gemini_total,
                "groq": groq_total,
            },
        }

    def write(self, output_dir: Optional[str] = None) -> Path:
        report = self.build()
        base = Path(output_dir) if output_dir else settings.resolve_path(settings.database_path).parent / "usage_reports"
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{self.campaign_id}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        logger.info(
            "usage report written campaign_id=%s path=%s groq_total=%s",
            self.campaign_id,
            path,
            report["totals"]["groq"].get("total_tokens"),
        )
        return path


def extract_usage(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        usage = payload.get("usage")
        return usage if isinstance(usage, dict) else None
    return None
