import csv
import os
import json
from apollo_scraper import ApolloScraper
import config
from database_manager import Neo4jManager
from smart_scraper_ai import SmartScraperAI
from persona_search_enrich import search_and_enrich, check_email_pro_llm, resolve_person_titles
from enrich_persona import enrich_person_with_traces
from persona_posts_scraper import PersonaPostScraper
from intent_global_orchestrator import IntentGlobalOrchestrator
from apollo_api_trace import save_token_report, compute_session_consumption
from gemini_api_trace import (
    GeminiTokenTracker,
    save_token_report as save_gemini_token_report,
    compute_session_consumption as compute_gemini_session_consumption,
)
from llm_helpers import (
    COMPANY_FULL_DESCRIPTION,
    COMPANY_INTENT_SUMMARY,
    CONTINENT_COUNTRIES,
    COUNTRY_ALIAS_MATCH,
    INDUSTRY_TAXONOMY_MATCH,
    PERSONA_INTENT_SUMMARY,
    invoke_chat,
    invoke_template,
)
from llm_provider import get_llm_client, get_llm_model
from run_usage import (
    build_tool_usage,
    empty_apollo_usage,
    empty_gemini_usage,
    set_last_orchestrator_usage,
)
from typing import Optional

# --- INITIALISATION DES CLIENTS ET COMPOSANTS ---
llm_client = get_llm_client()
LLM_MODEL = get_llm_model()

scraper = ApolloScraper(config.APOLLO_API_KEY)
ai_scraper = SmartScraperAI() 
post_scraper = PersonaPostScraper()
intent_orchestrator = IntentGlobalOrchestrator()


# =========================================================================
# --- HELPERS DE TEXTE ET D'IA (LangChain prompt templates) ---
# =========================================================================

def call_esprit_llm(prompt: str, system: Optional[str] = None) -> str:
    """Appelle le LLM actif via LangChain message formatting (ESPRIT ou Groq)."""
    system_text = system or (
        "You are a precise B2B data assistant. Follow the user instructions exactly. "
        "Do not add preamble or closing remarks."
    )
    return invoke_chat(
        [
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=400,
        fallback="Non renseigné",
        operation="call_esprit_llm",
    )


def generate_company_intent_summary(company_profile, intent_signals):
    """Génère un résumé concis des signaux d'intention commerciaux."""
    company_name = company_profile.get("name") or "the company"

    if not intent_signals:
        return f"{company_name} currently shows no recent commercial intent signals."

    selected_signals = []
    for item in intent_signals[:8]:
        title = item.get("title") or item.get("title_and_summary") or item.get("headline") or ""
        if title:
            selected_signals.append(title)

    signal_text = " | ".join(selected_signals) if selected_signals else "recent hiring and company updates"

    summary = invoke_template(
        COMPANY_INTENT_SUMMARY,
        company_name=company_name,
        signal_text=signal_text,
        temperature=0.3,
        max_tokens=250,
        fallback="Non renseigné",
        operation="company_intent_summary",
    )
    if summary and summary != "Non renseigné":
        return summary

    return f"{company_name} shows recent commercial intent signals including hiring and company updates."


def generate_company_full_description(company_profile):
    """Compile tous les attributs et appelle le LLM pour la description globale."""
    name = company_profile.get("name") or "Unknown"
    domain = company_profile.get("domain") or "Unknown"
    website_url = company_profile.get("website_url") or company_profile.get("website") or "Not specified"
    industry = company_profile.get("industry") or "Not specified"
    founded_year = company_profile.get("founded_year") or "Not specified"
    
    short_desc = company_profile.get("short_description") or "Not specified"
    seo_desc = company_profile.get("seo_description") or "Not specified"
    
    revenue = company_profile.get("annual_revenue") or "Not specified"
    employees = company_profile.get("estimated_num_employees") or "Not specified"
    alexa_ranking = company_profile.get("alexa_ranking") or "Not specified"
    total_funding = company_profile.get("total_funding") or "Not specified"
    funding_stage = company_profile.get("latest_funding_stage") or "Not specified"
    
    country = company_profile.get("country")
    if not country or country == "Non renseigné":
        country = company_profile.get("location", {}).get("country", "Not specified")
        
    city = company_profile.get("city")
    if not city or city == "Non renseigné":
        city = company_profile.get("location", {}).get("city", "Not specified")
        
    linkedin_url = company_profile.get("linkedin_url") or "Not specified"
    phone = company_profile.get("phone") or "Not specified"

    keywords = company_profile.get("keywords", [])
    if not isinstance(keywords, list): keywords = []
    kws_str = ", ".join([str(k) for k in keywords[:10]]) if keywords else "None"
        
    technologies = company_profile.get("technologies", [])
    if not isinstance(technologies, list): technologies = []
    tech_names = [t.get("name") for t in technologies if isinstance(t, dict) and t.get("name")]
    techs_str = ", ".join(tech_names[:10]) if tech_names else "None"

    competitors = company_profile.get("competitors", [])
    if not isinstance(competitors, list): competitors = []
    comps_str = ", ".join([str(c) for c in competitors[:5]]) if competitors else "None"

    departments = company_profile.get("departments", {})
    if not isinstance(departments, dict): departments = {}
    deps_str = ", ".join([f"{k} ({v})" for k, v in list(departments.items())[:5]]) if departments else "None"

    if short_desc in ["Non renseigné", "Not specified"] and industry in ["Non renseigné", "Not specified"] and not keywords:
        company_profile["full_description"] = "Non renseigné"
        return company_profile

    print(f"🧠 Génération LLM (Full Description) pour : {name}...")
    company_profile["full_description"] = invoke_template(
        COMPANY_FULL_DESCRIPTION,
        name=name,
        domain=domain,
        website_url=website_url,
        industry=industry,
        founded_year=founded_year,
        city=city,
        country=country,
        revenue=revenue,
        employees=employees,
        total_funding=total_funding,
        funding_stage=funding_stage,
        alexa_ranking=alexa_ranking,
        deps_str=deps_str,
        short_desc=short_desc,
        seo_desc=seo_desc,
        kws_str=kws_str,
        techs_str=techs_str,
        comps_str=comps_str,
        linkedin_url=linkedin_url,
        phone=phone,
        temperature=0.3,
        max_tokens=400,
        fallback="Non renseigné",
        operation="company_full_description",
    )
    return company_profile


def generate_persona_intent_summary(persona_name, posts_data):
    """Analyse l'activité LinkedIn d'un prospect pour en déduire un résumé d'intention commerciale."""
    if not posts_data:
        return ""

    signals_summary = []
    for i, post in enumerate(posts_data, 1):
        bs = post.get("businessSignal", "N/A")
        pi = post.get("personaInterest", "N/A")
        kt = post.get("keyTakeaway", "N/A")
        
        if bs != "N/A" or pi != "N/A" or kt != "N/A":
            signals_summary.append(f"Post {i}: Signal={bs} | Interest={pi} | Takeaway={kt}")

    if not signals_summary:
        return ""

    joined_signals = "\n".join(signals_summary)

    print(f"🧠 Génération du résumé d'intention (Intent) pour : {persona_name}...")
    # Empty fallback: do not persist failure text onto Persona.intent.
    return invoke_template(
        PERSONA_INTENT_SUMMARY,
        persona_name=persona_name,
        joined_signals=joined_signals,
        temperature=0.3,
        max_tokens=250,
        fallback="",
        operation="persona_intent_summary",
    )


def generate_merged_report(apollo_data, ai_json_path, output_dir="merged_profiles"):
    """Fusionne intelligemment les donnees Apollo et SmartScraper AI."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        with open(ai_json_path, 'r', encoding='utf-8') as f:
            ai_data = json.load(f)
    except Exception as e:
        print(f"⚠️ Impossible de lire le fichier IA pour la fusion : {e}")
        return None

    domain = apollo_data.get("domain", "unknown_domain")
    CONFIDENCE_THRESHOLD = 0.8

    def get_ai_val_and_conf(category, field=None):
        if field:
            target = ai_data.get(category, {}).get(field)
            if isinstance(target, dict):
                return target.get("value"), target.get("confidence", 0.0)
            return target, 0.0
        else:
            val = ai_data.get(category)
            if isinstance(val, dict) and "value" in val:
                return val.get("value"), val.get("confidence", 0.0)
            return val, 0.0

    def get_db_val(key):
        if key in apollo_data:
            return apollo_data[key]
        if key in ["city", "country", "raw_address", "state", "street_address", "postal_code"]:
            return apollo_data.get("location", {}).get(key, "Non renseigné")
        if key == "num_suborganizations":
            return apollo_data.get("hierarchy", {}).get(key, "Non renseigné")
        return "Non renseigné"

    def is_valid(val):
        invalid_strings = [
            None, "", "Non renseigné", "Non trouvé", "invalid or hallucinated link",
            "Non trouvé par l'IA", "Non trouvé pour cette entité spécifique", "[]", "{}"
        ]
        if val in invalid_strings:
            return False
        if isinstance(val, list) and len(val) == 0:
            return False
        if isinstance(val, dict) and len(val) == 0:
            return False
        return True

    def parse_list_safely(val):
        if not is_valid(val): return []
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list): return parsed
            except:
                if "[" not in val and "{" not in val:
                    return [v.strip() for v in val.split(',') if v.strip()]
        return val if isinstance(val, list) else []

    def calculate_final_quality_score(merged_data, ai_original_score):
        critical_fields = ["name", "domain", "industry", "country", "technologies", "linkedin_url"]
        filled_fields = [f for f in critical_fields if is_valid(merged_data.get(f))]
        completeness_score = len(filled_fields) / len(critical_fields)

        has_apollo = is_valid(merged_data.get("apollo_id"))
        has_ai = ai_original_score > 0
        synergy_score = 1.0 if (has_apollo and has_ai) else 0.5 if (has_apollo or has_ai) else 0.0

        final_score = (completeness_score * 0.5) + (synergy_score * 0.3) + (ai_original_score * 0.2)
        return round(final_score, 2)

    merged_profile = {}
    all_db_attributes = [
        "alexa_ranking", "annual_revenue", "apollo_id", "captured_at", "category", "city", 
        "country", "created_at", "crunchbase", "crunchbase_url", "data", "departments", 
        "description", "domain", "estimated_num_employees", "facebook", "facebook_url", 
        "founded_year", "full_address", "funding_events", "funding_stage", "id", "industry", 
        "keywords", "last_update", "last_verified_at", "latest_funding_stage", "linkedin", 
        "linkedin_url", "logo", "logo_url", "name", "nodes", "num_suborganizations", 
        "owned_by_organization_id", "parent_apollo_id", "parent_id", "phone", "postal_code", 
        "raw_address", "relationships", "revenue", "seo_description", "short_description", 
        "siret", "size", "state", "street_address", "style", "sub_orgs_count", 
        "suborganizations", "tech_stack", "technologies", "total_funding", "twitter", 
        "twitter_url", "uid", "visualisation", "website", "website_url"
    ]

    common_mapping = {
        "domain": ("identity", "domain"), "name": ("identity", "name"), "industry": ("identity", "industry"),
        "founded_year": ("identity", "founded_year"), "short_description": ("identity", "short_description"),
        "seo_description": ("identity", "seo_description"), "annual_revenue": ("performance", "annual_revenue_USD"),
        "total_funding": ("performance", "total_funding"), "estimated_num_employees": ("performance", "estimated_num_employees"),
        "latest_funding_stage": ("performance", "latest_funding_stage"), "linkedin_url": ("contact_social", "linkedin_url"),
        "twitter_url": ("contact_social", "twitter_url"), "facebook_url": ("contact_social", "facebook_url"),
        "phone": ("contact_social", "phone"), "num_suborganizations": ("hierarchy", "num_suborganizations"),
        "raw_address": ("location_detailed", "raw_address"), "city": ("location_detailed", "city"), "country": ("location_detailed", "country")
    }

    for attr in all_db_attributes:
        db_val = get_db_val(attr)
        db_valid = is_valid(db_val)

        if attr == "technologies":
            db_techs = parse_list_safely(db_val)
            ai_techs = ai_data.get("technologies", [])
            if db_valid or ai_techs:
                merged_techs = {}
                for t in db_techs:
                    if isinstance(t, dict) and "name" in t:
                        merged_techs[t["name"].lower()] = t
                for t in ai_techs:
                    if isinstance(t, dict) and "name" in t:
                        name_l = t["name"].lower()
                        if name_l not in merged_techs:
                            merged_techs[name_l] = {"uid": t.get("uid", name_l.replace(" ", "_")), "name": t.get("name"), "category": t.get("category", "Other")}
                merged_profile[attr] = list(merged_techs.values())
            else:
                merged_profile[attr] = db_val

        elif attr == "keywords":
            db_kws = parse_list_safely(db_val)
            ai_kw_raw, _ = get_ai_val_and_conf("keywords", None)
            ai_kws = parse_list_safely(ai_kw_raw)

            if db_valid and len(ai_kws) > 0:
                unique_kws = list(db_kws)
                lower_db_kws = {str(k).lower().strip() for k in db_kws}
                for k in ai_kws:
                    if str(k).lower().strip() not in lower_db_kws:
                        unique_kws.append(k)
                merged_profile[attr] = unique_kws
            elif len(ai_kws) > 0:
                merged_profile[attr] = ai_kws
            else:
                merged_profile[attr] = db_val

        elif attr == "suborganizations":
            db_subs = parse_list_safely(db_val)
            ai_subs_raw, _ = get_ai_val_and_conf("hierarchy", "subsidiaries_list")
            ai_subs = parse_list_safely(ai_subs_raw)

            if db_valid or len(ai_subs) > 0:
                merged_subs = {}
                if db_valid:
                    for s in db_subs:
                        if isinstance(s, dict) and "name" in s:
                            sub_name = str(s["name"]).lower().strip()
                            merged_subs[sub_name] = {
                                "id": s.get("id", "Non renseigné"),
                                "name": str(s.get("name")),
                                "domain": s.get("domain", "Non renseigné")
                            }
                        elif isinstance(s, str):
                            merged_subs[s.lower().strip()] = {
                                "id": "Non renseigné",
                                "name": s,
                                "domain": "Non renseigné"
                            }

                for s in ai_subs:
                    if isinstance(s, dict) and "name" in s:
                        sub_name = str(s["name"]).lower().strip()
                        if sub_name not in merged_subs:
                            merged_subs[sub_name] = {
                                "id": s.get("id", "Non renseigné"),
                                "name": str(s.get("name")),
                                "domain": s.get("domain", "Non renseigné")
                            }
                    elif isinstance(s, str):
                        sub_name = s.lower().strip()
                        if sub_name not in merged_subs:
                            merged_subs[sub_name] = {
                                "id": "Non renseigné",
                                "name": s,
                                "domain": "Non renseigné"
                            }
                merged_profile[attr] = list(merged_subs.values())
            else:
                merged_profile[attr] = db_val

        elif attr == "funding_events":
            db_fundings = parse_list_safely(db_val)
            ai_fundings = ai_data.get("funding_events", [])

            if db_valid or len(ai_fundings) > 0:
                merged_fundings = []
                seen_signatures = set()

                def get_signature(f_dict):
                    date_str = str(f_dict.get("date", "")).strip()
                    year = date_str[:4] if len(date_str) >= 4 else date_str
                    f_type = str(f_dict.get("type", "")).strip().lower()
                    return f"{year}_{f_type}"

                def normalize_funding(f_dict):
                    return {
                        "id": f_dict.get("id", "Non renseigné"),
                        "date": f_dict.get("date", "Non renseigné"),
                        "type": f_dict.get("type", "Non renseigné"),
                        "amount": f_dict.get("amount", "Non renseigné"),
                        "currency": f_dict.get("currency", "Non renseigné"),
                        "investors": f_dict.get("investors", "Non renseigné")
                    }

                for f in db_fundings:
                    if isinstance(f, dict):
                        sig = get_signature(f)
                        normalized_f = normalize_funding(f)
                        if sig == "_" or sig not in seen_signatures:
                            merged_fundings.append(normalized_f)
                            if sig != "_":
                                seen_signatures.add(sig)

                for f in ai_fundings:
                    if isinstance(f, dict):
                        sig = get_signature(f)
                        normalized_f = normalize_funding(f)
                        if sig == "_" or sig not in seen_signatures:
                            merged_fundings.append(normalized_f)
                            if sig != "_":
                                seen_signatures.add(sig)

                merged_profile[attr] = merged_fundings
            else:
                merged_profile[attr] = []

        elif attr in common_mapping:
            ai_cat, ai_field = common_mapping[attr]
            ai_val, ai_conf = get_ai_val_and_conf(ai_cat, ai_field)
            if not db_valid and is_valid(ai_val):
                merged_profile[attr] = ai_val
            elif db_valid and is_valid(ai_val):
                merged_profile[attr] = ai_val if ai_conf >= CONFIDENCE_THRESHOLD else db_val
            else:
                merged_profile[attr] = db_val if db_valid else None
        else:
            if db_valid: merged_profile[attr] = db_val

    ai_only_mapping = {
        "fiscal_year_end": ("performance", "fiscal_year_end"),
        "is_subsidiary": ("hierarchy", "is_subsidiary"),
        "parent_company": ("hierarchy", "parent_company")
    }

    for ai_key, (ai_cat, ai_field) in ai_only_mapping.items():
        ai_val, _ = get_ai_val_and_conf(ai_cat, ai_field)
        if is_valid(ai_val):
            merged_profile[ai_key] = ai_val

    competitors = ai_data.get("market_intelligence", {}).get("competitors", [])
    if is_valid(competitors):
        merged_profile["competitors"] = competitors

    initial_ai_score_raw, _ = get_ai_val_and_conf("data_quality_score", None)
    try:
        initial_ai_score = float(initial_ai_score_raw) if initial_ai_score_raw else 0.0
    except ValueError:
        initial_ai_score = 0.0

    merged_profile["data_quality_score"] = calculate_final_quality_score(merged_profile, initial_ai_score)

    safe_domain = domain.replace(".", "_")
    output_file = os.path.join(output_dir, f"{safe_domain}_MERGED.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged_profile, f, indent=4, ensure_ascii=False)

    print(f"📊 Profil consolidé avec succès (Union + Seuil Confiance + Schemas Unifiés) : {output_file}")
    
    return merged_profile


def generate_source_comparison_report(apollo_data, ai_json_path, output_dir="comparisons"):
    """Sauvegarde les rapports Apollo vs SmartScraper AI avant la fusion."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    try:
        with open(ai_json_path, "r", encoding="utf-8") as f:
            ai_data = json.load(f)
    except Exception as e:
        print(f"⚠️ Impossible de lire le fichier IA pour la comparaison : {e}")
        return None

    def get_db_val(key):
        if key in apollo_data:
            return apollo_data[key]
        if key in ["city", "country", "raw_address", "state", "street_address", "postal_code"]:
            return apollo_data.get("location", {}).get(key, "Non renseigné")
        if key == "num_suborganizations":
            return apollo_data.get("hierarchy", {}).get(key, "Non renseigné")
        return "Non renseigné"

    def get_ai_value(category, field=None):
        target = ai_data.get(category, {}).get(field) if field else ai_data.get(category)
        if isinstance(target, dict) and "value" in target:
            return target.get("value")
        return target

    comparison_groups = {
        "identity": {
            "name": ("identity", "name"),
            "domain": ("identity", "domain"),
            "industry": ("identity", "industry"),
            "founded_year": ("identity", "founded_year"),
            "short_description": ("identity", "short_description"),
            "seo_description": ("identity", "seo_description"),
        },
        "performance": {
            "annual_revenue": ("performance", "annual_revenue_USD"),
            "total_funding": ("performance", "total_funding"),
            "latest_funding_stage": ("performance", "latest_funding_stage"),
            "estimated_num_employees": ("performance", "estimated_num_employees"),
        },
        "contact_social": {
            "linkedin_url": ("contact_social", "linkedin_url"),
            "twitter_url": ("contact_social", "twitter_url"),
            "facebook_url": ("contact_social", "facebook_url"),
            "phone": ("contact_social", "phone"),
        },
        "location": {
            "raw_address": ("location_detailed", "raw_address"),
            "city": ("location_detailed", "city"),
            "country": ("location_detailed", "country"),
        },
        "hierarchy": {
            "num_suborganizations": ("hierarchy", "num_suborganizations"),
        },
        "complex_data": {
            "keywords": ("keywords", None),
            "technologies": ("technologies", None),
            "suborganizations": ("hierarchy", "subsidiaries_list"),
            "funding_events": ("funding_events", None),
            "competitors": ("market_intelligence", "competitors"),
        }
    }

    domain = apollo_data.get("domain", "unknown_domain")
    comparison = {
        "domain": domain,
        "comparison_status": "Apollo API vs SmartScraper AI",
        "common_attributes_comparison": {}
    }
    full_report = {
        "domain": domain,
        "report_summary": "Comparaison complete des sources",
        "common_attributes": {}
    }

    for group_name, fields in comparison_groups.items():
        comparison["common_attributes_comparison"][group_name] = {}
        for field_name, (ai_category, ai_field) in fields.items():
            db_value = get_db_val(field_name)
            ai_value = get_ai_value(ai_category, ai_field)
            comparison["common_attributes_comparison"][group_name][field_name] = {
                "apollo": db_value,
                "ai": ai_value
            }
            full_report["common_attributes"][field_name] = {
                "database_value": db_value,
                "ai_value": ai_value
            }

    safe_domain = str(domain).replace(".", "_")
    comparison_path = os.path.join(output_dir, f"{safe_domain}_COMPARISON.json")
    full_report_path = os.path.join(output_dir, f"{safe_domain}_FULL_REPORT.json")

    with open(comparison_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, indent=4, ensure_ascii=False)
    with open(full_report_path, "w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=4, ensure_ascii=False)

    print(f"📋 Rapport de comparaison Apollo vs IA généré : {comparison_path}")
    print(f"📄 Rapport complet Apollo vs IA généré : {full_report_path}")
    return {"comparison": comparison_path, "full_report": full_report_path}


# =========================================================================
# --- REQUÊTE 1 : DÉCOUVERTE INITIALE & STRUCTURE GRAPHE ---
# =========================================================================

def _map_local_company_row_to_profile(row: dict) -> dict:
    """Map Neo4j company_*/version_* row → flat Apollo-like company profile."""
    if not isinstance(row, dict):
        return {}

    def pick(*keys, default=None):
        for key in keys:
            value = row.get(key)
            if value not in (None, "", "Non renseigné"):
                return value
        return default

    apollo_id = pick("company_apollo_id", "version_apollo_id", "apollo_id", "id")
    return {
        "apollo_id": apollo_id,
        "id": apollo_id,
        "name": pick("company_name", "version_name", "name"),
        "domain": pick("company_domain", "version_domain", "domain"),
        "website_url": pick("version_website_url", "website_url", "website"),
        "industry": pick("version_industry", "industry"),
        "global_industry": pick("version_global_industry", "global_industry"),
        "estimated_num_employees": pick(
            "version_estimated_num_employees", "estimated_num_employees"
        ),
        "annual_revenue": pick("version_annual_revenue", "annual_revenue"),
        "founded_year": pick("version_founded_year", "founded_year"),
        "city": pick("version_city", "city"),
        "country": pick("version_country", "country"),
        "postal_code": pick("version_postal_code", "postal_code"),
        "street_address": pick("version_street_address", "street_address"),
        "latest_funding_stage": pick(
            "version_latest_funding_stage", "latest_funding_stage"
        ),
        "is_subsidiary": pick("version_is_subsidiary", "is_subsidiary", default=False),
        "parent_company": pick("version_parent_company", "parent_company"),
        "full_description": pick("version_full_description", "full_description"),
        "short_description": pick("version_short_description", "short_description"),
        "linkedin_url": pick("version_linkedin_url", "linkedin_url"),
        "data_quality_score": pick("version_data_quality_score", "data_quality_score"),
        "technologies": pick("version_technologies", "technologies", default=[]),
        "keywords": pick("version_keywords", "keywords", default=[]),
        "funding_events": pick("version_funding_events", "funding_events", default=[]),
        "competitors": pick("version_competitors", "competitors", default=[]),
        "departments": pick("version_departments", "departments", default={}),
        "suborganizations": pick(
            "version_suborganizations", "suborganizations", default=[]
        ),
        "company_intent": pick("company_company_intent", "version_company_intent"),
        "source": pick("version_source", default="neo4j_local"),
        "from_local_cache": True,
    }


def _intent_summary_is_present(summary) -> bool:
    if not summary or not isinstance(summary, str):
        return False
    cleaned = summary.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    return not (
        lowered.startswith("aucune intention")
        or lowered.startswith("erreur")
        or lowered in {"none", "null", "n/a", "non renseigné", "non renseigne"}
    )


def _map_intent_signals_to_qualifier(signals: list, company_intent_summary=None) -> dict:
    job_offers = []
    news = []
    for item in signals or []:
        if not isinstance(item, dict):
            continue
        itype = (item.get("intent_type") or "").lower()
        if itype in ("job_post", "job", "job_offer"):
            job_offers.append({
                "title": item.get("title") or item.get("title_and_summary") or item.get("name"),
                "posted_date": item.get("date") or item.get("posted_date") or item.get("published_date"),
                "description": item.get("description") or item.get("title_and_summary") or item.get("summary"),
                "source_origin": item.get("source_origin"),
            })
        else:
            news.append({
                "headline": item.get("headline") or item.get("title_and_summary") or item.get("title"),
                "published_date": item.get("date") or item.get("published_date"),
                "summary": item.get("summary") or item.get("title_and_summary") or item.get("description"),
                "source_origin": item.get("source_origin"),
            })
    return {
        "job_offers": job_offers,
        "news": news,
        "company_intent_summary": company_intent_summary,
    }


def _persona_has_meaningful_intent(persona: dict) -> bool:
    intent = (persona or {}).get("intent") or (persona or {}).get("persona_intent") or ""
    if not intent or not str(intent).strip():
        return False
    lowered = str(intent).strip().lower()
    # Match failure / empty placeholders written by generate_persona_intent_summary.
    meaningless = {
        "none",
        "null",
        "n/a",
        "non renseigné",
        "non renseigne",
        "impossible de générer le résumé d'intention.",
        "impossible de generer le resume d'intention.",
        "aucune activité récente pour déduire une intention.",
        "aucune activite recente pour deduire une intention.",
        "activité détectée, mais aucun signal d'affaires clair n'a été extrait.",
        "activite detectee, mais aucun signal d'affaires clair n'a ete extrait.",
    }
    return lowered not in meaningless


def _map_local_persona_to_qualifier(persona: dict, from_local_cache: bool = False) -> dict:
    # Neo4j Persona.intent is the canonical behavioral-intent summary.
    intent_text = ""
    if _persona_has_meaningful_intent(persona):
        intent_text = str(
            persona.get("intent") or persona.get("persona_intent") or ""
        ).strip()
    return {
        "apollo_id": persona.get("apollo_id") or persona.get("id"),
        "name": persona.get("name") or persona.get("full_name"),
        "title": persona.get("title") or persona.get("job_title"),
        "seniority": persona.get("seniority"),
        "department": persona.get("department"),
        "months_in_role": persona.get("months_in_role"),
        # Used by qualifier to derive months_in_role from current role start_date
        "employment_history": persona.get("employment_history") or [],
        "is_linkedin_connected": persona.get("is_linkedin_connected")
        or persona.get("linkedin_connected")
        or False,
        "email": persona.get("email") or persona.get("mail") or "",
        "phone_number": persona.get("phone_number") or persona.get("phone") or "",
        "linkedin_url": persona.get("linkedin_url") or persona.get("linkedin"),
        # Explicit Neo4j field — qualifier persona_ranker reads this first.
        "intent": intent_text,
        "public_signals": intent_text
        or persona.get("public_signals")
        or "",
        "raw": persona,
        "from_local_cache": from_local_cache,
    }


def _local_persona_has_email(persona: dict) -> bool:
    if not isinstance(persona, dict):
        return False
    if persona.get("has_email") is True:
        return True
    if persona.get("email"):
        return True
    emails = persona.get("sanitized_emails") or persona.get("emails") or []
    return bool(emails)


def _local_persona_has_phone(persona: dict) -> bool:
    if not isinstance(persona, dict):
        return False
    if persona.get("has_phone") is True:
        return True
    if persona.get("phone") or persona.get("phone_number"):
        return True
    phones = (
        persona.get("sanitized_numbers")
        or persona.get("raw_numbers")
        or persona.get("phone_numbers")
        or []
    )
    return bool(phones)


def _local_contact_payload_from_persona(persona: dict) -> dict:
    """Shape a Neo4j Persona node like an Apollo enrichment result."""
    email = persona.get("email")
    sanitized_emails = persona.get("sanitized_emails") or []
    emails = persona.get("emails") or []
    phone_numbers = persona.get("phone_numbers") or []
    sanitized_numbers = persona.get("sanitized_numbers") or []
    raw_numbers = persona.get("raw_numbers") or []
    has_email = _local_persona_has_email(persona)
    has_phone = _local_persona_has_phone(persona)
    return {
        "status": "success",
        "persona_apollo_id": persona.get("id") or persona.get("apollo_id"),
        "email": email,
        "sanitized_emails": sanitized_emails,
        "emails": emails,
        "email_status": persona.get("email_status"),
        "email_domain_catchall": persona.get("email_domain_catchall"),
        "email_domain_catchall_verdict": persona.get("email_domain_catchall_verdict"),
        "mail_pro": persona.get("mail_pro"),
        "has_email": has_email,
        "phone_numbers": phone_numbers,
        "sanitized_numbers": sanitized_numbers,
        "raw_numbers": raw_numbers,
        "phone": (raw_numbers[0] if raw_numbers else None)
        or (sanitized_numbers[0] if sanitized_numbers else None),
        "has_phone": has_phone,
        "linkedin_url": persona.get("linkedin_url"),
        "full_name": persona.get("name") or persona.get("full_name"),
        "from_local_cache": True,
    }


def request_local_persona_contacts(persona_apollo_ids: list) -> dict:
    """
    Check Neo4j for already-enriched email/phone on Persona nodes.
    Returns keyed report: found, has_email, has_phone, complete, contact fields.
    """
    if not persona_apollo_ids:
        return {}

    db = Neo4jManager()
    try:
        personas = db.get_personas_by_apollo_ids(persona_apollo_ids) or []
    finally:
        db.close()

    by_id = {}
    for persona in personas:
        pid = str(persona.get("id") or persona.get("apollo_id") or "").strip()
        if not pid:
            continue
        has_email = _local_persona_has_email(persona)
        has_phone = _local_persona_has_phone(persona)
        by_id[pid] = {
            "found": True,
            "persona_apollo_id": pid,
            "has_email": has_email,
            "has_phone": has_phone,
            "complete": has_email and has_phone,
            "email": persona.get("email"),
            "sanitized_emails": persona.get("sanitized_emails") or [],
            "emails": persona.get("emails") or [],
            "email_status": persona.get("email_status"),
            "phone_numbers": persona.get("phone_numbers") or [],
            "sanitized_numbers": persona.get("sanitized_numbers") or [],
            "raw_numbers": persona.get("raw_numbers") or [],
            "linkedin_url": persona.get("linkedin_url"),
            "full_name": persona.get("name") or persona.get("full_name"),
            "contact": _local_contact_payload_from_persona(persona),
        }

    for persona_id in persona_apollo_ids:
        pid = str(persona_id).strip()
        if pid and pid not in by_id:
            by_id[pid] = {
                "found": False,
                "persona_apollo_id": pid,
                "has_email": False,
                "has_phone": False,
                "complete": False,
            }
    return by_id


def request_discover_companies(
    industries: list, 
    locations: Optional[list] = None, 
    continent: Optional[str] = None, 
    employee_ranges: Optional[list] = None, 
    limit: int = 2,
    limit_per_element: int = 1,
    min_employees: Optional[float] = None,
    max_employees: Optional[float] = None,
) -> list:
    """
    [Flux Requête 1] Recherche initialement et enrichit structurellement les entreprises.
    Intègre une fusion intelligente des pays et continents via LLM.
    Distribue équitablement l'extraction sur chaque localisation jusqu'à atteindre la limite globale.

    Local-first: interrogates Neo4j (geo-intel) before spending Apollo credits.
    Skips Apollo only when local ICP matches >= LOCAL_COMPANY_MIN_HITS (env) AND >= limit.
    Otherwise Apollo fills the gap with companies not already present in Neo4j.
    """
    # ── Local-first Neo4j lookup ──────────────────────────────────────────
    local_profiles = []
    seen_local_ids = set()
    min_hits = max(int(getattr(config, "LOCAL_COMPANY_MIN_HITS", 2) or 2), 1)
    min_emp = int(min_employees) if min_employees is not None else None
    max_emp = int(max_employees) if max_employees is not None else None
    industry_list = industries if isinstance(industries, list) else ([industries] if industries else [])
    location_list = []
    if locations:
        location_list = [locations] if isinstance(locations, str) else list(locations)

    # Collect ALL ICP-matching local companies (for min-hits + Apollo exclusion).
    for industry in industry_list:
        if location_list:
            for country in location_list:
                try:
                    rows = request_search_companies_by_geo_llm(
                        industry=industry,
                        country=country,
                        continent=None,
                        min_employees=min_emp,
                        max_employees=max_emp,
                    ) or []
                except Exception as e:
                    print(f"[WARNING] Local company lookup failed for {industry}/{country}: {e}")
                    rows = []
                for row in rows:
                    profile = _map_local_company_row_to_profile(row)
                    apollo_id = profile.get("apollo_id")
                    if not apollo_id or apollo_id in seen_local_ids:
                        continue
                    seen_local_ids.add(apollo_id)
                    local_profiles.append(profile)
        elif continent:
            try:
                rows = request_search_companies_by_geo_llm(
                    industry=industry,
                    country=None,
                    continent=continent,
                    min_employees=min_emp,
                    max_employees=max_emp,
                ) or []
            except Exception as e:
                print(f"[WARNING] Local company lookup failed for {industry}/{continent}: {e}")
                rows = []
            for row in rows:
                profile = _map_local_company_row_to_profile(row)
                apollo_id = profile.get("apollo_id")
                if not apollo_id or apollo_id in seen_local_ids:
                    continue
                seen_local_ids.add(apollo_id)
                local_profiles.append(profile)

    local_hit_count = len(local_profiles)
    skip_apollo = local_hit_count >= min_hits and local_hit_count >= limit

    if skip_apollo:
        print(
            f"✅ [R1] Cache Neo4j hit — {local_hit_count} match(es) ICP "
            f"(min_hits={min_hits}, limit={limit}) → Apollo organizations/search ignoré."
        )
        set_last_orchestrator_usage(
            build_tool_usage(
                tool="sourcer.fetch_companies",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
                extra={"source": "neo4j_local_only", "local_hits": local_hit_count},
            )
        )
        return local_profiles[:limit]

    remaining_limit = max(limit - min(local_hit_count, limit), 0)
    # Below min_hits → force Apollo to fetch at least enough NEW companies
    if local_hit_count < min_hits:
        remaining_limit = max(remaining_limit, min_hits - local_hit_count)

    if local_hit_count:
        print(
            f"ℹ️ [R1] Cache Neo4j insuffisant — {local_hit_count} locale(s) "
            f"(min_hits={min_hits}, limit={limit}) → Apollo pour {remaining_limit} "
            f"entreprise(s) différente(s) (hors Neo4j)."
        )
    else:
        print(
            f"ℹ️ [R1] Cache Neo4j vide — fallback Apollo organizations/search "
            f"(quota={remaining_limit}, min_hits={min_hits})."
        )

    # Keep local hits (up to limit) and fill with Apollo; exclude seen_local_ids.
    local_profiles = local_profiles[:limit]

    # 1. Consolidation de la liste finale de localisations
    final_locations = []
    
    if locations:
        if isinstance(locations, str):
            final_locations.append(locations)
        else:
            final_locations.extend(locations)

    # --- ÉTAPE INTÉLLIGENTE : ÉLARGISSEMENT CONTINENT VIA LLM (continent-only) ---
    # Si des pays sont déjà fournis, on ne les élargit PAS au continent parent
    # (ex: Morocco ne doit pas devenir Afrique → Égypte, Tunisie, …).
    # L'expansion continent n'a lieu que lorsque le caller demande un continent
    # sans liste de pays (ICP continent-only).
    if continent and not final_locations:
        try:
            llm_response = invoke_template(
                CONTINENT_COUNTRIES,
                continent=continent,
                temperature=0.2,
                max_tokens=400,
                fallback="[]",
                operation="continent_countries",
            ).strip()
            if "```json" in llm_response:
                llm_response = llm_response.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_response:
                llm_response = llm_response.split("```")[1].split("```")[0].strip()
                
            dynamic_countries = json.loads(llm_response)
            if isinstance(dynamic_countries, list) and len(dynamic_countries) > 0:
                final_locations.extend(dynamic_countries)
        except Exception as e:
            print(f"[WARNING] Échec de la fusion géo via LLM, utilisation des locations de base : {e}")

    # Nettoyage et déduplication des localisations tout en gardant l'ordre
    seen = set()
    unique_locations = [loc for loc in final_locations if not (loc in seen or seen.add(loc))]

    if not unique_locations:
        unique_locations = ["Global"] # Sécurité si aucune localisation n'a pu être résolue

    original_limit = limit
    # Apollo quota only (local hits already reserved).
    limit = remaining_limit if remaining_limit > 0 else 0
    if limit <= 0:
        set_last_orchestrator_usage(
            build_tool_usage(
                tool="sourcer.fetch_companies",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
                extra={"source": "local_quota_full", "local_hits": local_hit_count},
            )
        )
        return local_profiles[:original_limit]

    print(
        f"🔎 [R1] Apollo pour {limit} entreprise(s) nouvelles "
        f"(local déjà retenues={len(local_profiles)}, min_hits={min_hits}, "
        f"limit campagne={original_limit}, locs={unique_locations}, effectifs={employee_ranges})..."
    )

    trace_identifier = "_".join(
        [str(industries[0] if industries else "unknown"), str(limit), str(len(unique_locations))]
    )
    gemini_tracker = GeminiTokenTracker()
    save_gemini_token_report(
        "company",
        "company_discover",
        trace_identifier,
        "initial",
        pro_models=ai_scraper.PRO_MODELS,
        fast_models=ai_scraper.FAST_MODELS,
    )
    initial_company_report, _ = save_token_report(
        "company",
        "company_discover",
        trace_identifier,
        "initial",
        config.APOLLO_API_KEY,
        rate_limit_keywords=["organizations", "search", "enrich"],
    )

    db = Neo4jManager()
    apollo_batch = []
    merged_batch = []
    total_collected = 0
    gemini_scrapes_attempted = 0
    gemini_scrapes_succeeded = 0
    target_industry = industries[0] if industries else "Unknown"

    # 2. Boucle intelligente sur chaque élément (localisation) de la liste
    for loc in unique_locations:
        if total_collected >= limit:
            print(f"[LeadPulse] Limite globale de {limit} atteinte. Arrêt de la boucle.")
            break

        # Calcul dynamique de la limite pour CETTE localisation
        remaining_global_slots = limit - total_collected
        current_batch_limit = min(limit_per_element, remaining_global_slots)
        target_loc = None if loc == "Global" else loc

        # Oversample Apollo results — many hits may already exist in Neo4j and get skipped.
        apollo_fetch_limit = max(current_batch_limit * 3, current_batch_limit + len(seen_local_ids))
        print(
            f"[LeadPulse] Extraction pour '{loc}' : Demande de {current_batch_limit} "
            f"nouvelle(s) (fetch Apollo={apollo_fetch_limit})..."
        )
        
        # Appel au Scraper UNIQUEMENT pour la localisation en cours
        batch_companies = scraper.search_companies(
            industries=industries, 
            locations=[target_loc] if target_loc else [], 
            employee_ranges=employee_ranges, 
            limit=apollo_fetch_limit,
            min_employees=min_employees,
            max_employees=max_employees,
            trace_identifier=loc or "global",
            trace_suffix=f"organizations_search_{loc or 'global'}",
        )
        
        if not batch_companies:
            print(f"⚠️ Aucune entreprise trouvée pour {loc}.")
            continue

        batch_ids = [
            c.get("apollo_id") or c.get("id")
            for c in batch_companies
            if c.get("apollo_id") or c.get("id")
        ]
        existing_in_db = db.get_existing_company_apollo_ids(batch_ids)
        exclude_ids = set(seen_local_ids) | set(existing_in_db)

        # Enrichissement pour chaque entreprise trouvée
        for company in batch_companies:
            company_apollo_id = company.get("apollo_id") or company.get("id")
            if company_apollo_id and str(company_apollo_id) in exclude_ids:
                print(
                    f"⏭️ Entreprise {company_apollo_id} déjà en Neo4j — "
                    f"Apollo enrich ignoré (chercher une différente)."
                )
                continue

            use_company_graph = getattr(config, "USE_COMPANY_GRAPH", True)
            if use_company_graph:
                from company_supervisor_graph import CompanyEnrichDeps, enrich_one_company

                print("🕸️ Company enrichment via LangGraph…")
                enrich_result = enrich_one_company(
                    CompanyEnrichDeps(
                        apollo_scraper=scraper,
                        ai_scraper=ai_scraper,
                        generate_merged_report=generate_merged_report,
                        generate_source_comparison_report=generate_source_comparison_report,
                        generate_company_full_description=generate_company_full_description,
                        gemini_tracker=gemini_tracker,
                    ),
                    company=company,
                    target_loc=target_loc,
                    target_industry=target_industry,
                )
                if enrich_result.get("scrape_attempted"):
                    gemini_scrapes_attempted += 1
                if enrich_result.get("scrape_succeeded"):
                    gemini_scrapes_succeeded += 1

                profile_out = enrich_result.get("profile_out") or company
                if enrich_result.get("profile_kind") == "merged":
                    merged_batch.append(profile_out)
                else:
                    apollo_batch.append(profile_out)
            else:
                domain = company.get('domain')
                valid_domain = domain and domain != "Non renseigné"
                full_data = company
                merged_data = None

                if valid_domain:
                    try:
                        # Enrichissement avec la méthode correcte "enrich_organization"
                        enriched_data = scraper.enrich_organization(
                            domain=domain,
                            target_location=target_loc,
                            trace_identifier=domain,
                        )
                        if enriched_data:
                            full_data = {**company, **enriched_data}
                    except Exception as e:
                        print(f"⚠️ Erreur enrichissement Apollo pour {domain}: {e}")

                # SmartScraper AI & Consolidation
                website_url = full_data.get('website_url') or full_data.get('website')
                loc_data = full_data.get("location", {}) if isinstance(full_data.get("location", {}), dict) else {}
                street = loc_data.get("street_address") or full_data.get("street_address") or ""
                city = loc_data.get("city") or full_data.get("city") or ""
                country = loc_data.get("country") or full_data.get("country") or target_loc or ""
                addr_parts = [p for p in [street, city, country] if p and p != "Non renseigné"]
                target_addr = ", ".join(addr_parts)

                if valid_domain and website_url and website_url != "Non renseigné" and str(website_url).startswith("http"):
                    try:
                        print(f"🤖 Lancement de SmartScraperAI pour le site : {website_url}")
                        if target_addr:
                            print(f"📍 Cible géographique transmise à l'IA : {target_addr}")

                        gemini_scrapes_attempted += 1
                        path_to_json = ai_scraper.scrape_and_save(
                            website_url,
                            target_address=target_addr,
                            token_tracker=gemini_tracker,
                        )
                        if path_to_json and path_to_json.endswith(".json"):
                            gemini_scrapes_succeeded += 1
                            comparison_paths = generate_source_comparison_report(full_data, path_to_json)
                            merged_data = generate_merged_report(full_data, path_to_json)
                            if merged_data and comparison_paths:
                                merged_data["comparison_report_path"] = comparison_paths.get("comparison")
                                merged_data["full_comparison_report_path"] = comparison_paths.get("full_report")
                        else:
                            print("⚠️ Le scraping IA n'a pas retourné de chemin JSON valide.")
                    except Exception as e:
                        print(f"❌ Erreur SmartScraperAI sur {website_url}: {e}")
                elif valid_domain:
                    print(f"⚠️ Pas d'URL valide pour {full_data.get('name', 'cette entreprise')}, SmartScraperAI ignoré.")

                # Sécurisation anti-collision
                if not full_data.get('domain') or full_data.get('domain') == "Non renseigné":
                    safe_name = str(full_data.get('name', 'unknown')).replace(' ', '_').lower()
                    full_data['domain'] = f"unknown_{safe_name}"

                # Assignation de l'industrie globale et description LLM
                if merged_data:
                    merged_data['global_industry'] = target_industry
                    merged_data = generate_company_full_description(merged_data)
                    merged_batch.append(merged_data)
                else:
                    full_data['global_industry'] = target_industry
                    full_data = generate_company_full_description(full_data)
                    apollo_batch.append(full_data)

            if company_apollo_id:
                exclude_ids.add(str(company_apollo_id))
                seen_local_ids.add(str(company_apollo_id))

            total_collected += 1
            
            # Vérification de sécurité interne pour ne pas dépasser la limite
            if total_collected >= limit:
                break

    # Persistance ciblée sur le périmètre structurel (:Company, :Version)
    try:
        if apollo_batch: 
            db.bulk_import_companies(apollo_batch)
        if merged_batch: 
            db.import_merged_profiles(merged_batch)
    except Exception as e:
        print(f"❌ Erreur lors de l'injection en base Neo4j : {e}")
    finally:
        db.close()

    session_consumption = compute_session_consumption(config.APOLLO_API_KEY, initial_company_report)
    save_token_report(
        "company",
        "company_discover",
        trace_identifier,
        "final",
        config.APOLLO_API_KEY,
        session_diff=session_consumption,
        rate_limit_keywords=["organizations", "search", "enrich"],
    )

    gemini_session_consumption = compute_gemini_session_consumption(
        gemini_tracker,
        extra={
            "companies_scraped_attempted": gemini_scrapes_attempted,
            "companies_scraped_succeeded": gemini_scrapes_succeeded,
            "industries": industries,
            "locations": unique_locations,
        },
    )
    save_gemini_token_report(
        "company",
        "company_discover",
        trace_identifier,
        "final",
        pro_models=ai_scraper.PRO_MODELS,
        fast_models=ai_scraper.FAST_MODELS,
        session_diff=gemini_session_consumption,
    )
    print(
        f"   • Tokens Gemini consommés : {gemini_session_consumption['total_tokens']} "
        f"(prompt: {gemini_session_consumption['prompt_tokens']}, "
        f"output: {gemini_session_consumption['candidates_tokens']}, "
        f"appels: {gemini_session_consumption['api_calls_consumed']})"
    )

    set_last_orchestrator_usage(
        build_tool_usage(
            tool="sourcer.fetch_companies",
            apollo=session_consumption,
            gemini=gemini_session_consumption,
            extra={
                "source": "apollo_and_or_local",
                "local_hits": local_hit_count,
                "apollo_new": len(merged_batch) + len(apollo_batch),
            },
        )
    )
    
    apollo_results = merged_batch + apollo_batch
    combined = local_profiles + apollo_results
    # Cap at campaign limit; if below min_hits we may keep up to min_hits to include Apollo fills.
    final_cap = original_limit
    if local_hit_count < min_hits:
        final_cap = max(original_limit, min(len(combined), min_hits))
    print(
        f"[LeadPulse] Fin de la recherche globale. "
        f"Local={len(local_profiles)} Apollo_new={len(apollo_results)} "
        f"(min_hits={min_hits}, return={min(len(combined), final_cap)}/{final_cap})"
    )
    return combined[:final_cap]


def request_run_company_mission(
    industries: list,
    locations: Optional[list] = None,
    continent: Optional[str] = None,
    employee_ranges: Optional[list] = None,
    limit: int = 2,
    limit_per_element: int = 1,
    min_employees: Optional[float] = None,
    max_employees: Optional[float] = None,
    target_country: Optional[str] = None,
    role: Optional[list] = None,
    include_intent: bool = False,
    include_personas: bool = False,
    include_contacts: bool = False,
) -> dict:
    """
    Supervisor LangGraph company-level:
    discover → (optional) intent → personas → contacts.

    Discover already scrapes/merges/persists to Neo4j via request_discover_companies.
    Intent/personas/contacts reuse the existing request_* tools (no LLM-driven Cypher).
    """
    from company_supervisor_graph import CompanyMissionDeps, run_company_mission

    print(
        "🕸️ [Mission supervisor] "
        f"intent={include_intent} personas={include_personas} contacts={include_contacts}"
    )
    result = run_company_mission(
        CompanyMissionDeps(
            discover_companies=request_discover_companies,
            enrich_intents=request_enrich_company_intents,
            enrich_personas=request_enrich_company_personas,
            enrich_contacts=request_enrich_contacts_for_orchestrator,
        ),
        industries=industries,
        locations=locations,
        continent=continent,
        employee_ranges=employee_ranges,
        limit=limit,
        limit_per_element=limit_per_element,
        min_employees=min_employees,
        max_employees=max_employees,
        target_country=target_country,
        role=role,
        include_intent=include_intent,
        include_personas=include_personas,
        include_contacts=include_contacts,
    )
    return {
        "companies": result.get("companies") or [],
        "company_apollo_ids": result.get("company_apollo_ids") or [],
        "intent_results": result.get("intent_results") or {},
        "persona_results": result.get("persona_results") or {},
        "contact_results": result.get("contact_results") or {},
        "error": result.get("error"),
    }


def request_refresh_company(
    apollo_id: str,
    domain: Optional[str] = None,
    global_industry: Optional[str] = None,
    target_country: Optional[str] = None,
) -> dict:
    """
    [Cron] Ré-enrichit une entreprise existante via Apollo + SmartScraperAI
    et persiste le profil (CURRENT / ARCHIVED géré par Neo4jManager).
    """
    if not apollo_id and not domain:
        return {"status": "error", "message": "apollo_id ou domain requis."}

    db = Neo4jManager()
    gemini_tracker = GeminiTokenTracker()

    try:
        if not domain and apollo_id:
            domain = db.get_company_domain_by_apollo_id(apollo_id)

        if not domain:
            return {"status": "error", "message": f"Domaine introuvable pour {apollo_id}."}

        valid_domain = (
            domain
            and domain != "Non renseigné"
            and not str(domain).startswith("unknown_")
        )
        full_data = {"apollo_id": apollo_id, "domain": domain}
        merged_data = None

        if valid_domain:
            try:
                enriched_data = scraper.enrich_organization(
                    domain=domain,
                    target_location=None,
                    trace_identifier=domain,
                )
                if enriched_data:
                    full_data = {**full_data, **enriched_data}
            except Exception as e:
                print(f"⚠️ Erreur enrichissement Apollo pour {domain}: {e}")

        apollo_id = full_data.get("apollo_id") or apollo_id

        website_url = full_data.get("website_url") or full_data.get("website")
        loc_data = full_data.get("location", {}) if isinstance(full_data.get("location", {}), dict) else {}
        street = loc_data.get("street_address") or full_data.get("street_address") or ""
        city = loc_data.get("city") or full_data.get("city") or ""
        country = loc_data.get("country") or full_data.get("country") or target_country or ""
        addr_parts = [p for p in [street, city, country] if p and p != "Non renseigné"]
        target_addr = ", ".join(addr_parts)

        if valid_domain and website_url and website_url != "Non renseigné" and str(website_url).startswith("http"):
            try:
                print(f"🤖 [Cron] SmartScraperAI pour : {website_url}")
                path_to_json = ai_scraper.scrape_and_save(
                    website_url,
                    target_address=target_addr,
                    token_tracker=gemini_tracker,
                )
                if path_to_json and path_to_json.endswith(".json"):
                    comparison_paths = generate_source_comparison_report(full_data, path_to_json)
                    merged_data = generate_merged_report(full_data, path_to_json)
                    if merged_data and comparison_paths:
                        merged_data["comparison_report_path"] = comparison_paths.get("comparison")
                        merged_data["full_comparison_report_path"] = comparison_paths.get("full_report")
            except Exception as e:
                print(f"❌ Erreur SmartScraperAI sur {website_url}: {e}")
        elif valid_domain:
            print(f"⚠️ Pas d'URL valide pour {full_data.get('name', domain)}, SmartScraperAI ignoré.")

        if not full_data.get("domain") or full_data.get("domain") == "Non renseigné":
            safe_name = str(full_data.get("name", "unknown")).replace(" ", "_").lower()
            full_data["domain"] = f"unknown_{safe_name}"

        industry = global_industry or full_data.get("global_industry") or "Unknown"

        if merged_data:
            merged_data["global_industry"] = industry
            merged_data = generate_company_full_description(merged_data)
            db.import_merged_profiles([merged_data])
            profile = merged_data
            source = "merged"
        else:
            full_data["global_industry"] = industry
            full_data = generate_company_full_description(full_data)
            db.bulk_import_companies([full_data])
            profile = full_data
            source = "apollo"

        return {
            "status": "success",
            "apollo_id": apollo_id,
            "domain": profile.get("domain") or domain,
            "name": profile.get("name"),
            "country": country or target_country,
            "source": source,
        }
    except Exception as e:
        print(f"❌ Erreur refresh company {apollo_id or domain}: {e}")
        return {"status": "error", "message": str(e), "apollo_id": apollo_id, "domain": domain}
    finally:
        db.close()


# =========================================================================
# --- REQUÊTE 2 : SIGNAUX D'INTENTION ENTREPRISES ---
# =========================================================================

def request_enrich_company_intents(company_apollo_ids: list, target_country: Optional[str] = None):
    """[Flux Requête 2] Analyse et lie les signaux d'intention (Jobs/News) aux entreprises via Apollo ID."""
    print(f"🌍 [R2] Collecte des intentions globales pour {len(company_apollo_ids)} entreprises (Apollo IDs)...")
    db = Neo4jManager()
    results = {}

    for apollo_id in company_apollo_ids:
        try:
            company_domain = db.get_company_domain_by_apollo_id(apollo_id)
            if company_domain:
                print(f"🔎 Domaine résolu pour Apollo ID {apollo_id} : {company_domain}")
            else:
                print(f"⚠️ Aucun domaine trouvé pour Apollo ID {apollo_id} en base. Le scraper web ne pourra pas fonctionner sans domaine.")

            if not company_domain:
                results[apollo_id] = {"status": "No domain found", "message": "Impossible de récupérer le domaine depuis Neo4j."}
                continue

            company_intents = intent_orchestrator.fetch_global_intent_signals(
                domain=company_domain,
                apollo_id=apollo_id,
                target_country=target_country,
            )
            if company_intents:
                mock_profile = {"name": company_domain.split('.')[0].capitalize(), "domain": company_domain}
                intent_summary = generate_company_intent_summary(mock_profile, company_intents)

                import_stats = db.bulk_import_company_intents(
                    company_intents,
                    company_domain,
                    company_intent=intent_summary,
                )
                results[company_domain] = {
                    "status": "Enriched",
                    "signals_count": len(company_intents),
                    "signals_imported": (import_stats or {}).get("imported", 0),
                    "signals_skipped_existing": (import_stats or {}).get("skipped_existing", 0),
                }
            else:
                results[company_domain] = {"status": "No signals found"}
        except Exception as e:
            error_key = company_domain or apollo_id
            print(f"❌ Erreur intentions globales pour {error_key} : {e}")
            results[error_key] = {"status": "Error", "message": str(e)}

    db.close()
    return results


def request_fetch_intent_signals_for_orchestrator(
    company_apollo_ids: list,
    target_country: Optional[str] = None,
) -> dict:
    """
    Collect intent for Apollo IDs and return qualifier-shaped intent_signals
    keyed by apollo_id: {job_offers: [...], news: [...]}.
    Also persists into Neo4j via the existing intent pipeline.

    Local-first: reuse IntentSignal + company_intent from Neo4j when present.
    """
    print(f"🌍 [Orchestrator] Intent signals for {len(company_apollo_ids)} companies...")
    db = Neo4jManager()
    by_apollo_id: dict = {}

    for apollo_id in company_apollo_ids:
        try:
            local_intent = db.get_company_intent_signals_by_apollo_id(apollo_id) or {}
            local_signals = local_intent.get("signals") or []
            local_summary = local_intent.get("company_intent")
            if local_signals or _intent_summary_is_present(local_summary):
                mapped = _map_intent_signals_to_qualifier(local_signals, local_summary)
                company_domain = db.get_company_domain_by_apollo_id(apollo_id)
                by_apollo_id[apollo_id] = {
                    **mapped,
                    "domain": company_domain,
                    "status": "From local cache",
                    "from_local_cache": True,
                }
                print(
                    f"✅ [Orchestrator] Intent cache hit for {apollo_id} "
                    f"(signals={len(local_signals)}, summary={bool(_intent_summary_is_present(local_summary))})"
                )
                continue

            company_domain = db.get_company_domain_by_apollo_id(apollo_id)
            if not company_domain:
                by_apollo_id[apollo_id] = {
                    "job_offers": [],
                    "news": [],
                    "status": "No domain found",
                }
                continue

            company_intents = intent_orchestrator.fetch_global_intent_signals(
                domain=company_domain,
                apollo_id=apollo_id,
                target_country=target_country,
            ) or []

            mapped = _map_intent_signals_to_qualifier(company_intents)
            mock_profile = {
                "name": company_domain.split(".")[0].capitalize(),
                "domain": company_domain,
            }
            intent_summary = generate_company_intent_summary(mock_profile, company_intents)
            db.bulk_import_company_intents(
                company_intents,
                company_domain,
                company_intent=intent_summary,
            )

            by_apollo_id[apollo_id] = {
                **mapped,
                "company_intent_summary": intent_summary,
                "domain": company_domain,
                "status": "Enriched" if company_intents else "No signals found",
                "from_local_cache": False,
            }
        except Exception as e:
            print(f"❌ Erreur intent orchestrator pour {apollo_id}: {e}")
            by_apollo_id[apollo_id] = {
                "job_offers": [],
                "news": [],
                "status": "Error",
                "message": str(e),
            }

    db.close()
    return by_apollo_id


def request_fetch_personas_for_orchestrator(
    company_apollo_ids: list,
    target_country: Optional[str] = None,
    role: Optional[list] = None,
    limit: int = 10,
    limit_per_element: int = 3,
) -> dict:
    """
    Enrich personas (scraping + intent) then return personas_by_company keyed by apollo_id
    in the shape expected by the qualifier resume_with_approvals tool.

    Local-first: if Neo4j already has personas (with intent signals preferred),
    skip Apollo persona search for that company.
    """
    personas_by_company: dict = {}
    companies_needing_apollo: list = []
    enrich_report: dict = {"local_hits": {}, "apollo": {}}

    for apollo_id in company_apollo_ids:
        raw_personas = request_company_personas_with_signals(apollo_id) or []
        with_intent = [p for p in raw_personas if _persona_has_meaningful_intent(p)]

        # Cache hit only when personas already carry intent signals.
        # Personas without intent still go through Apollo path (skip known IDs, refresh intent).
        if with_intent:
            mapped = [
                _map_local_persona_to_qualifier(p, from_local_cache=True)
                for p in with_intent[:limit_per_element]
            ]
            personas_by_company[apollo_id] = mapped
            enrich_report["local_hits"][apollo_id] = {
                "status": "From local cache",
                "count": len(mapped),
                "with_intent": len(with_intent),
            }
            print(
                f"✅ [Orchestrator] Personas cache hit for {apollo_id} "
                f"({len(mapped)} local with intent) — Apollo search skip."
            )
        else:
            companies_needing_apollo.append(apollo_id)

    if companies_needing_apollo:
        remaining_slots = max(limit - sum(len(v) for v in personas_by_company.values()), 0)
        if remaining_slots > 0:
            apollo_report = request_enrich_company_personas(
                company_apollo_ids=companies_needing_apollo,
                target_country=target_country,
                role=role,
                limit=remaining_slots,
                limit_per_element=limit_per_element,
            )
            enrich_report["apollo"] = apollo_report or {}
            for apollo_id in companies_needing_apollo:
                raw_personas = request_company_personas_with_signals(apollo_id) or []
                personas_by_company[apollo_id] = [
                    _map_local_persona_to_qualifier(p, from_local_cache=False)
                    for p in raw_personas
                ]
        else:
            for apollo_id in companies_needing_apollo:
                personas_by_company.setdefault(apollo_id, [])
    else:
        print("✅ [Orchestrator] All persona companies served from Neo4j — Apollo search skipped.")

    return {
        "enrich_report": enrich_report,
        "sourced_personas_by_company": personas_by_company,
    }


def _enrichment_has_email(result: dict) -> bool:
    if not isinstance(result, dict) or result.get("status") == "error":
        return False
    if result.get("has_email"):
        return True
    if result.get("email"):
        return True
    if result.get("sanitized_emails") or result.get("emails"):
        return True
    apollo = result.get("apollo_response") or {}
    return bool(
        apollo.get("email")
        or apollo.get("sanitized_emails")
        or apollo.get("emails")
    )


def _enrichment_has_phone(result: dict) -> bool:
    if not isinstance(result, dict) or result.get("status") == "error":
        return False
    if result.get("has_phone"):
        return True
    if result.get("phone") or result.get("phone_number"):
        return True
    if result.get("phone_numbers") or result.get("sanitized_numbers") or result.get("raw_numbers"):
        return True
    apollo = result.get("apollo_response") or {}
    return bool(
        apollo.get("phone_numbers")
        or apollo.get("sanitized_numbers")
        or apollo.get("raw_numbers")
        or apollo.get("phone")
        or apollo.get("phone_number")
    )


def _merge_contact_enrichment(primary: dict, fallback: dict) -> dict:
    """Prefer non-empty contact fields from primary, fill gaps from fallback."""
    if not isinstance(primary, dict) or primary.get("status") == "error":
        return fallback if isinstance(fallback, dict) else {}
    if not isinstance(fallback, dict) or fallback.get("status") == "error":
        return primary

    merged = dict(primary)
    for key in (
        "email",
        "sanitized_emails",
        "emails",
        "email_status",
        "email_domain_catchall",
        "email_domain_catchall_verdict",
        "mail_pro",
        "has_email",
        "phone",
        "phone_number",
        "phone_numbers",
        "sanitized_numbers",
        "raw_numbers",
        "has_phone",
        "linkedin_url",
        "full_name",
    ):
        primary_val = merged.get(key)
        fallback_val = fallback.get(key)
        empty_primary = primary_val in (None, "", [], False)
        if empty_primary and fallback_val not in (None, "", []):
            merged[key] = fallback_val

    merged["has_email"] = _enrichment_has_email(merged)
    merged["has_phone"] = _enrichment_has_phone(merged)
    merged["status"] = "success" if (
        merged.get("status") == "success" or fallback.get("status") == "success"
    ) else merged.get("status") or fallback.get("status")
    return merged


def request_enrich_contacts_for_orchestrator(persona_apollo_ids: list) -> dict:
    """
    Enrich email + phone for persona Apollo IDs.

    Strategy:
    0. Local-first: if Neo4j Persona already has email + phone → skip Apollo
    1. Sync reveal via enrich_persona_phone (often returns phone + email)
    2. If email or phone still missing → enrich_persona_waterfall_phone (async + webhook poll)
    3. If email still missing → enrich_persona_waterfall_email (LangGraph path)

    Set USE_CONTACT_GRAPH=false to force the legacy inline loop (steps 0–2 only).
    """
    use_contact_graph = getattr(config, "USE_CONTACT_GRAPH", True)
    if use_contact_graph:
        from persona_contact_waterfall_graph import (
            ContactWaterfallDeps,
            enrich_persona_contacts_batch,
        )

        print("🕸️ Contact enrich via LangGraph waterfall…")
        return enrich_persona_contacts_batch(
            ContactWaterfallDeps(
                get_local_contacts=request_local_persona_contacts,
                enrich_sync_phone=request_enrich_persona_phone,
                enrich_waterfall_phone=request_enrich_persona_waterfall_phone,
                enrich_waterfall_email=request_enrich_persona_waterfall_email,
                has_email=_enrichment_has_email,
                has_phone=_enrichment_has_phone,
                merge_enrichment=_merge_contact_enrichment,
                try_waterfall_email=True,
            ),
            persona_apollo_ids,
        )

    results = {}
    local_contacts = request_local_persona_contacts(persona_apollo_ids)
    ids_needing_apollo = []

    for persona_id in persona_apollo_ids:
        pid = str(persona_id).strip()
        local = local_contacts.get(pid) or {}
        if local.get("complete"):
            payload = local.get("contact") or {}
            print(
                f"✅ [Orchestrator] Contact cache hit for {pid} "
                f"(email+phone already in Neo4j) — Apollo enrich skip."
            )
            results[pid] = {
                "email_enrichment": payload,
                "phone_enrichment": payload,
                "enrichment_path": "neo4j_local",
                "used_waterfall_fallback": False,
                "from_local_cache": True,
            }
        else:
            ids_needing_apollo.append(pid)

    for persona_id in ids_needing_apollo:
        print(f"📇 [Orchestrator] Contact enrich — sync phone reveal for {persona_id}")
        sync_result = request_enrich_persona_phone(persona_id)
        used_waterfall = False
        final_result = sync_result

        if not _enrichment_has_email(sync_result) or not _enrichment_has_phone(sync_result):
            print(
                f"↘️  [Orchestrator] Sync incomplete "
                f"(email={_enrichment_has_email(sync_result)}, "
                f"phone={_enrichment_has_phone(sync_result)}) "
                f"— fallback waterfall phone for {persona_id}"
            )
            waterfall_result = request_enrich_persona_waterfall_phone(persona_id)
            final_result = _merge_contact_enrichment(sync_result, waterfall_result)
            used_waterfall = True

        results[persona_id] = {
            "email_enrichment": final_result,
            "phone_enrichment": final_result,
            "enrichment_path": (
                "enrich_persona_phone+waterfall_phone"
                if used_waterfall
                else "enrich_persona_phone"
            ),
            "used_waterfall_fallback": used_waterfall,
            "from_local_cache": False,
        }
    return results


# =========================================================================
# --- REQUÊTE 3 : TARGETING PERSONAS & SIGNAUX SOCIAUX ---
# =========================================================================

def request_enrich_company_personas(
    company_apollo_ids: list,
    target_country: Optional[str] = None,
    role: Optional[list] = None,
    limit: int = 10,
    limit_per_element: int = 3,
):
    """[Flux Requête 3] Recherche les Personas via Apollo ID, extrait leurs posts LinkedIn et synthétise l'intention."""
    resolved_titles = resolve_person_titles(role=role)
    context_label = f" ({target_country})" if target_country else ""
    print(
        f"👤 [R3] Prospection de Personas{context_label} pour {len(company_apollo_ids)} entreprises "
        f"(Apollo IDs) | titres={resolved_titles} | limite globale={limit}, "
        f"limite par entreprise={limit_per_element}..."
    )
    db = Neo4jManager()
    results = {}
    signals_dir = "persona_signals_archive"
    personas_dir = "personas_discovered"
    os.makedirs(signals_dir, exist_ok=True)
    os.makedirs(personas_dir, exist_ok=True)
    total_collected = 0

    for apollo_id in company_apollo_ids:
        if total_collected >= limit:
            print(f"[LeadPulse] Limite globale de {limit} persona(s) atteinte. Arrêt de la boucle.")
            break

        remaining_global_slots = limit - total_collected
        current_limit = min(limit_per_element, remaining_global_slots)

        try:
            domain = db.get_company_domain_by_apollo_id(apollo_id)
            if domain:
                print(f"🔎 Domaine résolu pour Apollo ID {apollo_id} : {domain}")
            else:
                print(f"⚠️ Aucun domaine trouvé pour Apollo ID {apollo_id} en base. La recherche Apollo utilisera uniquement l'Apollo ID.")

            persona_index = db.get_company_persona_index(apollo_id)
            if persona_index["ids"]:
                print(
                    f"ℹ️ {len(persona_index['ids'])} persona(s) déjà en base pour {apollo_id} "
                    f"({len(persona_index['with_intent_ids'])} avec intent)."
                )

            personas_found = search_and_enrich(
                apollo_id=apollo_id,
                domain=domain,
                location=target_country,
                role=role,
                limit=current_limit,
                skip_persona_ids=persona_index["ids"],
            )

            existing_personas = db.get_company_personas_by_apollo_id(apollo_id) or []

            if not personas_found and not existing_personas:
                results[apollo_id] = {"status": "No personas found", "domain": domain}
                continue

            if not personas_found and existing_personas:
                print(
                    f"ℹ️ Aucun nouveau persona Apollo pour {apollo_id} "
                    f"({len(existing_personas)} déjà en base) — refresh intent des existants."
                )

            total_collected += len(personas_found)

            # Normalisation des URLs LinkedIn (format unique anti-doublon)
            for persona in personas_found:
                persona["linkedin_url"] = Neo4jManager.normalize_linkedin_url(
                    persona.get("linkedin_url")
                )

            safe_label = str(domain or apollo_id).replace(".", "_").replace("/", "_")
            personas_output = os.path.join(personas_dir, f"{safe_label}_personas.json")
            if personas_found:
                with open(personas_output, "w", encoding="utf-8") as f:
                    json.dump(personas_found, f, indent=4, ensure_ascii=False)

            # 1. Import uniquement des NOUVEAUX personas (MERGE Apollo id = pas de doublon)
            if personas_found and domain:
                db.import_personas(
                    personas_found,
                    domain,
                    company_apollo_id=apollo_id,
                )
            elif personas_found and not domain:
                print(f"⚠️ Import Neo4j ignoré pour Apollo ID {apollo_id} : domaine introuvable.")

            # 2. Intent persona : TOUJOURS refresh (même si déjà présent, car évolutif)
            #    = nouveaux + tous les personas déjà liés à la company
            personas_for_signals = list(personas_found)
            known_ids = {str(p.get("id")) for p in personas_for_signals if p.get("id")}
            for existing in existing_personas:
                eid = str(existing.get("id") or "").strip()
                if eid and eid in known_ids:
                    continue
                existing["linkedin_url"] = Neo4jManager.normalize_linkedin_url(
                    existing.get("linkedin_url")
                )
                personas_for_signals.append(existing)

            print(
                f"🔁 Refresh intent LinkedIn pour {len(personas_for_signals)} persona(s) "
                f"(nouveaux={len(personas_found)}, existants={len(existing_personas)})."
            )

            for persona in personas_for_signals:
                linkedin_url = Neo4jManager.normalize_linkedin_url(persona.get("linkedin_url"))
                full_name = (
                    persona.get("name")
                    or persona.get("full_name")
                    or persona.get("clean_name_used")
                    or persona.get("raw_name_from_google")
                    or "Inconnu"
                )

                if linkedin_url and "linkedin.com/in/" in str(linkedin_url).lower():
                    safe_name_file = str(full_name).replace(" ", "_").replace("/", "")
                    output_filename = os.path.join(signals_dir, f"signals_{safe_name_file}.json")
                    try:
                        scrape_result = post_scraper.fetch_persona_signals(
                            linkedin_url=linkedin_url,
                            output_filename=output_filename,
                            trace_operation="persona_posts",
                            trace_identifier=safe_name_file,
                        )
                        posts_data = scrape_result.get("posts", []) if isinstance(scrape_result, dict) else scrape_result
                        if posts_data:
                            db.bulk_import_persona_posts(
                                posts_list=posts_data,
                                persona_linkedin_url=linkedin_url,
                            )
                            persona_intent = generate_persona_intent_summary(full_name, posts_data)
                            db.update_persona_intent(linkedin_url, persona_intent)
                    except Exception as e:
                        print(f"⚠️ Erreur posts LinkedIn pour {full_name}: {e}")

            results[apollo_id] = {
                "status": "Personas, Posts and Behavioral Intents Fully Enriched",
                "personas_count": len(personas_found),
                "personas_file": personas_output if personas_found else None,
                "domain": domain,
                "personas_already_in_db": len(persona_index["ids"]),
                "persona_intents_refreshed": len(personas_for_signals),
            }
        except Exception as e:
            print(f"❌ Erreur traitement Personas pour Apollo ID {apollo_id}: {e}")
            results[apollo_id] = {"status": "Error", "message": str(e)}

    db.close()
    return results


def request_run_csv_company_workflow(
    csv_filepath: str,
    limit: int = 10,
    limit_per_element: int = 1,
    role: Optional[list] = None,
) -> list:
    """
    Lit un fichier CSV avec des colonnes 'industry' et 'country', puis exécute
    successivement discover_companies, enrich_company_intents et enrich_company_personas
    pour chaque combinaison industry/country trouvée.
    """
    if not csv_filepath:
        raise ValueError("Le chemin du fichier CSV est obligatoire.")
    if not os.path.exists(csv_filepath):
        raise FileNotFoundError(f"Fichier CSV introuvable : {csv_filepath}")

    parsed_rows = []
    with open(csv_filepath, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        fields = [f.strip().lower() for f in (reader.fieldnames or [])]
        if 'industry' not in fields or 'country' not in fields:
            raise ValueError("Le fichier CSV doit contenir les colonnes 'industry' et 'country'.")

        for row in reader:
            industry = row.get('industry') or row.get('Industry') or row.get('INDUSTRY')
            country = row.get('country') or row.get('Country') or row.get('COUNTRY')
            if industry:
                industry = str(industry).strip()
            if country:
                country = str(country).strip()
            if industry and country:
                parsed_rows.append((industry, country))

    if not parsed_rows:
        raise ValueError("Aucune ligne valide n'a été trouvée dans le fichier CSV.")

    grouped = {}
    for industry, country in parsed_rows:
        grouped.setdefault(industry, []).append(country)

    workflow_results = []

    for industry, countries in grouped.items():
        for country in countries:
            iteration_result = {
                'industry': industry,
                'country': country,
                'discover': None,
                'intents': None,
                'personas': None,
            }

            discovered_companies = request_discover_companies(
                industries=[industry],
                locations=[country],
                continent=None,
                employee_ranges=None,
                limit=limit,
                limit_per_element=limit_per_element,
            )
            iteration_result['discover'] = {
                'companies_count': len(discovered_companies),
                'companies': discovered_companies,
            }

            apollo_ids = []
            for company in discovered_companies:
                if not isinstance(company, dict):
                    continue
                apollo_id = company.get('apollo_id')
                if apollo_id:
                    apollo_ids.append(apollo_id)

            apollo_ids = list(dict.fromkeys(apollo_ids))

            if apollo_ids:
                intents_result = request_enrich_company_intents(apollo_ids)
            else:
                intents_result = {
                    'status': 'skipped',
                    'reason': 'No apollo_id found for discovered companies.'
                }
            iteration_result['intents'] = intents_result

            if apollo_ids:
                personas_result = request_enrich_company_personas(apollo_ids, role=role)
            else:
                personas_result = {
                    'status': 'skipped',
                    'reason': 'No apollo_id found for discovered companies.'
                }
            iteration_result['personas'] = personas_result

            workflow_results.append(iteration_result)

    return workflow_results

# =========================================================================
# --- REQUÊTE 4 : RECHERCHE dans la base neo4j Aura ---
# =========================================================================

def request_search_local_companies(industry: str, country: str) -> list:
    """
    Exécute une recherche locale dans le graphe Neo4j pour trouver les entreprises déjà
    enregistrées correspondant à l'industrie et au pays fournis.
    """
    db = Neo4jManager()
    try:
        companies = db.get_companies_by_industry_and_country(industry, country)
        return companies
    finally:
        db.close()
        
def request_search_local_companies_by_employees(industry: str, country: str, min_employees: int = None, max_employees: int = None) -> list:
    """
    Exécute une recherche locale dans le graphe Neo4j pour trouver les entreprises déjà
    enregistrées correspondant à l'industrie, au pays et à la taille de l'effectif.
    """
    db = Neo4jManager()
    try:
        companies = db.get_companies_by_filters(industry, country, min_employees, max_employees)
        return companies
    finally:
        db.close()


def _parse_llm_json_list(raw_text: str) -> list:
    """Extract a JSON array of strings from an LLM response (tolerates markdown fences)."""
    if not raw_text or not str(raw_text).strip():
        return []
    text = str(raw_text).strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            parsed = json.loads(text[start : end + 1])
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if item is not None and str(item).strip()]


def _casefold_map(values: list) -> dict:
    """Map lowercased label → original DB label (first wins)."""
    mapping = {}
    for value in values or []:
        if value is None:
            continue
        key = str(value).strip().casefold()
        if key and key not in mapping:
            mapping[key] = str(value).strip()
    return mapping


def _match_icp_industries_via_llm(icp_industry: str, db_industries: list) -> list:
    """
    Map an ICP industry label to close/matching `v.industry` values present in Neo4j.
    Uses exact/substring heuristics first, then Groq/ESPRIT LLM for semantic matches.
    """
    if not icp_industry or not str(icp_industry).strip():
        return []
    if not db_industries:
        return []

    icp = str(icp_industry).strip()
    icp_cf = icp.casefold()
    by_cf = _casefold_map(db_industries)
    matched = []

    # 1) Exact case-insensitive
    if icp_cf in by_cf:
        matched.append(by_cf[icp_cf])

    # 2) Substring containment both ways
    for key, original in by_cf.items():
        if original in matched:
            continue
        if icp_cf in key or key in icp_cf:
            matched.append(original)

    # 3) LLM semantic match against the DB catalog
    catalog_for_llm = list(db_industries)
    # Cap prompt size while keeping matched ones + a broad catalog
    if len(catalog_for_llm) > 250:
        catalog_for_llm = catalog_for_llm[:250]

    try:
        llm_response = invoke_template(
            INDUSTRY_TAXONOMY_MATCH,
            icp=icp,
            catalog_json=json.dumps(catalog_for_llm, ensure_ascii=False),
            temperature=0.2,
            max_tokens=400,
            fallback="[]",
            operation="industry_taxonomy_match",
        )
        llm_picks = _parse_llm_json_list(llm_response)
        for pick in llm_picks:
            pick_cf = pick.casefold()
            if pick_cf in by_cf and by_cf[pick_cf] not in matched:
                matched.append(by_cf[pick_cf])
            elif pick in db_industries and pick not in matched:
                matched.append(pick)
    except Exception as e:
        print(f"[WARNING] Industry LLM matching failed: {e}")

    if matched:
        print(f"🏭 Industry match for ICP '{icp}' → {matched}")
    else:
        print(f"⚠️ No industry match found in Neo4j for ICP '{icp}'")
    return matched


def _resolve_countries_present_in_db(
    country: Optional[str],
    continent: Optional[str],
    db_countries: list,
) -> dict:
    """
    Resolve requested country/continent against countries that actually exist in Neo4j.

    Returns:
      {
        "requested": [...],
        "present": [...],   # intersection / mapped labels as stored in DB
        "missing": [...],
        "db_countries": [...],
      }
    """
    by_cf = _casefold_map(db_countries)
    requested = []

    if country and str(country).strip():
        requested = [str(country).strip()]
    elif continent and str(continent).strip():
        try:
            llm_response = invoke_template(
                CONTINENT_COUNTRIES,
                continent=continent,
                temperature=0.2,
                max_tokens=400,
                fallback="[]",
                operation="continent_countries",
            )
            requested = _parse_llm_json_list(llm_response)
        except Exception as e:
            print(f"[WARNING] Continent→countries LLM expansion failed: {e}")
            requested = []

    if not requested:
        return {
            "requested": [],
            "present": [],
            "missing": [],
            "db_countries": list(db_countries or []),
            "geo_filter_applied": False,
        }

    present = []
    missing = []
    unresolved = []

    for name in requested:
        key = name.casefold()
        if key in by_cf:
            mapped = by_cf[key]
            if mapped not in present:
                present.append(mapped)
        else:
            unresolved.append(name)

    # Alias / spelling rescue via LLM against DB country catalog
    if unresolved and db_countries:
        try:
            llm_response = invoke_template(
                COUNTRY_ALIAS_MATCH,
                requested_json=json.dumps(unresolved, ensure_ascii=False),
                catalog_json=json.dumps(list(db_countries)[:300], ensure_ascii=False),
                temperature=0.2,
                max_tokens=400,
                fallback="[]",
                operation="country_alias_match",
            )
            mapped_names = _parse_llm_json_list(llm_response)
            for mapped in mapped_names:
                key = mapped.casefold()
                if key in by_cf and by_cf[key] not in present:
                    present.append(by_cf[key])
                elif mapped in db_countries and mapped not in present:
                    present.append(mapped)
            still_missing = []
            present_cf = {c.casefold() for c in present}
            for name in unresolved:
                if name.casefold() not in present_cf and not any(
                    name.casefold() in p.casefold() or p.casefold() in name.casefold()
                    for p in present
                ):
                    still_missing.append(name)
            missing = still_missing
        except Exception as e:
            print(f"[WARNING] Country alias LLM matching failed: {e}")
            missing = unresolved
    else:
        missing = unresolved

    print(
        f"🌍 Geo resolve — requested={requested}, present_in_db={present}, missing={missing}"
    )
    return {
        "requested": requested,
        "present": present,
        "missing": missing,
        "db_countries": list(db_countries or []),
        "geo_filter_applied": True,
    }


def request_search_companies_by_geo_llm(
    industry: str,
    country: Optional[str] = None,
    continent: Optional[str] = None,
    min_employees: Optional[int] = None,
    max_employees: Optional[int] = None,
) -> list:
    """
    Local Neo4j company search with optional geo + size filters.

    - Matches on specific `v.industry` (not global_industry), expanding the ICP
      industry label to close DB industries via Groq/ESPRIT LLM.
    - Country / continent are optional. When provided, expands continent→countries
      via LLM then keeps only countries that exist in Neo4j.
    - Employee min/max are optional.
    Priority: country > continent when both are set.
    """
    if not industry or not str(industry).strip():
        return []

    db = Neo4jManager()
    try:
        db_industries = db.get_distinct_industries()
        matched_industries = _match_icp_industries_via_llm(industry, db_industries)
        if not matched_industries:
            print(
                f"ℹ️ Aucune industry Neo4j proche de '{industry}' — "
                f"recherche locale abandonnée."
            )
            return []

        countries_filter = None
        if (country and str(country).strip()) or (continent and str(continent).strip()):
            db_countries = db.get_distinct_countries()
            geo = _resolve_countries_present_in_db(country, continent, db_countries)
            if geo["geo_filter_applied"] and not geo["present"]:
                print(
                    f"ℹ️ Aucun pays demandé présent en base "
                    f"(requested={geo['requested']}, db_sample={db_countries[:10]})."
                )
                return []
            countries_filter = geo["present"] or None
            if geo["missing"]:
                print(
                    f"⚠️ Pays absents de Neo4j (ignorés) : {geo['missing']}"
                )
        else:
            print("ℹ️ Pas de filtre pays/continent — recherche sur toutes les géos en base.")

        companies = db.get_companies_by_geo_intel(
            matched_industries,
            countries_filter,
            min_employees,
            max_employees,
        )
        print(
            f"✅ Geo-intel local: {len(companies)} entreprise(s) "
            f"(industries={matched_industries}, countries={countries_filter}, "
            f"employees={min_employees}-{max_employees})"
        )
        return companies
    finally:
        db.close()
        
def request_company_raw_intent(apollo_id: str) -> str:
    """
    Interroge Neo4j pour obtenir uniquement la chaîne company_intent du nœud Company spécifié.
    """
    if not apollo_id:
        return "Erreur : L'apollo_id fourni est vide."
        
    db = Neo4jManager()
    try:
        clean_apollo_id = apollo_id.strip().lower()
        return db.get_company_raw_intent_by_domain(clean_apollo_id)
    finally:
        db.close()
        
def request_company_personas_by_domain(apollo_id: str) -> list:
    """
    Interroge le graphe Neo4j pour extraire tous les personas (décideurs) rattachés
    à un Apollo ID d'entreprise.
    """
    if not apollo_id:
        return []
        
    db = Neo4jManager()
    try:
        clean_apollo_id = apollo_id.strip()
        return db.get_company_personas_by_apollo_id(clean_apollo_id)
    finally:
        db.close()     
        
def request_company_personas_with_signals(apollo_id: str) -> list:
    """
    Interroge le graphe Neo4j pour extraire tous les personas et leurs signaux d'intention (intent)
    rattachés à un Apollo ID d'entreprise.
    """
    if not apollo_id:
        return []
        
    db = Neo4jManager()
    try:
        clean_apollo_id = apollo_id.strip()
        return db.get_company_personas_with_signals_by_apollo_id(clean_apollo_id)
    finally:
        db.close()


def request_enrich_persona(persona_apollo_id: str) -> dict:
    """
    Enrichit un persona via Apollo /people/match (sans waterfall ni reveal)
    et met à jour le nœud Persona correspondant dans Neo4j.
    """
    if not persona_apollo_id:
        return {"status": "error", "message": "Le persona_apollo_id est obligatoire."}

    clean_id = persona_apollo_id.strip()
    print(f"📧 [R4] Enrichissement email du persona Apollo ID : {clean_id}")

    match_result = enrich_person_with_traces(
        person_id=clean_id,
        operation="enrich_email",
        run_waterfall_email=False,
        run_waterfall_phone=False,
        reveal_personal_emails=False,
        reveal_phone_number=False,
    )

    person = match_result.get("person") if match_result else None
    if not person:
        return {
            "status": "error",
            "message": f"Aucun profil retourné par Apollo pour l'ID {clean_id}.",
        }

    email = person.get("email")
    sanitized_emails = person.get("sanitized_emails") or []
    person["has_email"] = bool(email or sanitized_emails)
    person["mail_pro"] = check_email_pro_llm(email) if email else False
    person["source"] = person.get("source") or "Apollo"

    db = Neo4jManager()
    try:
        updated = db.update_persona_by_apollo_id(clean_id, person)
        if not updated:
            return {
                "status": "error",
                "message": f"Persona '{clean_id}' introuvable en base Neo4j. Importez-le d'abord via enrich_company_personas.",
                "apollo_response": {
                    "email": email,
                    "sanitized_emails": sanitized_emails,
                    "email_status": person.get("email_status"),
                },
            }

        return {
            "status": "success",
            "persona_apollo_id": clean_id,
            "email": email,
            "sanitized_emails": sanitized_emails,
            "email_status": person.get("email_status"),
            "email_domain_catchall": person.get("email_domain_catchall"),
            "email_domain_catchall_verdict": person.get("email_domain_catchall_verdict"),
            "mail_pro": person.get("mail_pro"),
            "has_email": person.get("has_email"),
            "linkedin_url": person.get("linkedin_url"),
            "full_name": person.get("name") or person.get("full_name"),
        }
    finally:
        db.close()


def request_enrich_persona_phone(persona_apollo_id: str) -> dict:
    """
    Enrichit le numéro de téléphone d'un persona via Apollo /people/match
    (reveal_phone=true, sans waterfall ni reveal email) et met à jour Neo4j.
    """
    if not persona_apollo_id:
        return {"status": "error", "message": "Le persona_apollo_id est obligatoire."}

    clean_id = persona_apollo_id.strip()
    print(f"📞 [R5] Enrichissement téléphone du persona Apollo ID : {clean_id}")

    match_result = enrich_person_with_traces(
        person_id=clean_id,
        operation="enrich_phone",
        run_waterfall_email=False,
        run_waterfall_phone=False,
        reveal_personal_emails=False,
        reveal_phone_number=True,
    )

    person = match_result.get("person") if match_result else None
    if not person:
        return {
            "status": "error",
            "message": f"Aucun profil retourné par Apollo pour l'ID {clean_id}.",
        }

    phone_numbers = person.get("phone_numbers") or []
    sanitized_numbers = person.get("sanitized_numbers") or []
    raw_numbers = person.get("raw_numbers") or []
    email = person.get("email")
    sanitized_emails = person.get("sanitized_emails") or []
    emails = person.get("emails") or []
    person["has_phone"] = bool(phone_numbers or sanitized_numbers or raw_numbers)
    person["has_email"] = bool(email or sanitized_emails or emails)
    person["source"] = person.get("source") or "Apollo"

    db = Neo4jManager()
    try:
        updated = db.update_persona_by_apollo_id(clean_id, person)
        if not updated:
            return {
                "status": "error",
                "message": f"Persona '{clean_id}' introuvable en base Neo4j. Importez-le d'abord via enrich_company_personas.",
                "apollo_response": {
                    "phone_numbers": phone_numbers,
                    "sanitized_numbers": sanitized_numbers,
                    "raw_numbers": raw_numbers,
                    "email": email,
                    "sanitized_emails": sanitized_emails,
                    "emails": emails,
                },
            }

        return {
            "status": "success",
            "persona_apollo_id": clean_id,
            "phone_numbers": phone_numbers,
            "sanitized_numbers": sanitized_numbers,
            "raw_numbers": raw_numbers,
            "has_phone": person.get("has_phone"),
            "email": email,
            "sanitized_emails": sanitized_emails,
            "emails": emails,
            "email_status": person.get("email_status"),
            "email_domain_catchall": person.get("email_domain_catchall"),
            "email_domain_catchall_verdict": person.get("email_domain_catchall_verdict"),
            "has_email": person.get("has_email"),
            "linkedin_url": person.get("linkedin_url"),
            "full_name": person.get("name") or person.get("full_name"),
        }
    finally:
        db.close()


def request_enrich_persona_personal_email(persona_apollo_id: str) -> dict:
    """
    Enrichit l'email personnel d'un persona via Apollo /people/match
    (reveal_personal_emails=true, sans waterfall ni reveal phone) et met à jour Neo4j.
    """
    if not persona_apollo_id:
        return {"status": "error", "message": "Le persona_apollo_id est obligatoire."}

    clean_id = persona_apollo_id.strip()
    print(f"📧 [R6] Enrichissement email personnel du persona Apollo ID : {clean_id}")

    match_result = enrich_person_with_traces(
        person_id=clean_id,
        operation="enrich_personal_email",
        run_waterfall_email=False,
        run_waterfall_phone=False,
        reveal_personal_emails=True,
        reveal_phone_number=False,
    )

    person = match_result.get("person") if match_result else None
    if not person:
        return {
            "status": "error",
            "message": f"Aucun profil retourné par Apollo pour l'ID {clean_id}.",
        }

    email = person.get("email")
    sanitized_emails = person.get("sanitized_emails") or []
    emails = person.get("emails") or []
    person["has_email"] = bool(email or sanitized_emails or emails)
    person["mail_pro"] = check_email_pro_llm(email) if email else False
    person["source"] = person.get("source") or "Apollo"

    db = Neo4jManager()
    try:
        updated = db.update_persona_by_apollo_id(clean_id, person)
        if not updated:
            return {
                "status": "error",
                "message": f"Persona '{clean_id}' introuvable en base Neo4j. Importez-le d'abord via enrich_company_personas.",
                "apollo_response": {
                    "email": email,
                    "sanitized_emails": sanitized_emails,
                    "emails": emails,
                    "email_status": person.get("email_status"),
                },
            }

        return {
            "status": "success",
            "persona_apollo_id": clean_id,
            "email": email,
            "sanitized_emails": sanitized_emails,
            "emails": emails,
            "email_status": person.get("email_status"),
            "email_domain_catchall": person.get("email_domain_catchall"),
            "email_domain_catchall_verdict": person.get("email_domain_catchall_verdict"),
            "mail_pro": person.get("mail_pro"),
            "has_email": person.get("has_email"),
            "linkedin_url": person.get("linkedin_url"),
            "full_name": person.get("name") or person.get("full_name"),
        }
    finally:
        db.close()


def request_enrich_persona_waterfall_phone(persona_apollo_id: str) -> dict:
    """
    Enrichit le téléphone d'un persona via Apollo waterfall phone
    (run_waterfall_phone=true, autres flags false) et met à jour Neo4j.
    """
    if not persona_apollo_id:
        return {"status": "error", "message": "Le persona_apollo_id est obligatoire."}

    clean_id = persona_apollo_id.strip()
    print(f"📞 [R7] Waterfall téléphone du persona Apollo ID : {clean_id}")

    match_result = enrich_person_with_traces(
        person_id=clean_id,
        operation="enrich_waterfall_phone",
        run_waterfall_email=False,
        run_waterfall_phone=True,
        reveal_personal_emails=False,
        reveal_phone_number=False,
    )

    person = match_result.get("person") if match_result else None
    if not person:
        return {
            "status": "error",
            "message": f"Aucun profil retourné par Apollo pour l'ID {clean_id}.",
        }

    phone_numbers = person.get("phone_numbers") or []
    sanitized_numbers = person.get("sanitized_numbers") or []
    raw_numbers = person.get("raw_numbers") or []
    email = person.get("email")
    sanitized_emails = person.get("sanitized_emails") or []
    emails = person.get("emails") or []
    person["has_phone"] = bool(phone_numbers or sanitized_numbers or raw_numbers)
    person["has_email"] = bool(email or sanitized_emails or emails)
    person["source"] = person.get("source") or "Apollo"

    db = Neo4jManager()
    try:
        updated = db.update_persona_by_apollo_id(clean_id, person)
        if not updated:
            return {
                "status": "error",
                "message": f"Persona '{clean_id}' introuvable en base Neo4j. Importez-le d'abord via enrich_company_personas.",
                "apollo_response": {
                    "phone_numbers": phone_numbers,
                    "sanitized_numbers": sanitized_numbers,
                    "raw_numbers": raw_numbers,
                    "email": email,
                    "sanitized_emails": sanitized_emails,
                    "emails": emails,
                },
            }

        return {
            "status": "success",
            "persona_apollo_id": clean_id,
            "phone_numbers": phone_numbers,
            "sanitized_numbers": sanitized_numbers,
            "raw_numbers": raw_numbers,
            "has_phone": person.get("has_phone"),
            "email": email,
            "sanitized_emails": sanitized_emails,
            "emails": emails,
            "email_status": person.get("email_status"),
            "email_domain_catchall": person.get("email_domain_catchall"),
            "email_domain_catchall_verdict": person.get("email_domain_catchall_verdict"),
            "has_email": person.get("has_email"),
            "linkedin_url": person.get("linkedin_url"),
            "full_name": person.get("name") or person.get("full_name"),
        }
    finally:
        db.close()


def request_enrich_persona_waterfall_email(persona_apollo_id: str) -> dict:
    """
    Enrichit l'email d'un persona via Apollo waterfall email
    (run_waterfall_email=true, autres flags false) et met à jour Neo4j.
    """
    if not persona_apollo_id:
        return {"status": "error", "message": "Le persona_apollo_id est obligatoire."}

    clean_id = persona_apollo_id.strip()
    print(f"📧 [R8] Waterfall email du persona Apollo ID : {clean_id}")

    match_result = enrich_person_with_traces(
        person_id=clean_id,
        operation="enrich_waterfall_email",
        run_waterfall_email=True,
        run_waterfall_phone=False,
        reveal_personal_emails=False,
        reveal_phone_number=False,
    )

    person = match_result.get("person") if match_result else None
    if not person:
        return {
            "status": "error",
            "message": f"Aucun profil retourné par Apollo pour l'ID {clean_id}.",
        }

    email = person.get("email")
    sanitized_emails = person.get("sanitized_emails") or []
    emails = person.get("emails") or []
    person["has_email"] = bool(email or sanitized_emails or emails)
    person["mail_pro"] = check_email_pro_llm(email) if email else False
    person["source"] = person.get("source") or "Apollo"

    db = Neo4jManager()
    try:
        updated = db.update_persona_by_apollo_id(clean_id, person)
        if not updated:
            return {
                "status": "error",
                "message": f"Persona '{clean_id}' introuvable en base Neo4j. Importez-le d'abord via enrich_company_personas.",
                "apollo_response": {
                    "email": email,
                    "sanitized_emails": sanitized_emails,
                    "emails": emails,
                    "email_status": person.get("email_status"),
                },
            }

        return {
            "status": "success",
            "persona_apollo_id": clean_id,
            "email": email,
            "sanitized_emails": sanitized_emails,
            "emails": emails,
            "email_status": person.get("email_status"),
            "email_domain_catchall": person.get("email_domain_catchall"),
            "email_domain_catchall_verdict": person.get("email_domain_catchall_verdict"),
            "mail_pro": person.get("mail_pro"),
            "has_email": person.get("has_email"),
            "linkedin_url": person.get("linkedin_url"),
            "full_name": person.get("name") or person.get("full_name"),
        }
    finally:
        db.close()
