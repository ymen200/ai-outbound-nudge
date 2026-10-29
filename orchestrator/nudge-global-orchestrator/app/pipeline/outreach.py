from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.mcp_clients.outreach_client import OutreachClient
from app.store import CampaignStage, store

logger = logging.getLogger(__name__)


async def _register_outreach_send(
    campaign_id: str,
    workflow_id: str,
    email: str,
    linkedin_profile_id: str,
    linkedin_url: str,
    prospect_name: str,
    prospect_company: str,
) -> None:
    """Register prospect identifiers with the Message Generator for Unipile webhook lookup.

    Called after outreach dispatch so that when Unipile fires a webhook
    (reply received, connection accepted), the Message Generator can
    look up the corresponding campaign_id and workflow_id.

    linkedin_profile_id: The Unipile provider/profile ID (e.g., "ACoAAA...").
    linkedin_url: The full LinkedIn profile URL (fallback if profile_id is unknown).
    """
    import httpx
    import asyncio
    try:
        msg_gen_url = settings.message_generator_url.rstrip("/")
        # Retry once if the Msg Gen is temporarily unavailable.
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"{msg_gen_url}/api/unipile/register",
                        json={
                            "campaign_id": campaign_id,
                            "workflow_id": workflow_id,
                            "email": email,
                            "linkedin_profile_id": linkedin_profile_id,
                            "linkedin_url": linkedin_url,
                            "prospect_name": prospect_name,
                            "prospect_company": prospect_company,
                        },
                    )
                break  # Success — no retry needed
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(1)
                else:
                    raise
        logger.info(
            "Registered send: campaign=%s workflow=%s email=%s linkedin=%s",
            campaign_id, workflow_id, email, linkedin_profile_id or linkedin_url,
        )
    except Exception:
        logger.warning(
            "Failed to register send with Message Generator (campaign=%s). "
            "Unipile webhooks may not be routed correctly.",
            campaign_id,
            exc_info=True,
        )


def _to_signal(content: Any, signal_type: str, why_relevant: str) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    text = str(content).strip()
    if not text:
        return None
    return {
        "type": signal_type,
        "content": text,
        "strength": "medium",
        "why_relevant": why_relevant,
    }


def normalize_research_signals(pkg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert persona/company signals from a FinalLeadPackage into Outreach Orchestrator research_signals."""
    signals: List[Dict[str, Any]] = []
    persona = pkg.get("persona") or {}
    company = pkg.get("company") or {}

    # Persona-level signals
    raw_signals = persona.get("signals")
    if isinstance(raw_signals, str) and raw_signals.strip():
        sig = _to_signal(raw_signals, "persona_signal", "Public signal from ranked persona")
        if sig:
            signals.append(sig)
    elif isinstance(raw_signals, dict):
        for key, value in raw_signals.items():
            sig = _to_signal(value, f"persona_{key}", f"Persona signal: {key}")
            if sig:
                signals.append(sig)
    elif isinstance(raw_signals, list):
        for item in raw_signals:
            if isinstance(item, str):
                sig = _to_signal(item, "persona_signal", "Public signal from ranked persona")
                if sig:
                    signals.append(sig)
            elif isinstance(item, dict):
                sig_type = item.get("type") or "persona_signal"
                content = item.get("content") or item.get("summary") or str(item)
                why = item.get("why_relevant") or "Signal from persona data"
                sig = _to_signal(content, sig_type, why)
                if sig:
                    signals.append(sig)

    # Company intent signals
    intent = company.get("intent_signals") or {}
    for job in (intent.get("job_offers") or []):
        if isinstance(job, dict):
            title = job.get("title") or job.get("name") or str(job)
        else:
            title = str(job)
        sig = _to_signal(title, "job_offer", "Company is hiring, indicating growth/budget intent")
        if sig:
            signals.append(sig)

    for news in (intent.get("news") or []):
        if isinstance(news, dict):
            headline = news.get("headline") or news.get("title") or str(news)
        else:
            headline = str(news)
        sig = _to_signal(headline, "news", "Recent company news relevant to outreach timing")
        if sig:
            signals.append(sig)

    summary = company.get("intent_summary")
    if summary:
        sig = _to_signal(summary, "company_intent", "Synthesized company-level intent summary")
        if sig:
            signals.append(sig)

    return signals


def _resolve_str(
    key: str,
    overrides: Dict[str, Any],
    outreach_config: Dict[str, Any],
    default: str,
) -> str:
    """Three-tier string resolution: overrides > campaign outreach_config > env default."""
    return overrides.get(key) or outreach_config.get(key) or default


def _resolve_bool(
    key: str,
    overrides: Dict[str, Any],
    outreach_config: Dict[str, Any],
    default: bool,
) -> bool:
    """Three-tier bool resolution respecting explicit presence (not just truthiness)."""
    if key in overrides:
        return bool(overrides[key])
    if key in outreach_config:
        return bool(outreach_config[key])
    return default


def _resolve_optional(
    key: str,
    overrides: Dict[str, Any],
    outreach_config: Dict[str, Any],
    default: Optional[Any],
) -> Optional[Any]:
    """Three-tier optional resolution (may return None when explicitly set)."""
    if key in overrides:
        return overrides[key]
    if key in outreach_config:
        return outreach_config[key]
    return default


def build_outreach_payload(
    pkg: Dict[str, Any],
    campaign: Dict[str, Any],
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Map a FinalLeadPackage + campaign config to an Outreach Orchestrator MCP payload.

    The payload is a flat dict matching the ``run_outreach_pipeline`` MCP tool schema.
    """
    persona = pkg.get("persona") or {}
    company = pkg.get("company") or {}
    icp = pkg.get("icp") or {}
    outreach_config = campaign.get("outreach_config") or {}
    merged: Dict[str, Any] = dict(overrides) if overrides else {}

    # Resolve per-campaign / per-override config with env defaults as fallback
    sender_company = _resolve_str("sender_company", merged, outreach_config, settings.outreach_default_sender_company)
    sender_elevator_pitch = _resolve_str("sender_elevator_pitch", merged, outreach_config, settings.outreach_default_sender_elevator_pitch)
    offer_name = _resolve_str("offer_name", merged, outreach_config, settings.outreach_default_offer_name)
    solution_summary = _resolve_str("solution_summary", merged, outreach_config, settings.outreach_default_solution_summary)
    cta = _resolve_str("cta", merged, outreach_config, settings.outreach_default_cta)
    approval_mode = _resolve_str("approval_mode", merged, outreach_config, settings.outreach_default_approval_mode)
    use_native_language = _resolve_bool("use_native_language", merged, outreach_config, settings.outreach_default_use_native_language)
    message_language = _resolve_optional("message_language", merged, outreach_config, settings.outreach_default_message_language)
    has_inmail_credits = _resolve_bool("has_inmail_credits", merged, outreach_config, settings.outreach_default_has_inmail_credits)
    debug_mode = _resolve_bool("debug_mode", merged, outreach_config, settings.outreach_default_debug_mode)

    # Fallback solution summary to the campaign offering if nothing else provided
    if not solution_summary:
        solution_summary = campaign.get("user_offering") or icp.get("user_offering") or ""
    if not sender_elevator_pitch:
        sender_elevator_pitch = campaign.get("raw_icp") or icp.get("raw") or ""

    # The Outreach Orchestrator's MCP tool `run_outreach_pipeline` expects a
    # flat argument schema, not the nested REST shape.
    # Ensure no required string fields are sent as None; omit optional nulls.
    lead_id = pkg.get("lead_id") or ""
    campaign_id = pkg.get("campaign_id") or campaign.get("campaign_id") or "default_campaign"

    payload: Dict[str, Any] = {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "entreprise": company.get("name") or "",

        # Flattened contact_info
        "contact_full_name": (persona.get("name") or "Unknown"),
        "contact_job_title": persona.get("title") or "",
        "contact_email": persona.get("email") or "",
        "contact_country": company.get("country") or "",
        "contact_city": company.get("city") or "",
        "contact_linkedin": persona.get("linkedin_url") or "",
        # The Unipile provider/profile ID — needed for webhook matching.
        # Extract from persona data if available; otherwise derived from the URL.
        "contact_linkedin_profile_id": (
            persona.get("linkedin_profile_id")
            or persona.get("linkedin_id")
            or ""
        ),

        # Flattened contexte_web. persona["signals"] may be a str, dict, list,
        # or None depending on the lead package source. Coerce to a string before
        # slicing so the MCP tool always receives a string for web_profil_brut.
        "web_profil_brut": str(persona.get("signals") or persona.get("public_signals") or "")[:2000],
        "web_offer_context": campaign.get("user_offering") or icp.get("user_offering") or "",
        "web_icp_description": campaign.get("raw_icp") or icp.get("raw") or "",

        "research_signals": normalize_research_signals(pkg),
        "is_connected_on_linkedin": bool(persona.get("is_linkedin_connected", False)),
        "has_inmail_credits": bool(has_inmail_credits),
        "use_native_language": bool(use_native_language),
        "approval_mode": approval_mode,
        "sender_company": sender_company,
        "sender_elevator_pitch": sender_elevator_pitch,
        "offer_name": offer_name,
        "solution_summary": solution_summary,
        "cta": cta,
        "debug_mode": bool(debug_mode),
    }

    # Only pass message_language when explicitly set, because the MCP schema
    # expects a string and rejects None.
    if message_language is not None:
        payload["message_language"] = message_language

    # Forward a few optional overrides if the caller provided them
    for optional in ("max_touches", "max_days", "preferred_first_channel", "sequence_options", "stage_instructions", "personality_config", "feedback"):
        if optional in merged:
            payload[optional] = merged[optional]
        elif outreach_config.get(optional) is not None:
            payload[optional] = outreach_config[optional]

    return payload


async def start_outreach_for_campaign(
    campaign_id: str,
    lead_ids: Optional[List[str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Start outreach for one or more lead packages in a campaign.

    If lead_ids is None, all stored final_packages for the campaign are used.
    Returns a list of thread records saved to the DB.
    """
    campaign = store.get_campaign(campaign_id)
    if not campaign:
        raise ValueError(f"Campaign not found: {campaign_id}")

    packages = store.list_packages(campaign_id)
    if not packages:
        raise ValueError(f"No lead packages for campaign {campaign_id}")

    if lead_ids:
        lead_id_set = set(lead_ids)
        packages = [p for p in packages if p["lead_id"] in lead_id_set]
        if not packages:
            raise ValueError(f"No matching lead packages for lead_ids={lead_ids}")

    client = OutreachClient()
    results: List[Dict[str, Any]] = []

    for pkg_record in packages:
        pkg = pkg_record["package"]
        lead_id = pkg_record["lead_id"]
        payload: Optional[Dict[str, Any]] = None

        try:
            payload = build_outreach_payload(pkg, campaign, overrides)
            response = await client.start_outreach(payload)

            status = response.get("status", "unknown")
            thread_id = response.get("thread_id")
            saved = store.save_outreach_thread(
                campaign_id=campaign_id,
                lead_id=lead_id,
                thread_id=thread_id,
                status=status,
                payload={"request": payload, "response": response},
            )
            results.append({
                "thread_db_id": saved,
                "lead_id": lead_id,
                "thread_id": thread_id,
                "status": status,
            })

            # Register with Message Generator for Unipile webhook routing.
            # The temporal_workflow_id may not be available yet if awaiting approval;
            # registration will be updated when the user approves.
            twf_id = response.get("temporal_workflow_id") or ""
            await _register_outreach_send(
                campaign_id=campaign_id,
                workflow_id=twf_id,
                email=payload.get("contact_email", ""),
                linkedin_profile_id=payload.get("contact_linkedin_profile_id", ""),
                linkedin_url=payload.get("contact_linkedin", ""),
                prospect_name=payload.get("contact_full_name", ""),
                prospect_company=payload.get("entreprise", ""),
            )

            if status == "awaiting_approval":
                store.update_stage(
                    campaign_id,
                    CampaignStage.OUTREACH_AWAITING_APPROVAL,
                    status="running",
                )
            elif status == "completed":
                store.update_stage(
                    campaign_id,
                    CampaignStage.OUTREACH_DISPATCHED,
                    status="running",
                )
            else:
                store.update_stage(
                    campaign_id,
                    CampaignStage.OUTREACH_STARTED,
                    status="running",
                )
        except Exception as exc:
            logger.exception("Outreach failed for lead %s in campaign %s", lead_id, campaign_id)
            saved = store.save_outreach_thread(
                campaign_id=campaign_id,
                lead_id=lead_id,
                thread_id=None,
                status="failed",
                payload={"request": payload or {}, "error": str(exc)},
            )
            results.append({
                "thread_db_id": saved,
                "lead_id": lead_id,
                "thread_id": None,
                "status": "failed",
                "error": str(exc),
            })
            store.update_stage(campaign_id, CampaignStage.OUTREACH_FAILED, status="running")

    return results
