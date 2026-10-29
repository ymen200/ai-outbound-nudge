import requests
import json
import os
from datetime import datetime
from typing import Optional
from apollo_api_trace import save_trace_json
import config

class ApolloSignalsTester:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }

    def parse_date(self, date_str):
        """Helper pour parser de manière robuste les différents formats de date d'Apollo."""
        if not date_str:
            return None
        # Nettoyage des formats ISO (ex: 2026-05-14T10:00:00.000Z)
        date_clean = str(date_str).split(".")[0].replace("Z", "").replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_clean[:19], fmt)
            except ValueError:
                continue
        return None

    def get_organization_id(self, domain, trace_identifier: Optional[str] = None):
        """Étape 1 : Convertit le domaine en ID unique Apollo via l'enrichissement."""
        url = "https://api.apollo.io/v1/organizations/enrich"
        params = {"domain": domain}
        
        try:
            response = requests.get(url, headers=self.headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "organizations_enrich",
                        data,
                        scope="intent",
                    )
                org_data = data.get("organization", {})
                org_id = org_data.get("id")
                org_name = org_data.get("name")
                print(f"🏢 Entreprise identifiée : {org_name} ➔ ID unique : {org_id}")
                return org_id
            else:
                print(f"❌ Erreur lors de la récupération de l'ID ({response.status_code}) : {response.text}")
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "organizations_enrich_error",
                        {"status_code": response.status_code, "body": response.text},
                        scope="intent",
                    )
                return None
        except Exception as e:
            print(f"❌ Erreur de connexion durant l'enrichissement : {e}")
            return None

    def fetch_job_postings(self, organization_id, trace_identifier: Optional[str] = None):
        """Étape 2 : Interroge l'endpoint d'Apollo pour lister les jobs (GET)."""
        url = f"https://api.apollo.io/v1/organizations/{organization_id}/job_postings"
        
        try:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "job_postings",
                        data,
                        scope="intent",
                    )
                return data
            else:
                print(f"❌ Erreur API Job Postings ({response.status_code}) : {response.text}")
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "job_postings_error",
                        {"status_code": response.status_code, "body": response.text},
                        scope="intent",
                    )
                return None
        except Exception as e:
            print(f"❌ Erreur de connexion durant l'appel Job Postings : {e}")
            return None

    def fetch_news_articles(self, organization_id, trace_identifier: Optional[str] = None):
        """Étape 3 : Interroge l'endpoint de recherche d'articles de presse (POST)."""
        url = "https://api.apollo.io/v1/news_articles/search"
        
        payload = {
            "organization_ids": [organization_id],
            "per_page": 20  # Gardé à 20 pour maximiser la profondeur de choix des plus récents
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "news_articles_search",
                        data,
                        scope="intent",
                    )
                return data
            else:
                print(f"❌ Erreur API News Articles ({response.status_code}) : {response.text}")
                if trace_identifier:
                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "news_articles_search_error",
                        {"status_code": response.status_code, "body": response.text},
                        scope="intent",
                    )
                return None
        except Exception as e:
            print(f"❌ Erreur de connexion durant l'appel News Articles : {e}")
            return None


# --- SCRIPT DE TEST MIXTE AVEC FILTRE DE RÉCENCE STRICT (INTENT CHAUD) ---
if __name__ == "__main__":
    # Paramètres de configuration
    APOLLO_API_KEY = config.APOLLO_API_KEY
    target_domain = "sagemcom.com"
    target_country = "France"      # Filtre géographique (Jobs uniquement)
    
    # Seuils d'ancienneté distincts (en jours) — configurables via .env
    MAX_JOB_AGE_DAYS = config.MAX_JOB_AGE_DAYS
    MAX_NEWS_AGE_DAYS = config.MAX_NEWS_AGE_DAYS
    
    # ------------------------------------------------------------------
    # CONFIGURATION DES LIMITES PAR ENTREPRISE (PARAMÉTRABLE)
    # ------------------------------------------------------------------
    MAX_JOBS_PER_COMPANY = 3  # Nombre maximum de offres d'emploi à conserver
    MAX_NEWS_PER_COMPANY = 3  # Nombre maximum d'actualités à conserver
    # ------------------------------------------------------------------

    tester = ApolloSignalsTester(api_key=APOLLO_API_KEY)
    
    print(f"⚡ [Phase 1] Recherche de l'ID pour le domaine : {target_domain}...")
    org_id = tester.get_organization_id(target_domain)
    
    if org_id:
        # --- EXTRACTION ET FILTRAGE DES OFFRES D'EMPLOI (LOCAL & RÉCENT) ---
        print(f"\n⚡ [Phase 2] Analyse des '/job_postings' (Filtre Pays: {target_country} + Récence < {MAX_JOB_AGE_DAYS} jours)...")
        jobs_json = tester.fetch_job_postings(org_id)
        
        raw_jobs_list = []
        extracted_jobs_list = []
        
        if jobs_json:
            if "jobs" in jobs_json:
                raw_jobs_list = jobs_json["jobs"]
            elif "job_postings" in jobs_json:
                raw_jobs_list = jobs_json["job_postings"]
            elif "organization_job_postings" in jobs_json:
                raw_jobs_list = jobs_json["organization_job_postings"]
            else:
                raw_jobs_list = jobs_json if isinstance(jobs_json, list) else [jobs_json]
            
            for job in raw_jobs_list:
                # 1. Validation Géographique
                if target_country:
                    job_geo = str(job.get("location") or job.get("country") or job.get("locality") or "").lower()
                    if target_country.lower() not in job_geo:
                        continue
                
                # 2. Validation de Récence
                job_date_str = job.get("posted_at") or job.get("created_at") or job.get("updated_at")
                job_date = tester.parse_date(job_date_str)
                
                if job_date:
                    days_ago = (datetime.now() - job_date).days
                    if days_ago > MAX_JOB_AGE_DAYS:
                        continue  # On ignore si le signal est trop ancien
                    job["_parsed_date"] = job_date
                else:
                    job["_parsed_date"] = datetime.min  # Fallback si aucune date trouvée
                
                # 3. Ajout de l'indicateur d'intention
                job["intent_type"] = "job_post"
                
                extracted_jobs_list.append(job)
            
            # --- APPLICATION DE LA LIMITE STRICTE PARAMÉTRABLE (LES PLUS RÉCENTS) ---
            extracted_jobs_list.sort(key=lambda x: x.get("_parsed_date", datetime.min), reverse=True)
            extracted_jobs_list = extracted_jobs_list[:MAX_JOBS_PER_COMPANY]
            
            print(f"✅ Offres d'emploi récentes retenues (Limité aux {MAX_JOBS_PER_COMPANY} plus récents) : {len(extracted_jobs_list)} postes sur {len(raw_jobs_list)} au total.")
        
        # --- EXTRACTION ET FILTRAGE DES ARTICLES DE PRESSE (GLOBAL & RÉCENT) ---
        print(f"\n⚡ [Phase 3] Analyse des '/news_articles/search' (Mode Récence < {MAX_NEWS_AGE_DAYS} jours)...")
        news_json = tester.fetch_news_articles(org_id)
        
        raw_news_list = []
        extracted_news_list = []
        
        if news_json:
            if "news_articles" in news_json:
                raw_news_list = news_json["news_articles"]
            elif "articles" in news_json:
                raw_news_list = news_json["articles"]
            else:
                raw_news_list = news_json if isinstance(news_json, list) else [news_json]
            
            for news in raw_news_list:
                # Validation de Récence
                news_date_str = news.get("published_at") or news.get("date") or news.get("created_at")
                news_date = tester.parse_date(news_date_str)
                
                if news_date:
                    days_ago = (datetime.now() - news_date).days
                    if days_ago > MAX_NEWS_AGE_DAYS:
                        continue  # Élimination des vieux communiqués de presse
                    news["_parsed_date"] = news_date
                else:
                    news["_parsed_date"] = datetime.min
                
                # Ajout de l'indicateur d'intention
                news["intent_type"] = "news"
                
                extracted_news_list.append(news)

            # --- APPLICATION DE LA LIMITE STRICTE PARAMÉTRABLE (LES PLUS RÉCENTS) ---
            extracted_news_list.sort(key=lambda x: x.get("_parsed_date", datetime.min), reverse=True)
            extracted_news_list = extracted_news_list[:MAX_NEWS_PER_COMPANY]

            print(f"✅ Articles de presse récents retenus (Limité aux {MAX_NEWS_PER_COMPANY} plus récents) : {len(extracted_news_list)} articles sur {len(raw_news_list)} reçus.")
                
        # --- RE-STRUCTURATION ET ENREGISTREMENT ---
        
        # 1. Fusion des deux listes filtrées et limitées en un seul tableau
        combined_intents = extracted_jobs_list + extracted_news_list
        
        # 2. Tri chronologique global (du plus récent au plus ancien)
        combined_intents.sort(key=lambda x: x.get("_parsed_date", datetime.min), reverse=True)
        
        # 3. Nettoyage de la clé de tri temporaire interne
        for intent in combined_intents:
            intent.pop("_parsed_date", None)
        
        print("\n========================================================")
        print("💾 SAUVEGARDE DES SIGNAL INTENTIONS RÉCENTS :")
        print("========================================================")
        
        safe_domain_name = target_domain.replace(".", "_")
        output_filename = f"{safe_domain_name}_recent_intent_signals.json"
        
        try:
            # Sauvegarde directe du tableau fusionné
            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(combined_intents, f, indent=4, ensure_ascii=False)
            print(f"✅ Succès ! {len(combined_intents)} signaux (jobs + news) ont été triés et sauvegardés.")
            print(f"📂 Chemin du fichier : {os.path.abspath(output_filename)}")
        except Exception as e:
            print(f"❌ Erreur lors de l'écriture du fichier de sortie : {e}")

        # Bilan
        print(f"\n📊 Bilan des intentions chaudes stockées :")
        print(f" ➔ Offres d'emploi (Max configuré: {MAX_JOBS_PER_COMPANY}) : {len(extracted_jobs_list)}")
        print(f" ➔ Actualités (Max configuré: {MAX_NEWS_PER_COMPANY}) : {len(extracted_news_list)}")
        print(f" ➔ Total enregistré dans le fichier final : {len(combined_intents)}")

    else:
        print("❌ Impossible d'appeler les sous-endpoints sans un ID valide.")