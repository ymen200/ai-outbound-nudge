"""
Per-tool / per-run usage helpers for Apollo credits, Gemini tokens, and Groq tokens.

Used by orchestrator MCP tools so the global orchestrator can build a single
JSON usage report across sourcer + qualifier.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from apollo_api_trace import build_token_report, compute_session_consumption

_lock = threading.Lock()
_groq_totals = {
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "total_tokens": 0,
    "total_llm_calls": 0,
}
_groq_by_operation: Dict[str, Dict[str, int]] = {}
_last_orchestrator_usage: Dict[str, Any] = {}


def empty_apollo_usage() -> Dict[str, Any]:
    return {
        "lead_credits_consumed": 0,
        "direct_dial_credits_consumed": 0,
        "ai_credits_consumed": 0,
    }


def empty_gemini_usage() -> Dict[str, Any]:
    return {
        "api_calls_consumed": 0,
        "successful_calls": 0,
        "failed_calls": 0,
        "prompt_tokens": 0,
        "candidates_tokens": 0,
        "thoughts_tokens": 0,
        "cached_content_tokens": 0,
        "total_tokens": 0,
        "by_model": {},
        "by_operation": {},
    }


def sanitize_gemini_usage(gemini: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Drop bulky call logs; keep aggregate counters for the usage report."""
    if not gemini:
        return empty_gemini_usage()
    cleaned = dict(gemini)
    cleaned.pop("calls_detail", None)
    for key, default in empty_gemini_usage().items():
        cleaned.setdefault(key, default)
    return cleaned


def empty_groq_usage() -> Dict[str, Any]:
    return {
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_tokens": 0,
        "total_llm_calls": 0,
        "by_operation": {},
    }


def record_groq_usage(
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    operation: str = "unknown",
) -> None:
    """Accumulate Groq token usage for the current MCP process."""
    tin = int(tokens_in or 0)
    tout = int(tokens_out or 0)
    with _lock:
        _groq_totals["total_tokens_in"] += tin
        _groq_totals["total_tokens_out"] += tout
        _groq_totals["total_tokens"] += tin + tout
        _groq_totals["total_llm_calls"] += 1
        bucket = _groq_by_operation.setdefault(
            operation or "unknown",
            {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0},
        )
        bucket["llm_calls"] += 1
        bucket["tokens_in"] += tin
        bucket["tokens_out"] += tout
        bucket["total_tokens"] += tin + tout


def get_groq_usage(reset: bool = False) -> Dict[str, Any]:
    with _lock:
        snapshot = {
            "total_tokens_in": _groq_totals["total_tokens_in"],
            "total_tokens_out": _groq_totals["total_tokens_out"],
            "total_tokens": _groq_totals["total_tokens"],
            "total_llm_calls": _groq_totals["total_llm_calls"],
            "by_operation": {
                k: dict(v) for k, v in _groq_by_operation.items()
            },
        }
        if reset:
            _groq_totals["total_tokens_in"] = 0
            _groq_totals["total_tokens_out"] = 0
            _groq_totals["total_tokens"] = 0
            _groq_totals["total_llm_calls"] = 0
            _groq_by_operation.clear()
        return snapshot


def snapshot_apollo(api_key: Optional[str]) -> Dict[str, Any]:
    if not api_key:
        return {"monthly_credits": {}, "active_rate_limits": {}}
    try:
        return build_token_report(api_key)
    except Exception as exc:
        return {"monthly_credits": {"status": "error", "message": str(exc)}}


def apollo_diff(api_key: Optional[str], initial_report: Dict[str, Any]) -> Dict[str, Any]:
    if not api_key:
        return empty_apollo_usage()
    try:
        return compute_session_consumption(api_key, initial_report)
    except Exception:
        return empty_apollo_usage()


def build_tool_usage(
    *,
    tool: str,
    apollo: Optional[Dict[str, Any]] = None,
    gemini: Optional[Dict[str, Any]] = None,
    groq: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tool": tool,
        "apollo": apollo if apollo is not None else empty_apollo_usage(),
        "gemini": sanitize_gemini_usage(gemini),
        "groq": groq if groq is not None else get_groq_usage(reset=True),
    }
    if extra:
        payload["extra"] = extra
    return payload


def usage_from_apollo_window(
    *,
    tool: str,
    api_key: Optional[str],
    initial_report: Dict[str, Any],
    gemini: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a tool usage blob after an Apollo-backed MCP call."""
    return build_tool_usage(
        tool=tool,
        apollo=apollo_diff(api_key, initial_report),
        gemini=gemini,
        groq=get_groq_usage(reset=True),
        extra=extra,
    )


def set_last_orchestrator_usage(usage: Dict[str, Any]) -> None:
    global _last_orchestrator_usage
    with _lock:
        _last_orchestrator_usage = dict(usage or {})


def pop_last_orchestrator_usage() -> Dict[str, Any]:
    global _last_orchestrator_usage
    with _lock:
        usage = dict(_last_orchestrator_usage)
        _last_orchestrator_usage = {}
        return usage
