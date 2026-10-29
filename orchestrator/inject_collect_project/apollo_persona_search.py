import os
import json
import requests
from typing import List, Dict, Any, Optional
import config

class ApolloPersonaSearcher:
    def __init__(self):
        self.api_key = config.APOLLO_API_KEY
        
        # Endpoint de recherche (Search)
        self.search_url = "https://api.apollo.io/api/v1/mixed_people/api_search"
        
        # Base de l'endpoint d'enrichissement
        self.enrich_base_url = "https://api.apollo.io/api/v1/people"
        
        # URL d'usage des quotas de requêtes
        self.usage_stats_url = "https://api.apollo.io/api/v1/usage_stats/api_usage_stats"
        
        # URL du profil utilisateur
        self.user_profile_url = "https://api.apollo.io/api/v1/users/api_profile"
        
        # En-têtes requis avec authentification par X-Api-Key
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }
        
    def generate_and_save_token_report(self, output_filename: str = "apollo_tokens_report.json", session_diff: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Interroge le profil de l'utilisateur avec include_credit_usage=true, extrait l'intégralité
        des métriques de crédits spécifiées dans la documentation pour les sauvegarder dans le JSON.
        Filtre active_rate_limits pour n'inclure que les endpoints actuellement utilisés par ce script.
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
                
                # Mapping strict avec les clés exactes de la documentation fournie
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
                
                # Affichage dans le terminal
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
                
                # Élargissement des mots-clés cibles pour être sûr de matcher les formats d'Apollo
                target_keywords = ["search", "mixed_people", "people", "show", "enrich"]
                
                if not usage_data:
                    print(f"\n⚡ Limites d'appels API : L'API d'Apollo n'a renvoyé aucune statistique active pour le moment.")
                else:
                    print(f"\n⚡ Limites d'appels API (Filtre appliqué sur les modules de recherche/enrichissement) :")
                    has_printed_any = False
                    
                    for key, val in usage_data.items():
                        str_key = str(key).lower()
                        
                        # Si la clé contient l'un de nos mots-clés de traitement
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
        domain: str, 
        person_location: str,
        organization_location: str,
        limit_per_company: int = 1,
        person_titles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recherche des personas selon le domaine, la localisation, et les titres.
        person_titles comes from ICP target_roles when provided; otherwise uses
        the legacy sales preset.
        """
        clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip()

        sales_titles = [
            str(t).strip() for t in (person_titles or []) if str(t).strip()
        ] or [
            "Sales", "Sales Manager", "Account Executive", "Business Development", 
            "Head of Sales", "VP of Sales", "SDR", "BDR", "Commercial"
        ]

        payload = {
            "q_organization_domains_list": [clean_domain],
            "person_titles": sales_titles,
            "organization_locations": [organization_location],
            "person_locations": [person_location],
            "page": 1,
            "per_page": limit_per_company
        }

        try:
            print(f"🔍 Recherche des personas chez {clean_domain} (Limite : {limit_per_company})...")
            print(f"🏷️  Titres (person_titles) : {sales_titles}")
            print(f"📍 Filtres -> Personne : {person_location} | Entreprise HQ : {organization_location}")
            
            response = requests.post(self.search_url, json=payload, headers=self.headers)
            
            if response.status_code == 401:
                print("❌ Erreur 401 : Clé API Apollo non valide.")
                return []
            
            response.raise_for_status()
            data = response.json()
            
            raw_contacts = data.get("people", [])
            personas_complets = []
            for person in raw_contacts:
                personas_complets.append(person)
                
            print(f"✅ {len(personas_complets)} personas récupérés avec l'intégralité de leurs attributs.")
            return personas_complets

        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la requête Apollo Search : {e}")
            return []

    def get_complete_person_info(self, person_id: str) -> Dict[str, Any]:
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
            
            person_info = data.get("person", {})
            if person_info:
                person_info.pop("organization", None)
                
            return person_info
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur lors de la requête d'enrichissement Apollo : {e}")
            return {}


if __name__ == "__main__":
    searcher = ApolloPersonaSearcher()
    
    # =========================================================================
    # CONFIGURATION DES PARAMÈTRES DE RECHERCHE
    # =========================================================================
    target_domain = "klinger.co.uk"
    target_person_location = "United Kingdom"
    target_company_location = "United Kingdom"
    max_personas_limit = 1  # <--- Limite dynamique de personas par entreprise
    # Prefer ICP target_roles (same list orchestrator passes as `role`).
    # Leave empty to use the legacy sales preset fallback.
    icp_target_roles = [
        # "VP of Sales",
        # "Head of Sales",
        # "Chief Revenue Officer",
    ]
    # =========================================================================
    
    # 1. Capture de l'état initial des crédits
    initial_report = searcher.generate_and_save_token_report()
    
    # 2. Exécution de la recherche avec les nouveaux paramètres
    results = searcher.search_sales_personas(
        domain=target_domain,
        person_location=target_person_location,
        organization_location=target_company_location,
        limit_per_company=max_personas_limit,
        person_titles=icp_target_roles or None,
    )
    
    # 3. Traitement et enrichment des profils trouvés
    if results:
        print(f"\n--- Début de l'enrichissement pour {len(results)} profil(s) ---")
        enriched_profiles = []
        
        for index, person in enumerate(results):
            persona_id = person.get("id")
            
            # Extraction des attributs de présence d'email et téléphone depuis l'api_search
            has_email_val = person.get("has_email", False)
            has_phone_val = person.get("has_phone", False)
            
            print(f"\n[{index + 1}/{len(results)}] ID : {persona_id}")
            print(f"   ↳ Nom d'origine : {person.get('first_name')} {person.get('last_name_obfuscated', 'Me***e')}")
            print(f"   ↳ Disponibilité détectée -> Has Email: {has_email_val} | Has Phone: {has_phone_val}")
            
            if persona_id:
                complete_profile = searcher.get_complete_person_info(persona_id)
                if complete_profile:
                    # Injection directe des deux attributs récupérés de l'api_search
                    complete_profile["has_email"] = has_email_val
                    complete_profile["has_phone"] = has_phone_val
                    
                    enriched_profiles.append(complete_profile)
        
        # Sauvegarde de tous les profils enrichis de la session
        output_filename = "enriched_personas_list.json"
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(enriched_profiles, f, indent=2, ensure_ascii=False)
            print(f"\n💾 SUCCÈS : {len(enriched_profiles)} profil(s) enrichi(s) avec indicateurs sauvegardé(s) dans : {output_filename}")
        except IOError as e:
            print(f"❌ Erreur lors de la sauvegarde du fichier JSON : {e}")
                
    # 4. Calcul de la consommation de cette session spécifique
    session_consumption = {
        "lead_credits_consumed": 0,
        "direct_dial_credits_consumed": 0,
        "ai_credits_consumed": 0
    }
    
    # Appel de fin pour identifier la consommation exacte
    try:
        params = {"include_credit_usage": "true"}
        temp_res = requests.get(searcher.user_profile_url, headers=searcher.headers, params=params)
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
    searcher.generate_and_save_token_report(session_diff=session_consumption)
    
    # Affichage terminal récapitulatif
    print("\n" + "⏱️ RÉCAPITULATIF DE LA SESSION ".center(60, "🔥"))
    print(f"   • Crédits Lead consommés      : {session_consumption['lead_credits_consumed']}")
    print(f"   • Crédits Direct Dial utilisés: {session_consumption['direct_dial_credits_consumed']}")
    print(f"   • Crédits AI exploités        : {session_consumption['ai_credits_consumed']}")
    print("="*60 + "\n")