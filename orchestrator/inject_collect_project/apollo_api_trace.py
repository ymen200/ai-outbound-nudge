import os
import json
import requests
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

TRACE_ROOTS = {
    "persona": "apollo_persona_traces",
    "company": "apollo_company_traces",
    "intent": "apollo_intent_traces",
}

USER_PROFILE_URL = "https://api.apollo.io/api/v1/users/api_profile"
USAGE_STATS_URL = "https://api.apollo.io/api/v1/usage_stats/api_usage_stats"


def _get_scope_dirs(scope: str) -> Tuple[str, str]:
    root = TRACE_ROOTS.get(scope, TRACE_ROOTS["persona"])
    return os.path.join(root, "tokens"), os.path.join(root, "responses")


def ensure_trace_dirs(scope: str = "persona") -> None:
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
    scope: str = "persona",
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
    scope: str = "persona",
) -> Optional[str]:
    path = build_trace_path(category, operation, identifier, suffix, scope=scope)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Trace Apollo [{scope}] sauvegardée : {path}")
        return path
    except IOError as e:
        print(f"❌ Erreur sauvegarde trace Apollo [{scope}] : {e}")
        return None


def _apollo_headers(api_key: str) -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }


def build_token_report(
    api_key: str,
    session_diff: Optional[Dict[str, Any]] = None,
    rate_limit_keywords: Optional[list] = None,
) -> Dict[str, Any]:
    report_data: Dict[str, Any] = {"monthly_credits": {}, "active_rate_limits": {}}
    if session_diff:
        report_data["session_consumption"] = session_diff

    headers = _apollo_headers(api_key)
    keywords = rate_limit_keywords or ["search", "people", "match", "enrich", "organizations", "news", "job"]

    try:
        user_res = requests.get(
            USER_PROFILE_URL,
            headers=headers,
            params={"include_credit_usage": "true"},
            timeout=30,
        )
        if user_res.status_code == 200:
            user_data = user_res.json()
            report_data["monthly_credits"] = {
                "id": user_data.get("id"),
                "team_id": user_data.get("team_id"),
                "first_name": user_data.get("first_name"),
                "last_name": user_data.get("last_name"),
                "email": user_data.get("email"),
                "num_credits_remaining": user_data.get("num_credits_remaining"),
                "effective_num_lead_credits": user_data.get("effective_num_lead_credits"),
                "num_lead_credits_used": user_data.get("num_lead_credits_used"),
                "effective_num_direct_dial_credits": user_data.get("effective_num_direct_dial_credits"),
                "num_direct_dial_credits_used": user_data.get("num_direct_dial_credits_used"),
                "effective_num_export_credits": user_data.get("effective_num_export_credits"),
                "num_export_credits_used": user_data.get("num_export_credits_used"),
                "effective_num_ai_credits": user_data.get("effective_num_ai_credits"),
                "num_ai_credits_used": user_data.get("num_ai_credits_used"),
                "total_unified_credits_used": user_data.get("total_unified_credits_used"),
            }
    except Exception as e:
        report_data["monthly_credits"] = {"status": "error", "message": str(e)}

    try:
        usage_res = requests.post(USAGE_STATS_URL, headers=headers, json={}, timeout=30)
        if usage_res.status_code == 200:
            usage_data = usage_res.json()
            for key, val in usage_data.items():
                str_key = str(key).lower()
                if any(kw in str_key for kw in keywords) and isinstance(val, dict):
                    report_data["active_rate_limits"][str(key)] = val
    except Exception as e:
        report_data["active_rate_limits"] = {"status": "error", "message": str(e)}

    return report_data


def save_token_report(
    scope: str,
    operation: str,
    identifier: str,
    suffix: str,
    api_key: str,
    session_diff: Optional[Dict[str, Any]] = None,
    rate_limit_keywords: Optional[list] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    report_data = build_token_report(api_key, session_diff, rate_limit_keywords)
    path = build_trace_path("tokens", operation, identifier, suffix, scope=scope)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False, default=str)
        print(f"💾 Rapport tokens Apollo [{scope}] sauvegardé : {path}")
        return report_data, path
    except IOError as e:
        print(f"❌ Erreur sauvegarde rapport tokens [{scope}] : {e}")
        return report_data, None


def compute_session_consumption(api_key: str, initial_report: Dict[str, Any]) -> Dict[str, Any]:
    session_consumption = {
        "lead_credits_consumed": 0,
        "direct_dial_credits_consumed": 0,
        "ai_credits_consumed": 0,
    }
    try:
        headers = _apollo_headers(api_key)
        temp_res = requests.get(
            USER_PROFILE_URL,
            headers=headers,
            params={"include_credit_usage": "true"},
            timeout=30,
        )
        if temp_res.status_code == 200:
            temp_data = temp_res.json()
            init_credits = initial_report.get("monthly_credits", {})
            if init_credits and "num_credits_remaining" in init_credits:
                session_consumption["lead_credits_consumed"] = (
                    init_credits["num_credits_remaining"] - temp_data.get("num_credits_remaining", 0)
                )
                session_consumption["direct_dial_credits_consumed"] = (
                    temp_data.get("num_direct_dial_credits_used", 0)
                    - init_credits.get("num_direct_dial_credits_used", 0)
                )
                session_consumption["ai_credits_consumed"] = (
                    temp_data.get("num_ai_credits_used", 0)
                    - init_credits.get("num_ai_credits_used", 0)
                )
    except Exception:
        pass
    return session_consumption
