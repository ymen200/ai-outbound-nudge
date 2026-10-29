"""
Live / staged MCP smoke checks before a full Phase A run.

Usage (from nudge-global-orchestrator):
    .\\venv\\Scripts\\activate
    # 1) qualifier only
    python scripts/smoke_live.py --step qualifier
    # 2) sourcer only (costs Apollo credits)
    python scripts/smoke_live.py --step sourcer
    # 3) full Phase A with real MCP (slow + paid APIs)
    python scripts/smoke_live.py --step full

Edit ICP_DESCRIPTION_TEXT / USER_OFFERING in .env to change targeting.
Module logs (qualifier logging + sourcer prints) stream on stderr via MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.mcp_clients import QualifierClient, SourcerClient
from app.pipeline import PhaseAPipeline
from app.store import store


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # Child MCP servers already write business logs to stderr; keep root noisy enough
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)


def _as_dict(payload) -> dict:
    """Ensure smoke helpers always work on plain dicts."""
    if payload is None:
        return {}
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if hasattr(payload, "dict"):
        return payload.dict()
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"value": payload}
    return {"value": payload}


def _print(title: str, payload) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    plain = _as_dict(payload) if not isinstance(payload, (dict, list, str, int, float, bool, type(None))) else payload
    if isinstance(plain, (dict, list)):
        text = json.dumps(plain, indent=2, default=str)
        print(text[:4000] + ("..." if len(text) > 4000 else ""))
    else:
        print(plain)


def _icp_preview(text: str, max_len: int = 120) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= max_len:
        return one_line
    return one_line[: max_len - 3] + "..."


async def smoke_qualifier() -> None:
    logger = logging.getLogger("smoke")
    logger.info("Qualifier MCP: %s", settings.qualifier_mcp_path)
    logger.info("Qualifier Python: %s", settings.qualifier_python or "(default)")
    logger.info("ICP preview: %s", _icp_preview(settings.icp_description_text))
    client = QualifierClient()
    result = await client.start_campaign(
        user_id="smoke-live-user",
        icp_description_text=settings.icp_description_text,
        user_offering=settings.user_offering,
    )
    result = _as_dict(result)
    _print("start_campaign result", result)
    if result.get("error"):
        raise SystemExit(f"Qualifier failed: {result['error']}")
    print("\nOK — qualifier ICP extract works.")
    print(f"Keep campaign_id for debugging: {result.get('campaign_id')}")


async def smoke_sourcer() -> None:
    logger = logging.getLogger("smoke")
    logger.info("Sourcer MCP: %s", settings.sourcer_mcp_path)
    logger.info("Sourcer Python: %s", settings.sourcer_python or "(default)")
    print("WARNING: this calls Apollo / Neo4j / scrapers (real cost).")
    print("Watch stderr for sourcer module prints (LeadPulse / Apollo / scraper).")
    client = SourcerClient()
    result = await client.fetch_companies(
        industries=["Insurance"],
        locations=["France"],
        continent=None,
        employee_ranges=["201-500", "501-1000"],
        limit=1,
        limit_per_element=1,
    )
    result = _as_dict(result)
    # Unwrap FastMCP {"result": {...}} if still present
    if "companies" not in result and isinstance(result.get("result"), dict):
        result = result["result"]
    _print("orchestrator_fetch_companies result", result)
    if result.get("error"):
        raise SystemExit(f"Sourcer failed: {result['error']}")
    count = result.get("count")
    if count is None:
        count = len(result.get("companies") or [])
    print(f"\nOK — sourcer returned {count} company(ies).")
    if count == 0:
        print("NOTE: Apollo may have matched 0 orgs for these filters, or enrichment returned empty.")
        print("Try broader industry/location, or inspect apollo_company_traces/")


async def smoke_full() -> None:
    logger = logging.getLogger("smoke")
    if settings.orchestrator_mock:
        raise SystemExit(
            "ORCHESTRATOR_MOCK=true. Set ORCHESTRATOR_MOCK=false in .env for real data."
        )
    logger.info("Starting FULL Phase A with live MCP (can take many minutes)...")
    logger.info(
        "company_limit=%s persona_limit=%s",
        settings.company_limit,
        settings.persona_limit,
    )
    logger.info("ICP preview: %s", _icp_preview(settings.icp_description_text))
    cid = store.create_campaign(
        "smoke-live-user",
        settings.icp_description_text,
        settings.user_offering,
    )
    result = await PhaseAPipeline().run(
        orchestrator_campaign_id=cid,
        user_id="smoke-live-user",
        icp_description_text=settings.icp_description_text,
        user_offering=settings.user_offering,
        company_limit=settings.company_limit,
    )
    _print("Phase A completed", {
        "campaign_id": result["campaign_id"],
        "status": result["status"],
        "stage": result["stage"],
        "package_count": result["package_count"],
        "first_package": (result.get("packages") or [None])[0],
    })
    print(f"\nInspect full state: GET http://localhost:8100/campaigns/{cid}")
    print(f"PostgreSQL: {settings.postgres_db} ({settings.resolved_database_url()})")


async def main() -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(description="Live MCP smoke tests")
    parser.add_argument(
        "--step",
        choices=["qualifier", "sourcer", "full"],
        required=True,
        help="Which smoke check to run",
    )
    args = parser.parse_args()

    print("Config:")
    print(f"  ORCHESTRATOR_MOCK = {settings.orchestrator_mock}")
    print(f"  LOG_LEVEL         = {settings.log_level}")
    print(f"  QUALIFIER_MCP_PATH = {settings.qualifier_mcp_path}")
    print(f"  SOURCER_MCP_PATH   = {settings.sourcer_mcp_path}")
    print(f"  ICP preview        = {_icp_preview(settings.icp_description_text)}")

    if args.step == "qualifier":
        await smoke_qualifier()
    elif args.step == "sourcer":
        await smoke_sourcer()
    else:
        await smoke_full()


if __name__ == "__main__":
    asyncio.run(main())
