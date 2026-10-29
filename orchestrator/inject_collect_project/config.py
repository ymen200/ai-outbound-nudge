"""Configuration centralisée chargée depuis le fichier .env."""

import os
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()


def require_env(*names: str) -> str:
    """Retourne la première variable d'environnement définie ou lève une erreur."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    raise ValueError(
        f"Variable d'environnement '{names[0]}' manquante. "
        "Ajoutez-la dans votre fichier .env (voir .env.example)."
    )


def optional_env(*names: str, default: Optional[str] = None) -> Optional[str]:
    """Retourne la première variable définie, ou default si aucune n'est trouvée."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def optional_int_env(name: str, default: int) -> int:
    """Retourne une variable d'environnement entière, ou default si absente ou invalide."""
    value = os.getenv(name)
    if value and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"Variable d'environnement '{name}' invalide : attendu un entier, reçu {value!r}."
            ) from exc
        if parsed <= 0:
            raise ValueError(
                f"Variable d'environnement '{name}' invalide : la valeur doit être > 0."
            )
        return parsed
    return default


def optional_non_negative_int_env(name: str, default: int) -> int:
    """Comme optional_int_env, mais accepte 0 (utile pour heures/minutes)."""
    value = os.getenv(name)
    if value and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"Variable d'environnement '{name}' invalide : attendu un entier, reçu {value!r}."
            ) from exc
        if parsed < 0:
            raise ValueError(
                f"Variable d'environnement '{name}' invalide : la valeur doit être >= 0."
            )
        return parsed
    return default


def optional_bool_env(name: str, default: bool = False) -> bool:
    """Parse true/false/1/0/yes/no depuis l'environnement."""
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(
        f"Variable d'environnement '{name}' invalide : attendu true/false, reçu {value!r}."
    )


MAX_INTENT_SIGNALS_PER_COMPANY = optional_int_env("MAX_INTENT_SIGNALS_PER_COMPANY", 30)
MAX_JOB_AGE_DAYS = optional_int_env("MAX_JOB_AGE_DAYS", 30)
MAX_NEWS_AGE_DAYS = optional_int_env("MAX_NEWS_AGE_DAYS", 180)

# Cron : entreprises dont la version courante a plus de N jours sans mise à jour
CRON_COMPANY_MAX_AGE_DAYS = optional_int_env("CRON_COMPANY_MAX_AGE_DAYS", 7)
CRON_COMPANY_BATCH_LIMIT = optional_int_env("CRON_COMPANY_BATCH_LIMIT", 50)
CRON_PERSONA_LIMIT_PER_COMPANY = optional_int_env("CRON_PERSONA_LIMIT_PER_COMPANY", 10)
CRON_PERSONA_LIMIT_PER_ELEMENT = optional_int_env("CRON_PERSONA_LIMIT_PER_ELEMENT", 3)

# APScheduler : job hebdomadaire (activable via CRON_SCHEDULER_ENABLED)
CRON_SCHEDULER_ENABLED = optional_bool_env("CRON_SCHEDULER_ENABLED", default=False)
CRON_SCHEDULER_DAY = (optional_env("CRON_SCHEDULER_DAY", default="mon") or "mon").strip().lower()
CRON_SCHEDULER_HOUR = optional_non_negative_int_env("CRON_SCHEDULER_HOUR", 3)
CRON_SCHEDULER_MINUTE = optional_non_negative_int_env("CRON_SCHEDULER_MINUTE", 0)


def is_cron_scheduler_enabled() -> bool:
    """Relit le flag d'activation (permet de désactiver sans redéployer le code)."""
    load_dotenv(override=True)
    return optional_bool_env("CRON_SCHEDULER_ENABLED", default=False)

UNIPILE_POSTED_LIMIT = optional_env("UNIPILE_POSTED_LIMIT", default="month").lower()
UNIPILE_TARGET_COUNT = optional_int_env("UNIPILE_TARGET_COUNT", 10)

UNIPILE_POSTS_DAYS_MAP = {"week": 7, "month": 30, "year": 365}

# Optional LinkedIn cookie auth (used when UNIPILE_ACCOUNT_ID is empty)
UNIPILE_LI_AT = optional_env("UNIPILE_LI_AT")
UNIPILE_LI_A = optional_env("UNIPILE_LI_A")
UNIPILE_USER_AGENT = optional_env("UNIPILE_USER_AGENT")
UNIPILE_ACCOUNT_ID = optional_env("UNIPILE_ACCOUNT_ID")


# LLM : auto = health-check ESPRIT puis fallback Groq ; esprit|groq = forcé
LLM_PROVIDER = (optional_env("LLM_PROVIDER", default="auto") or "auto").strip().lower()
ESPRIT_HEALTHCHECK_TIMEOUT = optional_int_env("ESPRIT_HEALTHCHECK_TIMEOUT", 10)
GROQ_API_KEY = optional_env("GROQ_API_KEY")
GROQ_MODEL = optional_env("GROQ_MODEL", default="llama-3.3-70b-versatile") or "llama-3.3-70b-versatile"

# Minimum Neo4j ICP company matches required to skip Apollo organizations/search.
# Example: 2 → one local hit still triggers Apollo to fetch different companies.
LOCAL_COMPANY_MIN_HITS = optional_int_env("LOCAL_COMPANY_MIN_HITS", 2)

# SmartScraperAI: use LangGraph orchestration (true) or legacy while-loop (false).
USE_SCRAPER_GRAPH = optional_bool_env("USE_SCRAPER_GRAPH", default=True)

# Company pipeline: LangGraph per-company enrichment inside request_discover_companies.
USE_COMPANY_GRAPH = optional_bool_env("USE_COMPANY_GRAPH", default=True)

# Contact enrich: LangGraph persona email/phone waterfall (local → sync → waterfall).
USE_CONTACT_GRAPH = optional_bool_env("USE_CONTACT_GRAPH", default=True)


def get_unipile_days_back(posted_limit: Optional[str] = None) -> int:
    """Convertit posted_limit (week|month|year) en nombre de jours."""
    limit = (posted_limit or UNIPILE_POSTED_LIMIT).lower()
    days = UNIPILE_POSTS_DAYS_MAP.get(limit)
    if days is None:
        allowed = ", ".join(sorted(UNIPILE_POSTS_DAYS_MAP))
        raise ValueError(
            f"Variable UNIPILE_POSTED_LIMIT invalide : {limit!r}. "
            f"Valeurs acceptées : {allowed}."
        )
    return days


def get_neo4j_credentials() -> Tuple[str, str, str]:
    """Retourne (uri, user, password) pour Neo4j Aura ou local."""
    use_local = optional_env("USE_LOCAL_NEO4J", default="false").lower() in ("true", "1", "yes")
    if use_local:
        return (
            require_env("LOCAL_NEO4J_URI"),
            require_env("LOCAL_NEO4J_USER"),
            require_env("LOCAL_NEO4J_PASSWORD"),
        )
    return (
        require_env("NEO4J_URI"),
        require_env("NEO4J_USER"),
        require_env("NEO4J_PASSWORD"),
    )


def __getattr__(name: str):
    """Chargement paresseux des variables — erreur uniquement à l'utilisation."""
    if name == "APOLLO_API_KEY":
        return require_env("APOLLO_API_KEY")
    if name == "ESPRIT_TOKEN_FACTORY_KEY":
        return require_env("ESPRIT_TOKEN_FACTORY_KEY", "ESPRIT_LLM_API_KEY")
    if name == "GEMINI_API_KEY":
        return require_env("GEMINI_API_KEY")
    if name == "UNIPILE_API_KEY":
        return require_env("UNIPILE_API_KEY")
    if name == "UNIPILE_DSN":
        return require_env("UNIPILE_DSN").strip().rstrip("/")
    if name == "UNIPILE_ACCOUNT_ID":
        # Optional — resolved via unipile_account.ensure_unipile_account_id() from li_at
        return optional_env("UNIPILE_ACCOUNT_ID")
    if name == "UNIPILE_LI_AT":
        return optional_env("UNIPILE_LI_AT")
    if name == "UNIPILE_LI_A":
        return optional_env("UNIPILE_LI_A")
    if name == "UNIPILE_USER_AGENT":
        return optional_env("UNIPILE_USER_AGENT")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
