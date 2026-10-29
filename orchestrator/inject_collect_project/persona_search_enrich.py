import os
import json
import requests
from typing import List, Dict, Any, Optional, Union
import config
from apollo_api_trace import build_trace_path, save_trace_json
from llm_helpers import EMAIL_PRO_CHECK, invoke_template
from llm_provider import get_llm_client, get_llm_model

# =========================================================================
# CONFIGURATION API & LLM
# =========================================================================
llm_client = get_llm_client()
LLM_MODEL = get_llm_model()

def check_email_pro_llm(email: str) -> bool:
    """
    Vérifie si un email est professionnel via le LLM actif (ESPRIT ou Groq).
    Retourne True si pro, False sinon.
    """
    if not email or email in ["Non trouvé", "None", "N/A", ""]:
        return False

    try:
        result = invoke_template(
            EMAIL_PRO_CHECK,
            email=email,
            temperature=0.1,
            max_tokens=10,
            fallback="False",
            operation="email_pro_check",
        ).strip().lower()
        return "true" in result
    except Exception as e:
        print(f"❌ Erreur lors de la validation LLM de l'email '{email}' : {e}")
        return False

# =========================================================================
# TITRES APOLLO — PRESET SALES
# =========================================================================
SALES_PERSONA_TITLES = [
    "Sales",
    "Sales Manager",
    "Account Executive",
    "Business Development",
    "Head of Sales",
    "VP of Sales",
    "SDR",
    "BDR",
    "Commercial",
]

SALES_ROLE_ALIASES = frozenset({
    "sales",
    "business development",
    "bdr",
    "sdr",
    "commercial",
})


def resolve_person_titles(
    role: Optional[Union[str, List[str]]] = None,
    person_titles: Optional[List[str]] = None,
) -> List[str]:
    """Retourne la liste de titres Apollo à utiliser pour person_titles."""
    if person_titles:
        cleaned = [str(title).strip() for title in person_titles if str(title).strip()]
        if cleaned:
            return cleaned

    if isinstance(role, list):
        cleaned = [str(title).strip() for title in role if str(title).strip()]
        return cleaned or list(SALES_PERSONA_TITLES)

    if role is None:
        return list(SALES_PERSONA_TITLES)

    role_key = str(role).strip().lower()
    if role_key in SALES_ROLE_ALIASES:
        return list(SALES_PERSONA_TITLES)

    return [str(role).strip()]

# =========================================================================
# CLASSE APOLLO
# =========================================================================
class ApolloPersonaSearcher:
    def __init__(self):
        self.api_key = config.APOLLO_API_KEY
        self.search_url = "https://api.apollo.io/api/v1/mixed_people/api_search"
        self.enrich_base_url = "https://api.apollo.io/api/v1/people"
        self.usage_stats_url = "https://api.apollo.io/api/v1/usage_stats/api_usage_stats"
        self.user_profile_url = "https://api.apollo.io/api/v1/users/api_profile"
        
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }
        
    def generate_and_save_token_report(self, output_filename: str = "apollo_tokens_report.json", session_diff: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Interroge le profil de l'utilisateur avec include_credit_usage=true, extrait l'intégralité
        des métriques de crédits et filtre active_rate_limits.
        """
        report_data = {
            "monthly_credits": {},
            "active_rate_limits": {}
        }
        
        if session_diff:
            report_data["session_consumption"] = session_diff
            
        print("\n" + "📊 RAPPORT DE CONSOMMATION DES CRÉDITS APOLLO ".center(60, "="))
        
        # 1. Récupération exhaustive de tous les crédits du profil utilisateur
        try:
            params = {"include_credit_usage": "true"}
            user_res = requests.get(self.user_profile_url, headers=self.headers, params=params)

            if user_res.status_code == 200:
                user_data = user_res.json()
                
                report_data["monthly_credits"] = {
                    "id": user_data.get("id"),
                    "team_id": user_data.get("team_id"),
                    "first_name": user_data.get("first_name"),
                    "last_name": user_data.get("last_name"),
                    "title": user_data.get("title"),
                    "email": user_data.get("email"),
                    "num_credits_remaining": user_data.get("num_credits_remaining"),
                    "effective_num_lead_credits": user_data.get("effective_num_lead_credits"),
                    "num_lead_credits_used": user_data.get("num_lead_credits_used"),
                    "effective_num_direct_dial_credits": user_data.get("effective_num_direct_dial_credits"),
                    "num_direct_dial_credits_used": user_data.get("num_direct_dial_credits_used"),
                    "effective_num_export_credits": user_data.get("effective_num_export_credits"),
                    "num_export_credits_used": user_data.get("num_export_credits_used"),
                    "effective_num_ai_credits": user_data.get("effective_num_ai_credits"),
                    "num_ai_credits_used": user_data.get("num_ai_credits_used"),
                    "effective_num_power_up_credits": user_data.get("effective_num_power_up_credits"),
                    "num_power_up_credits_used": user_data.get("num_power_up_credits_used"),
                    "total_unified_credits_used": user_data.get("total_unified_credits_used")
                }
                
                credits = report_data["monthly_credits"]
                print(f"\n💳 État Actuel des Crédits Mensuels :")
                print(f"   👤 Utilisateur : {credits['first_name']} {credits['last_name']} ({credits['email']})")
                print(f"   ↳ [Leads]        Restant : {credits['num_credits_remaining']} | Utilisé : {credits['num_lead_credits_used']}/{credits['effective_num_lead_credits']}")
                print(f"   ↳ [Direct Dial]  Utilisé : {credits['num_direct_dial_credits_used']}/{credits['effective_num_direct_dial_credits']}")
                print(f"   ↳ [AI Credits]   Utilisé : {credits['num_ai_credits_used']}/{credits['effective_num_ai_credits']}")
                if credits["total_unified_credits_used"] is not None:
                    print(f"   ↳ [Unified Total] Utilisé : {credits['total_unified_credits_used']}")
            else:
                print(f"⚠️ Impossible de récupérer le profil utilisateur (Statut {user_res.status_code})")
                report_data["monthly_credits"] = {"status": "error", "code": user_res.status_code}
        except Exception as e:
            print(f"⚠️ Erreur lors de l'accès au profil utilisateur : {e}")

        # 2. Récupération filtrée des limites techniques d'appels API
        try:
            usage_res = requests.post(self.usage_stats_url, headers=self.headers, json={})
            if usage_res.status_code == 200:
                usage_data = usage_res.json()
                
                target_keywords = ["search", "mixed_people", "people", "show", "enrich"]
                
                if not usage_data:
                    print(f"\n⚡ Limites d'appels API : L'API d'Apollo n'a renvoyé aucune statistique active pour le moment.")
                else:
                    print(f"\n⚡ Limites d'appels API (Filtre appliqué sur les modules de recherche/enrichissement) :")
                    has_printed_any = False
                    
                    for key, val in usage_data.items():
                        str_key = str(key).lower()
                        
                        if any(kw in str_key for kw in target_keywords) and isinstance(val, dict):
                            report_data["active_rate_limits"][str(key)] = val
                            has_printed_any = True
                            
                            display_key = str(key).replace('_', ' ').replace('/', ' ➔ ').title()
                            print(f"   🔹 {display_key} :")
                            for period, metrics in val.items():
                                if isinstance(metrics, dict):
                                    print(f"      ↳ {period} : Consommé {metrics.get('consumed')}/{metrics.get('limit')} (Restant : {metrics.get('left_over')})")
                    
                    if not has_printed_any:
                        print("   ℹ️ Des statistiques globales existent mais aucune ne correspond aux filtres de recherche/enrichissement.")
                        
        except Exception as e:
            print(f"⚠️ Erreur lors de l'accès aux statistiques d'usage : {e}")
            
        print("\n" + "="*60)
        
        # 3. Sauvegarde du rapport complet dans le fichier JSON
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
            print(f"💾 Rapport complet sauvegardé dans : {output_filename}\n")
        except IOError as e:
            print(f"❌ Erreur lors de l'écriture du rapport JSON : {e}")
            
        return report_data

    def search_sales_personas(
        self,
        domain: Optional[str] = None,
        apollo_id: Optional[str] = None,
        person_location: Optional[str] = None,
        organization_location: Optional[str] = None,
        role: Union[str, List[str], None] = None,
        person_titles: Optional[List[str]] = None,
        limit_per_company: int = 1,
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
        trace_suffix: str = "api_search",
    ) -> List[Dict[str, Any]]:
        """
        Recherche des personas via l'API People Search d'Apollo.
        Utilise organization_ids[] si apollo_id est fourni, sinon q_organization_domains_list[].
        """
        if not apollo_id and not domain:
            print("❌ Recherche Apollo impossible : apollo_id ou domain requis.")
            return []

        clean_domain = None
        if domain:
            clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip()

        selected_titles = resolve_person_titles(role=role, person_titles=person_titles)

        payload: Dict[str, Any] = {
            "page": 1,
            "per_page": limit_per_company,
            "person_titles": selected_titles,
        }
        if apollo_id:
            payload["organization_ids"] = [apollo_id]
        elif clean_domain:
            payload["q_organization_domains_list"] = [clean_domain]
        if person_location:
            payload["person_locations"] = [person_location]
        if organization_location:
            payload["organization_locations"] = [organization_location]

        try:
            target_label = f"Apollo ID {apollo_id}" if apollo_id else clean_domain
            print(
                f"🔍 Recherche de personas chez {target_label} "
                f"(Limite : {limit_per_company}, Titres : {selected_titles})..."
            )
            print(f"📍 Filtres -> Personne : {person_location or 'Aucun'} | Entreprise HQ : {organization_location or 'Aucun'}")

            response = requests.post(self.search_url, json=payload, headers=self.headers)
            
            if response.status_code == 401:
                print("❌ Erreur 401 : Clé API Apollo non valide.")
                return []
            
            response.raise_for_status()
            data = response.json()

            if trace_operation and trace_identifier:
                save_trace_json(
                    "responses",
                    trace_operation,
                    trace_identifier,
                    trace_suffix,
                    data,
                )
            
            raw_contacts = data.get("people", [])
            print(f"✅ {len(raw_contacts)} personas récupérés avec l'intégralité de leurs attributs.")
            return raw_contacts

        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la requête Apollo Search : {e}")
            return []

    def get_complete_person_info(
        self,
        person_id: str,
        trace_operation: Optional[str] = None,
        trace_identifier: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enrichit et récupère les informations complètes d'un profil via une requête GET.
        Supprime le bloc 'organization' s'il est présent.
        """
        url_complete = f"{self.enrich_base_url}/{person_id}"
        
        try:
            print(f"🔓 Enrichissement du profil via l'URL : {url_complete}...")
            response = requests.get(url_complete, headers=self.headers)
            
            if response.status_code == 401:
                print("❌ Erreur 401 : Clé API Apollo non valide.")
                return {}
            
            response.raise_for_status()
            data = response.json()

            if trace_operation and trace_identifier:
                save_trace_json(
                    "responses",
                    trace_operation,
                    trace_identifier,
                    f"people_show_{person_id}",
                    data,
                )
            
            person_info = data.get("person", {})
            if person_info:
                person_info.pop("organization", None)
                
            return person_info
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la requête d'enrichissement Apollo : {e}")
            return {}

# =========================================================================
# FONCTION PRINCIPALE (RECHERCHE + ENRICHISSEMENT + VALIDATION LLM)
# =========================================================================
def search_and_enrich(
    domain: Optional[str] = None,
    apollo_id: Optional[str] = None,
    person_location: Optional[str] = None,
    organization_location: Optional[str] = None,
    location: Optional[str] = None,
    role: Union[str, List[str], None] = None,
    person_titles: Optional[List[str]] = None,
    limit: int = 3,
    skip_persona_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Recherche et enrichissement de personas Apollo.

    Compatibilité avec les appels existants :
    - ancien appel: search_and_enrich(domain=..., person_location=..., organization_location=...)
    - appel courant: search_and_enrich(apollo_id=..., location=target_country, role=role)

    skip_persona_ids: Apollo IDs déjà présents en base — enrichissement ignoré,
    et la recherche over-fetch pour remplir `limit` avec de nouveaux profils.
    """
    if not apollo_id and not domain:
        print("❌ Recherche personas impossible : apollo_id ou domain requis.")
        return []

    if not person_location:
        person_location = location
    if not organization_location:
        organization_location = location

    skip_ids = {str(pid) for pid in (skip_persona_ids or set()) if pid}
    # Over-fetch Apollo si on doit contourner des personas déjà connus
    search_limit = limit
    if skip_ids:
        search_limit = min(max(limit + len(skip_ids), limit * 3), 25)

    target_label = f"Apollo ID {apollo_id}" if apollo_id else domain
    resolved_titles = resolve_person_titles(role=role, person_titles=person_titles)
    print(
        f"👤 Recherche de personas pour {target_label} | Titres : {resolved_titles} | "
        f"Person Location: {person_location} | Org Location: {organization_location}"
    )
    if skip_ids:
        print(
            f"⏭️ {len(skip_ids)} persona(s) déjà en base — "
            f"recherche Apollo élargie à {search_limit} pour trouver de nouveaux profils."
        )

    trace_operation = "persona_search"
    trace_identifier = apollo_id or domain or "unknown"
    searcher = ApolloPersonaSearcher()
    
    # 1. Capture de l'état initial des crédits
    initial_report = searcher.generate_and_save_token_report(
        output_filename=build_trace_path("tokens", trace_operation, trace_identifier, "initial")
    )
    
    # 2. Exécution de la recherche avec fallback si aucune localisation n'est fournie
    search_candidates = []
    for candidate in [person_location, organization_location, location]:
        if candidate and candidate not in search_candidates:
            search_candidates.append(candidate)

    if not search_candidates:
        search_candidates = [None]
    else:
        search_candidates.append(None)

    raw_results = []
    for candidate_location in search_candidates:
        location_suffix = str(candidate_location or "global").replace(" ", "_").lower()
        raw_results = searcher.search_sales_personas(
            domain=domain,
            apollo_id=apollo_id,
            person_location=candidate_location,
            organization_location=candidate_location,
            role=role,
            person_titles=person_titles,
            limit_per_company=search_limit,
            trace_operation=trace_operation,
            trace_identifier=trace_identifier,
            trace_suffix=f"api_search_{location_suffix}",
        )
        if raw_results:
            break
    
    final_profiles = []
    skipped_existing = 0
    
    # 3. Traitement, enrichment des profils trouvés et validation LLM
    if raw_results:
        print(f"\n--- Début de l'enrichissement et validation LLM pour {len(raw_results)} profil(s) ---")
        
        for index, person in enumerate(raw_results):
            if len(final_profiles) >= limit:
                break

            persona_id = person.get("id")
            persona_id_str = str(persona_id) if persona_id else ""
            has_email = person.get("has_email", False)
            has_phone = person.get("has_phone", False)
            
            print(f"\n[{index + 1}/{len(raw_results)}] ID : {persona_id}")
            print(f"   ↳ Nom d'origine : {person.get('first_name')} {person.get('last_name_obfuscated', 'Me***e')}")
            print(f"   ↳ Disponibilité détectée -> Has Email: {has_email} | Has Phone: {has_phone}")

            if persona_id_str and persona_id_str in skip_ids:
                skipped_existing += 1
                print(f"   ⏭️ Déjà en base Neo4j — enrichissement Apollo ignoré.")
                continue
            
            if persona_id:
                complete_profile = searcher.get_complete_person_info(
                    persona_id,
                    trace_operation=trace_operation,
                    trace_identifier=trace_identifier,
                )
                if complete_profile:
                    # Injection directe des deux attributs récupérés de l'api_search
                    complete_profile["has_email"] = has_email
                    complete_profile["has_phone"] = has_phone
                    
                    # Validation LLM de l'email
                    email = complete_profile.get("email")
                    print(f"   ↳ Validation LLM de l'email : {email}")
                    complete_profile["mail_pro"] = check_email_pro_llm(email)
                    
                    complete_profile["source"] = "Apollo"
                    final_profiles.append(complete_profile)

    if skipped_existing:
        print(
            f"\nℹ️ {skipped_existing} persona(s) Apollo ignoré(s) (déjà en base). "
            f"{len(final_profiles)} nouveau(x) enrichi(s)."
        )

    # Sauvegarde des résultats
    output_dir = "personas_discovered"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    safe_label = (apollo_id or domain or "unknown").replace('.', '_')
    output_file = os.path.join(output_dir, f"{safe_label}_personas.json")

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_profiles, f, indent=4, ensure_ascii=False)
        print(f"\n✅ Pipeline Terminé ! {len(final_profiles)} profil(s) collecté(s).")
        print(f"💾 Fichier sauvegardé : {output_file}")
    except Exception as e:
        print(f"❌ Erreur lors de la sauvegarde JSON : {e}")

    # 4. Calcul de consommation de session
    session_consumption = {
        "lead_credits_consumed": 0, 
        "direct_dial_credits_consumed": 0, 
        "ai_credits_consumed": 0
    }
    
    try:
        temp_res = requests.get(searcher.user_profile_url, headers=searcher.headers, params={"include_credit_usage": "true"})
        if temp_res.status_code == 200:
            temp_data = temp_res.json()
            init_credits = initial_report.get("monthly_credits", {})
            
            if init_credits and "num_credits_remaining" in init_credits:
                session_consumption["lead_credits_consumed"] = init_credits["num_credits_remaining"] - temp_data.get("num_credits_remaining", 0)
                session_consumption["direct_dial_credits_consumed"] = temp_data.get("num_direct_dial_credits_used", 0) - init_credits["num_direct_dial_credits_used"]
                session_consumption["ai_credits_consumed"] = temp_data.get("num_ai_credits_used", 0) - init_credits["num_ai_credits_used"]
    except Exception as e:
        print(f"⚠️ Impossible de pré-calculer la consommation de la session : {e}")

    # 5. Capture finale intégrant le rapport filtré et la session courante
    searcher.generate_and_save_token_report(
        output_filename=build_trace_path("tokens", trace_operation, trace_identifier, "final"),
        session_diff=session_consumption,
    )
    save_trace_json(
        "responses",
        trace_operation,
        trace_identifier,
        "enriched_profiles",
        final_profiles,
    )
    
    # Affichage terminal récapitulatif
    print("\n" + "⏱️ RÉCAPITULATIF DE LA SESSION ".center(60, "🔥"))
    print(f"   • Crédits Lead consommés      : {session_consumption['lead_credits_consumed']}")
    print(f"   • Crédits Direct Dial utilisés: {session_consumption['direct_dial_credits_consumed']}")
    print(f"   • Crédits AI exploités        : {session_consumption['ai_credits_consumed']}")
    print("="*60 + "\n")
    
    return final_profiles


if __name__ == "__main__":
    # =========================================================================
    # CONFIGURATION DES PARAMÈTRES DE RECHERCHE
    # =========================================================================
    TARGET_DOMAIN = "Tesla.com"
    TARGET_PERSON_LOCATION = "United States"
    TARGET_COMPANY_LOCATION = "United States"
    MAX_LIMIT = 3
    # =========================================================================
    
    profiles = search_and_enrich(
        domain=TARGET_DOMAIN, 
        person_location=TARGET_PERSON_LOCATION, 
        organization_location=TARGET_COMPANY_LOCATION, 
        limit=MAX_LIMIT
    )