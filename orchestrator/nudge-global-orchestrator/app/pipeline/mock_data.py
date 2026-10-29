from __future__ import annotations

from typing import Any, Dict

from app.store import CampaignStage, store


async def mock_phase_a(
    *,
    orchestrator_campaign_id: str,
    user_id: str,
    icp_description_text: str,
    user_offering: str,
) -> Dict[str, Any]:
    """Offline Phase A path for smoke tests without live MCP modules."""

    # ── Rich ICP filters ──────────────────────────────────────────────
    icp_filters = {
        "industries": ["Cybersecurity", "InsurTech", "RegTech", "Financial Services"],
        "target_countries": ["France"],
        "target_continents": ["Europe"],
        "target_roles": [
            "Chief Information Security Officer",
            "VP of Engineering",
            "Head of Compliance",
            "CTO",
            "Director of Risk",
        ],
        "company_size": {"min": 200, "max": 5000},
        "revenue_range": {"min": 50_000_000, "max": 2_000_000_000},
    }

    store.update_stage(orchestrator_campaign_id, CampaignStage.ICP_EXTRACT)
    store.save_artifact(
        orchestrator_campaign_id,
        "icp_extract",
        {"campaign_id": "mock-qualifier-1", "icp_filters": icp_filters},
    )

    store.update_stage(
        orchestrator_campaign_id,
        CampaignStage.ICP_PERSISTED,
        qualifier_campaign_id="mock-qualifier-1",
        icp_features=icp_filters,
    )

    # ── Rich company profile ──────────────────────────────────────────
    companies = [
        {
            "apollo_id": "mock_co_001",
            "name": "CyberShield Assurances SA",
            "domain": "cybershield-assurances.fr",
            "country": "France",
            "city": "Paris",
            "description": (
                "CyberShield is a Paris-based insurtech founded in 2018 that "
                "provides cyber-risk insurance and continuous threat monitoring "
                "for mid-market European enterprises. They serve 400+ corporate "
                "clients across France, Belgium, and Switzerland. In March 2026 "
                "they raised a EUR 60M Series B led by Index Ventures to expand "
                "their AI-driven underwriting platform. They are currently under "
                "regulatory pressure to comply with DORA (Digital Operational "
                "Resilience Act) by the January 2027 deadline."
            ),
            "industry": "InsurTech / Cybersecurity",
            "founded_year": 2018,
            "employee_count": 480,
            "estimated_revenue": "EUR 85M (2025)",
            "headquarters": "Paris, Île-de-France, France",
            "linkedin_url": "https://linkedin.com/company/cybershield-assurances",
            "tech_stack": [
                "AWS (ECS, Lambda, RDS)",
                "Python / FastAPI",
                "React / TypeScript",
                "PostgreSQL",
                "Temporal.io",
                "Kafka",
                "Datadog",
                "GitHub Actions",
            ],
            "qualification_metrics": {
                "firmographic_score": 89,
                "intent_score": 76,
                "total_score": 84.1,
                "tier": "A",
                "breakdown": {
                    "industry_match": 0.95,
                    "size_fit": 0.88,
                    "revenue_fit": 0.82,
                    "tech_stack_alignment": 0.91,
                },
            },
        }
    ]
    store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_COMPANIES)
    store.save_artifact(
        orchestrator_campaign_id, "fetch_companies", {"companies": companies, "count": 1}
    )
    store.update_stage(orchestrator_campaign_id, CampaignStage.RANK_COMPANIES)
    store.save_artifact(
        orchestrator_campaign_id,
        "rank_companies",
        {
            "ranked_companies": companies,
            "scoring_note": (
                "Top-ranked company: strong industry fit (insurtech with cybersecurity "
                "focus), 480 employees in target range, EUR 85M revenue, growing team, "
                "recent Series B funding signals expansion budget, active DORA compliance "
                "hiring indicates urgent regulatory need."
            ),
        },
    )

    # ── Rich intent signals ───────────────────────────────────────────
    intent = {
        "mock_co_001": {
            "job_offers": [
                {
                    "title": "Senior Backend Engineer (Python/FastAPI)",
                    "posted_date": "2026-07-15",
                    "department": "Engineering",
                    "location": "Paris (hybrid)",
                },
                {
                    "title": "DevOps / Platform Engineer",
                    "posted_date": "2026-07-10",
                    "department": "Infrastructure",
                    "location": "Paris (remote-friendly)",
                },
                {
                    "title": "Compliance & Risk Analyst (DORA/NIS2)",
                    "posted_date": "2026-07-20",
                    "department": "Compliance",
                    "location": "Paris",
                },
                {
                    "title": "Enterprise Sales Executive",
                    "posted_date": "2026-06-28",
                    "department": "Sales",
                    "location": "Paris",
                },
            ],
            "news": [
                {
                    "headline": "CyberShield raises EUR 60M to scale AI-powered cyber insurance platform",
                    "published_date": "2026-03-12",
                    "source": "TechCrunch",
                    "url": "https://techcrunch.com/2026/03/12/cybershield-series-b",
                },
                {
                    "headline": "EU's DORA regulation goes into effect — insurers scramble to comply",
                    "published_date": "2026-06-15",
                    "source": "Financial Times",
                },
                {
                    "headline": "CyberShield partners with AXA to offer SME cyber-risk bundles",
                    "published_date": "2026-05-08",
                    "source": "Les Echos",
                },
            ],
            "company_intent_summary": (
                "CyberShield is in active growth mode: post-Series B scaling of "
                "engineering & compliance teams, responding to EU DORA regulatory "
                "deadlines, and expanding enterprise sales. Strong buy-side intent "
                "for DevSecOps tooling, compliance automation, and API security. "
                "The DORA/NIS2 compliance analyst hire (posted July 20) signals "
                "urgent need for regulatory tooling."
            ),
        }
    }
    store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_INTENT)
    store.save_artifact(
        orchestrator_campaign_id, "fetch_intent", {"intent_by_apollo_id": intent}
    )
    store.update_stage(orchestrator_campaign_id, CampaignStage.RESCORE_INTENT)
    store.save_artifact(
        orchestrator_campaign_id,
        "rescore_intent",
        {
            "ranked_companies": companies,
            "intent_boost": (
                "Intent signals added +8 to total score: DORA compliance hiring + "
                "Series B funding + AXA partnership indicate strong budget + urgency."
            ),
        },
    )

    # ── Rich persona ──────────────────────────────────────────────────
    personas_by_company = {
        "mock_co_001": [
            {
                "apollo_id": "mock_persona_001",
                "name": "Sophie Moreau",
                "title": "Chief Information Security Officer (CISO)",
                "seniority": "C-Suite",
                "email": "",
                "phone_number": "",
                "linkedin_url": "https://linkedin.com/in/sophie-moreau-ciso",
                "public_signals": (
                    "Sophie posted last week about CyberShield's DORA compliance "
                    "roadmap, asking her network for recommendations on automated "
                    "risk-assessment platforms. She also engaged with posts about "
                    "API security and third-party vendor risk management. Previously, "
                    "she was Head of Security at BNP Paribas Cardif for 6 years. "
                    "She is the named executive sponsor for CyberShield's DORA "
                    "compliance program and has a EUR 2M budget for tooling in H2 2026."
                ),
                "location": "Paris, France",
                "years_in_role": 2,
                "years_at_company": 3,
            }
        ]
    }
    store.update_stage(orchestrator_campaign_id, CampaignStage.FETCH_PERSONAS)
    store.save_artifact(
        orchestrator_campaign_id,
        "fetch_personas",
        {"sourced_personas_by_company": personas_by_company},
    )

    ranked_personas = [
        {
            "apollo_id": "mock_persona_001",
            "name": "Sophie Moreau",
            "title": "Chief Information Security Officer (CISO)",
            "persona_score": 92,
            "persona_score_breakdown": {
                "fit_score": 0.94,
                "authority_score": 0.97,
                "reachability_score": 0.82,
                "timing_score": 0.91,
                "engagement_signals": 0.89,
            },
            "email": "",
            "phone_number": "",
        }
    ]
    store.update_stage(orchestrator_campaign_id, CampaignStage.RANK_PERSONAS)
    store.save_artifact(
        orchestrator_campaign_id,
        "rank_personas",
        {
            "ranked_personas": ranked_personas,
            "ranking_note": (
                "CISO is the ideal persona: budget authority (EUR 2M tooling budget), "
                "direct DORA compliance responsibility, public signal of active tooling "
                "search, 6 years prior security leadership at a top-3 French bank."
            ),
        },
    )

    contacts = {
        "mock_persona_001": {
            "email_enrichment": {
                "email": "sophie.moreau@cybershield-assurances.fr",
                "status": "success",
                "confidence": "high",
            },
            "phone_enrichment": {
                "phone_number": "+33 1 45 67 89 10",
                "status": "success",
                "confidence": "medium",
            },
        }
    }
    store.update_stage(orchestrator_campaign_id, CampaignStage.ENRICH_CONTACTS)
    store.save_artifact(
        orchestrator_campaign_id, "enrich_contacts", {"contacts": contacts}
    )

    qualifier_campaign_id = "mock-qualifier-1"
    packages = [
        {
            "lead_id": f"{orchestrator_campaign_id}:mock_persona_001",
            "campaign_id": orchestrator_campaign_id,
            "qualifier_campaign_id": qualifier_campaign_id,
            "icp": {
                "raw": icp_description_text,
                "features": icp_filters,
                "user_offering": user_offering,
            },
            "company": {
                "apollo_id": "mock_co_001",
                "name": "CyberShield Assurances SA",
                "domain": "cybershield-assurances.fr",
                "country": "France",
                "city": "Paris",
                "description": companies[0]["description"],
                "industry": "InsurTech / Cybersecurity",
                "size": "480 employees",
                "revenue": "EUR 85M",
                "headquarters": "Paris, France",
                "linkedin_url": "https://linkedin.com/company/cybershield-assurances",
                "qualification_metrics": companies[0]["qualification_metrics"],
                "intent_signals": {
                    "job_offers": intent["mock_co_001"]["job_offers"],
                    "news": intent["mock_co_001"]["news"],
                },
                "intent_summary": intent["mock_co_001"]["company_intent_summary"],
            },
            "persona": {
                "apollo_id": "mock_persona_001",
                "name": "Sophie Moreau",
                "title": "Chief Information Security Officer (CISO)",
                "email": "sophie.moreau@cybershield-assurances.fr",
                "phone": "+33 1 45 67 89 10",
                "persona_score": 92,
                "signals": (
                    "Publicly searching for automated risk-assessment platforms. "
                    "Named executive sponsor for DORA compliance program with EUR 2M "
                    "tooling budget for H2 2026. 6 years prior security leadership at "
                    "BNP Paribas Cardif. Engages with API security & vendor risk content."
                ),
                "linkedin_url": "https://linkedin.com/in/sophie-moreau-ciso",
                "seniority": "C-Suite",
                "years_in_role": 2,
                "years_at_company": 3,
            },
        }
    ]
    store.save_final_packages(orchestrator_campaign_id, packages)
    store.save_artifact(
        orchestrator_campaign_id, "final_packages", {"packages": packages}
    )
    store.update_stage(
        orchestrator_campaign_id,
        CampaignStage.PACKAGE_READY,
        status="completed",
    )

    return {
        "campaign_id": orchestrator_campaign_id,
        "qualifier_campaign_id": qualifier_campaign_id,
        "status": "completed",
        "stage": CampaignStage.PACKAGE_READY.value,
        "package_count": len(packages),
        "packages": packages,
        "user_id": user_id,
    }
