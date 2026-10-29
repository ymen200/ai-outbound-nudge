import os
import json
from datetime import datetime
import config

# Importation des deux modules de collecte
try:
    from Intent_search import ApolloSignalsTester
except ImportError:
    print("⚠️ Impossible d'importer ApolloSignalsTester depuis Intent_search.py. Assurez-vous que le fichier est dans le même dossier.")
    ApolloSignalsTester = None

try:
    from intent_signals_scraper import IntentSignalsScraper
except ImportError:
    print("⚠️ Impossible d'importer IntentSignalsScraper depuis intent_signals_scraper.py. Assurez-vous que le fichier est dans le même dossier.")
    IntentSignalsScraper = None

from apollo_api_trace import save_trace_json, save_token_report, compute_session_consumption

class IntentGlobalOrchestrator:
    def __init__(self):
        # Récupération des clés API depuis l'environnement
        self.apollo_key = config.APOLLO_API_KEY
        self.output_dir = "combined_intent_data"
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _normalize_date(self, item):
        """
        Helper pour tenter d'extraire une date exploitable pour le tri final.
        """
        # Clés potentielles provenant d'Apollo ou du Scraper
        date_str = item.get("posted_at") or item.get("published_at") or item.get("date") or item.get("created_at")
        if not date_str or "not specified" in str(date_str).lower():
            return datetime.min
        
        # Nettoyage rapide du format ISO si présent
        date_clean = str(date_str).split(".")[0].replace("Z", "").replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(date_clean[:19], fmt)
            except ValueError:
                continue
        return datetime.min

    def _deduplicate_signals(self, combined_list):
        """
        Dédoublonne les signaux d'intentions basés sur le type et la similarité des titres.
        """
        unique_items = []
        seen_keys = set()

        for item in combined_list:
            # Récupération du titre selon la structure de l'objet (Apollo vs Scraper)
            title = item.get("title") or item.get("title_and_summary") or ""
            intent_type = item.get("intent_type", "unknown")
            
            # Création d'une clé de dédoublonnement normalisée (minuscule, sans espace superflu)
            normalized_title = "".join(title.lower().split())
            dedup_key = f"{intent_type}_{normalized_title}"

            if dedup_key not in seen_keys and len(title) > 0:
                seen_keys.add(dedup_key)
                unique_items.append(item)
                
        return unique_items

    def _limit_intent_signals(self, signals, max_items=config.MAX_INTENT_SIGNALS_PER_COMPANY):
        """Limite le nombre de signaux d'intention conservés par entreprise."""
        if not signals:
            return []
        if max_items <= 0:
            return []
        return signals[:max_items]

    def _passes_recency_filter(self, item, intent_type, date_parser):
        """Filtre jobs et news trop anciens (même logique que Intent_search.py)."""
        if intent_type == "job_post":
            max_days = config.MAX_JOB_AGE_DAYS
            date_str = item.get("posted_at") or item.get("created_at") or item.get("updated_at")
        elif intent_type == "news":
            max_days = config.MAX_NEWS_AGE_DAYS
            date_str = item.get("published_at") or item.get("date") or item.get("created_at")
        else:
            return True

        parsed_date = date_parser(date_str) if date_str else None
        if parsed_date:
            if (datetime.now() - parsed_date).days > max_days:
                return False
            item["_parsed_date"] = parsed_date
        else:
            item["_parsed_date"] = datetime.min
        return True

    def fetch_global_intent_signals(self, domain, apollo_id=None, target_country=None, output_filename=None, max_items=config.MAX_INTENT_SIGNALS_PER_COMPANY):
        """
        Orchestre la collecte globale via Apollo API et Scraping Web, fusionne et sauvegarde les résultats.
        """
        print("=" * 70)
        print(f"🚀 Lancement de l'orchestration d'intention pour le domaine : {domain} (Apollo ID: {apollo_id})")
        print("=" * 70)

        all_signals = []
        domain_clean = domain.replace("https://", "").replace("http://", "").replace("www.", "").replace(".", "_")

        # ---------------------------------------------------------------------
        # SOURCE 1 : APOLLO API
        # ---------------------------------------------------------------------
        apollo_signals = []
        trace_identifier = apollo_id or domain.replace("https://", "").replace("http://", "").replace("www.", "")
        initial_apollo_report = None
        if ApolloSignalsTester and self.apollo_key:
            initial_apollo_report, _ = save_token_report(
                "intent",
                "intent_apollo",
                trace_identifier,
                "initial",
                self.apollo_key,
                rate_limit_keywords=["organizations", "news", "job", "enrich"],
            )
            if apollo_id:
                print(f"\n📡 [SOURCE 1] Utilisation directe de l'Apollo ID {apollo_id} pour l'API Apollo...")
            else:
                print(f"\n📡 [SOURCE 1] Interrogation de l'API Apollo pour {domain} (recherche d'ID)...")
            try:
                tester = ApolloSignalsTester(api_key=self.apollo_key)
                org_id = apollo_id if apollo_id else tester.get_organization_id(domain, trace_identifier=trace_identifier)
                
                if org_id:
                    # Collecte des jobs
                    jobs_json = tester.fetch_job_postings(org_id, trace_identifier=trace_identifier)
                    raw_jobs = (jobs_json or {}).get("jobs") or (jobs_json or {}).get("job_postings") or (jobs_json or {}).get("organization_job_postings") or []
                    if not isinstance(raw_jobs, list): raw_jobs = []
                    
                    # Filtrage géographique + récence (réplica de Intent_search.py)
                    print(
                        f"   Filtres Apollo : pays={target_country or 'tous'}, "
                        f"jobs < {config.MAX_JOB_AGE_DAYS}j, news < {config.MAX_NEWS_AGE_DAYS}j"
                    )
                    for j in raw_jobs:
                        if target_country:
                            geo = str(
                                j.get("location") or j.get("country") or j.get("locality") or ""
                            ).lower()
                            if target_country.lower() not in geo:
                                continue
                        if not self._passes_recency_filter(j, "job_post", tester.parse_date):
                            continue
                        j["intent_type"] = "job_post"
                        j["source_origin"] = "Apollo API"
                        apollo_signals.append(j)
                        
                    # Collecte des actualités
                    news_json = tester.fetch_news_articles(org_id, trace_identifier=trace_identifier)
                    raw_news = (news_json or {}).get("news_articles") or (news_json or {}).get("articles") or []
                    if not isinstance(raw_news, list): raw_news = []
                    
                    for n in raw_news:
                        if not self._passes_recency_filter(n, "news", tester.parse_date):
                            continue
                        n["intent_type"] = "news"
                        n["source_origin"] = "Apollo API"
                        apollo_signals.append(n)

                    save_trace_json(
                        "responses",
                        "intent_apollo",
                        trace_identifier,
                        "apollo_signals_processed",
                        apollo_signals,
                        scope="intent",
                    )
                    print(f"✅ Apollo API a retourné {len(apollo_signals)} signaux valides.")
                else:
                    print("⚠️ Aucun ID d'organisation trouvé sur Apollo pour ce domaine.")
            except Exception as e:
                print(f"❌ Erreur lors de l'exécution d'Apollo API : {e}")
            finally:
                if initial_apollo_report:
                    session_consumption = compute_session_consumption(self.apollo_key, initial_apollo_report)
                    save_token_report(
                        "intent",
                        "intent_apollo",
                        trace_identifier,
                        "final",
                        self.apollo_key,
                        session_diff=session_consumption,
                        rate_limit_keywords=["organizations", "news", "job", "enrich"],
                    )
        else:
            print("\n⏩ [SOURCE 1] Apollo API ignoré (Module manquant ou clé absente).")

        # ---------------------------------------------------------------------
        # SOURCE 2 : SCRAPER WEB AUTONOME (PLAYWRIGHT + LLM)
        # ---------------------------------------------------------------------
        scraper_signals = []
        if IntentSignalsScraper:
            print(f"\n🌐 [SOURCE 2] Lancement du Scraper Web profond (Playwright) pour {domain}...")
            try:
                scraper = IntentSignalsScraper()
                # Le scraper génère un fichier et retourne son chemin
                saved_file_path = scraper.scrape_and_extract_intents(domain, target_country=target_country)
                
                if saved_file_path and os.path.exists(saved_file_path):
                    with open(saved_file_path, "r", encoding="utf-8") as sf:
                        scraped_data = json.load(sf)
                        if isinstance(scraped_data, list):
                            for item in scraped_data:
                                item["source_origin"] = "Web Scraping (LLM Enrichment)"
                                scraper_signals.append(item)
                    print(f"✅ Le Scraper Web a extrait {len(scraper_signals)} signaux valides depuis le site.")
                else:
                    print("⚠️ Aucun fichier de données généré par le scraper de site.")
            except Exception as e:
                print(f"❌ Erreur lors de l'exécution du Scraper Web : {e}")
        else:
            print("\n⏩ [SOURCE 2] Scraper Web d'intention ignoré (Module manquant).")

        # ---------------------------------------------------------------------
        # FUSION, ENRICHISSEMENT ET DÉDOUBLONNEMENT
        # ---------------------------------------------------------------------
        print("\n🔀 [Fusion & Traitement] Fusion des flux de données d'intentions...")
        combined_raw = apollo_signals + scraper_signals
        
        # Dédoublonnement intelligent
        final_items = self._deduplicate_signals(combined_raw)
        
        # Tri chronologique global (du plus récent au plus ancien)
        final_items.sort(key=lambda x: self._normalize_date(x), reverse=True)

        # Limitation finale configurable pour éviter de surcharger la base
        final_items = self._limit_intent_signals(final_items, max_items=max_items)

        # Définition du nom de fichier final de sortie
        if not output_filename:
            output_filename = os.path.join(self.output_dir, f"global_intent_{domain_clean}.json")

        # Sauvegarde finale
        try:
            for item in final_items:
                item.pop("_parsed_date", None)

            with open(output_filename, "w", encoding="utf-8") as f:
                json.dump(final_items, f, indent=4, ensure_ascii=False, default=str)
            
            print("\n========================================================")
            print("💾 SAUVEGARDE DE L'ORCHESTRATION TERMINÉE :")
            print("========================================================")
            print(f"✅ Succès ! {len(final_items)} signaux globaux d'intention ont été unifiés.")
            print(f"📂 Fichier consolidé disponible ici : {os.path.abspath(output_filename)}")
            
            # Bilan rapide
            jobs_count = sum(1 for x in final_items if x.get("intent_type") == "job_post")
            news_count = sum(1 for x in final_items if x.get("intent_type") == "news")
            print(f" ➔ Offres d'emploi unifiées : {jobs_count}")
            print(f" ➔ Actualités / Presse unifiées : {news_count}")
            
            return final_items
        except Exception as e:
            print(f"❌ Erreur lors de l'écriture du fichier final orchestré : {e}")
            return final_items

if __name__ == "__main__":
    # Test à blanc du système global orchestré
    orchestrator = IntentGlobalOrchestrator()
    
    # Paramètres cibles (Modifiables pour vos tests)
    target_company_domain = "indabaxtunisia.com"
    target_geo_filter = "Tunisia"
    
    # Exécution globale
    intents = orchestrator.fetch_global_intent_signals(
        domain=target_company_domain, 
        target_country=target_geo_filter
    )