import os
import json
import httpx
from openai import OpenAI
import config
from apollo_scraper import ApolloScraper
from database_manager import Neo4jManager
from smart_scraper_ai import SmartScraperAI
from persona_search_enrich import search_and_enrich
from persona_posts_scraper import PersonaPostScraper
from intent_global_orchestrator import IntentGlobalOrchestrator # <-- NOUVEAU : Importation de l'orchestrateur d'intentions

# --- INITIALISATION DU CLIENT ESPRIT TOKEN FACTORY ---
http_client = httpx.Client(verify=False)
llm_client = OpenAI(
    api_key=config.ESPRIT_TOKEN_FACTORY_KEY,
    base_url="https://tokenfactory.esprit.tn/api",
    http_client=http_client
)

def call_esprit_llm(prompt: str) -> str:
    """
    Appelle le modèle LLM de l'ESPRIT via la Token Factory.
    """
    try:
        response = llm_client.chat.completions.create(
            model="hosted_vllm/Llama-3.1-70B-Instruct",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert B2B data enrichment engineer. Your goal is to write a comprehensive, professional, and impactful company description in English based on raw data points. Do not include any introductory or concluding remarks like 'Here is the description'."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=400
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Erreur lors de l'appel LLM ESPRIT : {e}")
        return "Non renseigné"

def generate_company_intent_summary(company_profile, intent_signals):
    """Generate a concise English company intent summary with the Esprit LLM."""
    company_name = company_profile.get("name") or "the company"

    if not intent_signals:
        return f"{company_name} currently shows no recent commercial intent signals."

    selected_signals = []
    for item in intent_signals[:8]:
        title = item.get("title") or item.get("title_and_summary") or item.get("headline") or ""
        if title:
            selected_signals.append(title)

    signal_text = " | ".join(selected_signals) if selected_signals else "recent hiring and company updates"

    prompt = f"""
    Write a short, professional, and natural English summary of the commercial intent of '{company_name}' based on these signals:
    {signal_text}

    The summary should describe whether the company is hiring, expanding, launching products, or showing other growth signals.
    Return only one concise paragraph in English.
    """

    summary = call_esprit_llm(prompt)
    if summary and summary != "Non renseigné":
        return summary

    return f"{company_name} shows recent commercial intent signals including hiring and company updates."


def generate_company_full_description(company_profile):
    """
    Compile TOUS les attributs disponibles et appelle l'IA pour générer un paragraphe descriptif complet en anglais.
    """
    # 1. Identité de base
    name = company_profile.get("name") or "Unknown"
    domain = company_profile.get("domain") or "Unknown"
    website_url = company_profile.get("website_url") or "Not specified"
    industry = company_profile.get("industry") or "Not specified"
    founded_year = company_profile.get("founded_year") or "Not specified"
    
    # 2. Descriptions existantes
    short_desc = company_profile.get("short_description") or "Not specified"
    seo_desc = company_profile.get("seo_description") or "Not specified"
    
    # 3. Performance & Chiffres
    revenue = company_profile.get("annual_revenue") or "Not specified"
    employees = company_profile.get("estimated_num_employees") or "Not specified"
    alexa_ranking = company_profile.get("alexa_ranking") or "Not specified"
    total_funding = company_profile.get("total_funding") or "Not specified"
    funding_stage = company_profile.get("latest_funding_stage") or "Not specified"
    
    # 4. Localisation
    country = company_profile.get("country")
    if not country or country == "Non renseigné":
        country = company_profile.get("location", {}).get("country", "Not specified")
        
    city = company_profile.get("city")
    if not city or city == "Non renseigné":
        city = company_profile.get("location", {}).get("city", "Not specified")
        
    # 5. Réseaux & Contact
    linkedin_url = company_profile.get("linkedin_url") or "Not specified"
    phone = company_profile.get("phone") or "Not specified"

    # 6. Sécurisation et extraction des listes/dictionnaires
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

    # Si l'entreprise est vide de sens, on ignore
    if short_desc in ["Non renseigné", "Not specified"] and industry in ["Non renseigné", "Not specified"] and not keywords:
        company_profile["full_description"] = "Non renseigné"
        return company_profile

    # --- CONSTRUCTION DU PROMPT EXHAUSTIF ---
    prompt = f"""
    Write a complete, detailed, and highly professional corporate overview (full_description) in English for '{name}'.
    Synthesize all the following raw attributes into a natural, cohesive paragraph (4 to 7 sentences maximum). 
    Do not just list the facts; weave them together to present the company's scale, market position, and technological footprint.
    
    --- Raw Data Profile ---
    [Identity & Web]
    - Company Name: {name}
    - Domain / Website: {domain} / {website_url}
    - Industry: {industry}
    - Founded Year: {founded_year}
    - Headquarters: {city}, {country}
    
    [Performance & Scale]
    - Estimated Annual Revenue: {revenue}
    - Estimated Employees: {employees}
    - Total Funding & Stage: {total_funding} ({funding_stage})
    - Web Popularity (Alexa Ranking): {alexa_ranking}
    - Major Departments (Headcount): {deps_str}
    
    [Market & Technology]
    - Short Description: {short_desc}
    - SEO Description: {seo_desc}
    - Top Industry Keywords: {kws_str}
    - Key Technologies Used: {techs_str}
    - Known Competitors: {comps_str}
    
    [Contact Presence]
    - LinkedIn: {linkedin_url}
    - Phone: {phone}
    
    Respond ONLY with the final generated text paragraph.
    """
    
    print(f"🧠 Génération LLM (Full Description avec {len(company_profile)} attributs) pour : {name}...")
    full_desc = call_esprit_llm(prompt)
    
    # On assigne le résultat à l'objet
    company_profile["full_description"] = full_desc
    return company_profile


def generate_merged_report(apollo_data, ai_json_path, output_dir="merged_profiles"):
    """
    Fusionne les données Apollo et SmartScraper AI en un seul profil unifié.
    """
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

    # --- HELPERS D'EXTRACTION & PARSING ---
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
        if not is_valid(val):
            return []
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
            except:
                if "[" not in val and "{" not in val:
                    return [v.strip() for v in val.split(',') if v.strip()]
                return []
        if isinstance(val, list):
            return val
        return []

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
        "domain": ("identity", "domain"),
        "name": ("identity", "name"),
        "industry": ("identity", "industry"),
        "founded_year": ("identity", "founded_year"),
        "short_description": ("identity", "short_description"),
        "seo_description": ("identity", "seo_description"),
        "annual_revenue": ("performance", "annual_revenue_USD"),
        "total_funding": ("performance", "total_funding"),
        "estimated_num_employees": ("performance", "estimated_num_employees"),
        "latest_funding_stage": ("performance", "latest_funding_stage"),
        "linkedin_url": ("contact_social", "linkedin_url"),
        "twitter_url": ("contact_social", "twitter_url"),
        "facebook_url": ("contact_social", "facebook_url"),
        "phone": ("contact_social", "phone"),
        "num_suborganizations": ("hierarchy", "num_suborganizations"),
        "raw_address": ("location_detailed", "raw_address"),
        "city": ("location_detailed", "city"),
        "country": ("location_detailed", "country")
    }

    for attr in all_db_attributes:
        db_val = get_db_val(attr)
        db_valid = is_valid(db_val)

        if attr == "technologies":
            db_techs = parse_list_safely(db_val)
            ai_techs = ai_data.get("technologies", [])
            
            if db_valid or len(ai_techs) > 0:
                merged_techs = {}
                if db_valid:
                    for t in db_techs:
                        if isinstance(t, dict) and "name" in t:
                            tech_name = t["name"].lower()
                            merged_techs[tech_name] = {
                                "uid": t.get("uid", tech_name.replace(" ", "_")),
                                "name": t.get("name"),
                                "category": t.get("category", "Other")
                            }
                for t in ai_techs:
                    if isinstance(t, dict) and "name" in t:
                        tech_name = t["name"].lower()
                        if tech_name not in merged_techs:
                            generated_uid = t.get("uid", tech_name.replace(" ", "_").replace("-", "_"))
                            merged_techs[tech_name] = {
                                "uid": generated_uid,
                                "name": t.get("name"),
                                "category": t.get("category", "Other")
                            }
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
                            merged_subs[s.lower().strip()] = {"id": "Non renseigné", "name": s, "domain": "Non renseigné"}

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
                            merged_subs[sub_name] = {"id": "Non renseigné", "name": s, "domain": "Non renseigné"}
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
                            if sig != "_": seen_signatures.add(sig)

                for f in ai_fundings:
                    if isinstance(f, dict):
                        sig = get_signature(f)
                        normalized_f = normalize_funding(f)
                        if sig == "_" or sig not in seen_signatures:
                            merged_fundings.append(normalized_f)
                            if sig != "_": seen_signatures.add(sig)

                merged_profile[attr] = merged_fundings
            else:
                merged_profile[attr] = []

        elif attr in common_mapping:
            ai_cat, ai_field = common_mapping[attr]
            ai_val, ai_conf = get_ai_val_and_conf(ai_cat, ai_field)
            ai_valid = is_valid(ai_val)

            if not db_valid and ai_valid:
                merged_profile[attr] = ai_val
            elif db_valid and ai_valid:
                if ai_conf >= CONFIDENCE_THRESHOLD:
                    merged_profile[attr] = ai_val
                else:
                    merged_profile[attr] = db_val
            elif db_valid and not ai_valid:
                merged_profile[attr] = db_val
            else:
                merged_profile[attr] = None
        else:
            if db_valid:
                merged_profile[attr] = db_val

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

def generate_persona_intent_summary(persona_name, posts_data):
    """
    Analyse la liste des posts d'un persona et génère un résumé global (intent)
    exploitable pour l'approche commerciale.
    """
    if not posts_data:
        return "Aucune activité récente pour déduire une intention."

    # Rassembler les signaux extraits de chaque post
    signals_summary = []
    for i, post in enumerate(posts_data, 1):
        bs = post.get("businessSignal", "N/A")
        pi = post.get("personaInterest", "N/A")
        kt = post.get("keyTakeaway", "N/A")
        
        # On ne garde que les signaux valides
        if bs != "N/A" or pi != "N/A" or kt != "N/A":
            signals_summary.append(f"Post {i}: Signal={bs} | Interest={pi} | Takeaway={kt}")

    if not signals_summary:
        return "Activité détectée, mais aucun signal d'affaires clair n'a été extrait."

    joined_signals = "\n".join(signals_summary)

    prompt = f"""
    You are an expert B2B Sales Analyst. I have collected recent LinkedIn activity signals from a prospect named '{persona_name}'.
    Based on the list of signals below (Business Signals, Interests, and Key Takeaways from their recent posts), write a concise, powerful 3-4 sentence summary of their current INTENT.
    What are they currently focused on? What problems are they trying to solve? How should a sales rep approach them?
    
    Write the response in English. Do not include introductory phrases, just the summary.
    
    --- Recent Signals ---
    {joined_signals}
    """

    print(f"🧠 Génération du résumé d'intention (Intent) pour : {persona_name}...")
    
    try:
        response = llm_client.chat.completions.create(
            model="hosted_vllm/Llama-3.1-70B-Instruct",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert B2B Sales Analyst. Return only the generated text in French."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=250
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Erreur lors de la génération de l'intent pour {persona_name}: {e}")
        return "Impossible de générer le résumé d'intention."


def discover_and_inject():
    # --- CONFIGURATION DYNAMIQUE ---
    TARGET_INDUSTRY = "Aerospace"  # Exemple : "Cosmetics", "Software", "Healthcare"
    TARGET_LOCATION = "Germany"  # Exemple : "France", "Germany", "United Kingdom"
    MAX_COMPANIES_TO_GET = 2  

    scraper = ApolloScraper(config.APOLLO_API_KEY)
    db = Neo4jManager()
    ai_scraper = SmartScraperAI() 
    post_scraper = PersonaPostScraper()
    
    # NOUVEAU : Initialisation de l'orchestrateur d'intentions globales des entreprises
    intent_orchestrator = IntentGlobalOrchestrator()
    
    all_discovered_personas = {}
    all_company_intents = {} # Dictionnaire pour stocker les intentions d'entreprise

    # 1. PHASE DE DÉCOUVERTE (SEARCH)
    print(f"🔎 Recherche initiale de {MAX_COMPANIES_TO_GET} entreprises en {TARGET_LOCATION}...")
    basic_companies = scraper.search_companies(
        industries=[TARGET_INDUSTRY],
        locations=[TARGET_LOCATION],
        limit=MAX_COMPANIES_TO_GET
    )

    if not basic_companies:
        print("❌ Résultats de recherche vides. Vérifiez les filtres ou la clé API.")
        db.close()
        return

    # 2. PHASE D'ENRICHISSEMENT & SCRAPING IA
    apollo_batch = []
    merged_batch = []
    
    print(f"💎 Enrichissement profond de {len(basic_companies)} entreprises...")

    for company in basic_companies:
        domain = company.get('domain')
        valid_domain = domain and domain != "Non renseigné"

        full_data = company
        merged_data = None

        # --- ENRICHISSEMENT APOLLO ---
        if valid_domain:
            print(f"💎 Tentative d'enrichissement pour le domaine : {domain}...")
            try:
                enriched_data = scraper.enrich_organization(domain=domain, target_location=TARGET_LOCATION)
                if enriched_data:
                    full_data = enriched_data
                else:
                    print(f"🟠 Fallback : Enrichissement échoué. Utilisation des données basiques.")
            except Exception as e:
                print(f"⚠️ Erreur API lors de l'enrichissement : {e}")
                print(f"🟠 Fallback : Utilisation des données basiques.")
        else:
            print(f"⏩ Aucun domaine pour {company.get('name', 'Compagnie inconnue')}. Enrichissement Apollo ignoré.")

        # --- ÉTAPE : SMART SCRAPER AI ---
        website_url = full_data.get('website_url') or full_data.get('website')
        loc = full_data.get("location", {})
        street = loc.get("street_address", "")
        city = loc.get("city", "")
        country = loc.get("country", "")
        
        addr_parts = [p for p in [street, city, country] if p and p != "Non renseigné"]
        target_addr = ", ".join(addr_parts)

        if valid_domain and website_url and website_url != "Non renseigné" and website_url.startswith("http"):
            print(f"🤖 Lancement de SmartScraperAI pour le site : {website_url}")
            if target_addr:
                print(f"📍 Cible géographique transmise à l'IA : {target_addr}")
                
            try:
                path_to_json = ai_scraper.scrape_and_save(website_url, target_address=target_addr) 
                
                if path_to_json and path_to_json.endswith(".json"):
                    print(f"✅ Scraping IA terminé. Fichier généré : {path_to_json}")
                    merged_data = generate_merged_report(full_data, path_to_json)
                else:
                    print(f"⚠️ Le scraping IA n'a pas retourné de chemin valide ou de JSON.")
            except Exception as e:
                print(f"❌ Erreur lors du scraping IA de {website_url} : {e}")
        else:
            if not valid_domain:
                print(f"⚠️ SmartScraperAI ignoré car le domaine est manquant.")
            else:
                print(f"⚠️ Pas d'URL valide pour {full_data.get('name', 'cette entreprise')}, SmartScraperAI ignoré.")

        # --- RECHERCHE DE PERSONAS (SALES) ---
        if valid_domain:
            target_obj = merged_data if merged_data else full_data
            
            company_country = target_obj.get("country")
            if not company_country or company_country == "Non renseigné":
                company_country = target_obj.get("location", {}).get("country", TARGET_LOCATION)
                
            print(f"👤 Lancement de la recherche de personas (Sales) pour {domain} en {company_country}...")
            try:
                personas_found = search_and_enrich(domain=domain, location=company_country, role="Sales")
                
                if personas_found:
                    all_discovered_personas[domain] = personas_found
                    print(f"👥 {len(personas_found)} personas découverts et mis en attente pour l'injection Neo4j.")
                else:
                    print(f"ℹ️ Aucun persona trouvé pour {domain}.")
                
            except Exception as e:
                print(f"❌ Erreur lors de la recherche des personas : {e}")
                
            # --- RECHERCHE DES SIGNAUX D'INTENTION DE L'ENTREPRISE (JOBS & NEWS) ---
            print(f"🌍 Lancement de la collecte globale des signaux d'intention pour {domain}...")
            try:
                company_intents = intent_orchestrator.fetch_global_intent_signals(
                    domain=domain, 
                    target_country=company_country,
                )
                if company_intents:
                    all_company_intents[domain] = company_intents
            except Exception as e:
                print(f"❌ Erreur lors de la récupération des intentions d'entreprise : {e}")

            if merged_data:
                merged_data = target_obj
            else:
                full_data = target_obj

            if company_intents:
                company_profile_for_llm = merged_data if merged_data else full_data
                company_profile_for_llm["company_intent"] = generate_company_intent_summary(
                    company_profile_for_llm,
                    company_intents
                )

        # --- FILTRAGE DE SÉCURITÉ (Anti-Collision) ---
        current_domain = full_data.get('domain')
        current_id = full_data.get('apollo_id')
        if (not current_domain or current_domain == "Non renseigné") and (not current_id or current_id == "Non renseigné"):
            safe_name = str(full_data.get('name', 'unknown')).replace(' ', '_').lower()
            full_data['domain'] = f"unknown_{safe_name}"
            print(f"🔧 Correction Anti-Collision appliquée : domaine fictif généré -> {full_data['domain']}")

        # --- AJOUT DE GLOBAL_INDUSTRY ---
        if merged_data:
            merged_data['global_industry'] = TARGET_INDUSTRY
        else:
            full_data['global_industry'] = TARGET_INDUSTRY

        # --- APPEL LLM ESPRIT (FULL DESCRIPTION) & PREPARATION BATCHS ---
        print(f"💾 Préparation injection & Appel LLM pour : {full_data.get('name', 'Compagnie inconnue')}")
        if merged_data:
            merged_data = generate_company_full_description(merged_data)
            merged_batch.append(merged_data)
        else:
            full_data = generate_company_full_description(full_data)
            apollo_batch.append(full_data)

    # 3. INJECTION DANS NEO4J (ENTREPRISES D'ABORD)
    if apollo_batch:
        print(f"🚀 Injection de {len(apollo_batch)} profils classiques (Apollo)...")
        db.bulk_import_companies(apollo_batch)
        
    if merged_batch:
        print(f"🚀 Injection de {len(merged_batch)} profils fusionnés (Apollo+IA)...")
        db.import_merged_profiles(merged_batch)
        
    if not apollo_batch and not merged_batch:
        print("⚠️ Aucun profil n'a été conservé pour l'injection Neo4j.")

    # 3.5 INJECTION DANS NEO4J (SIGNAUX D'INTENTION DES ENTREPRISES)
    if all_company_intents:
        print(f"\n🚀 Injection des signaux d'intention (Jobs/News) pour {len(all_company_intents)} entreprises...")
        for comp_domain, intents_list in all_company_intents.items():
            if intents_list:
                # Appel de la nouvelle méthode (à créer dans database_manager.py)
                company_intent_text = None
                if intents_list:
                    company_intent_text = intents_list[0].get("company_intent") if intents_list and isinstance(intents_list[0], dict) else None
                db.bulk_import_company_intents(intents_list, comp_domain, company_intent=company_intent_text)

    # 4. INJECTION DANS NEO4J (PERSONAS ET LEURS POSTS ENSUITE)
    if all_discovered_personas:
        print(f"\n🚀 Injection des personas et de leurs signaux en base de données pour {len(all_discovered_personas)} entreprises...")
        
        signals_dir = "persona_signals_archive"
        if not os.path.exists(signals_dir):
            os.makedirs(signals_dir)
            
        for comp_domain, personas_list in all_discovered_personas.items():
            
            # --- 🛠️ NORMALISATION DES URLS LINKEDIN ---
            for persona in personas_list:
                raw_url = persona.get("linkedin_url", "")
                if raw_url and str(raw_url).lower() not in ["non trouvé", "none", "n/a", "null", ""]:
                    if "linkedin.com/in/" in raw_url:
                        profile_path = raw_url.split("linkedin.com/in/")[-1].strip(" /")
                        normalized_url = f"https://www.linkedin.com/in/{profile_path}/"
                        persona["linkedin_url"] = normalized_url

            # 4.1 Injection de base des personas
            db.import_personas(personas_list, comp_domain)
            
            # 4.2 Scraping et Injection des posts LinkedIn + Intention (Intent)
            for persona in personas_list:
                linkedin_url = persona.get("linkedin_url")
                full_name = persona.get("clean_name_used") or persona.get("raw_name_from_google") or "Inconnu"
                
                if linkedin_url and "linkedin.com/in/" in str(linkedin_url).lower():
                    print(f"\n⚡ Extraction des signaux LinkedIn pour le persona : {full_name} ({linkedin_url})")
                    safe_name_file = full_name.replace(" ", "_").replace("/", "")
                    output_filename = os.path.join(signals_dir, f"signals_{safe_name_file}.json")
                    
                    try:
                        # Scraping des posts et ajout des 3 attributs d'analyse par post
                        posts_data = post_scraper.fetch_persona_signals(
                            linkedin_url=linkedin_url,
                            posted_limit="month",
                            target_count=10,
                            output_filename=output_filename
                        )
                        
                        if posts_data:
                            # 1. Injecte les posts dans Neo4j
                            db.bulk_import_persona_posts(posts_list=posts_data, persona_linkedin_url=linkedin_url)
                            
                            # 2. --- GÉNÉRATION DU RÉSUMÉ D'INTENTION (INTENT) ---
                            persona_intent = generate_persona_intent_summary(full_name, posts_data)
                            
                            # 3. --- MISE À JOUR DU PERSONA DANS NEO4J ---
                            db.update_persona_intent(linkedin_url, persona_intent)
                            
                        else:
                            print(f"ℹ️ Aucun post récent trouvé pour {full_name}.")
                    except Exception as e:
                        print(f"❌ Erreur lors de l'extraction des signaux pour {full_name} : {e}")
                else:
                    print(f"⏩ Extraction des posts ignorée pour {full_name} (URL LinkedIn invalide ou manquante).")
    
    db.close()
    print("✅ Processus complet terminé avec succès.")

if __name__ == "__main__":
    discover_and_inject()