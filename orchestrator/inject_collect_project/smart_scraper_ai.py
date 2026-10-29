import os
import json
import io
import time
import requests
import re
import fitz
from PIL import Image
from google import genai
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import config
from fake_useragent import UserAgent
from difflib import SequenceMatcher  # <-- NOUVEAU : Pour la métrique de Calibration

PROMPT_SYSTEME_APOLLO_MIRROR = """
RÔLE :
Tu es un agent d'extraction de données spécialisé dans le mapping de sites web vers un schéma de données type 'Apollo.io'.

MISSION :
Analyse le texte scrapé, qui inclut :
- le texte visible du site,
- des extraits de rapports financiers PDF,
- des empreintes techniques brutes,
- des signaux de pages de confiance, de conformité et de structure corporate,

afin de remplir la structure de données ci-dessous.

ATTENTION CRITIQUE (CIBLAGE RÉGIONAL / GLOBAL) :
1. CIBLE SPÉCIFIQUE : Si une "ADRESSE CIBLE" ou localisation de référence est explicitement fournie dans le texte, tu DOIS extraire les informations (revenus, employés, adresse, dirigeants) de la FILIALE ou de l'entité correspondant à cette localisation précise (ex: la branche française), et NON du siège mondial global (Global HQ).
2. SANS CIBLE : Si aucune cible n'est fournie, extrais par défaut les informations du siège social mondial.
3. Pour 'annual_revenue', NE TE CONTENTE PAS de dire "Publicly Traded". Cherche activement un chiffre exact de la branche ciblée (ex: '1.3 Trillion JPY', '$10.5 Billion'). Si seul le revenu mondial est disponible, précise-le dans "source".
4. TECHNOLOGIES DÉTECTÉES : Analyse la section "EMPREINTE TECHNIQUE AVANCÉE" (Headers HTTP, Scripts, Objets JS, Classes CSS). Déduis-en les outils utilisés et liste-les dans 'technologies'.
5. STRUCTURE CORPORATIVE : Identifie la maison mère / ultimate parent si l'entreprise est une filiale.
6. CYCLE BUDGÉTAIRE : Cherche activement le mois de clôture de l'exercice fiscal (Fiscal Year End).
7. SCORING DE CONFIANCE : Pour chaque champ, retourne un objet avec :
   - "value" : la donnée
   - "confidence" : un nombre entre 0.0 et 1.0
   - "source" : la citation EXACTE du texte qui prouve cette donnée (très important pour les métriques XAI).

RÈGLES DE SORTIE :
- Réponds UNIQUEMENT avec du JSON valide.
- N'ajoute aucune explication.
- N'utilise pas de Markdown.
- N'utilise pas de commentaires.
- Si une donnée est introuvable, mets null dans "value" et une confidence faible, par exemple 0.0 à 0.3.

STRUCTURE DE SORTIE ATTENDUE :

{
  "identity": {
    "domain": { "value": "Domaine principal", "confidence": 1.0, "source": "URL" },
    "name": { "value": "Nom de l'organisation ciblée", "confidence": 0.9, "source": "Page d'accueil" },
    "industry": { "value": "Secteur d'activité", "confidence": 0.8, "source": "Site web / page about" },
    "founded_year": { "value": "Année de création", "confidence": 0.9, "source": "Page about / rapport" },
    "short_description": { "value": "Description concise", "confidence": 0.8, "source": "Page d'accueil / about" },
    "seo_description": { "value": "Description SEO trouvée", "confidence": 0.8, "source": "Meta description / page d'accueil" }
  },
  "performance": {
    "annual_revenue": { "value": "Valeur exacte du revenu", "confidence": 0.85, "source": "PDF financier / rapport annuel" },
    "fiscal_year_end": { "value": "Mois de clôture fiscal", "confidence": 0.9, "source": "Rapport annuel / note financière" },
    "total_funding": { "value": "Montant total levé", "confidence": 0.7, "source": "Page funding / newsroom / base de données" },
    "estimated_num_employees": { "value": "Nombre estimé d'employés", "confidence": 0.8, "source": "Site / base enrichie" },
    "latest_funding_stage": { "value": "Dernier stade de financement", "confidence": 0.9, "source": "Rapport / base enrichie" }
  },
  "contact_social": {
    "linkedin_url": { "value": "Lien LinkedIn", "confidence": 0.9, "source": "Site / footer / page contact" },
    "twitter_url": { "value": "Lien Twitter/X", "confidence": 0.9, "source": "Site / footer / page contact" },
    "facebook_url": { "value": "Lien Facebook", "confidence": 0.9, "source": "Site / footer / page contact" },
    "phone": { "value": "Numéro de l'entité ciblée", "confidence": 0.6, "source": "Site / page contact" }
  },
  "hierarchy": {
    "is_subsidiary": { "value": true, "confidence": 0.9, "source": "Déduction corporate" },
    "parent_company": { "value": "Nom de la maison mère", "confidence": 0.95, "source": "Site / rapport / déduction" },
    "num_suborganizations": { "value": "Nombre de filiales mentionnées", "confidence": 0.7, "source": "Site / rapport / déduction" },
    "subsidiaries_list": {
      "value": ["Nom des filiales/sous-organisations"],
      "confidence": 0.7,
      "source": "Site / rapport / déduction"
    }
  },
  "location_detailed": {
    "raw_address": { "value": "Adresse complète de l'entité ciblée", "confidence": 0.8, "source": "Page contact / about" },
    "city": { "value": "Ville de l'entité ciblée", "confidence": 0.9, "source": "Page contact / about" },
    "country": { "value": "Pays de l'entité ciblée", "confidence": 0.9, "source": "Page contact / about" }
  },
  "technologies": [
    {
      "name": "Nom de la technologie",
      "category": "Catégorie",
      "confidence": 0.99,
      "source": "Déduction IA depuis empreinte technique"
    }
  ],
  "funding_events": [
    {
      "date": "Date de l'événement",
      "type": "Type de levée",
      "amount": "Montant"
    }
  ],
  "keywords": {
    "value": "Liste de mots-clés séparés par des virgules",
    "confidence": 0.8,
    "source": "Site / page about / SEO"
  }
}

CONTRAINTE :
Ne génère aucune explication. Réponds uniquement avec le JSON.
"""

class SmartScraperAI:
    def __init__(self, output_dir="scraped_data"):
        self.output_dir = output_dir
        self._token_tracker = None
        self.client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options={'api_version': 'v1beta'}
        )
        
        # --- DEFINITION DES PALIERS DE MODELES CORRIGÉS ---
        self.PRO_MODELS = [
            "gemini-3-flash-preview",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemma-4-31b-it",
            "gemma-4-26b-a4b-it",
            "gemini-flash-latest",
        ]

        self.FAST_MODELS = [
            "gemini-3.1-flash-lite-preview",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-flash-lite-latest",
            "gemini-robotics-er-1.5-preview",
        ]

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
                print(
                    f"⚠️ {operation_name} échoué ({type(e).__name__}). "
                    f"Retentative dans {wait_time}s (Essai {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)

    def _record_gemini_usage(self, model_name, level, operation, response=None, success=True, error=None):
        tracker = self._token_tracker
        if not tracker:
            return

        usage_metadata = getattr(response, "usage_metadata", None) if response else None
        tracker.record(
            model=model_name,
            level=level,
            operation=operation,
            usage_metadata=usage_metadata,
            success=success,
            error=error,
        )

    def safe_generate_content(self, contents, level="pro", force_json=True, operation="generate_content"):
        priority_list = self.PRO_MODELS if level == "pro" else self.FAST_MODELS
        
        for i, model_name in enumerate(priority_list):
            try:
                config = {'response_mime_type': 'application/json'} if force_json else {}
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                
                raw_text = response.text.strip()
                if "```" in raw_text:
                    raw_text = raw_text.split("```")[1].replace("json", "").strip()
                self._record_gemini_usage(model_name, level, operation, response=response, success=True)
                return raw_text

            except Exception as e:
                err_msg = str(e).upper()
                if "503" in err_msg or "429" in err_msg or "UNAVAILABLE" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "NOT_FOUND" in err_msg:
                    self._record_gemini_usage(
                        model_name,
                        level,
                        operation,
                        success=False,
                        error=str(e),
                    )
                    if i < len(priority_list) - 1:
                        next_model = priority_list[i + 1]
                        print(f"    ⚠️ Modèle {model_name} saturé/indisponible. 🔄 Basculement vers : {next_model}...")
                        time.sleep(2)
                        continue
                    else:
                        print(f"    🛑 Tous les modèles de la catégorie '{level}' ont échoué. Échec de la requête.")
                        break
                else:
                    self._record_gemini_usage(
                        model_name,
                        level,
                        operation,
                        success=False,
                        error=str(e),
                    )
                    print(f"    ❌ Erreur inattendue avec {model_name} : {e}")
                    break
        return None

    # =========================================================================
    # NOUVEAU BLOC : METRIQUES XAI (EXPLAINABLE AI)
    # =========================================================================
    def inject_xai_metrics(self, data_node, raw_text):
        """
        Parcourt récursivement le JSON et injecte les métriques XAI 
        là où 'value', 'confidence' et 'source' sont présents.
        """
        if isinstance(data_node, dict):
            # Si c'est un noeud "feuille" contenant nos métadonnées cibles
            if "confidence" in data_node and "source" in data_node:
                source_str = str(data_node.get("source", ""))
                conf = float(data_node.get("confidence", 0.0))
                
                # Récupération de la valeur extraite (généralement "value" ou "name")
                val_str = ""
                if "value" in data_node:
                    val_str = str(data_node["value"])
                elif "name" in data_node:
                    val_str = str(data_node["name"])

                # --- 1. Faithfulness Metric (Fidélité) ---
                # On vérifie si la source citée existe bien dans le texte brut
                is_faithful = 1 if source_str and source_str.lower().strip() in raw_text.lower() else 0

                # --- 2. Confidence Calibration ---
                # Similarité entre la valeur extraite et la preuve fournie
                similarity = SequenceMatcher(None, val_str.lower(), source_str.lower()).ratio()
                calibration_error = abs(conf - similarity)

                # --- 3. Evidence Density ---
                # Ratio longueur valeur / longueur source
                density = len(val_str) / len(source_str) if len(source_str) > 0 else 0.0

                # Injection du rapport XAI dans le noeud
                data_node["xai_metrics"] = {
                    "faithfulness_score": is_faithful,
                    "calibration_error": round(calibration_error, 2),
                    "evidence_density": round(density, 2)
                }

            # Continuer la récursion pour les dictionnaires imbriqués
            for key, value in data_node.items():
                if isinstance(value, (dict, list)):
                    self.inject_xai_metrics(value, raw_text)
                    
        elif isinstance(data_node, list):
            # Continuer la récursion pour les listes
            for item in data_node:
                self.inject_xai_metrics(item, raw_text)

        return data_node
    # =========================================================================

    def smart_scroll(self, page):
        print("    ⏬ Lancement de l'auto-scroll dynamique (Lazy Loading)...")
        try:
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 600;
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= scrollHeight - window.innerHeight || totalHeight > 10000) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 300);
                    });
                }
            """)
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"    ⚠️ Erreur lors du scroll : {e}")

    def extract_tech_footprint(self, page, response):
        print("    🕵️‍♂️ Collecte des empreintes techniques avancées (Headers, Scripts, JS, CSS)...")
        footprint = ["\n=== EMPREINTE TECHNIQUE AVANCÉE ==="]

        if response:
            headers = response.headers
            important_keys = [
                'x-powered-by', 'server', 'via',
                'x-nextjs-cache', 'x-vercel-id', 'x-generator', 'link'
            ]
            found_headers = {k: v for k, v in headers.items() if k.lower() in important_keys}
            if found_headers:
                footprint.append("--- HEADERS HTTP ---")
                for k, v in found_headers.items():
                    footprint.append(f"{k}: {v}")

        try:
            scripts = page.locator('script[src]').evaluate_all("list => list.map(s => s.src)")
            if scripts:
                footprint.append("--- SCRIPTS EXTERNES CHARGÉS (Échantillon) ---")
                unique_scripts = list(set([urlparse(s).netloc for s in scripts if s]))[:40]
                footprint.append(", ".join(unique_scripts))
        except Exception:
            pass

        try:
            js_check = """
            () => {
                const keys = Object.keys(window);
                const ignore = ['document', 'window', 'location', 'top', 'chrome', 'console', 'History', 'Math'];
                return keys.filter(k => !ignore.includes(k) && k.length > 2).slice(0, 40);
            }
            """
            window_keys = page.evaluate(js_check)
            if window_keys:
                footprint.append("--- OBJETS GLOBAUX JS (WINDOW) ---")
                footprint.append(", ".join(window_keys))
        except Exception:
            pass

        try:
            css_check = """
            () => {
                const allElements = document.querySelectorAll('*');
                const classSet = new Set();
                allElements.forEach(el => {
                    if (el.classList) {
                        el.classList.forEach(c => {
                            if (c.includes('-')) classSet.add(c.split('-')[0] + '-*');
                        });
                    }
                });
                return Array.from(classSet).slice(0, 30);
            }
            """
            classes = page.evaluate(css_check)
            if classes:
                footprint.append("--- PRÉFIXES CSS DÉTECTÉS ---")
                footprint.append(", ".join(classes))
        except Exception:
            pass

        footprint.append("===================================")
        return "\n".join(footprint)

    def extract_hidden_tech(self, html):
        tech_signatures = {
            "HubSpot": r"js\.hs-scripts\.com|js\.hs-analytics\.net",
            "WordPress": r"wp-content|wp-includes",
            "Salesforce": r"salesforce\.com|force\.com",
            "Marketo": r"munchkin\.marketo\.net",
            "Segment": r"cdn\.segment\.com",
            "Google Analytics": r"google-analytics\.com|gtag\(",
            "Google Tag Manager": r"googletagmanager\.com",
            "Hotjar": r"static\.hotjar\.com",
            "Stripe": r"js\.stripe\.com",
            "Intercom": r"widget\.intercom\.io",
            "Zendesk": r"static\.zdassets\.com",
            "Shopify": r"cdn\.shopify\.com",
            "React": r"data-reactroot|_reactRoot",
            "Next.js": r"_next/static",
            "Vercel": r"vercel\.app",
            "Datadog": r"browser\.datadoghq\.com",
            "Mixpanel": r"cdn\.mxpnl\.com"
        }
        found_techs = set()
        for tech_name, pattern in tech_signatures.items():
            if re.search(pattern, html, re.IGNORECASE):
                found_techs.add(tech_name)
        return list(found_techs)

    def clean_html(self, html):
        """
        Amélioration de l'extraction: Conversion de la structure HTML en pseudo-Markdown
        pour maximiser la compréhension sémantique du LLM.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Suppression stricte du bruit (ajout de svg, button, form, dialog, etc.)
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript', 'svg', 'button', 'form', 'meta', 'link']):
            tag.decompose()

        # 2. Conversion structurelle en pseudo-Markdown
        for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(h.name[1])
            h.insert_before(f"\n\n{'#' * level} ")
            h.insert_after("\n\n")

        for li in soup.find_all('li'):
            li.insert_before("\n- ")

        for p in soup.find_all('p'):
            p.insert_before("\n")
            p.insert_after("\n")

        for br in soup.find_all('br'):
            br.replace_with('\n')

        # 3. Extraction du texte avec espacement
        text = soup.get_text(separator=' ')

        # 4. Nettoyage et compactage
        text = re.sub(r'[ \t]+', ' ', text)
        clean_lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        return "\n".join(clean_lines)

    def read_image_with_vision(self, img):
        prompt = """
Tu es un analyste financier. Lis cette image extraite d'un rapport annuel.
Retranscris les tableaux financiers en texte clair, de manière structurée.
Concentre-toi sur le chiffre d'affaires (Revenue / Sales), les dates, et la devise.
Ne fais pas de phrases inutiles, donne juste les données.
"""
        print("    👁️ [Vision - PRO] Analyse visuelle du tableau financier...")
        raw_text = self.safe_generate_content([prompt, img], level="pro", force_json=False, operation="vision_pdf")
        return raw_text if raw_text else "[Erreur d'extraction visuelle - Modèles indisponibles]"

    def extract_pdf_in_memory(self, pdf_url):
        print(f"📄 Analyse Smart-Scan du PDF financier : {pdf_url}")
        headers = {'User-Agent': self.ua.random}

        def fetch_pdf():
            res = requests.get(pdf_url, headers=headers, timeout=25)
            res.raise_for_status()
            return res

        try:
            response = self.execute_with_retry(fetch_pdf, operation_name="Téléchargement PDF")
            doc = fitz.open(stream=response.content, filetype="pdf")
            relevant_pages_text = []

            triggers = [
                "consolidated statement of income", "financial highlights",
                "balance sheet", "financial summary", "profit and loss",
                "key figures", "états financiers", "chiffres clés",
                "fiscal year ended", "for the year ended"
            ]

            for i in range(len(doc)):
                page = doc[i]
                page_text = page.get_text()
                content_lower = page_text.lower()

                if any(trigger in content_lower for trigger in triggers):
                    lines = [line for line in page_text.split('\n') if line.strip()]
                    word_count = len(page_text.split())
                    is_bouillie = len(page_text.strip()) < 200 or (len(lines) > 0 and (word_count / len(lines)) < 3)

                    if is_bouillie:
                        pix = page.get_pixmap(dpi=150)
                        img_data = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_data))
                        vision_text = self.read_image_with_vision(img)
                        relevant_pages_text.append(f"--- PAGE PDF {i+1} (DÉCODÉE PAR VISION) ---\n{vision_text}")
                    else:
                        relevant_pages_text.append(f"--- PAGE PDF {i+1} ---\n{page_text}")

                if len(relevant_pages_text) >= 8:
                    break

            if not relevant_pages_text:
                for i in range(min(5, len(doc))):
                    relevant_pages_text.append(doc[i].get_text())

            doc.close()
            return "\n\n".join(relevant_pages_text)

        except Exception as e:
            print(f"⚠️ Erreur Smart-Scan PDF : {e}")
            return ""

    def check_missing_fields(self, data):
        if not data:
            return ["all"]

        missing = []

        rev = data.get("performance", {}).get("annual_revenue", {})
        val = str(rev.get("value", "")).lower()
        if rev.get("confidence", 0) < 0.75 or "public" in val or val in ["", "null", "none", "unknown"]:
            missing.append("annual_revenue (chiffre exact)")

        city = data.get("location_detailed", {}).get("city", {})
        if city.get("confidence", 0) < 0.7 or not city.get("value"):
            missing.append("city (Localisation ciblée)")

        return missing

    def get_targeted_links_with_ai(self, links_list, base_url, missing_fields, seen_urls):
        domain = urlparse(base_url).netloc
        internal_links = []

        for link in links_list:
            url = link['url']
            if domain in url and url not in seen_urls and len(link['text']) > 3:
                internal_links.append(link)

        unique_links = {v['url']: v for v in internal_links}.values()
        sample_links = list(unique_links)[:60]

        prompt_nav = f"""
RÔLE : Agent de navigation autonome.
MISSION : Sélectionner 1 à 2 URLs maximum pour trouver LES INFORMATIONS MANQUANTES : {', '.join(missing_fields)}.

RÈGLES :
- Ne choisis que les pages pertinentes.
- Pour les revenus, privilégie "Investors", "Annual Report", "Financials", "Results", "Mentions légales".
- Pour la ville et l'adresse de l'entité, privilégie "Contact", "About", "Office", "Locations", "Mentions légales".
- Pour la conformité, privilégie "Trust Center", "Security", "Legal", "Privacy".

INPUT (JSON) :
{json.dumps(list(sample_links), indent=2)}

SORTIE :
Un tableau JSON d'URLs. Exemple: ["url1", "url2"]
"""
        print(f"🧠 [Agentic Mind - FAST] Choix du prochain déplacement pour trouver : {missing_fields}...")
        raw_json = self.safe_generate_content(prompt_nav, level="fast", operation="navigation")
        
        if raw_json:
            try:
                return json.loads(raw_json)
            except Exception as e:
                print(f"    ⚠️ Erreur parsing JSON (Navigation) : {e}")
        return []

    def extract_apollo_json(self, full_text):
        print(f"🧠 [Agentic Mind - PRO] Extraction des données Apollo-Style en cours...")
        prompt_final = f"{PROMPT_SYSTEME_APOLLO_MIRROR}\n\nTEXTE SCRAPÉ DU SITE ET DES RAPPORTS :\n{full_text}"
        
        raw_json = self.safe_generate_content(prompt_final, level="pro", operation="extract_apollo")
        
        if raw_json:
            try:
                return json.loads(raw_json)
            except Exception as e:
                print(f"❌ Erreur lors du parsing JSON (Extraction) : {e}")
        return None

    def finalize_data_with_llm(self, extracted_data, full_text):
        print("    🪄 [Agentic Mind - PRO] Post-traitement unifié (Devise USD, Qualité, Concurrents)...")
        prompt = f"""
Tu es un analyste expert en Data Enrichment.
Voici un JSON partiel contenant les données extraites d'une entreprise :
{json.dumps(extracted_data, ensure_ascii=False, indent=2)}

Mission : Tu dois compléter ce profil en générant un JSON contenant STRICTEMENT ces 3 clés :
1. "annual_revenue_USD" : Convertis la valeur de `performance.annual_revenue` en un nombre (USD). Si cest impossible, retourne null. Inclus un score de confiance et la source.
2. "data_quality_score" : Évalue la qualité globale et la complétude du JSON partiel. Donne un score entre 0.0 et 1.0.
3. "competitors" : Déduis une liste (Array of strings) de 3 à 5 concurrents directs basés sur le nom et l'industrie.

Format exact attendu :
{{
  "annual_revenue_USD": {{ "value": 0, "confidence": 0.0, "source": "string" }},
  "data_quality_score": {{ "value": 0.0, "confidence": 0.0, "source": "string" }},
  "competitors": ["comp1", "comp2", "comp3"]
}}

Contexte supplémentaire si besoin :
{full_text[:15000]}
"""
        raw_json = self.safe_generate_content(prompt, level="pro", operation="post_process")

        if raw_json:
            try:
                result = json.loads(raw_json)
                if "performance" not in extracted_data:
                    extracted_data["performance"] = {}
                    
                extracted_data["performance"]["annual_revenue_USD"] = result.get("annual_revenue_USD", {
                    "value": None, "confidence": 0.0, "source": "LLM unified processing failed"
                })
                
                extracted_data["data_quality_score"] = result.get("data_quality_score", {
                    "value": 0.0, "confidence": 0.0, "source": "LLM unified processing failed"
                })
                
                extracted_data.setdefault("market_intelligence", {})["competitors"] = result.get("competitors", [])

            except Exception as e:
                print(f"    ⚠️ Erreur parsing JSON (Post-traitement) : {e}")
                
        return extracted_data

    def extract_social_links_from_html(self, page):
        social = {
            "linkedin_url": None,
            "twitter_url": None,
            "facebook_url": None
        }

        try:
            links = page.locator("a[href]").evaluate_all(
                "els => els.map(a => a.href)"
            )

            for link in links:
                l = link.lower()

                if "linkedin.com/company/" in l:
                    social["linkedin_url"] = link

                elif "twitter.com/" in l or "x.com/" in l:
                    social["twitter_url"] = link

                elif "facebook.com/" in l:
                    social["facebook_url"] = link

        except Exception as e:
            print(f"⚠️ Erreur extraction liens sociaux : {e}")

        return social

    def url_page_exists(self, url):
        try:
            res = requests.get(
                url,
                timeout=8,
                headers={"User-Agent": self.ua.random}
            )
            if res.status_code >= 400:
                return False, res.text.lower()
            return True, res.text.lower()
        except Exception:
            return False, ""

    def validate_social_url(self, url, platform):
        if not url:
            return False

        exists, html = self.url_page_exists(url)
        if not exists:
            return False

        error_signatures = {
            "twitter": [
                "this account doesn’t exist",
                "this account doesn't exist",
                "try searching for another",
                "account suspended",
                "page doesn’t exist",
                "page not found"
            ],
            "linkedin": [
                "page not found",
                "this page does not exist",
                "profile not found",
                "sign in to linkedin",
                "join linkedin"
            ],
            "facebook": [
                "content isn't available",
                "page not found",
                "this page isn't available",
                "sorry, this content isn't available right now"
            ]
        }

        for sig in error_signatures.get(platform, []):
            if sig in html:
                return False

        return True

    def fix_social_links(self, extracted_data, real_social_links):
        social = extracted_data.get("contact_social", {})

        checks = {
            "linkedin_url": "linkedin",
            "twitter_url": "twitter",
            "facebook_url": "facebook"
        }

        for field, platform in checks.items():
            real_url = real_social_links.get(field)
            llm_value = social.get(field, {}).get("value") if isinstance(social.get(field), dict) else None

            if real_url and self.validate_social_url(real_url, platform):
                social[field] = {
                    "value": real_url,
                    "confidence": 0.98,
                    "source": "HTML direct + validation page"
                }
            elif llm_value and self.validate_social_url(llm_value, platform):
                social[field] = {
                    "value": llm_value,
                    "confidence": 0.6,
                    "source": "LLM validated by page check"
                }
            else:
                social[field] = {
                    "value": None,
                    "confidence": 0.0,
                    "source": "invalid or hallucinated link"
                }

        extracted_data["contact_social"] = social
        return extracted_data

    def get_browser_config_with_ai(self, target_address):
        """
        Demande au LLM de définir les paramètres techniques du navigateur.
        """
        if not target_address:
            return {"locale": "en-US", "timezone_id": "UTC"}

        prompt = f"""
        RÔLE : Expert en configuration système navigateur.
        MISSION : Pour l'adresse suivante : '{target_address}', détermine :
        1. La 'locale' appropriée (ex: fr-FR, en-GB, ja-JP).
        2. Le 'timezone_id' IANA officiel (ex: Africa/Tunis, Europe/Paris, Asia/Tokyo).

        RÈGLE : Réponds UNIQUEMENT en JSON.
        FORMAT : {{"locale": "...", "timezone_id": "..."}}
        """
        
        raw_json = self.safe_generate_content(prompt, level="fast", force_json=True, operation="browser_config")
        
        if raw_json:
            try:
                return json.loads(raw_json)
            except Exception as e:
                print(f"    ⚠️ Erreur parsing JSON (Config Navigateur) : {e}")
                
        return {"locale": "en-US", "timezone_id": "UTC"}

    def scrape_and_save(self, url, target_address=None, token_tracker=None):
        self._token_tracker = token_tracker
        try:
            use_graph = getattr(config, "USE_SCRAPER_GRAPH", True)
            if use_graph:
                from smart_scraper_graph import run_scraper_graph

                print("🕸️ SmartScraperAI: orchestration LangGraph activée")
                return run_scraper_graph(self, url, target_address=target_address)
            print("📜 SmartScraperAI: chemin legacy (while-loop)")
            return self._scrape_and_save_impl(url, target_address=target_address)
        finally:
            self._token_tracker = None

    def _scrape_and_save_impl(self, url, target_address=None):
        with sync_playwright() as p:
            print(f"🚀 Lancement du navigateur pour : {url}")
            browser = p.chromium.launch(headless=True)
            random_user_agent = self.ua.random

            print(f"🧠 L'IA configure le navigateur pour la cible : {target_address}")
            config = self.get_browser_config_with_ai(target_address)
            
            context = browser.new_context(
                locale=config.get("locale", "en-US"),
                timezone_id=config.get("timezone_id", "UTC"),
                user_agent=random_user_agent,
                viewport={'width': 1280, 'height': 800}
            )
            
            page = context.new_page()

            try:
                def go_main():
                    return page.goto(url, wait_until="domcontentloaded", timeout=60000)

                response_main = self.execute_with_retry(go_main, operation_name=f"Navigation principale {url}")
                page.wait_for_timeout(2000)

                try:
                    page.click("text='Accept All'", timeout=3000)
                except Exception:
                    pass

                self.smart_scroll(page)

                title = page.title()
                raw_html = page.content()

                tech_footprint_text = self.extract_tech_footprint(page, response_main)
                hidden_techs_regex = self.extract_hidden_tech(raw_html)
                real_social_links = self.extract_social_links_from_html(page)

                all_links_raw = page.locator('a').evaluate_all(
                    "list => list.map(a => ({text: a.innerText.trim(), url: a.href}))"
                )

                pdf_keywords = ['report', 'annual', 'integrated', 'financial', 'investors']
                potential_pdfs = []
                standard_links = []

                for link in all_links_raw:
                    link_url = link['url'].lower()
                    link_text = link['text'].lower()
                    if '.pdf' in link_url and any(kw in link_url or kw in link_text for kw in pdf_keywords):
                        potential_pdfs.append(link['url'])
                    else:
                        standard_links.append(link)

                full_content = [f"--- PAGE D'ACCUEIL : {title} ---"]
                
                if target_address:
                    full_content.append(f"\n⚠️ DIRECTIVE DE CIBLAGE (APOLLO) ⚠️")
                    full_content.append(f"ADRESSE CIBLE : {target_address}")
                    full_content.append("Instructions : L'utilisateur recherche spécifiquement cette entité régionale. Ignore le siège mondial global et focalise-toi sur les données (revenus, adresse, filiale) de CETTE localisation.\n")

                full_content.append(tech_footprint_text)
                if hidden_techs_regex:
                    full_content.append(f"--- MATCHES REGEX CLASSIQUES ---\n{', '.join(hidden_techs_regex)}\n")
                full_content.append(self.clean_html(raw_html))

                extracted_data = self.extract_apollo_json("\n".join(full_content))

                missing_fields = self.check_missing_fields(extracted_data)
                seen_urls = {url}
                depth = 0
                max_depth = 2

                while missing_fields and depth < max_depth:
                    print(f"\n🔄 Boucle Autonome (Step {depth+1}/{max_depth}) - Infos manquantes : {missing_fields}")
                    next_urls = self.get_targeted_links_with_ai(standard_links, url, missing_fields, seen_urls)

                    if not next_urls:
                        print("    ⚠️ Plus d'URLs pertinentes pour ces infos.")
                        break

                    for sub_url in next_urls:
                        if sub_url in seen_urls:
                            continue

                        print(f"🎯 Investigation ciblée : {sub_url}")
                        try:
                            def go_sub():
                                return page.goto(sub_url, wait_until="domcontentloaded", timeout=45000)

                            response_sub = self.execute_with_retry(
                                go_sub,
                                max_retries=2,
                                operation_name=f"Sous-page {sub_url}"
                            )
                            page.wait_for_timeout(2000)

                            self.smart_scroll(page)

                            sub_raw_html = page.content()
                            sub_tech_footprint = self.extract_tech_footprint(page, response_sub)

                            full_content.append(f"\n\n--- PAGE STRATÉGIQUE : {sub_url} ---")
                            full_content.append(sub_tech_footprint)
                            full_content.append(self.clean_html(sub_raw_html))
                            seen_urls.add(sub_url)

                            sub_page_pdfs = page.locator('a[href$=".pdf"]').evaluate_all("list => list.map(a => a.href)")
                            for pdf in sub_page_pdfs:
                                if any(kw in pdf.lower() for kw in pdf_keywords) and pdf not in potential_pdfs:
                                    potential_pdfs.append(pdf)
                        except Exception as e:
                            print(f"    ⚠️ Erreur de navigation : {e}")

                    extracted_data = self.extract_apollo_json("\n".join(full_content))
                    missing_fields = self.check_missing_fields(extracted_data)
                    depth += 1

                if potential_pdfs and "annual_revenue (chiffre exact)" in missing_fields:
                    target_pdf = potential_pdfs[0]
                    pdf_text = self.extract_pdf_in_memory(target_pdf)
                    if pdf_text:
                        full_content.append(f"\n\n--- EXTRAITS FINANCIERS DU PDF ({target_pdf}) ---")
                        full_content.append(pdf_text)
                        extracted_data = self.extract_apollo_json("\n".join(full_content))

                # --- APPEL DE LA FONCTION UNIFIÉE ET XAI ---
                if extracted_data:
                    extracted_data = self.fix_social_links(extracted_data, real_social_links)
                    extracted_data = self.finalize_data_with_llm(extracted_data, "\n".join(full_content))
                    
                    # INJECTION DES METRIQUES XAI
                    print("    🧪 [XAI] Calcul des métriques d'explicabilité (Faithfulness, Calibration, Density)...")
                    extracted_data = self.inject_xai_metrics(extracted_data, "\n".join(full_content))

                domain_name = urlparse(url).netloc.replace(".", "_")
                raw_filepath = os.path.join(self.output_dir, f"{domain_name}_RAW.txt")

                with open(raw_filepath, "w", encoding="utf-8") as f:
                    f.write("\n".join(full_content))

                if extracted_data:
                    json_filepath = os.path.join(self.output_dir, f"{domain_name}_APOLLO.json")
                    with open(json_filepath, "w", encoding="utf-8") as f:
                        json.dump(extracted_data, f, indent=4, ensure_ascii=False)
                    print(f"\n✅ Succès ! Fichier JSON final généré avec XAI Metrics : {json_filepath}")
                    return json_filepath
                else:
                    print("⚠️ Échec de la génération du JSON final.")
                    return raw_filepath

            finally:
                browser.close()

if __name__ == "__main__":
    scraper = SmartScraperAI()
    
    # Exemple pour cibler spécifiquement l'entité en France
    target_url = "https://www.ibm.com/"
    apollo_target_location = "USA" 
    
    scraper.scrape_and_save(target_url, target_address=apollo_target_location)