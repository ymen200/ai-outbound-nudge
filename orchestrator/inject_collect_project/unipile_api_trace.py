import os
import json
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

TRACE_ROOT = "unipile_persona_traces"


def _get_scope_dirs() -> Tuple[str, str]:
    return os.path.join(TRACE_ROOT, "tokens"), os.path.join(TRACE_ROOT, "responses")


def ensure_trace_dirs() -> None:
    tokens_dir, responses_dir = _get_scope_dirs()
    os.makedirs(tokens_dir, exist_ok=True)
    os.makedirs(responses_dir, exist_ok=True)


def _safe_identifier(value: str) -> str:
    return str(value or "unknown").replace("/", "_").replace(".", "_").replace(" ", "_")


def build_trace_path(
    category: str,
    operation: str,
    identifier: str,
    suffix: str,
) -> str:
    ensure_trace_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{operation}_{_safe_identifier(identifier)}_{timestamp}_{suffix}.json"
    tokens_dir, responses_dir = _get_scope_dirs()
    base_dir = tokens_dir if category == "tokens" else responses_dir
    return os.path.join(base_dir, filename)


def save_trace_json(
    category: str,
    operation: str,
    identifier: str,
    suffix: str,
    data: Any,
) -> Optional[str]:
    path = build_trace_path(category, operation, identifier, suffix)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Trace Unipile sauvegardée : {path}")
        return path
    except IOError as e:
        print(f"❌ Erreur sauvegarde trace Unipile : {e}")
        return None


def _unipile_headers(api_key: str) -> Dict[str, str]:
    return {
        "X-API-KEY": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }


def _extract_rate_limit_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not headers:
        return {}
    return {
        key: value
        for key, value in headers.items()
        if any(token in key.lower() for token in ("rate", "limit", "retry"))
    }


class UnipileApiTracker:
    """Suit les appels API Unipile effectués pendant une session."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def record(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        headers: Optional[Dict[str, str]] = None,
        success: bool = True,
    ) -> None:
        self.calls.append(
            {
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "success": success,
                "timestamp": datetime.now().isoformat(),
                "rate_limit_headers": _extract_rate_limit_headers(headers),
            }
        )

    def compute_session_consumption(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        endpoints: Dict[str, int] = {}
        for call in self.calls:
            key = f"{call['method']} {call['endpoint']}"
            endpoints[key] = endpoints.get(key, 0) + 1

        consumption = {
            "api_calls_consumed": len(self.calls),
            "successful_calls": sum(1 for call in self.calls if call["success"]),
            "failed_calls": sum(1 for call in self.calls if not call["success"]),
            "endpoints": endpoints,
            "calls_detail": self.calls,
        }
        if extra:
            consumption.update(extra)
        return consumption


def build_token_report(
    api_key: str,
    dsn: str,
    account_id: str,
    session_diff: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    report_data: Dict[str, Any] = {
        "account_snapshot": {},
        "connected_accounts": {},
    }
    if session_diff:
        report_data["session_consumption"] = session_diff

    headers = _unipile_headers(api_key)

    try:
        account_res = requests.get(
            f"{dsn}/api/v1/accounts/{account_id}",
            headers=headers,
            timeout=30,
        )
        if account_res.status_code == 200:
            account_data = account_res.json()
            report_data["account_snapshot"] = {
                "id": account_data.get("id"),
                "name": account_data.get("name"),
                "type": account_data.get("type"),
                "created_at": account_data.get("created_at"),
                "sources": account_data.get("sources", []),
            }
        else:
            report_data["account_snapshot"] = {
                "status": "error",
                "code": account_res.status_code,
            }
    except Exception as e:
        report_data["account_snapshot"] = {"status": "error", "message": str(e)}

    try:
        accounts_res = requests.get(
            f"{dsn}/api/v1/accounts",
            headers=headers,
            timeout=30,
        )
        if accounts_res.status_code == 200:
            items = accounts_res.json().get("items", [])
            types: Dict[str, int] = {}
            for item in items:
                account_type = item.get("type", "unknown")
                types[account_type] = types.get(account_type, 0) + 1
            report_data["connected_accounts"] = {
                "count": len(items),
                "types": types,
            }
        else:
            report_data["connected_accounts"] = {
                "status": "error",
                "code": accounts_res.status_code,
            }
    except Exception as e:
        report_data["connected_accounts"] = {"status": "error", "message": str(e)}

    return report_data


def save_token_report(
    operation: str,
    identifier: str,
    suffix: str,
    api_key: str,
    dsn: str,
    account_id: str,
    session_diff: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    report_data = build_token_report(api_key, dsn, account_id, session_diff)
    path = build_trace_path("tokens", operation, identifier, suffix)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Rapport tokens Unipile sauvegardé : {path}")
        return report_data, path
    except IOError as e:
        print(f"❌ Erreur sauvegarde rapport tokens Unipile : {e}")
        return report_data, None


def compute_session_consumption(tracker: UnipileApiTracker, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return tracker.compute_session_consumption(extra=extra)
