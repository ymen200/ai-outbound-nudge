"""
Resolve / create a Unipile LinkedIn account_id.

Priority:
  1. UNIPILE_ACCOUNT_ID from env (if set)
  2. First existing LINKEDIN account on the Unipile workspace
  3. Create a new account via cookie auth (li_at → access_token)

Docs: https://developer.unipile.com/docs/linkedin
     https://developer.unipile.com/reference/accountscontroller_createaccount
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

import requests

import config

_lock = threading.Lock()
_cached_account_id: Optional[str] = None

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _dsn() -> str:
    return (config.UNIPILE_DSN or "").strip().rstrip("/")


def _api_key() -> str:
    return (config.UNIPILE_API_KEY or "").strip()


def _headers() -> Dict[str, str]:
    return {
        "X-API-KEY": _api_key(),
        "accept": "application/json",
        "content-type": "application/json",
    }


def _optional_env(name: str) -> Optional[str]:
    value = getattr(config, name, None)
    if value is None:
        # Lazy optional keys may not be on the module yet — read via optional_env.
        value = config.optional_env(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def list_linkedin_accounts() -> list:
    """Return LinkedIn accounts already connected on this Unipile workspace."""
    url = f"{_dsn()}/api/v1/accounts"
    res = requests.get(url, headers=_headers(), timeout=30)
    if res.status_code != 200:
        print(f"[Unipile] ⚠️ Liste accounts échouée ({res.status_code}): {res.text[:300]}")
        return []
    items = (res.json() or {}).get("items") or []
    linkedin = []
    for item in items:
        account_type = str(item.get("type") or item.get("provider") or "").upper()
        if "LINKEDIN" in account_type or account_type == "LINKEDIN":
            linkedin.append(item)
    return linkedin


def create_linkedin_account_from_cookie(
    *,
    li_at: str,
    li_a: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    POST /api/v1/accounts with LinkedIn cookie auth.
    access_token = li_at cookie value.
    """
    payload: Dict[str, Any] = {
        "provider": "LINKEDIN",
        "access_token": li_at.strip(),
        "user_agent": (user_agent or DEFAULT_USER_AGENT).strip(),
    }
    if li_a:
        payload["premium_token"] = li_a.strip()

    url = f"{_dsn()}/api/v1/accounts"
    print("[Unipile] Création du compte LinkedIn via cookie li_at...")
    res = requests.post(url, headers=_headers(), json=payload, timeout=60)
    data = {}
    try:
        data = res.json() if res.content else {}
    except Exception:
        data = {"raw": res.text}

    if res.status_code in (200, 201):
        account_id = (
            data.get("account_id")
            or data.get("id")
            or (data.get("account") or {}).get("id")
        )
        if not account_id:
            raise RuntimeError(
                f"Compte Unipile créé mais account_id introuvable dans la réponse: {data}"
            )
        print(f"[Unipile] ✅ Compte LinkedIn connecté — account_id={account_id}")
        return str(account_id)

    if res.status_code == 202:
        account_id = data.get("account_id") or data.get("id")
        checkpoint = data.get("checkpoint") or {}
        raise RuntimeError(
            "Unipile demande un checkpoint (2FA/OTP/IN_APP_VALIDATION) pour finaliser "
            f"la connexion LinkedIn. account_id={account_id}, checkpoint={checkpoint}. "
            "Résous le checkpoint via POST /api/v1/accounts/checkpoint puis "
            "renseigne UNIPILE_ACCOUNT_ID dans .env."
        )

    raise RuntimeError(
        f"Échec création compte Unipile LinkedIn ({res.status_code}): {data or res.text}"
    )


def ensure_unipile_account_id(*, force_refresh: bool = False) -> str:
    """
    Resolve a usable Unipile LinkedIn account_id for persona post scraping.
    Caches the result for the process lifetime.
    """
    global _cached_account_id
    with _lock:
        if _cached_account_id and not force_refresh:
            return _cached_account_id

        configured = _optional_env("UNIPILE_ACCOUNT_ID")
        if configured:
            _cached_account_id = configured
            print(f"[Unipile] Utilisation UNIPILE_ACCOUNT_ID={configured}")
            return configured

        # Prefer an already-connected LinkedIn account when present.
        try:
            existing = list_linkedin_accounts()
            if existing:
                account_id = str(existing[0].get("id") or "").strip()
                if account_id:
                    _cached_account_id = account_id
                    print(
                        f"[Unipile] Réutilisation du compte LinkedIn existant "
                        f"account_id={account_id} "
                        f"(ajoute UNIPILE_ACCOUNT_ID={account_id} dans .env pour fixer)"
                    )
                    return account_id
        except Exception as exc:
            print(f"[Unipile] ⚠️ Impossible de lister les comptes: {exc}")

        li_at = _optional_env("UNIPILE_LI_AT")
        if not li_at:
            raise RuntimeError(
                "Aucun UNIPILE_ACCOUNT_ID et aucun UNIPILE_LI_AT. "
                "Ajoute le cookie LinkedIn li_at dans .env (UNIPILE_LI_AT=...) "
                "pour créer le compte via POST /api/v1/accounts."
            )

        account_id = create_linkedin_account_from_cookie(
            li_at=li_at,
            li_a=_optional_env("UNIPILE_LI_A"),
            user_agent=_optional_env("UNIPILE_USER_AGENT"),
        )
        _cached_account_id = account_id
        print(
            f"[Unipile] Astuce: ajoute UNIPILE_ACCOUNT_ID={account_id} dans .env "
            "pour éviter de recréer le compte à chaque démarrage."
        )
        return account_id
