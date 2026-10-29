import os
import json
import io
import time
import requests
import re
from datetime import datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
from difflib import SequenceMatcher

from llm_helpers import (
    INTENT_GEO_FILTER,
    INTENT_NAVIGATION,
    INTENT_SIGNALS_EXTRACT,
    invoke_chat,
    invoke_template,
)
from llm_provider import get_llm_client, get_llm_model

class IntentSignalsScraper:
    def __init__(self, output_dir="intent_signals_data"):
        self.output_dir = output_dir
        self.client = get_llm_client()
        self.model_name = get_llm_model()
        self.ua = UserAgent()

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def execute_with_retry(self, operation, max_retries=3, initial_delay=1.0, operation_name="Action"):
        for attempt in range(max_retries):
            try:
                return operation()
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"❌ {operation_name} a échoué après {max_retries} tentatives. Erreur finale : {e}")
                    raise e
                wait_time = initial_delay * (2 ** attempt)
                print(f"⚠️ {operation_name} échoué ({type(e).__name__}). Récurrence dans {wait_time}s ({attempt + 1}/{max_retries})...")
                time.sleep(wait_time)

    def safe_generate_content(self, system_prompt, user_prompt, temperature=0.1):
        try:
            raw_text = invoke_chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=4000,
                fallback=None,
                operation="intent_signals",
            ).strip()

            backtick = "```"
            if backtick in raw_text:
                parts = raw_text.split(backtick)
                if len(parts) >= 3:
                    raw_text = parts[1].replace("json", "").strip()
                else:
                    raw_text = parts[1].strip()
            return raw_text
        except Exception as e:
            print(f"❌ Erreur lors de l'appel au LLM ({self.model_name}) : {e}")
            return None

    def extract_json_block(self, text):
        if not text:
            return None

        cleaned = text.strip()
        if not cleaned:
            return None

        start_index = None
        for idx, char in enumerate(cleaned):
            if char in '{[':
                start_index = idx
                break

        if start_index is None:
            return None

        stack = []
        in_string = False
        escaped = False

        for idx in range(start_index, len(cleaned)):
            char = cleaned[idx]

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char in '{[':
                stack.append(char)
            elif char in '}]':
                if not stack:
                    return cleaned[start_index:idx + 1]
                opener = stack.pop()
                if (opener == '{' and char == '}') or (opener == '[' and char == ']'):
                    if not stack:
                        return cleaned[start_index:idx + 1]
                else:
                    return None

        return None

    def parse_json_response(self, raw_text):
        if not raw_text:
            return None

        candidates = [raw_text.strip()]

        if raw_text.strip().startswith("```"):
            fenced = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.I)
            fenced = re.sub(r"\s*```$", "", fenced, flags=re.I)
            candidates.append(fenced.strip())

        for candidate in candidates:
            if not candidate:
                continue

            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

            extracted = self.extract_json_block(candidate)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass

        return None

    def inject_xai_metrics(self, data_node, raw_text):
        """ Injecte les métriques XAI globales pour chaque élément ayant une confidence et une source. """
        if isinstance(data_node, dict):
            if "confidence" in data_node and "source" in data_node:
                source_str = str(data_node.get("source", ""))
                conf = float(data_node.get("confidence", 0.0))
                
                # Détermine le texte principal pour calculer la similarité
                val_str = ""
                if data_node.get("intent_type") == "job_post":
                    val_str = str(data_node.get("title", ""))
                elif data_node.get("intent_type") == "news":
                    val_str = str(data_node.get("title_and_summary", ""))
                else:
                    val_str = str(data_node.get("title", ""))

                is_faithful = 1 if source_str and source_str.lower().strip() in raw_text.lower() else 0
                similarity = SequenceMatcher(None, val_str.lower(), source_str.lower()).ratio()
                calibration_error = abs(conf - similarity)
                density = len(val_str) / len(source_str) if len(source_str) > 0 else 0.0

                data_node["xai_metrics"] = {
                    "faithfulness_score": is_faithful,
                    "calibration_error": round(calibration_error, 2),
                    "evidence_density": round(density, 2)
                }

            # On explore de manière récursive au cas où
            for key, value in data_node.items():
                if isinstance(value, (dict, list)) and key != "xai_metrics":
                    self.inject_xai_metrics(value, raw_text)
                    
        elif isinstance(data_node, list):
            for item in data_node:
                self.inject_xai_metrics(item, raw_text)

        return data_node

    def smart_scroll(self, page):
        print("    ⏬ Auto-scroll dynamique (Lazy Loading des annonces)...")
        try:
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 500;
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= scrollHeight - window.innerHeight || totalHeight > 8000) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 250);
                    });
                }
            """)
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"    ⚠️ Erreur de scrolling : {e}")

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'iframe', 'noscript', 'svg', 'button', 'form', 'meta', 'link']):
            tag.decompose()

        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(h.name[1])
            h.insert_before(f"\n\n{'#' * level} ")
            h.insert_after("\n\n")

        for li in soup.find_all('li'):
            li.insert_before("\n- ")

        for p in soup.find_all('p'):
            p.insert_before("\n")
            p.insert_after("\n")

        text = soup.get_text(separator=' ')
        text = re.sub(r'[ \t]+', ' ', text)
        clean_lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(clean_lines)

    def check_missing_fields(self, data):
        if not data:
            return ["all_intent_signals"]
        missing = []
        if not data.get("job_offers") or len(data["job_offers"]) == 0:
            missing.append("job_offers")
        if not data.get("news") or len(data["news"]) == 0:
            missing.append("news")
        return missing

    def get_targeted_links_with_ai(self, links_list, base_url, missing_fields, seen_urls, target_country=None):
        domain = urlparse(base_url).netloc
        internal_links = []

        for link in links_list:
            url = link['url']
            if domain in url and url not in seen_urls and len(link['text']) > 3:
                internal_links.append(link)

        unique_links = {v['url']: v for v in internal_links}.values()
        
        def sort_by_relevance(item):
            score = 0
            text_low = item['text'].lower()
            url_low = item['url'].lower()
            if target_country:
                c_low = target_country.lower()
                if c_low in text_low or c_low in url_low:
                    score += 10
            if "career" in url_low or "job" in url_low or "recrut" in url_low:
                score += 5
            return score

        sorted_links = sorted(unique_links, key=sort_by_relevance, reverse=True)
        sample_links = list(sorted_links)[:50]

        country_hint = (
            f" Specifically target routes related to '{target_country}'."
            if target_country
            else ""
        )
        print(f"🧠 [Agentic Navigation] Analyse des routes vers les hubs d'intentions : {missing_fields}...")
        try:
            raw_json = invoke_template(
                INTENT_NAVIGATION,
                missing_fields=", ".join(missing_fields),
                country_hint=country_hint,
                links_json=json.dumps(sample_links, indent=2),
                temperature=0.1,
                max_tokens=4000,
                fallback="",
                operation="intent_navigation",
            )
        except Exception as e:
            print(f"❌ Erreur lors de l'appel au LLM ({self.model_name}) : {e}")
            raw_json = ""
        if raw_json:
            backtick = "```"
            if backtick in raw_json:
                parts = raw_json.split(backtick)
                if len(parts) >= 3:
                    raw_json = parts[1].replace("json", "").strip()
                else:
                    raw_json = parts[1].strip()
        
        if raw_json:
            try:
                parsed = self.parse_json_response(raw_json)
                if isinstance(parsed, list):
                    return parsed
            except Exception as e:
                print(f"    ⚠️ Échec du parsing de navigation : {e}")
        return []

    def extract_intent_json(self, full_text, target_country=None):
        print("🧠 [Llama-3.1-70B] Extraction en cours du profil d'intentions commercial...")
        
        now = datetime.now()
        current_year = now.year

        user_prompt = f"📅 REFERENCE DATE: {now.strftime('%B %d, %Y')} (Year: {current_year})\n"
        user_prompt += f"🛑 STRICT RECENCY RULE: Ignore any news, event, or job offer that is obsolete or dates from a year prior to {current_year}.\n"
        
        if target_country:
            user_prompt += (
                f"⚠️ STRICT GEOGRAPHICAL CONSTRAINT: You are the SOLE arbiter of location. EXCLUSIVELY extract job offers (job_offers) "
                f"whose actual location is in this country: '{target_country}'. Rigorously verify each city using your knowledge. "
                f"If a position is in another country, simply ignore it. News items (news) remain global.\n\n"
            )
        
        user_prompt += f"TEXT COLLECTED DURING SCRAPING:\n{full_text}"

        try:
            raw_json = invoke_template(
                INTENT_SIGNALS_EXTRACT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=4000,
                fallback="",
                operation="intent_extract",
            )
        except Exception as e:
            print(f"❌ Erreur lors de l'appel au LLM ({self.model_name}) : {e}")
            raw_json = ""
        if raw_json:
            backtick = "```"
            if backtick in raw_json:
                parts = raw_json.split(backtick)
                if len(parts) >= 3:
                    raw_json = parts[1].replace("json", "").strip()
                else:
                    raw_json = parts[1].strip()
        
        if raw_json:
            parsed = self.parse_json_response(raw_json)
            if isinstance(parsed, dict):
                return {
                    "job_offers": parsed.get("job_offers", []),
                    "news": parsed.get("news", [])
                }
            if isinstance(parsed, list):
                print("⚠️ Réponse LLM vide ou non structurée, retour d'un résultat vide.")
                return {"job_offers": [], "news": []}

            print("⚠️ Réponse LLM non exploitable, retour d'un résultat vide.")
            return {"job_offers": [], "news": []}

        return {"job_offers": [], "news": []}

    def filter_jobs_by_country_with_llm(self, job_offers, target_country):
        """
        Vérification post-extraction pour forcer le retrait des offres 
        dont la localisation ne correspond pas au pays cible.
        """
        if not job_offers or not target_country:
            return job_offers

        print(f"🌍 [LLM Verification] Audit géographique strict des offres pour le pays : {target_country}...")
        
        try:
            raw_json = invoke_template(
                INTENT_GEO_FILTER,
                target_country=target_country,
                job_offers_json=json.dumps(job_offers, indent=2),
                temperature=0.0,
                max_tokens=4000,
                fallback="",
                operation="intent_geo_filter",
            )
        except Exception as e:
            print(f"❌ Erreur lors de l'appel au LLM ({self.model_name}) : {e}")
            raw_json = ""
        if raw_json:
            backtick = "```"
            if backtick in raw_json:
                parts = raw_json.split(backtick)
                if len(parts) >= 3:
                    raw_json = parts[1].replace("json", "").strip()
                else:
                    raw_json = parts[1].strip()
        
        if raw_json:
            try:
                filtered_jobs = self.parse_json_response(raw_json)
                if isinstance(filtered_jobs, list):
                    print(f"    ✅ Filtrage terminé : {len(filtered_jobs)} offre(s) conservée(s) sur {len(job_offers)}.")
                    return filtered_jobs
            except Exception as e:
                print(f"    ⚠️ Échec du parsing JSON lors du filtrage géographique : {e}")
        return job_offers

    def scrape_and_extract_intents(self, domain, target_country=None):
        """
        Prend un nom de domaine (ex: 'talan.com' ou 'capgemini.com') en entrée,
        construit automatiquement l'URL cible et gère l'extraction.
        """
        if domain.startswith(("http://", "https://")):
            url = domain
            domain_name = urlparse(domain).netloc
        else:
            url = f"https://{domain}"
            domain_name = domain

        domain_clean = domain_name.replace("www.", "").replace(".", "_")

        with sync_playwright() as p:
            print(f"🚀 Initialisation du navigateur Playwright pour le domaine : {domain_name} ({url})")
            browser = p.chromium.launch(headless=True)
            
            context = browser.new_context(
                viewport={'width': 1280, 'height': 850},
                user_agent=self.ua.random
            )
            page = context.new_page()

            try:
                def go_home():
                    return page.goto(url, wait_until="domcontentloaded", timeout=60000)

                self.execute_with_retry(go_home, operation_name=f"Navigation Accueil {url}")
                page.wait_for_timeout(2000)

                try:
                    page.click("text='Accept All'>>text='Accepter tout'", timeout=2500)
                except Exception:
                    pass

                self.smart_scroll(page)

                raw_html = page.content()
                all_links = page.locator('a').evaluate_all(
                    "list => list.map(a => ({text: a.innerText.trim(), url: a.href}))"
                )

                full_corpus = [f"--- LANDING PAGE CONTEXT : {page.title()} ---"]
                full_corpus.append(self.clean_html(raw_html))

                extracted_data = self.extract_intent_json("\n".join(full_corpus), target_country)

                missing_signals = self.check_missing_fields(extracted_data)
                seen_urls = {url}
                depth = 0
                max_depth = 2

                while missing_signals and depth < max_depth:
                    print(f"\n🔄 Boucle Autonome Intent (Step {depth+1}/{max_depth}) -> Signaux faibles : {missing_signals}")
                    targeted_routes = self.get_targeted_links_with_ai(all_links, url, missing_signals, seen_urls, target_country)

                    if not targeted_routes:
                        print("    ⚠️ Aucun itinéraire ciblé trouvé par l'IA.")
                        break

                    for route_url in targeted_routes:
                        if route_url in seen_urls:
                            continue
                        
                        print(f"🎯 Investigation de la sous-page d'intentions : {route_url}")
                        try:
                            def go_route():
                                return page.goto(route_url, wait_until="domcontentloaded", timeout=45000)
                            
                            self.execute_with_retry(go_route, max_retries=2, operation_name=f"Sous-page {route_url}")
                            page.wait_for_timeout(2000)
                            self.smart_scroll(page)

                            sub_html = page.content()
                            full_corpus.append(f"\n\n--- SUB-PAGE TARGET : {route_url} ---")
                            full_corpus.append(self.clean_html(sub_html))
                            seen_urls.add(route_url)
                        except Exception as e:
                            print(f"    ⚠️ Navigation avortée sur la route : {e}")

                    extracted_data = self.extract_intent_json("\n".join(full_corpus), target_country)
                    missing_signals = self.check_missing_fields(extracted_data)
                    depth += 1

                if extracted_data:
                    # APPEL DU FILTRE LLM POST-EXTRACTION
                    if target_country and "job_offers" in extracted_data and extracted_data["job_offers"]:
                        extracted_data["job_offers"] = self.filter_jobs_by_country_with_llm(
                            extracted_data["job_offers"], 
                            target_country
                        )

                    print("🧪 [XAI Process] Alignement des scores de calibration et fidélité de la preuve...")
                    extracted_data = self.inject_xai_metrics(extracted_data, "\n".join(full_corpus))

                    # --- RE-STRUCTURATION POUR MATCHER L'OUTPUT DE INTENT_SEARCH.PY ---
                    combined_intents = []
                    
                    if "job_offers" in extracted_data:
                        combined_intents.extend(extracted_data["job_offers"])
                    if "news" in extracted_data:
                        combined_intents.extend(extracted_data["news"])
                        
                else:
                    combined_intents = []

                json_filename = os.path.join(self.output_dir, f"{domain_clean}_INTENT_SIGNALS.json")
                
                with open(json_filename, "w", encoding="utf-8") as f:
                    json.dump(combined_intents, f, indent=4, ensure_ascii=False)
                
                print(f"\n✅ Terminé avec succès ! {len(combined_intents)} données d'intention stockées dans : {json_filename}")
                return json_filename

            finally:
                browser.close()

if __name__ == "__main__":
    intent_scraper = IntentSignalsScraper()
    
    # Renseigne directement le domaine ici (sans https ni sous-pages)
    company_domain = "wevioo.com" 
    country_filter = "Tunisia" 
    
    intent_scraper.scrape_and_extract_intents(company_domain, target_country=country_filter)