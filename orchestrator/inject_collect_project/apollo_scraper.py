import requests
import re
from typing import List, Optional
from apollo_api_trace import save_trace_json

# ICP labels → Apollo keyword tags (ANY OF). Apollo often stores canonical
# industries like "oil & energy", not ICP phrasing like "Oil Production".
_INDUSTRY_KEYWORD_EXPANSION = {
    "oil production": [
        "oil & energy",
        "oil and gas",
        "oil & gas",
        "petroleum",
        "oil and gas production",
        "energy & utilities",
        "Oil Production",
    ],
    "oil & energy": ["oil & energy", "oil and gas", "oil & gas", "petroleum"],
    "oil and gas": ["oil & energy", "oil and gas", "oil & gas", "petroleum"],
    "software": [
        "Software",
        "computer software",
        "information technology & services",
        "information technology and services",
        "saas",
    ],
    "information technology & services": [
        "information technology & services",
        "information technology and services",
        "information technology",
        "computer software",
        "Software",
        "IT services",
        "saas",
    ],
    "information technology and services": [
        "information technology & services",
        "information technology and services",
        "information technology",
        "computer software",
        "Software",
        "IT services",
    ],
    "information technology": [
        "information technology & services",
        "information technology",
        "computer software",
        "Software",
    ],
    "insurance": ["Insurance", "insurance", "financial services"],
    "fintech": ["fintech", "financial services", "financial technology"],
}

# Apollo expects "1,10" / "10001," — legacy hyphen / plus forms break some geos.
_EMPLOYEE_RANGE_TO_APOLLO = {
    "1-10": "1,10",
    "11-50": "11,50",
    "51-200": "51,200",
    "201-500": "201,500",
    "501-1000": "501,1000",
    "1001-5000": "1001,5000",
    "5001-10000": "5001,10000",
    "10001+": "10001,",
    "1,10": "1,10",
    "11,50": "11,50",
    "51,200": "51,200",
    "201,500": "201,500",
    "501,1000": "501,1000",
    "1001,5000": "1001,5000",
    "5001,10000": "5001,10000",
    "10001,": "10001,",
}


def expand_industry_keywords(industries: Optional[List[str]]) -> List[str]:
    """Expand ICP industry labels into Apollo keyword tags (deduped, order preserved)."""
    if not industries:
        return []
    seen = set()
    out: List[str] = []
    for raw in industries:
        if not raw or not str(raw).strip():
            continue
        label = str(raw).strip()
        key = label.lower()
        variants = _INDUSTRY_KEYWORD_EXPANSION.get(key, [label])
        for v in variants:
            low = v.lower()
            if low not in seen:
                seen.add(low)
                out.append(v)
        # Always keep the original ICP label as a keyword too
        if key not in seen:
            seen.add(key)
            out.append(label)
    return out


def normalize_employee_ranges_for_apollo(employee_ranges: Optional[List[str]]) -> List[str]:
    """Convert legacy hyphen ranges to Apollo comma format; drop unknown blanks."""
    if not employee_ranges:
        return []
    out: List[str] = []
    seen = set()
    for raw in employee_ranges:
        if not raw:
            continue
        key = str(raw).strip()
        mapped = _EMPLOYEE_RANGE_TO_APOLLO.get(key, key)
        if mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    return out


class ApolloScraper:
    def __init__(self, api_key):
        self.api_key = api_key
        # Endpoints officiels d'Apollo v1
        self.search_url = "https://api.apollo.io/v1/organizations/search"
        self.enrich_url = "https://api.apollo.io/v1/organizations/enrich"
        
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key 
        }

    def search_companies(
        self,
        industries=None,
        locations=None,
        employee_ranges=None,
        limit=5,
        min_employees=None,
        max_employees=None,
        trace_identifier: Optional[str] = None,
        trace_suffix: Optional[str] = None,
    ):
        """
        Phase 1 : Découverte (Search) avec Double-Mapping dynamique et tranches d'employés.

        Apollo's top bucket (10001+) is open-ended, so when min/max employees are
        provided we over-fetch and post-filter by exact headcount before returning.
        ICP industry labels are expanded to Apollo keyword synonyms (ANY OF).
        Employee ranges are normalized to Apollo's "min,max" / "10001," format —
        legacy "10001+" hyphen form can zero out results for some countries.
        """
        needs_size_filter = min_employees is not None or max_employees is not None
        # Over-fetch so post-filter still has enough candidates (esp. 10001+ bucket).
        safe_limit = min(max(limit * (10 if needs_size_filter else 2), limit), 25)
        keyword_tags = expand_industry_keywords(industries)
        apollo_ranges = normalize_employee_ranges_for_apollo(employee_ranges)

        data = {
            "organization_locations": locations if locations else [],
            "q_organization_keyword_tags": keyword_tags,
            "per_page": safe_limit
        }

        # Ajout du filtre de tranches d'employés si fourni (ex: ["51,200", "201,500"])
        if apollo_ranges:
            data["organization_num_employees_ranges"] = apollo_ranges

        # Do NOT set q_organization_name from the country/city. That required the
        # company *name* to contain e.g. "Morocco" and zeroed out real local orgs.
        # Geo targeting belongs only in organization_locations above.
        try:
            target_str = locations[0] if locations else "Global"
            print(
                f"📡 Apollo Search : [{target_str}] keywords={keyword_tags} "
                f"effectifs={apollo_ranges or 'any'}..."
            )
            response = requests.post(self.search_url, json=data, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "company_search",
                        trace_identifier,
                        trace_suffix or "organizations_search",
                        data,
                        scope="company",
                    )
                results = data.get('organizations', [])
                formatted = self._format_org_data(results, enriched=False)
                if needs_size_filter:
                    before = len(formatted)
                    formatted = [
                        c for c in formatted
                        if self._within_employee_bounds(c, min_employees, max_employees)
                    ]
                    print(
                        f"📏 Size post-filter: {before} → {len(formatted)} "
                        f"(min={min_employees}, max={max_employees})"
                    )
                return formatted[:limit]
            else:
                print(f"⚠️ Erreur Apollo Search {response.status_code}: {response.text}")
                return []
        except Exception as e:
            print(f"❌ Erreur lors du search : {e}")
            return []

    @staticmethod
    def _parse_employee_count(value):
        if value in (None, "", "Non renseigné"):
            return None
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        s = str(value).strip().replace(",", "").replace(" ", "")
        if s.endswith("+"):
            s = s[:-1]
        if "-" in s and not s.startswith("-"):
            parts = s.split("-")
            s = parts[-1] if parts[-1] else parts[0]
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return None

    def _within_employee_bounds(self, company, min_employees, max_employees, near_miss_band=0.10):
        """Keep companies inside ICP headcount (±10%); missing headcount is kept."""
        co_size = self._parse_employee_count(company.get("estimated_num_employees"))
        if co_size is None:
            return True
        try:
            min_s = float(min_employees) if min_employees is not None else 0.0
            max_s = float(max_employees) if max_employees is not None else float("inf")
        except (TypeError, ValueError):
            return True
        lower = min_s * (1.0 - near_miss_band) if min_s > 0 else 0.0
        upper = max_s * (1.0 + near_miss_band) if max_s != float("inf") else float("inf")
        return lower <= co_size <= upper

    # MODIFICATION : Ajout de depth et visited_domains pour stopper les boucles infinies
    def enrich_organization(
        self,
        domain=None,
        target_location=None,
        depth=0,
        max_depth=2,
        visited_domains=None,
        trace_identifier: Optional[str] = None,
        trace_suffix: Optional[str] = None,
    ):
        """
        Phase 2 : Enrichissement basé uniquement sur le domaine avec Sanity Check.
        Sécurisé contre les boucles infinies et la surconsommation de tokens.
        """
        if visited_domains is None:
            visited_domains = set()

        # --- LOGIQUE STRICTE SUR LE DOMAINE ---
        valid_domain = domain and domain != "Non renseigné"

        if not valid_domain:
            print("⏩ Aucun domaine valide fourni. Enrichissement annulé.")
            return None

        # --- 1. SÉCURITÉ ANTI-BOUCLE ---
        if domain in visited_domains:
            print(f"🛑 Boucle infinie évitée ! Le domaine '{domain}' a déjà été analysé dans cette session.")
            return None
        
        # --- 2. SÉCURITÉ PROFONDEUR ---
        if depth > max_depth:
            print(f"🛑 Profondeur maximale de récursion atteinte ({max_depth}) pour '{domain}'. Arrêt par sécurité.")
            return None

        # On mémorise que l'on vient de visiter ce domaine
        visited_domains.add(domain)

        params = {
            "domain": domain
        }
        identifier_used = domain
        # ------------------------------------------------------

        try:
            print(f"💎 Enrichissement profond (Niveau {depth}) pour : {identifier_used}...")
            response = requests.get(self.enrich_url, params=params, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "company_enrich",
                        trace_identifier,
                        trace_suffix or f"organizations_enrich_depth_{depth}",
                        data,
                        scope="company",
                    )
                org = data.get('organization', {})
                
                # --- FEATURE 2 & 4 : SANITY CHECK + SUBORGANIZATIONS ---
                if target_location:
                    actual_country = org.get('country', '').lower()
                    target = target_location.lower()
                    
                    # --- CORRECTION DE LA LOGIQUE HQ VS BRANCHE ---
                    if target in actual_country or actual_country in target or (target == "usa" and actual_country in ["united states", "us"]):
                        print(f"✅ {org.get('name')} est déjà localisée en {org.get('country')}. Acceptation du profil.")
                    
                    # Sinon, si le siège n'est PAS dans le pays cible
                    else:
                        print(f"⚠️ {org.get('name')} a son siège en {org.get('country')}. Recherche de la branche locale...")
                        
                        subs = org.get('suborganizations', [])
                        local_domain = None
                        
                        # On fouille les sous-organisations pour trouver le pays cible
                        for sub in subs:
                            sub_name = sub.get('name', '').lower()
                            if target in sub_name:
                                local_domain = sub.get('primary_domain')
                                break
                                
                        if local_domain and local_domain != domain:
                            print(f"🎯 Filiale locale identifiée : {local_domain}. Basculement automatique...")
                            # RECURSION SÉCURISÉE : On passe les variables de contrôle mises à jour
                            return self.enrich_organization(
                                domain=local_domain, 
                                target_location=target_location,
                                depth=depth + 1,
                                max_depth=max_depth,
                                visited_domains=visited_domains,
                                trace_identifier=trace_identifier or local_domain,
                                trace_suffix=f"organizations_enrich_depth_{depth + 1}",
                            )
                        else:
                            print(f"⏩ Aucune filiale '{target_location}' trouvée pour {identifier_used}. Profil ignoré.")
                            return None 
                # ---------------------------------------------------------

                return self._format_org_data([org], enriched=True)[0]
            else:
                print(f"⚠️ Erreur Apollo Enrichment {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Erreur lors de l'enrichissement : {e}")
            return None

    def _normalize_domain(self, domain):
        if not domain:
            return None
        domain_str = str(domain).strip().lower()
        domain_str = re.sub(r'^https?://', '', domain_str)
        domain_str = re.sub(r'^www\.', '', domain_str)
        domain_str = domain_str.split('/')[0]
        if domain_str in ["", "non renseigné", "non trouvé", "null", "none"]:
            return None
        return domain_str

    def _format_org_data(self, results, enriched=False):
        """
        Nettoyeur centralisé pour structurer la donnée avant l'insertion Neo4j.
        """
        formatted_list = []
        default_val = "Non renseigné"

        for org in results:
            def clean(val):
                return val if val not in [None, "", [], {}] else default_val

            raw_domain = org.get("primary_domain")
            normalized_domain = self._normalize_domain(raw_domain)
            apollo_id = org.get("id") or None

            # --- 1. IDENTITÉ & SEO ---
            data = {
                # On conserve la récupération de l'ID au cas où tu en as besoin pour ta BDD, 
                # même s'il n'est plus utilisé pour chercher.
                "apollo_id": apollo_id,
                "domain": normalized_domain or clean(raw_domain),
                "name": clean(org.get("name")),
                "industry": clean(org.get("industry")),
                "founded_year": clean(org.get("founded_year")),
                "logo_url": clean(org.get("logo_url")),
                "website_url": clean(org.get("website_url")),
                "short_description": clean(org.get("short_description")),
                "seo_description": clean(org.get("seo_description")),
                
                # --- 2. PERFORMANCE & CHIFFRES ---
                "alexa_ranking": clean(org.get("alexa_ranking")),
                "annual_revenue": clean(org.get("annual_revenue")),
                "total_funding": clean(org.get("total_funding_printed")),
                "estimated_num_employees": clean(org.get("estimated_num_employees")),
                "latest_funding_stage": clean(org.get("latest_funding_stage")),

                # --- 3. RÉSEAUX SOCIAUX & CONTACT ---
                "linkedin_url": clean(org.get("linkedin_url")),
                "twitter_url": clean(org.get("twitter_url")),
                "facebook_url": clean(org.get("facebook_url")),
                "crunchbase_url": clean(org.get("crunchbase_url")),
                "phone": clean(org.get("phone")),

                # --- 4. LOCALISATION DÉTAILLÉE ---
                "location": {
                    "raw_address": clean(org.get("raw_address")),
                    "street_address": clean(org.get("street_address")),
                    "city": clean(org.get("city")),
                    "state": clean(org.get("state")),
                    "postal_code": clean(org.get("postal_code")),
                    "country": clean(org.get("country"))
                },

                # --- 5. STRUCTURE HIÉRARCHIQUE ---
                "hierarchy": {
                    "num_suborganizations": org.get("num_suborganizations") or 0,
                    "owned_by_organization_id": clean(org.get("owned_by_organization_id")),
                }
            }

            # --- 6. DONNÉES COMPLEXES (Seulement si enrichi) ---
            if enriched:
                # Technologies
                techs = org.get("current_technologies", [])
                data["technologies"] = [
                    {
                        "uid": clean(t.get("uid")),
                        "name": clean(t.get("name")),
                        "category": clean(t.get("category"))
                    } for t in techs
                ] if techs else []

                # Headcount par Département
                data["departments"] = org.get("departmental_head_count", {})

                # Historique de Financement
                fundings = org.get("funding_events", [])
                data["funding_events"] = [
                    {
                        "id": clean(fe.get("id")),
                        "date": clean(fe.get("date")),
                        "type": clean(fe.get("type")),
                        "amount": clean(fe.get("amount")),
                        "currency": clean(fe.get("currency")),
                        "investors": clean(fe.get("investors"))
                    } for fe in fundings
                ] if fundings else []

                # Liste détaillée des sous-organisations
                subs = org.get("suborganizations", [])
                data["suborganizations"] = [
                    {
                        "id": clean(s.get("id")),
                        "name": clean(s.get("name")),
                        "domain": clean(s.get("primary_domain"))
                    } for s in subs
                ] if subs else []

                # Mots-clés (Keywords)
                data["keywords"] = clean(org.get("keywords"))

            formatted_list.append(data)
            
        return formatted_list