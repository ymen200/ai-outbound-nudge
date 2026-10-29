import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

TRACE_ROOTS = {
    "company": "gemini_company_traces",
}


def _get_scope_dirs(scope: str = "company") -> Tuple[str, str]:
    root = TRACE_ROOTS.get(scope, TRACE_ROOTS["company"])
    return os.path.join(root, "tokens"), os.path.join(root, "responses")


def ensure_trace_dirs(scope: str = "company") -> None:
    tokens_dir, responses_dir = _get_scope_dirs(scope)
    os.makedirs(tokens_dir, exist_ok=True)
    os.makedirs(responses_dir, exist_ok=True)


def _safe_identifier(value: str) -> str:
    return str(value or "unknown").replace("/", "_").replace(".", "_").replace(" ", "_")


def build_trace_path(
    category: str,
    operation: str,
    identifier: str,
    suffix: str,
    scope: str = "company",
) -> str:
    ensure_trace_dirs(scope)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{operation}_{_safe_identifier(identifier)}_{timestamp}_{suffix}.json"
    tokens_dir, responses_dir = _get_scope_dirs(scope)
    base_dir = tokens_dir if category == "tokens" else responses_dir
    return os.path.join(base_dir, filename)


def save_trace_json(
    category: str,
    operation: str,
    identifier: str,
    suffix: str,
    data: Any,
    scope: str = "company",
) -> Optional[str]:
    path = build_trace_path(category, operation, identifier, suffix, scope=scope)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Trace Gemini [{scope}] sauvegardée : {path}")
        return path
    except IOError as e:
        print(f"❌ Erreur sauvegarde trace Gemini [{scope}] : {e}")
        return None


def extract_usage_metadata(usage_metadata: Any) -> Dict[str, int]:
    if usage_metadata is None:
        return {}

    if isinstance(usage_metadata, dict):
        return {
            "prompt_token_count": int(usage_metadata.get("prompt_token_count") or 0),
            "candidates_token_count": int(usage_metadata.get("candidates_token_count") or 0),
            "total_token_count": int(usage_metadata.get("total_token_count") or 0),
            "thoughts_token_count": int(usage_metadata.get("thoughts_token_count") or 0),
            "cached_content_token_count": int(usage_metadata.get("cached_content_token_count") or 0),
        }

    return {
        "prompt_token_count": int(getattr(usage_metadata, "prompt_token_count", 0) or 0),
        "candidates_token_count": int(getattr(usage_metadata, "candidates_token_count", 0) or 0),
        "total_token_count": int(getattr(usage_metadata, "total_token_count", 0) or 0),
        "thoughts_token_count": int(getattr(usage_metadata, "thoughts_token_count", 0) or 0),
        "cached_content_token_count": int(getattr(usage_metadata, "cached_content_token_count", 0) or 0),
    }


class GeminiTokenTracker:
    """Suit les appels Gemini et la consommation de tokens pendant une session."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record(
        self,
        model: str,
        level: str,
        operation: str,
        usage_metadata: Any = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        usage = extract_usage_metadata(usage_metadata)
        self.calls.append(
            {
                "model": model,
                "level": level,
                "operation": operation,
                "success": success,
                "error": error,
                "timestamp": datetime.now().isoformat(),
                **usage,
            }
        )

    def compute_session_consumption(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        by_model: Dict[str, Dict[str, int]] = {}
        by_operation: Dict[str, Dict[str, int]] = {}

        totals = {
            "prompt_tokens": 0,
            "candidates_tokens": 0,
            "thoughts_tokens": 0,
            "cached_content_tokens": 0,
            "total_tokens": 0,
        }

        for call in self.calls:
            if not call.get("success"):
                continue

            prompt_tokens = int(call.get("prompt_token_count") or 0)
            candidates_tokens = int(call.get("candidates_token_count") or 0)
            thoughts_tokens = int(call.get("thoughts_token_count") or 0)
            cached_tokens = int(call.get("cached_content_token_count") or 0)
            total_tokens = int(call.get("total_token_count") or 0)

            totals["prompt_tokens"] += prompt_tokens
            totals["candidates_tokens"] += candidates_tokens
            totals["thoughts_tokens"] += thoughts_tokens
            totals["cached_content_tokens"] += cached_tokens
            totals["total_tokens"] += total_tokens

            model_key = str(call.get("model") or "unknown")
            model_stats = by_model.setdefault(
                model_key,
                {"calls": 0, "total_tokens": 0, "prompt_tokens": 0, "candidates_tokens": 0},
            )
            model_stats["calls"] += 1
            model_stats["total_tokens"] += total_tokens
            model_stats["prompt_tokens"] += prompt_tokens
            model_stats["candidates_tokens"] += candidates_tokens

            operation_key = str(call.get("operation") or "unknown")
            operation_stats = by_operation.setdefault(
                operation_key,
                {"calls": 0, "total_tokens": 0, "prompt_tokens": 0, "candidates_tokens": 0},
            )
            operation_stats["calls"] += 1
            operation_stats["total_tokens"] += total_tokens
            operation_stats["prompt_tokens"] += prompt_tokens
            operation_stats["candidates_tokens"] += candidates_tokens

        consumption = {
            "api_calls_consumed": len(self.calls),
            "successful_calls": sum(1 for call in self.calls if call.get("success")),
            "failed_calls": sum(1 for call in self.calls if not call.get("success")),
            **totals,
            "by_model": by_model,
            "by_operation": by_operation,
            "calls_detail": self.calls,
        }
        if extra:
            consumption.update(extra)
        return consumption


def build_token_report(
    pro_models: Optional[List[str]] = None,
    fast_models: Optional[List[str]] = None,
    session_diff: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    report_data: Dict[str, Any] = {
        "provider": "google_gemini",
        "models_config": {
            "pro_models": pro_models or [],
            "fast_models": fast_models or [],
        },
    }
    if session_diff:
        report_data["session_consumption"] = session_diff
    return report_data


def save_token_report(
    scope: str,
    operation: str,
    identifier: str,
    suffix: str,
    pro_models: Optional[List[str]] = None,
    fast_models: Optional[List[str]] = None,
    session_diff: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    report_data = build_token_report(pro_models, fast_models, session_diff)
    path = build_trace_path("tokens", operation, identifier, suffix, scope=scope)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Rapport tokens Gemini [{scope}] sauvegardé : {path}")
        return report_data, path
    except IOError as e:
        print(f"❌ Erreur sauvegarde rapport tokens Gemini [{scope}] : {e}")
        return report_data, None


def compute_session_consumption(
    tracker: GeminiTokenTracker,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return tracker.compute_session_consumption(extra=extra)
