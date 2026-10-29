"""
Client LLM unifie : Token Factory ESPRIT avec fallback Groq.

Au premier usage (demarrage du projet), une requete LLM simple teste ESPRIT
dans un delai court (~10s). Si elle echoue ou timeout, tous les appels
passent automatiquement sur Groq pour le reste de la session.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, Optional

import httpx
from openai import OpenAI

import config

ESPRIT_BASE_URL = "https://tokenfactory.esprit.tn/api"
ESPRIT_MODEL = "hosted_vllm/Llama-3.1-70B-Instruct"
HEALTHCHECK_PROMPT = "Reply with exactly: OK"


class _ModelForcedCompletions:
    """Force le modele du provider actif, quel que soit l'argument passe par l'appelant."""

    def __init__(self, client: Any, model: str, provider: str, operation: str = "llm"):
        self._client = client
        self._model = model
        self._provider = provider
        self._operation = operation

    def create(self, *args, **kwargs):
        kwargs["model"] = self._model
        response = self._client.chat.completions.create(*args, **kwargs)
        if self._provider == "groq":
            try:
                from run_usage import record_groq_usage

                usage = getattr(response, "usage", None)
                record_groq_usage(
                    tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
                    tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
                    operation=self._operation,
                )
            except Exception:
                pass
        return response


class LlmRouter:
    """Proxy OpenAI-compatible : meme surface API, provider choisi au demarrage."""

    def __init__(self, client: Any, model: str, provider: str):
        self._client = client
        self.model = model
        self.provider = provider
        self.chat = SimpleNamespace(
            completions=_ModelForcedCompletions(client, model, provider)
        )


_lock = threading.Lock()
_router: Optional[LlmRouter] = None


def _build_esprit_client(timeout_seconds: float) -> OpenAI:
    http_client = httpx.Client(
        verify=False,
        timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
    )
    return OpenAI(
        api_key=config.ESPRIT_TOKEN_FACTORY_KEY,
        base_url=ESPRIT_BASE_URL,
        http_client=http_client,
        timeout=timeout_seconds,
    )


def _build_groq_client() -> Any:
    from groq import Groq

    api_key = config.GROQ_API_KEY
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY manquante dans le fichier .env (necessaire pour le fallback)."
        )
    return Groq(api_key=api_key)


def _runtime_timeout() -> float:
    raw = config.optional_env("REQUEST_TIMEOUT", default="120") or "120"
    try:
        return float(raw)
    except ValueError:
        return 120.0


def _probe_esprit(timeout_seconds: float) -> bool:
    """Requete LLM minimale pour verifier qu'ESPRIT repond a temps."""
    print(
        f"[LLM] Health-check ESPRIT Token Factory "
        f"(timeout {timeout_seconds:.0f}s)...",
        flush=True,
    )
    started = time.monotonic()
    try:
        client = _build_esprit_client(timeout_seconds)
        response = client.chat.completions.create(
            model=ESPRIT_MODEL,
            messages=[
                {"role": "system", "content": "You are a connectivity probe. Reply briefly."},
                {"role": "user", "content": HEALTHCHECK_PROMPT},
            ],
            temperature=0,
            max_tokens=5,
        )
        content = (response.choices[0].message.content or "").strip()
        elapsed = time.monotonic() - started
        print(
            f"[LLM] ESPRIT OK en {elapsed:.1f}s (reponse: {content[:40]!r}). "
            f"Provider actif: esprit",
            flush=True,
        )
        return True
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(
            f"[LLM] ESPRIT indisponible apres {elapsed:.1f}s "
            f"({type(exc).__name__}: {exc}). Fallback Groq.",
            flush=True,
        )
        return False


def _resolve_provider() -> LlmRouter:
    forced = (config.LLM_PROVIDER or "auto").strip().lower()
    timeout_seconds = float(config.ESPRIT_HEALTHCHECK_TIMEOUT)
    groq_model = config.GROQ_MODEL

    if forced == "groq":
        print("[LLM] LLM_PROVIDER=groq -> utilisation forcee de Groq.", flush=True)
        return LlmRouter(_build_groq_client(), groq_model, "groq")

    if forced == "esprit":
        print("[LLM] LLM_PROVIDER=esprit -> utilisation forcee d'ESPRIT.", flush=True)
        return LlmRouter(_build_esprit_client(_runtime_timeout()), ESPRIT_MODEL, "esprit")

    # auto
    if _probe_esprit(timeout_seconds):
        return LlmRouter(_build_esprit_client(_runtime_timeout()), ESPRIT_MODEL, "esprit")

    print(f"[LLM] Provider actif: groq (modele {groq_model})", flush=True)
    return LlmRouter(_build_groq_client(), groq_model, "groq")


def ensure_llm_ready() -> LlmRouter:
    """Initialise une seule fois le provider (thread-safe)."""
    global _router
    if _router is not None:
        return _router
    with _lock:
        if _router is None:
            _router = _resolve_provider()
    return _router


def get_llm_client() -> LlmRouter:
    """Retourne le client LLM route (ESPRIT ou Groq)."""
    return ensure_llm_ready()


def get_llm_model() -> str:
    """Retourne le nom de modele du provider actif."""
    return ensure_llm_ready().model


def get_llm_provider() -> str:
    """Retourne 'esprit' ou 'groq'."""
    return ensure_llm_ready().provider
