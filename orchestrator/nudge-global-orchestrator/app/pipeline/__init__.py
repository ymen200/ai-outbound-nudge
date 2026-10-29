from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.config import settings
from app.domain import (
    build_final_packages,
    icp_filters_to_sourcer_args,
    limit_companies_for_persona_fetch,
    select_best_persona,
    to_qualifier_company,
)
from app.mcp_clients import QualifierClient, SourcerClient
from app.pipeline.mock_data import mock_phase_a
from app.pipeline.outreach import start_outreach_for_campaign
from app.store import CampaignStage, store
from app.usage_report import UsageReportBuilder, extract_usage

logger = logging.getLogger(__name__)


class PhaseAPipeline:
    """
    Phase A orchestration:

      1. Qualifier: extract ICP features
      2. Persist raw ICP + features
      3. Sourcer: fetch companies (4 filters)
      4. Qualifier: rank companies (firmographic)
      5. Sourcer: fetch intent for selected companies
      6. Qualifier: rescore with intent
      7. Sourcer: fetch personas + signals
      8. Qualifier: rank personas
      9. Pick single best lead (company score + persona score)
     10. Sourcer: enrich email/phone for winner only
     11. Structure FinalLeadPackage (single lead)
    """

    def __init__(
        self,
        qualifier: Optional[QualifierClient] = None,
        sourcer: Optional[SourcerClient] = None,
    ):
        self.qualifier = qualifier or QualifierClient()
        self.sourcer = sourcer or SourcerClient()

    async def run(
        self,
        *,
        orchestrator_campaign_id: str,
        user_id: str,
        icp_description_text: str,
        user_offering: str,
        blacklist: Optional[Dict[str, List[str]]] = None,
        configurable_weights: Optional[Dict[str, float]] = None,
        company_limit: Optional[int] = None,
        auto_approve_all: bool = True,
        auto_start_outreach: bool = False,
    ) -> Dict[str, Any]:
        if settings.orchestrator_mock:
            logger.info(
                "[%s] mock mode — skipping live MCP", orchestrator_campaign_id
            )
            return await mock_phase_a(
                orchestrator_campaign_id=orchestrator_campaign_id,
                user_id=user_id,
                icp_description_text=icp_description_text,
                user_offering=user_offering,
            )

        usage_report = UsageReportBuilder(orchestrator_campaign_id)

        def _finalize_usage_report() -> None:
            try:
                path = usage_report.write()
                report_payload = usage_report.build()
                report_payload["report_path"] = str(path)
                store.save_artifact(
                    orchestrator_campaign_id, "usage_report", report_payload
                )
                store.save_token_usage_report(orchestrator_campaign_id, report_payload)
            except Exception:
                logger.exception(
                    "[%s] failed to write usage report", orchestrator_campaign_id
                )

        try:
            logger.info(
                "[%s] Phase A start user=%s", orchestrator_campaign_id, user_id
            )

            # ── 1. ICP extract ────────────────────────────────────────────
            logger.info("[%s] stage=icp_extract", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.ICP_EXTRACT)
            # Env defaults for blacklist + scoring weights; caller overrides win.
            blacklist_from_request = blacklist is not None
            weights_from_request = bool(configurable_weights)
            resolved_blacklist = (
                blacklist if blacklist_from_request else settings.default_blacklist()
            )
            weights = settings.default_configurable_weights()
            weights.update(configurable_weights or {})

            bl_companies = list(resolved_blacklist.get("companies") or [])
            bl_personas = list(resolved_blacklist.get("personas") or [])
            logger.info(
                "[%s] blacklist source=%s companies=%d personas=%d",
                orchestrator_campaign_id,
                "request" if blacklist_from_request else "env",
                len(bl_companies),
                len(bl_personas),
            )
            if bl_companies:
                logger.info(
                    "[%s] blacklist companies (regex)=%s",
                    orchestrator_campaign_id,
                    bl_companies,
                )
            if bl_personas:
                logger.info(
                    "[%s] blacklist personas (linkedin_url)=%s",
                    orchestrator_campaign_id,
                    bl_personas,
                )
            store.save_blacklist_entries(
                user_id,
                {"companies": bl_companies, "personas": bl_personas},
            )
            logger.info(
                "[%s] configurable_weights source=%s (env defaults%s)",
                orchestrator_campaign_id,
                "request+env" if weights_from_request else "env",
                " + request overrides" if weights_from_request else "",
            )
            logger.info(
                "[%s] firmographic weights industry=%.3f size=%.3f revenue=%.3f "
                "tech_stack=%.3f firmographic=%.3f intent=%.3f max_km_radius=%.1f",
                orchestrator_campaign_id,
                weights.get("industry_weight", 0.0),
                weights.get("size_weight", 0.0),
                weights.get("revenue_weight", 0.0),
                weights.get("tech_stack_weight", 0.0),
                weights.get("firmographic_weight", 0.0),
                weights.get("intent_weight", 0.0),
                weights.get("max_km_radius", 0.0),
            )
            logger.info(
                "[%s] persona weights fit=%.3f reachability=%.3f timing=%.3f "
                "functional=%.3f authority=%.3f primary_role_match=%.1f "
                "startup_fallback=%.1f partial_title=%.1f engagement=%.1f "
                "verified_email=%.1f risky_email=%.1f",
                orchestrator_campaign_id,
                weights.get("fit_weight", 0.0),
                weights.get("reachability_weight", 0.0),
                weights.get("timing_weight", 0.0),
                weights.get("functional_weight", 0.0),
                weights.get("authority_weight", 0.0),
                weights.get("primary_role_match", 0.0),
                weights.get("startup_fallback_match", 0.0),
                weights.get("partial_title_match", 0.0),
                weights.get("engagement_weight", 0.0),
                weights.get("verified_email_bonus", 0.0),
                weights.get("risky_email_bonus", 0.0),
            )
            if weights_from_request:
                logger.info(
                    "[%s] weight overrides from request=%s",
                    orchestrator_campaign_id,
                    dict(configurable_weights or {}),
                )
            store.upsert_campaign_weights(user_id, weights)

            start = await self.qualifier.start_campaign(
                user_id=user_id,
                icp_description_text=icp_description_text,
                user_offering=user_offering,
                blacklist=resolved_blacklist,
                configurable_weights=weights,
            )
            usage_report.record("qualifier.start_campaign", extract_usage(start))
            if start.get("error"):
                raise RuntimeError(f"ICP extract failed: {start['error']}")

            qualifier_campaign_id = start["campaign_id"]
            usage_report.set_qualifier_campaign_id(qualifier_campaign_id)
            icp_filters = start.get("icp_filters") or {}
            store.save_artifact(orchestrator_campaign_id, "icp_extract", start)
            logger.info(
                "[%s] ICP extracted qualifier_campaign_id=%s industries=%s countries=%s roles=%s",
                orchestrator_campaign_id,
                qualifier_campaign_id,
                icp_filters.get("industries"),
                icp_filters.get("target_countries"),
                icp_filters.get("target_roles"),
            )

            # ── 2. Persist raw ICP + features ─────────────────────────────
            logger.info("[%s] stage=icp_persisted", orchestrator_campaign_id)
            store.update_stage(
                orchestrator_campaign_id,
                CampaignStage.ICP_PERSISTED,
                qualifier_campaign_id=qualifier_campaign_id,
                icp_features=icp_filters,
            )
            store.save_artifact(
                orchestrator_campaign_id,
                "icp_persisted",
                {"raw_icp": icp_description_text, "features": icp_filters},
            )
            store.upsert_campaign_inputs(
                user_id,
                icp_description_text,
                user_offering,
                {
                    "industries": icp_filters.get("industries") or [],
                    "target_countries": icp_filters.get("target_countries") or [],
                    "target_continents": icp_filters.get("target_continents") or [],
                    "target_roles": icp_filters.get("target_roles") or [],
                    "company_size": icp_filters.get("company_size") or {},
                    "revenue_range": icp_filters.get("revenue_range") or {},
                    "tech_stack": icp_filters.get("tech_stack") or [],
                    "growth_stage": icp_filters.get("growth_stage"),
                    "funding_stage": icp_filters.get("funding_stage"),
                    "target_cities": icp_filters.get("target_cities") or [],
                },
            )
            logger.info(
                "[%s] user_campaign_inputs ICP attrs saved industries=%s "
                "revenue=%s tech=%s cities=%s growth=%s funding=%s",
                orchestrator_campaign_id,
                icp_filters.get("industries"),
                icp_filters.get("revenue_range"),
                icp_filters.get("tech_stack"),
                icp_filters.get("target_cities"),
                icp_filters.get("growth_stage"),
                icp_filters.get("funding_stage"),
            )

            # ── 3. Fetch companies ────────────────────────────────────────
            logger.info("[%s] stage=fetch_companies", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_COMPANIES)
            sourcer_args = icp_filters_to_sourcer_args(icp_filters)
            logger.info(
                "[%s] sourcer args industries=%s locations=%s continent=%s "
                "employee_ranges=%s min_employees=%s max_employees=%s limit=%s",
                orchestrator_campaign_id,
                sourcer_args["industries"],
                sourcer_args["locations"],
                sourcer_args["continent"],
                sourcer_args["employee_ranges"],
                sourcer_args.get("min_employees"),
                sourcer_args.get("max_employees"),
                company_limit or settings.company_limit,
            )
            fetch = await self.sourcer.fetch_companies(
                industries=sourcer_args["industries"],
                locations=sourcer_args["locations"] or None,
                continent=sourcer_args["continent"],
                employee_ranges=sourcer_args["employee_ranges"] or None,
                limit=company_limit or settings.company_limit,
                limit_per_element=settings.company_limit_per_element,
                min_employees=sourcer_args.get("min_employees"),
                max_employees=sourcer_args.get("max_employees"),
            )
            usage_report.record("sourcer.fetch_companies", extract_usage(fetch))
            if fetch.get("error"):
                raise RuntimeError(f"Sourcer company fetch failed: {fetch['error']}")

            raw_companies = fetch.get("companies") or []
            store.save_artifact(orchestrator_campaign_id, "fetch_companies", fetch)
            store.save_campaign_companies(orchestrator_campaign_id, raw_companies)
            logger.info(
                "[%s] fetched %d companies",
                orchestrator_campaign_id,
                len(raw_companies),
            )
            if not raw_companies:
                raise RuntimeError("Sourcer returned zero companies.")

            qualifier_companies = [to_qualifier_company(c) for c in raw_companies]

            # ── 4. Rank companies (firmographic, empty intent) ───────────
            logger.info("[%s] stage=rank_companies", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.RANK_COMPANIES)
            ranked = await self.qualifier.resume_with_companies(
                campaign_id=qualifier_campaign_id,
                sourced_companies=qualifier_companies,
            )
            usage_report.record("qualifier.resume_with_companies", extract_usage(ranked))
            if ranked.get("error"):
                raise RuntimeError(f"Company rank failed: {ranked['error']}")
            store.save_artifact(orchestrator_campaign_id, "rank_companies", ranked)

            ranked_companies = list(ranked.get("ranked_companies") or [])
            nurture_companies = list(ranked.get("nurture_companies") or [])
            if not ranked_companies and nurture_companies:
                logger.warning(
                    "[%s] no companies above passing threshold — using %d nurture companies",
                    orchestrator_campaign_id,
                    len(nurture_companies),
                )
                ranked_companies = nurture_companies

            if not ranked_companies:
                disq = ranked.get("disqualification_summary") or {}
                raise RuntimeError(
                    "Company ranking returned zero ranked/nurture companies "
                    f"(disqualification_summary={disq}). "
                    "Scoring likely failed or every company was gated out."
                )

            selected_ids = [
                c["apollo_id"] for c in ranked_companies if c.get("apollo_id")
            ]
            logger.info(
                "[%s] ranked companies=%d selected=%d",
                orchestrator_campaign_id,
                len(ranked_companies),
                len(selected_ids),
            )

            # ── 5. Fetch intent for selected companies ────────────────────
            logger.info("[%s] stage=fetch_intent", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_INTENT)
            target_country = (icp_filters.get("target_countries") or [None])[0]
            intent_resp = await self.sourcer.fetch_intent(
                company_apollo_ids=selected_ids,
                target_country=target_country,
            )
            usage_report.record("sourcer.fetch_intent", extract_usage(intent_resp))
            if intent_resp.get("error"):
                raise RuntimeError(f"Intent fetch failed: {intent_resp['error']}")
            store.save_artifact(orchestrator_campaign_id, "fetch_intent", intent_resp)
            intent_by_apollo_id = intent_resp.get("intent_by_apollo_id") or {}
            logger.info(
                "[%s] intent for %d companies",
                orchestrator_campaign_id,
                len(intent_by_apollo_id),
            )

            # Qualifier rescore: raw signals + synthesized company_intent summary
            intent_payload = {
                apollo_id: {
                    "job_offers": (payload or {}).get("job_offers") or [],
                    "news": (payload or {}).get("news") or [],
                    "company_intent_summary": (payload or {}).get("company_intent_summary") or "",
                }
                for apollo_id, payload in intent_by_apollo_id.items()
            }

            # ── 6. Rescore with intent ────────────────────────────────────
            logger.info("[%s] stage=rescore_intent", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.RESCORE_INTENT)
            rescored = await self.qualifier.rescore_with_intent(
                campaign_id=qualifier_campaign_id,
                intent_by_apollo_id=intent_payload,
            )
            usage_report.record("qualifier.rescore_with_intent", extract_usage(rescored))
            if rescored.get("error"):
                raise RuntimeError(f"Intent rescore failed: {rescored['error']}")
            store.save_artifact(orchestrator_campaign_id, "rescore_intent", rescored)
            ranked_companies = rescored.get("ranked_companies") or ranked_companies

            persona_fetch_limit = (
                settings.companies_for_persona_fetch or settings.company_limit
            )
            companies_for_personas = limit_companies_for_persona_fetch(
                ranked_companies, persona_fetch_limit
            )
            selected_ids = [
                c["apollo_id"] for c in companies_for_personas if c.get("apollo_id")
            ]
            if auto_approve_all and not selected_ids:
                selected_ids = [
                    c["apollo_id"] for c in qualifier_companies if c.get("apollo_id")
                ]
            logger.info(
                "[%s] after intent rescore ranked=%d selected_for_personas=%d (limit=%d)",
                orchestrator_campaign_id,
                len(ranked_companies),
                len(selected_ids),
                persona_fetch_limit,
            )

            # ── 7. Fetch personas + signals ───────────────────────────────
            logger.info("[%s] stage=fetch_personas", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_PERSONAS)
            target_roles = [
                str(r).strip()
                for r in (icp_filters.get("target_roles") or [])
                if str(r).strip()
            ]
            logger.info(
                "[%s] persona search titles (ICP target_roles)=%s",
                orchestrator_campaign_id,
                target_roles or "(fallback: sourcer sales preset)",
            )
            personas_resp = await self.sourcer.fetch_personas_with_signals(
                company_apollo_ids=selected_ids,
                target_country=target_country,
                role=target_roles or None,
                limit=settings.persona_limit,
                limit_per_element=settings.persona_limit_per_element,
            )
            usage_report.record("sourcer.fetch_personas", extract_usage(personas_resp))
            if personas_resp.get("error"):
                raise RuntimeError(f"Persona fetch failed: {personas_resp['error']}")
            store.save_artifact(orchestrator_campaign_id, "fetch_personas", personas_resp)
            personas_by_company = personas_resp.get("sourced_personas_by_company") or {}
            store.save_campaign_personas(
                orchestrator_campaign_id, personas_by_company
            )
            persona_count = sum(len(v) for v in personas_by_company.values())
            logger.info(
                "[%s] personas=%d across %d companies",
                orchestrator_campaign_id,
                persona_count,
                len(personas_by_company),
            )

            # No Apollo personas → skip rank/enrich, still package company + intent.
            if persona_count == 0:
                logger.warning(
                    "[%s] no personas from sourcer — packaging company+intent only",
                    orchestrator_campaign_id,
                )
                approved_ids = selected_ids if auto_approve_all else selected_ids
                approvals_resp = await self.qualifier.resume_with_approvals(
                    campaign_id=qualifier_campaign_id,
                    approved_apollo_ids=approved_ids,
                    sourced_personas_by_company=personas_by_company,
                )
                usage_report.record(
                    "qualifier.resume_with_approvals", extract_usage(approvals_resp)
                )
                packages = build_final_packages(
                    campaign_id=orchestrator_campaign_id,
                    qualifier_campaign_id=qualifier_campaign_id,
                    raw_icp=icp_description_text,
                    user_offering=user_offering,
                    icp_filters=icp_filters,
                    ranked_companies=ranked_companies,
                    intent_by_apollo_id=intent_by_apollo_id,
                    ranked_personas=[],
                    contacts={},
                    personas_by_company=personas_by_company,
                )
                store.save_final_packages(orchestrator_campaign_id, packages)
                store.save_artifact(
                    orchestrator_campaign_id, "final_packages", {"packages": packages}
                )
                store.update_stage(
                    orchestrator_campaign_id,
                    CampaignStage.PACKAGE_READY,
                    status="completed",
                )
                _finalize_usage_report()
                return {
                    "campaign_id": orchestrator_campaign_id,
                    "qualifier_campaign_id": qualifier_campaign_id,
                    "status": "completed",
                    "stage": CampaignStage.PACKAGE_READY.value,
                    "package_count": len(packages),
                    "packages": packages,
                    "usage": usage_report.build(),
                    "warning": "no personas from sourcer",
                }

            # ── 8. Rank personas ──────────────────────────────────────────
            logger.info("[%s] stage=rank_personas", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.RANK_PERSONAS)
            approved_ids = selected_ids if auto_approve_all else selected_ids
            personas_ranked = await self.qualifier.resume_with_approvals(
                campaign_id=qualifier_campaign_id,
                approved_apollo_ids=approved_ids,
                sourced_personas_by_company=personas_by_company,
            )
            usage_report.record(
                "qualifier.resume_with_approvals", extract_usage(personas_ranked)
            )
            if personas_ranked.get("error"):
                raise RuntimeError(f"Persona rank failed: {personas_ranked['error']}")
            store.save_artifact(orchestrator_campaign_id, "rank_personas", personas_ranked)
            ranked_personas = personas_ranked.get("ranked_personas") or []
            logger.info(
                "[%s] ranked personas=%d",
                orchestrator_campaign_id,
                len(ranked_personas),
            )

            winner = select_best_persona(
                ranked_personas,
                ranked_companies,
                personas_by_company,
                company_weight=settings.lead_company_score_weight,
                persona_weight=settings.lead_persona_score_weight,
            )
            if not winner:
                logger.warning(
                    "[%s] no persona selected after ranking — packaging company+intent only",
                    orchestrator_campaign_id,
                )
                packages = build_final_packages(
                    campaign_id=orchestrator_campaign_id,
                    qualifier_campaign_id=qualifier_campaign_id,
                    raw_icp=icp_description_text,
                    user_offering=user_offering,
                    icp_filters=icp_filters,
                    ranked_companies=companies_for_personas,
                    intent_by_apollo_id=intent_by_apollo_id,
                    ranked_personas=[],
                    contacts={},
                    personas_by_company=personas_by_company,
                )
                store.save_final_packages(orchestrator_campaign_id, packages)
                store.save_artifact(
                    orchestrator_campaign_id, "final_packages", {"packages": packages}
                )
                store.update_stage(
                    orchestrator_campaign_id,
                    CampaignStage.PACKAGE_READY,
                    status="completed",
                )
                _finalize_usage_report()
                return {
                    "campaign_id": orchestrator_campaign_id,
                    "qualifier_campaign_id": qualifier_campaign_id,
                    "status": "completed",
                    "stage": CampaignStage.PACKAGE_READY.value,
                    "package_count": len(packages),
                    "packages": packages,
                    "usage": usage_report.build(),
                    "warning": "no persona selected after ranking",
                }

            logger.info(
                "[%s] selected lead persona=%s company=%s combined_score=%s",
                orchestrator_campaign_id,
                winner.get("name"),
                winner.get("company_apollo_id"),
                winner.get("combined_lead_score"),
            )
            store.save_artifact(
                orchestrator_campaign_id,
                "selected_lead",
                {"winner": winner, "candidates_ranked": len(ranked_personas)},
            )

            # ── 9. Enrich contacts (winner only) ──────────────────────────
            logger.info("[%s] stage=enrich_contacts", orchestrator_campaign_id)
            store.update_stage(orchestrator_campaign_id, CampaignStage.ENRICH_CONTACTS)
            winner_id = winner.get("apollo_id")
            contacts: Dict[str, Any] = {}
            if winner_id:
                contacts_resp = await self.sourcer.enrich_contacts(
                    persona_apollo_ids=[str(winner_id)]
                )
                usage_report.record(
                    "sourcer.enrich_contacts", extract_usage(contacts_resp)
                )
                if contacts_resp.get("error"):
                    logger.warning("Contact enrichment error: %s", contacts_resp["error"])
                store.save_artifact(
                    orchestrator_campaign_id, "enrich_contacts", contacts_resp
                )
                contacts = contacts_resp.get("contacts") or {}
                logger.info(
                    "[%s] enriched winner contact id=%s",
                    orchestrator_campaign_id,
                    winner_id,
                )
            else:
                logger.warning("[%s] winner has no apollo_id — skip enrich", orchestrator_campaign_id)
                store.save_artifact(
                    orchestrator_campaign_id,
                    "enrich_contacts",
                    {"contacts": {}, "warning": "winner has no apollo_id"},
                )

            # ── 10. Structure single-lead package ───────────────────────
            logger.info("[%s] stage=package_ready", orchestrator_campaign_id)
            packages = build_final_packages(
                campaign_id=orchestrator_campaign_id,
                qualifier_campaign_id=qualifier_campaign_id,
                raw_icp=icp_description_text,
                user_offering=user_offering,
                icp_filters=icp_filters,
                ranked_companies=ranked_companies,
                intent_by_apollo_id=intent_by_apollo_id,
                ranked_personas=[winner],
                contacts=contacts,
                personas_by_company=personas_by_company,
                single_lead_mode=True,
            )
            store.save_final_packages(orchestrator_campaign_id, packages)
            store.save_artifact(
                orchestrator_campaign_id, "final_packages", {"packages": packages}
            )
            store.update_stage(
                orchestrator_campaign_id,
                CampaignStage.PACKAGE_READY,
                status="completed",
            )
            _finalize_usage_report()
            logger.info(
                "[%s] Phase A completed packages=%d",
                orchestrator_campaign_id,
                len(packages),
            )

            # ── Optional Phase B: auto-start outreach ──────────────────────
            if auto_start_outreach:
                logger.info(
                    "[%s] auto_start_outreach enabled — starting Phase B",
                    orchestrator_campaign_id,
                )
                try:
                    await start_outreach_for_campaign(orchestrator_campaign_id)
                except Exception:
                    logger.exception(
                        "[%s] auto-start outreach failed", orchestrator_campaign_id
                    )

            return {
                "campaign_id": orchestrator_campaign_id,
                "qualifier_campaign_id": qualifier_campaign_id,
                "status": "completed",
                "stage": CampaignStage.PACKAGE_READY.value,
                "package_count": len(packages),
                "packages": packages,
                "usage": usage_report.build(),
            }

        except Exception as exc:
            logger.exception("Phase A failed for %s", orchestrator_campaign_id)
            try:
                _finalize_usage_report()
            except Exception:
                pass
            store.update_stage(
                orchestrator_campaign_id,
                CampaignStage.FAILED,
                status="failed",
                error=str(exc),
            )
            store.save_artifact(
                orchestrator_campaign_id, "error", {"error": str(exc)}
            )
            raise

