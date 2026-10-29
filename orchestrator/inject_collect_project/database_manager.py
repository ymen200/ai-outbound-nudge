from neo4j import GraphDatabase
import sys
import json
import re

from config import get_neo4j_credentials, MAX_INTENT_SIGNALS_PER_COMPANY


def build_company_intent_summary(company_name, intent_signals):
    """Create a concise English summary from a company's intent signals."""
    if not company_name:
        company_name = "the company"

    if not intent_signals:
        return f"{company_name} currently shows no recent intent signals."

    jobs = [s for s in intent_signals if s.get("intent_type") == "job_post"]
    news = [s for s in intent_signals if s.get("intent_type") == "news"]

    parts = [f"{company_name} shows recent commercial intent signals"]

    if jobs:
        job_titles = []
        for job in jobs[:3]:
            title = job.get("title") or "open role"
            job_titles.append(title)
        parts.append(f"including hiring activity such as {', '.join(job_titles)}")

    if news:
        news_titles = []
        for item in news[:3]:
            title = item.get("title_and_summary") or item.get("title") or "recent company update"
            news_titles.append(title)
        parts.append(f"and recent company updates such as {', '.join(news_titles)}")

    summary = " ".join(parts)
    summary = re.sub(r"\s+", " ", summary).strip()
    return summary + "."


class Neo4jManager:
    def __init__(self):
        self.uri, self.user, self.password = get_neo4j_credentials()

        try:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self.driver.verify_connectivity()
            print("✅ Connectivité Neo4j établie.")
        except Exception as e:
            print(f"❌ Erreur de connexion : {e}")
            sys.exit(1)

    def clean_domain(self, domain: str) -> str:
        if not domain:
            return None
        cleaned = str(domain).strip().lower()
        cleaned = re.sub(r'^https?://', '', cleaned)
        cleaned = re.sub(r'^www\.', '', cleaned)
        cleaned = cleaned.split('/')[0]
        if cleaned in ["", "non renseigné", "non trouvé", "null", "none"]:
            return None
        return cleaned

    @staticmethod
    def normalize_linkedin_url(url) -> str | None:
        """Normalise une URL LinkedIn pour éviter les doublons http/https et slash final."""
        if url is None:
            return None
        raw = str(url).strip()
        if not raw or raw.lower() in {"non trouvé", "non trouve", "null", "none", "n/a", ""}:
            return None
        if "linkedin.com/in/" not in raw.lower():
            return raw
        profile_path = raw.split("linkedin.com/in/")[-1].strip(" /")
        if not profile_path:
            return None
        return f"https://www.linkedin.com/in/{profile_path}/"

    def intent_signal_uid(self, intent: dict, company_domain: str) -> str:
        """Identifiant stable d'un signal d'intention pour une entreprise."""
        domain_clean = self.clean_domain(company_domain) or str(company_domain or "unknown")
        key = (
            intent.get("id")
            or intent.get("title")
            or intent.get("title_and_summary")
            or "unknown"
        )
        return f"{key}_{domain_clean}"

    def get_company_persona_index(self, apollo_id: str) -> dict:
        """
        Index des personas déjà liés à une company.
        Retourne ids Apollo, linkedin normalisés, et ids déjà enrichis (intent présent).
        """
        empty = {"ids": set(), "linkedin_urls": set(), "with_intent_ids": set()}
        if not apollo_id:
            return empty

        query = """
        MATCH (c:Company {apollo_id: $apollo_id})<-[:WORKS_AT]-(p:Persona)
        RETURN p.id AS id,
               p.linkedin_url AS linkedin_url,
               p.intent AS intent
        """
        try:
            with self.driver.session() as session:
                rows = list(session.run(query, apollo_id=apollo_id.strip()))
        except Exception as e:
            print(f"[ERROR] Lecture index personas pour {apollo_id} : {e}")
            return empty

        index = {"ids": set(), "linkedin_urls": set(), "with_intent_ids": set()}
        for row in rows:
            persona_id = row.get("id")
            if persona_id:
                index["ids"].add(str(persona_id))
                intent = row.get("intent")
                if intent and str(intent).strip() and str(intent).strip().lower() not in {
                    "none", "null", "n/a", "non renseigné", "non renseigne"
                }:
                    index["with_intent_ids"].add(str(persona_id))
            normalized = self.normalize_linkedin_url(row.get("linkedin_url"))
            if normalized:
                index["linkedin_urls"].add(normalized)
        return index

    def get_existing_intent_uids(self, company_identifier: str) -> set:
        """Retourne les uid IntentSignal déjà liés à une entreprise (apollo_id ou domain)."""
        if not company_identifier:
            return set()

        domain_clean = self.clean_domain(company_identifier) or company_identifier
        query = """
        MATCH (c:Company)-[:HAS_INTENT_SIGNAL]->(signal:IntentSignal)
        WHERE c.apollo_id = $company_identifier OR c.domain = $domain
        RETURN collect(signal.uid) AS uids
        """
        try:
            with self.driver.session() as session:
                record = session.run(
                    query,
                    company_identifier=company_identifier,
                    domain=domain_clean,
                ).single()
                uids = record["uids"] if record else []
                return {uid for uid in uids if uid}
        except Exception as e:
            print(f"[ERROR] Lecture IntentSignal pour {company_identifier} : {e}")
            return set()

    def dedupe_personas_for_company(self, apollo_id: str) -> int:
        """
        Fusionne les doublons Persona d'une company partageant le même Apollo id.
        Conserve un noeud canonique, rattache les relations, supprime les autres.
        """
        if not apollo_id:
            return 0

        query = """
        MATCH (c:Company {apollo_id: $apollo_id})<-[:WORKS_AT]-(p:Persona)
        WHERE p.id IS NOT NULL AND trim(toString(p.id)) <> ''
        WITH p.id AS pid, collect(p) AS nodes
        WHERE size(nodes) > 1
        WITH pid, nodes,
             reduce(
               keeper = nodes[0],
               n IN nodes |
                 CASE
                   WHEN n.linkedin_url STARTS WITH 'https://www.linkedin.com/in/' THEN n
                   WHEN keeper.linkedin_url STARTS WITH 'https://www.linkedin.com/in/' THEN keeper
                   ELSE n
                 END
             ) AS keeper
        UNWIND nodes AS n
        WITH pid, keeper, n
        WHERE elementId(n) <> elementId(keeper)
        OPTIONAL MATCH (n)-[r:POSTED]->(post:Post)
        FOREACH (_ IN CASE WHEN post IS NULL THEN [] ELSE [1] END |
          MERGE (keeper)-[:POSTED]->(post)
          DELETE r
        )
        DETACH DELETE n
        RETURN count(*) AS removed
        """
        try:
            with self.driver.session() as session:
                record = session.run(query, apollo_id=apollo_id.strip()).single()
                removed = int(record["removed"]) if record and record["removed"] else 0
                if removed:
                    print(
                        f"🧹 Dedup personas company {apollo_id} : "
                        f"{removed} doublon(s) supprimé(s)."
                    )
                return removed
        except Exception as e:
            print(f"[ERROR] Dedup personas pour {apollo_id} : {e}")
            return 0

    def get_company_apollo_id_by_domain(self, domain: str):
        """
        Renvoie l'apollo_id du nœud Company correspondant à un domaine nettoyé.
        """
        if not domain:
            return None
        clean_domain = self.clean_domain(domain)
        query = """
        MATCH (c:Company)
        WHERE c.domain = $domain OR c.domain = $clean_domain OR c.apollo_id = $domain
        RETURN c.apollo_id AS apollo_id
        LIMIT 1
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, domain=domain, clean_domain=clean_domain)
                record = result.single()
                return record["apollo_id"] if record and record["apollo_id"] else None
        except Exception as e:
            print(f"[ERROR] Erreur lors de la récupération de l'apollo_id pour {domain} : {e}")
            return None

    def get_company_domain_by_apollo_id(self, apollo_id: str):
        """
        Renvoie le domaine nettoyé du nœud Company correspondant à un Apollo ID.
        """
        if not apollo_id:
            return None
        query = """
        MATCH (c:Company {apollo_id: $apollo_id})
        RETURN c.domain AS domain
        LIMIT 1
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, apollo_id=apollo_id)
                record = result.single()
                return record["domain"] if record and record["domain"] else None
        except Exception as e:
            print(f"[ERROR] Erreur lors de la récupération du domaine pour l'apollo_id {apollo_id} : {e}")
            return None

    def get_existing_company_apollo_ids(self, apollo_ids: list) -> set:
        """Retourne le sous-ensemble d'apollo_ids déjà présents comme nœuds Company."""
        clean_ids = [str(aid).strip() for aid in (apollo_ids or []) if aid]
        if not clean_ids:
            return set()
        query = """
        MATCH (c:Company)
        WHERE c.apollo_id IN $apollo_ids
        RETURN collect(c.apollo_id) AS existing
        """
        try:
            with self.driver.session() as session:
                record = session.run(query, apollo_ids=clean_ids).single()
                existing = (record or {}).get("existing") or []
                return {str(aid) for aid in existing if aid}
        except Exception as e:
            print(f"[ERROR] Lecture apollo_ids Company existants : {e}")
            return set()

    def bulk_import_companies(self, companies_list):
        """
        Importation avec Versioning Exhaustif.
        Synchronisé à 100% avec les sorties du scraper Apollo.
        """
        default_msg = "Non renseigné"

        # --- 1. PRÉPARATION DES DONNÉES (Sérialisation JSON) ---
        for company in companies_list:
            for key in ["departments", "funding_events", "suborganizations", "technologies"]:
                if key in company and not isinstance(company[key], str):
                    company[key] = json.dumps(company[key])

        query = """
        UNWIND $batch AS data
        
        // 1. CRÉATION DU DOMAINE DE SÉCURITÉ (ANTI-COLLISION)
        WITH data,
             CASE 
                 WHEN data.domain IS NULL OR data.domain = 'Non renseigné' OR trim(data.domain) = ''
                 THEN 'unknown_' + replace(toLower(COALESCE(data.name, 'unknown')), ' ', '_') + '_' + replace(toLower(COALESCE(data.country, data.location.country, 'unknown')), ' ', '_')
                 ELSE split(replace(replace(replace(toLower(trim(data.domain)), 'http://', ''), 'https://', ''), 'www.', ''), '/')[0]
             END AS safe_domain

        // 2. Identification ou création de l'entreprise racine
        MERGE (c:Company {apollo_id: COALESCE(data.apollo_id, safe_domain)})
        SET c.uid = COALESCE(data.apollo_id, safe_domain),
            c.domain = safe_domain,
            c.name = COALESCE(data.name, c.name, $msg),
            c.apollo_id = COALESCE(data.apollo_id, c.apollo_id)
        
        // 3. Récupération de la version actuelle
        OPTIONAL MATCH (c)-[old_rel:CURRENT]->(old_v:Version)
        
        // 4. LOGIQUE DE COMPARAISON EXHAUSTIVE (Correction du bug de fallback $msg)
        WITH c, data, old_rel, old_v, safe_domain,
             (old_v IS NULL 
              // Identité & SEO
              OR COALESCE(old_v.name, $msg) <> COALESCE(data.name, $msg)
              OR COALESCE(old_v.industry, $msg) <> COALESCE(data.industry, $msg)
              OR COALESCE(old_v.founded_year, $msg) <> COALESCE(data.founded_year, $msg)
              OR COALESCE(old_v.logo_url, $msg) <> COALESCE(data.logo_url, $msg)
              OR COALESCE(old_v.website_url, $msg) <> COALESCE(data.website_url, $msg)
              OR COALESCE(old_v.short_description, $msg) <> COALESCE(data.short_description, $msg)
              OR COALESCE(old_v.full_description, $msg) <> COALESCE(data.full_description, $msg) // <-- AJOUT DU CHECK FULL_DESCRIPTION
              OR COALESCE(old_v.seo_description, $msg) <> COALESCE(data.seo_description, $msg)
              OR COALESCE(old_v.global_industry, $msg) <> COALESCE(data.global_industry, $msg) // <-- AJOUT DU CHECK GLOBAL_INDUSTRY
              
              // Performance & Chiffres
              OR COALESCE(old_v.alexa_ranking, $msg) <> COALESCE(data.alexa_ranking, $msg)
              OR COALESCE(old_v.annual_revenue, $msg) <> COALESCE(data.annual_revenue, $msg)
              OR COALESCE(old_v.total_funding, $msg) <> COALESCE(data.total_funding, $msg)
              OR COALESCE(old_v.estimated_num_employees, $msg) <> COALESCE(data.estimated_num_employees, $msg)
              OR COALESCE(old_v.latest_funding_stage, $msg) <> COALESCE(data.latest_funding_stage, $msg)
              
              // Réseaux Sociaux & Contact
              OR COALESCE(old_v.linkedin_url, $msg) <> COALESCE(data.linkedin_url, $msg)
              OR COALESCE(old_v.twitter_url, $msg) <> COALESCE(data.twitter_url, $msg)
              OR COALESCE(old_v.facebook_url, $msg) <> COALESCE(data.facebook_url, $msg)
              OR COALESCE(old_v.crunchbase_url, $msg) <> COALESCE(data.crunchbase_url, $msg)
              OR COALESCE(old_v.phone, $msg) <> COALESCE(data.phone, $msg)
              
              // Localisation
              OR COALESCE(old_v.raw_address, $msg) <> COALESCE(data.location.raw_address, $msg)
              OR COALESCE(old_v.street_address, $msg) <> COALESCE(data.location.street_address, $msg)
              OR COALESCE(old_v.city, $msg) <> COALESCE(data.location.city, $msg)
              OR COALESCE(old_v.state, $msg) <> COALESCE(data.location.state, $msg)
              OR COALESCE(old_v.postal_code, $msg) <> COALESCE(data.location.postal_code, $msg)
              OR COALESCE(old_v.country, $msg) <> COALESCE(data.location.country, $msg)
              
              // Structure Hiérarchique
              OR COALESCE(old_v.num_suborganizations, 0) <> COALESCE(data.hierarchy.num_suborganizations, 0)
              OR COALESCE(old_v.owned_by_organization_id, $msg) <> COALESCE(data.hierarchy.owned_by_organization_id, $msg)
              
              // Données Complexes
              OR COALESCE(old_v.technologies, "[]") <> COALESCE(data.technologies, "[]")
              OR COALESCE(old_v.departments, "{}") <> COALESCE(data.departments, "{}")
              OR COALESCE(old_v.funding_events, "[]") <> COALESCE(data.funding_events, "[]")
              OR COALESCE(old_v.suborganizations, "[]") <> COALESCE(data.suborganizations, "[]")
              OR COALESCE(old_v.keywords, []) <> COALESCE(data.keywords, [])
             ) AS has_changed

        // 5. ARCHIVAGE UNIQUEMENT SI CHANGEMENT
        FOREACH (_ IN CASE WHEN old_rel IS NOT NULL AND has_changed THEN [1] ELSE [] END |
            DELETE old_rel
            MERGE (c)-[:ARCHIVED]->(old_v)
        )

        // 6. CRÉATION NOUVELLE VERSION UNIQUEMENT SI CHANGEMENT
        FOREACH (_ IN CASE WHEN has_changed THEN [1] ELSE [] END |
            CREATE (new_v:Version)
            SET new_v.captured_at = datetime(),
                new_v.company_intent = COALESCE(data.company_intent, $msg),
                c.company_intent = COALESCE(data.company_intent, c.company_intent, $msg),
                new_v.name = COALESCE(data.name, $msg),
                new_v.industry = COALESCE(data.industry, $msg),
                new_v.global_industry = COALESCE(data.global_industry, $msg), // <-- ENREGISTREMENT DE GLOBAL_INDUSTRY
                new_v.founded_year = COALESCE(data.founded_year, $msg),
                new_v.logo_url = COALESCE(data.logo_url, $msg),
                new_v.website_url = COALESCE(data.website_url, $msg),
                new_v.short_description = COALESCE(data.short_description, $msg),
                new_v.full_description = COALESCE(data.full_description, $msg), // <-- ENREGISTREMENT DE FULL_DESCRIPTION
                new_v.seo_description = COALESCE(data.seo_description, $msg),
                new_v.alexa_ranking = COALESCE(data.alexa_ranking, $msg),
                new_v.annual_revenue = COALESCE(data.annual_revenue, $msg),
                new_v.total_funding = COALESCE(data.total_funding, $msg),
                new_v.estimated_num_employees = COALESCE(data.estimated_num_employees, $msg),
                new_v.latest_funding_stage = COALESCE(data.latest_funding_stage, $msg),
                new_v.linkedin_url = COALESCE(data.linkedin_url, $msg),
                new_v.twitter_url = COALESCE(data.twitter_url, $msg),
                new_v.facebook_url = COALESCE(data.facebook_url, $msg),
                new_v.crunchbase_url = COALESCE(data.crunchbase_url, $msg),
                new_v.phone = COALESCE(data.phone, $msg),
                new_v.raw_address = COALESCE(data.location.raw_address, $msg),
                new_v.street_address = COALESCE(data.location.street_address, $msg),
                new_v.city = COALESCE(data.location.city, $msg),
                new_v.state = COALESCE(data.location.state, $msg),
                new_v.postal_code = COALESCE(data.location.postal_code, $msg),
                new_v.country = COALESCE(data.location.country, $msg),
                new_v.num_suborganizations = COALESCE(data.hierarchy.num_suborganizations, 0),
                new_v.owned_by_organization_id = COALESCE(data.hierarchy.owned_by_organization_id, $msg),
                new_v.technologies = COALESCE(data.technologies, "[]"),
                new_v.departments = COALESCE(data.departments, "{}"),
                new_v.funding_events = COALESCE(data.funding_events, "[]"),
                new_v.suborganizations = COALESCE(data.suborganizations, "[]"),
                new_v.keywords = COALESCE(data.keywords, [])
            
            CREATE (c)-[:CURRENT]->(new_v)
        )

        // 7. MISE À JOUR DU TIMESTAMP SI LES DONNÉES SONT IDENTIQUES
        FOREACH (_ IN CASE WHEN NOT has_changed THEN [1] ELSE [] END |
            SET old_v.last_verified_at = datetime()
        )

        // 8. HIÉRARCHIE (Relations entre Company)
        WITH data, safe_domain
        WHERE data.hierarchy.owned_by_organization_id IS NOT NULL 
          AND data.hierarchy.owned_by_organization_id <> "Non renseigné"
        
        MATCH (parent:Company {apollo_id: data.hierarchy.owned_by_organization_id})
        MATCH (child:Company {domain: safe_domain})
        WHERE parent <> child
        MERGE (parent)-[:OWNS]->(child)
        MERGE (child)-[:OWNED_BY]->(parent)
        """
        
        try:
            with self.driver.session() as session:
                session.run(query, batch=companies_list, msg=default_msg)
                print(f"🚀 Graph Engine : {len(companies_list)} profils synchronisés avec succès.")
        except Exception as e:
            print(f"❌ Erreur lors de l'import : {e}")

    def import_merged_profiles(self, merged_list):
        """
        Importation des profils fusionnés (Apollo + AI).
        Maintient les anciens attributs, met à jour les existants, et ajoute les nouveaux (ex: IA).
        """
        default_msg = "Non renseigné"

        # --- PRÉPARATION DES DONNÉES ---
        safe_list = []
        for data in merged_list:
            safe_data = data.copy()
            complex_keys = ["departments", "funding_events", "suborganizations", "technologies", "competitors", "keywords"]
            for key in complex_keys:
                if key in safe_data and safe_data[key] is not None and not isinstance(safe_data[key], str):
                    safe_data[key] = json.dumps(safe_data[key])
            safe_list.append(safe_data)

        query = """
        UNWIND $batch AS data
        
        // 1. CRÉATION DU DOMAINE DE SÉCURITÉ
        WITH data,
             CASE 
                 WHEN data.domain IS NULL OR data.domain = 'Non renseigné' OR trim(data.domain) = ''
                 THEN 'unknown_' + replace(toLower(COALESCE(data.name, 'unknown')), ' ', '_') + '_' + replace(toLower(COALESCE(data.country, data.location.country, 'unknown')), ' ', '_')
                 ELSE split(replace(replace(replace(toLower(trim(data.domain)), 'http://', ''), 'https://', ''), 'www.', ''), '/')[0]
             END AS safe_domain
             
        // 2. Identification de l'entreprise
        MERGE (c:Company {apollo_id: COALESCE(data.apollo_id, safe_domain)})
        SET c.domain = safe_domain,
            c.name = COALESCE(data.name, c.name, $msg),
            c.apollo_id = COALESCE(data.apollo_id, c.apollo_id),
            c.uid = COALESCE(data.uid, c.uid, safe_domain)
        
        OPTIONAL MATCH (c)-[old_rel:CURRENT]->(old_v:Version)
        
        // 3. VÉRIFICATION DYNAMIQUE DES CHANGEMENTS (Nouvelle logique ajoutée !)
        WITH c, data, safe_domain, old_rel, old_v,
             (old_v IS NULL 
              // Vérifie si N'IMPORTE QUELLE clé de 'data' est différente de l'ancienne version
              OR any(k IN keys(data) WHERE COALESCE(toString(old_v[k]), 'NULL') <> COALESCE(toString(data[k]), 'NULL'))
             ) AS has_changed

        // 4. Archivage automatique (UNIQUEMENT SI CHANGEMENT)
        FOREACH (_ IN CASE WHEN old_rel IS NOT NULL AND has_changed THEN [1] ELSE [] END |
            DELETE old_rel
            MERGE (c)-[:ARCHIVED]->(old_v)
        )

        // 5. CRÉATION DE LA NOUVELLE VERSION DYNAMIQUE (UNIQUEMENT SI CHANGEMENT)
        FOREACH (_ IN CASE WHEN has_changed THEN [1] ELSE [] END |
            CREATE (new_v:Version)
            SET new_v += CASE WHEN old_v IS NOT NULL THEN properties(old_v) ELSE {} END
            SET new_v += data
            SET new_v.company_intent = COALESCE(data.company_intent, $msg),
                c.company_intent = COALESCE(data.company_intent, c.company_intent, $msg),
                new_v.global_industry = COALESCE(data.global_industry, $msg) // <-- ENREGISTREMENT DE GLOBAL_INDUSTRY POUR LES PROFILS FUSIONNÉS
            SET new_v.captured_at = datetime(),
                new_v.source = "Merged_Apollo_AI"
            CREATE (c)-[:CURRENT]->(new_v)
        )

        // 6. MISE À JOUR DU TIMESTAMP (SI AUCUN CHANGEMENT)
        FOREACH (_ IN CASE WHEN NOT has_changed THEN [1] ELSE [] END |
            SET old_v.last_verified_at = datetime()
        )
        """
        
        try:
            with self.driver.session() as session:
                session.run(query, batch=safe_list, msg=default_msg)
                print(f"🚀 Graph Engine : {len(safe_list)} profils FUSIONNÉS (Apollo+IA) synchronisés avec succès.")
        except Exception as e:
            print(f"❌ Erreur lors de l'import fusionné : {e}")

    def bulk_import_company_intents(self, intents_list, company_domain, max_items=MAX_INTENT_SIGNALS_PER_COMPANY, company_intent=None):
        """
        Importation en batch des signaux d'intention (Jobs, News, etc.) pour une entreprise spécifique.
        Ignore les IntentSignal déjà présents (uid) pour éviter les reinsertions inutiles.
        """
        if not intents_list:
            print(f"⚠️ Aucun signal d'intention à importer pour l'entreprise : {company_domain}")
            return {"imported": 0, "skipped_existing": 0}

        company_clean = self.clean_domain(company_domain) or company_domain
        existing_uids = self.get_existing_intent_uids(company_domain)

        limited_intents = intents_list[:max_items] if max_items and max_items > 0 else intents_list
        new_intents = []
        skipped_existing = 0
        for intent in limited_intents:
            uid = self.intent_signal_uid(intent, company_clean)
            if uid in existing_uids:
                skipped_existing += 1
                continue
            i_clean = intent.copy()
            if 'xai_metrics' in i_clean and isinstance(i_clean['xai_metrics'], (list, dict)):
                i_clean['xai_metrics'] = json.dumps(i_clean['xai_metrics'], ensure_ascii=False)
            new_intents.append(i_clean)

        if skipped_existing:
            print(
                f"⏭️ {skipped_existing} signal(aux) d'intention déjà en base "
                f"ignoré(s) pour {company_domain}."
            )

        if not new_intents and not company_intent:
            print(f"ℹ️ Aucun nouvel IntentSignal à importer pour {company_domain}.")
            return {"imported": 0, "skipped_existing": skipped_existing}

        query = """
        UNWIND $batch AS intent_data
        MATCH (c:Company)
        WHERE c.apollo_id = $company_identifier OR c.domain = $domain

        WITH c, intent_data,
             COALESCE(intent_data.id, intent_data.title, intent_data.title_and_summary, 'unknown')
             + '_' + $domain AS unique_id
        MERGE (signal:IntentSignal {uid: unique_id})
        SET signal += intent_data,
            signal.last_updated = datetime()
        MERGE (c)-[:HAS_INTENT_SIGNAL]->(signal)
        """

        summary_query = """
        MATCH (c:Company)
        WHERE c.apollo_id = $company_identifier OR c.domain = $domain
        OPTIONAL MATCH (c)-[:CURRENT]->(current_v:Version)
        SET c.company_intent = COALESCE($company_intent, c.company_intent),
            current_v.company_intent = COALESCE($company_intent, current_v.company_intent)
        """

        try:
            with self.driver.session() as session:
                if new_intents:
                    session.run(
                        query,
                        batch=new_intents,
                        domain=company_clean,
                        company_identifier=company_domain,
                    )
                    print(
                        f"🎯 {len(new_intents)} nouveaux signaux d'intention importés "
                        f"pour {company_domain} "
                        f"(ignorés existants: {skipped_existing}, limite batch: {max_items})."
                    )
                if company_intent:
                    session.run(
                        summary_query,
                        domain=company_clean,
                        company_identifier=company_domain,
                        company_intent=company_intent,
                    )
            return {"imported": len(new_intents), "skipped_existing": skipped_existing}
        except Exception as e:
            print(f"❌ Erreur lors de l'importation des signaux d'intention dans Neo4j : {e}")
            return {"imported": 0, "skipped_existing": skipped_existing, "error": str(e)}

    def _normalize_neo4j_property(self, value):
        """Convertit les structures complexes en types acceptés par Neo4j."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, (list, tuple, set)):
            normalized_items = []
            for item in value:
                normalized_item = self._normalize_neo4j_property(item)
                if isinstance(normalized_item, (dict, list, tuple, set)):
                    normalized_item = json.dumps(normalized_item, ensure_ascii=False, default=str)
                normalized_items.append(normalized_item)
            return normalized_items

        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, default=str)

        return str(value)

    def import_personas(self, personas_list, company_domain, company_apollo_id=None):
        """
        Importe les personas en MERGE prioritaire sur l'Apollo id (évite les doublons LinkedIn).
        """
        if not personas_list:
            print(f"⚠️ Aucun persona à importer pour : {company_domain}")
            return {"imported": 0, "skipped_existing": 0}

        if company_apollo_id:
            self.dedupe_personas_for_company(company_apollo_id)

        company_clean = self.clean_domain(company_domain)
        existing_index = (
            self.get_company_persona_index(company_apollo_id)
            if company_apollo_id
            else {"ids": set(), "linkedin_urls": set(), "with_intent_ids": set()}
        )

        with_id = []
        without_id = []
        skipped_existing = 0

        for p in personas_list:
            p_clean = p.copy()
            p_clean["linkedin_url"] = self.normalize_linkedin_url(p_clean.get("linkedin_url"))
            p_clean["full_name"] = (
                p.get("full_name")
                or p.get("name")
                or p.get("clean_name_used")
                or "Inconnu"
            )
            p_clean["title"] = p.get("title") or p.get("job_title_role") or "Non trouvé"

            if p_clean["full_name"] in ["Non trouvé", "null", ""]:
                p_clean["full_name"] = "Inconnu"

            persona_id = p_clean.get("id")
            if persona_id is not None:
                persona_id = str(persona_id).strip()
                p_clean["id"] = persona_id or None
            else:
                p_clean["id"] = None

            for key, value in list(p_clean.items()):
                p_clean[key] = self._normalize_neo4j_property(value)

            already_known = False
            if p_clean.get("id") and p_clean["id"] in existing_index["ids"]:
                already_known = True
            elif p_clean.get("linkedin_url") and p_clean["linkedin_url"] in existing_index["linkedin_urls"]:
                already_known = True

            if already_known:
                skipped_existing += 1
                # Mise à jour légère des propriétés sans créer de nouveau noeud
                if p_clean.get("id"):
                    with_id.append(p_clean)
                elif p_clean.get("linkedin_url"):
                    without_id.append(p_clean)
                continue

            if p_clean.get("id"):
                with_id.append(p_clean)
            else:
                without_id.append(p_clean)

        query_by_id = """
        UNWIND $batch AS p_data
        MATCH (c:Company)
        WHERE c.apollo_id = $company_identifier OR c.domain = $domain
        MERGE (p:Persona {id: p_data.id})
        SET p += p_data,
            p.last_updated = datetime()
        MERGE (p)-[:WORKS_AT]->(c)
        """

        query_by_linkedin = """
        UNWIND $batch AS p_data
        MATCH (c:Company)
        WHERE c.apollo_id = $company_identifier OR c.domain = $domain
        MERGE (p:Persona {
            linkedin_url: COALESCE(p_data.linkedin_url, p_data.full_name + '_' + $domain)
        })
        SET p += p_data,
            p.last_updated = datetime()
        MERGE (p)-[:WORKS_AT]->(c)
        """

        company_identifier = company_apollo_id or company_domain
        try:
            with self.driver.session() as session:
                if with_id:
                    session.run(
                        query_by_id,
                        batch=with_id,
                        domain=company_clean,
                        company_identifier=company_identifier,
                    )
                if without_id:
                    session.run(
                        query_by_linkedin,
                        batch=without_id,
                        domain=company_clean,
                        company_identifier=company_identifier,
                    )
                print(
                    f"👥 Personas sync pour {company_domain} : "
                    f"{len(with_id) + len(without_id)} traité(s) "
                    f"(déjà connus: {skipped_existing})."
                )
            return {
                "imported": len(with_id) + len(without_id) - skipped_existing,
                "updated_existing": skipped_existing,
                "skipped_existing": skipped_existing,
            }
        except Exception as e:
            print(f"❌ Erreur lors de l'import dynamique des personas : {e}")
            return {"imported": 0, "skipped_existing": skipped_existing, "error": str(e)}

    def bulk_import_persona_posts(self, posts_list, persona_linkedin_url):
        """
        Importation en batch des posts LinkedIn d'un Persona spécifique.
        Crée les nœuds Post et la relation (Persona)-[:POSTED]->(Post).
        """
        if not posts_list:
            print(f"⚠️ Aucun post à importer pour le persona : {persona_linkedin_url}")
            return

        processed_posts = []
        for post in posts_list:
            p_clean = post.copy()

            if 'postImages' in p_clean and isinstance(p_clean['postImages'], (list, dict)):
                p_clean['postImages'] = json.dumps(p_clean['postImages'], ensure_ascii=False)

            processed_posts.append(p_clean)

        query = """
        UNWIND $batch AS post_data
        MATCH (p:Persona {linkedin_url: $persona_url})
        
        // Utilisation de l'id unique du post LinkedIn pour le MERGE (évite les doublons)
        MERGE (post:Post {id: post_data.id})
        
        // Injection dynamique de toutes les propriétés du post (content, businessSignal, keyTakeaway, etc.)
        SET post += post_data,
            post.last_updated = datetime()
            
        // Création ou mise à jour de la relation directionnelle
        MERGE (p)-[:POSTED]->(post)
        """

        try:
            with self.driver.session() as session:
                session.run(query, batch=processed_posts, persona_url=persona_linkedin_url)
                print(f"📝 {len(processed_posts)} posts LinkedIn importés et liés au persona : {persona_linkedin_url}")
        except Exception as e:
            print(f"❌ Erreur lors de l'importation des posts dans Neo4j : {e}")

    def update_persona_intent(self, linkedin_url, intent_summary):
        """
        Met à jour le nœud Persona existant avec le résumé d'intention global (Intent) généré par l'IA.
        """
        if not linkedin_url or not intent_summary:
            return

        query = """
        MATCH (p:Persona {linkedin_url: $linkedin_url})
        SET p.intent = $intent_summary,
            p.intent_updated_at = datetime()
        """
        try:
            with self.driver.session() as session:
                session.run(query, linkedin_url=linkedin_url, intent_summary=intent_summary)
                print(f"🎯 Intention (Intent) mise à jour avec succès dans Neo4j pour le profil LinkedIn cible.")
        except Exception as e:
            print(f"❌ Erreur lors de la mise à jour de l'intention dans Neo4j : {e}")

    def update_persona_by_apollo_id(self, persona_apollo_id: str, persona_data: dict) -> bool:
        """
        Met à jour un nœud Persona existant identifié par son Apollo ID (propriété id).
        """
        if not persona_apollo_id or not persona_data:
            return False

        p_clean = persona_data.copy()
        p_clean.pop("organization", None)

        for key, value in list(p_clean.items()):
            p_clean[key] = self._normalize_neo4j_property(value)

        query = """
        MATCH (p:Persona {id: $persona_apollo_id})
        SET p += $persona_data,
            p.last_updated = datetime()
        RETURN p.linkedin_url AS linkedin_url
        """
        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    persona_apollo_id=persona_apollo_id,
                    persona_data=p_clean,
                )
                if result.single():
                    print(f"✅ Persona {persona_apollo_id} enrichi et mis à jour dans Neo4j.")
                    return True
                print(f"⚠️ Aucun persona trouvé avec l'Apollo ID : {persona_apollo_id}")
                return False
        except Exception as e:
            print(f"❌ Erreur lors de la mise à jour du persona {persona_apollo_id} : {e}")
            return False

    def get_companies_due_for_update(self, max_age_days: int = 7, limit: int = None):
        """
        Retourne les entreprises dont la version courante (CURRENT) n'a pas été
        rafraîchie depuis au moins max_age_days jours.

        L'âge est calculé à partir de last_verified_at (si présent) ou captured_at.
        """
        if max_age_days <= 0:
            raise ValueError("max_age_days doit être > 0.")

        query = """
        MATCH (c:Company)-[:CURRENT]->(v:Version)
        WITH c, v,
             COALESCE(v.last_verified_at, v.captured_at) AS last_refresh
        WHERE last_refresh IS NOT NULL
          AND duration.between(last_refresh, datetime()).days >= $max_age_days
        RETURN c.apollo_id AS apollo_id,
               c.domain AS domain,
               c.name AS name,
               c.uid AS uid,
               v.captured_at AS captured_at,
               v.last_verified_at AS last_verified_at,
               last_refresh AS last_refresh,
               duration.between(last_refresh, datetime()).days AS age_days,
               v.country AS country,
               v.global_industry AS global_industry
        ORDER BY last_refresh ASC
        """
        if limit is not None and limit > 0:
            query += "\nLIMIT $limit"

        params = {"max_age_days": max_age_days}
        if limit is not None and limit > 0:
            params["limit"] = limit

        try:
            with self.driver.session() as session:
                result = session.run(query, **params)
                return [record.data() for record in result]
        except Exception as e:
            print(f"❌ Erreur lors de la recherche des entreprises à mettre à jour : {e}")
            return []

    def get_companies_by_industry_and_country(self, industry: str, country: str):
        """
        Récupère toutes les entreprises et leurs versions actuelles selon le secteur et le pays.
        """
        query = """
        MATCH (c:Company)-[r:CURRENT]->(v:Version)
        WHERE v.global_industry = $industry AND v.country = $country
        RETURN c.apollo_id AS company_apollo_id, 
               c.company_intent AS company_company_intent, 
               c.domain AS company_domain, 
               c.name AS company_name, 
               c.uid AS company_uid, 
               v.full_description AS version_full_description, 
               v.funding_events AS version_funding_events, 
               v.global_industry AS version_global_industry, 
               v.logo_url AS version_logo_url, 
               v.captured_at AS version_captured_at, 
               v.departments AS version_departments, 
               v.is_subsidiary AS version_is_subsidiary, 
               v.owned_by_organization_id AS version_owned_by_organization_id, 
               v.phone AS version_phone, 
               v.source AS version_source, 
               v.data_quality_score AS version_data_quality_score, 
               v.total_funding AS version_total_funding, 
               v.company_intent AS version_company_intent, 
               v.country AS version_country, 
               v.intent AS version_intent, 
               v.linkedin_url AS version_linkedin_url, 
               v.name AS version_name, 
               v.suborganizations AS version_suborganizations, 
               v.latest_funding_stage AS version_latest_funding_stage, 
               v.short_description AS version_short_description, 
               v.city AS version_city, 
               v.competitors AS version_competitors, 
               v.keywords AS version_keywords, 
               v.last_verified_at AS version_last_verified_at, 
               v.personas AS version_personas, 
               v.postal_code AS version_postal_code, 
               v.seo_description AS version_seo_description, 
               v.crunchbase_url AS version_crunchbase_url, 
               v.domain AS version_domain, 
               v.founded_year AS version_founded_year, 
               v.raw_address AS version_raw_address, 
               v.facebook_url AS version_facebook_url, 
               v.industry AS version_industry, 
               v.num_suborganizations AS version_num_suborganizations, 
               v.parent_company AS version_parent_company, 
               v.street_address AS version_street_address, 
               v.technologies AS version_technologies, 
               v.twitter_url AS version_twitter_url, 
               v.website_url AS version_website_url, 
               v.alexa_ranking AS version_alexa_ranking, 
               v.annual_revenue AS version_annual_revenue, 
               v.apollo_id AS version_apollo_id, 
               v.estimated_num_employees AS version_estimated_num_employees, 
               v.fiscal_year_end AS version_fiscal_year_end
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, industry=industry, country=country)
                # On transforme le résultat en liste de dictionnaires
                return [record.data() for record in result]
        except Exception as e:
            print(f"❌ Erreur lors de la recherche locale Neo4j : {e}")
            return []
    def get_companies_by_filters(self, industry: str, country: str, min_employees: int = None, max_employees: int = None):
        """
        Récupère toutes les entreprises et leurs versions actuelles selon le secteur, le pays
        et une tranche optionnelle du nombre d'employés.
        Prend en compte les formats hétérogènes : entiers, floats et chaînes avec séparateurs (ex: "100,000").
        """
        # Requête de base
        query = """
        MATCH (c:Company)-[r:CURRENT]->(v:Version)
        WHERE v.global_industry = $industry AND v.country = $country
        """
        
        # Nettoyage et conversion Cypher à la volée :
        # 1. toString(v.estimated_num_employees) : s'assure qu'on manipule du texte (même si c'est un int à la base)
        # 2. replace(..., ',', '') : supprime les virgules de séparation des milliers (ex: "100,000" -> "100000")
        # 3. toInteger(...) : convertit le résultat propre en entier exploitable pour les comparaisons numériques
        cleaned_emp_expr = "toInteger(replace(toString(v.estimated_num_employees), ',', ''))"

        # Ajout dynamique des filtres numériques
        if min_employees is not None:
            query += f" AND {cleaned_emp_expr} >= $min_employees"
        if max_employees is not None:
            query += f" AND {cleaned_emp_expr} <= $max_employees"
            
        # Bloc RETURN complet
        query += """
        RETURN c.apollo_id AS company_apollo_id, 
               c.company_intent AS company_company_intent, 
               c.domain AS company_domain, 
               c.name AS company_name, 
               c.uid AS company_uid, 
               v.full_description AS version_full_description, 
               v.funding_events AS version_funding_events, 
               v.global_industry AS version_global_industry, 
               v.logo_url AS version_logo_url, 
               v.captured_at AS version_captured_at, 
               v.departments AS version_departments, 
               v.is_subsidiary AS version_is_subsidiary, 
               v.owned_by_organization_id AS version_owned_by_organization_id, 
               v.phone AS version_phone, 
               v.source AS version_source, 
               v.data_quality_score AS version_data_quality_score, 
               v.total_funding AS version_total_funding, 
               v.company_intent AS version_company_intent, 
               v.country AS version_country, 
               v.intent AS version_intent, 
               v.linkedin_url AS version_linkedin_url, 
               v.name AS version_name, 
               v.suborganizations AS version_suborganizations, 
               v.latest_funding_stage AS version_latest_funding_stage, 
               v.short_description AS version_short_description, 
               v.city AS version_city, 
               v.competitors AS version_competitors, 
               v.keywords AS version_keywords, 
               v.last_verified_at AS version_last_verified_at, 
               v.personas AS version_personas, 
               v.postal_code AS version_postal_code, 
               v.seo_description AS version_seo_description, 
               v.crunchbase_url AS version_crunchbase_url, 
               v.domain AS version_domain, 
               v.founded_year AS version_founded_year, 
               v.raw_address AS version_raw_address, 
               v.facebook_url AS version_facebook_url, 
               v.industry AS version_industry, 
               v.num_suborganizations AS version_num_suborganizations, 
               v.parent_company AS version_parent_company, 
               v.street_address AS version_street_address, 
               v.technologies AS version_technologies, 
               v.twitter_url AS version_twitter_url, 
               v.website_url AS version_website_url, 
               v.alexa_ranking AS version_alexa_ranking, 
               v.annual_revenue AS version_annual_revenue, 
               v.apollo_id AS version_apollo_id, 
               v.estimated_num_employees AS version_estimated_num_employees, 
               v.fiscal_year_end AS version_fiscal_year_end
        """
        try:
            with self.driver.session() as session:
                result = session.run(
                    query, 
                    industry=industry, 
                    country=country, 
                    min_employees=min_employees, 
                    max_employees=max_employees
                )
                return [record.data() for record in result]
        except Exception as e:
            print(f"[ERROR] Erreur lors de la recherche locale Neo4j : {e}")
            return []
    def get_distinct_countries(self) -> list:
        """Retourne la liste distincte des pays présents sur les Version courantes."""
        query = """
        MATCH (c:Company)-[:CURRENT]->(v:Version)
        WHERE v.country IS NOT NULL AND trim(toString(v.country)) <> ''
        RETURN DISTINCT v.country AS country
        ORDER BY country
        """
        try:
            with self.driver.session() as session:
                result = session.run(query)
                return [
                    record["country"]
                    for record in result
                    if record.get("country")
                ]
        except Exception as e:
            print(f"[ERROR] Lecture des pays distincts Neo4j : {e}")
            return []

    def get_distinct_industries(self) -> list:
        """
        Retourne la liste distincte des industries spécifiques (v.industry),
        pas global_industry.
        """
        query = """
        MATCH (c:Company)-[:CURRENT]->(v:Version)
        WHERE v.industry IS NOT NULL AND trim(toString(v.industry)) <> ''
        RETURN DISTINCT v.industry AS industry
        ORDER BY industry
        """
        try:
            with self.driver.session() as session:
                result = session.run(query)
                return [
                    record["industry"]
                    for record in result
                    if record.get("industry")
                ]
        except Exception as e:
            print(f"[ERROR] Lecture des industries distinctes Neo4j : {e}")
            return []

    def get_companies_by_geo_intel(
        self,
        industries,
        countries_list: list = None,
        min_employees: int = None,
        max_employees: int = None,
    ):
        """
        Récupère les entreprises / versions courantes filtrées par :
        - industries spécifiques (v.industry IN list) — pas global_industry
        - pays optionnels (v.country IN list) si fournis
        - tranche d'effectifs optionnelle
        """
        if isinstance(industries, str):
            industry_list = [industries] if industries.strip() else []
        else:
            industry_list = [i for i in (industries or []) if i]

        if not industry_list:
            return []

        query = """
        MATCH (c:Company)-[r:CURRENT]->(v:Version)
        WHERE v.industry IN $industries
        """

        cleaned_emp_expr = "toInteger(replace(toString(v.estimated_num_employees), ',', ''))"

        if countries_list:
            query += " AND v.country IN $countries_list"
        if min_employees is not None:
            query += f" AND {cleaned_emp_expr} >= $min_employees"
        if max_employees is not None:
            query += f" AND {cleaned_emp_expr} <= $max_employees"

        query += """
        RETURN c.apollo_id AS company_apollo_id, 
               c.company_intent AS company_company_intent, 
               c.domain AS company_domain, 
               c.name AS company_name, 
               c.uid AS company_uid, 
               v.full_description AS version_full_description, 
               v.funding_events AS version_funding_events, 
               v.global_industry AS version_global_industry, 
               v.logo_url AS version_logo_url, 
               v.captured_at AS version_captured_at, 
               v.departments AS version_departments, 
               v.is_subsidiary AS version_is_subsidiary, 
               v.owned_by_organization_id AS version_owned_by_organization_id, 
               v.phone AS version_phone, 
               v.source AS version_source, 
               v.data_quality_score AS version_data_quality_score, 
               v.total_funding AS version_total_funding, 
               v.company_intent AS version_company_intent, 
               v.country AS version_country, 
               v.intent AS version_intent, 
               v.linkedin_url AS version_linkedin_url, 
               v.name AS version_name, 
               v.suborganizations AS version_suborganizations, 
               v.latest_funding_stage AS version_latest_funding_stage, 
               v.short_description AS version_short_description, 
               v.city AS version_city, 
               v.competitors AS version_competitors, 
               v.keywords AS version_keywords, 
               v.last_verified_at AS version_last_verified_at, 
               v.personas AS version_personas, 
               v.postal_code AS version_postal_code, 
               v.seo_description AS version_seo_description, 
               v.crunchbase_url AS version_crunchbase_url, 
               v.domain AS version_domain, 
               v.founded_year AS version_founded_year, 
               v.raw_address AS version_raw_address, 
               v.facebook_url AS version_facebook_url, 
               v.industry AS version_industry, 
               v.num_suborganizations AS version_num_suborganizations, 
               v.parent_company AS version_parent_company, 
               v.street_address AS version_street_address, 
               v.technologies AS version_technologies, 
               v.twitter_url AS version_twitter_url, 
               v.website_url AS version_website_url, 
               v.alexa_ranking AS version_alexa_ranking, 
               v.annual_revenue AS version_annual_revenue, 
               v.apollo_id AS version_apollo_id, 
               v.estimated_num_employees AS version_estimated_num_employees, 
               v.fiscal_year_end AS version_fiscal_year_end
        """
        try:
            with self.driver.session() as session:
                result = session.run(
                    query,
                    industries=industry_list,
                    countries_list=countries_list or [],
                    min_employees=min_employees,
                    max_employees=max_employees,
                )
                return [record.data() for record in result]
        except Exception as e:
            print(f"[ERROR] Erreur lors de la recherche locale géo-intelligente Neo4j : {e}")
            return []
    def get_company_raw_intent_by_domain(self, domain: str) -> str:
        """
        Récupère uniquement la propriété company_intent du nœud Company à partir de son domaine ou de son apollo_id.
        """
        clean_domain = self.clean_domain(domain)
        query = """
        MATCH (c:Company)
        WHERE c.apollo_id = $identifier OR c.domain = $domain
        RETURN c.company_intent AS company_intent
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, domain=clean_domain, identifier=domain)
                record = result.single()
                if record and record["company_intent"]:
                    return record["company_intent"]
                return f"Aucune intention (company_intent) trouvée pour le domaine '{domain}'."
        except Exception as e:
            print(f"[ERROR] Erreur lors de la récupération de company_intent pour {domain} : {e}")
            return f"Erreur base de données : {str(e)}"
    def get_company_personas_by_apollo_id(self, apollo_id: str):
        """
        Récupère tous les personas liés à une entreprise via son apollo_id,
        avec l'ensemble de leurs propriétés (hors show_intent).
        """
        if not apollo_id:
            return []

        query = """
        MATCH (p:Persona)-[:WORKS_AT]->(c:Company)
        WHERE c.apollo_id = $apollo_id
        RETURN apoc.map.removeKey(properties(p), 'show_intent') AS persona_properties
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, apollo_id=apollo_id.strip())
                return [
                    record["persona_properties"]
                    for record in result
                    if record.get("persona_properties")
                ]
        except Exception as e:
            print(f"[ERROR] Erreur lors de la récupération des personas pour apollo_id {apollo_id} : {e}")
            return []

    def get_company_personas_with_signals_by_apollo_id(self, apollo_id: str):
        """
        Récupère tous les personas (avec tous leurs attributs, dont intent)
        liés à une entreprise via son apollo_id.
        """
        if not apollo_id:
            return []

        query = """
        MATCH (c:Company {apollo_id: $apollo_id})<-[:WORKS_AT]-(p:Persona)
        RETURN p
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, apollo_id=apollo_id.strip())
                return [dict(record["p"]) for record in result if record.get("p")]
        except Exception as e:
            print(f"[ERROR] Erreur lors de la récupération des personas et signaux pour apollo_id {apollo_id} : {e}")
            return []

    def get_company_intent_signals_by_apollo_id(self, apollo_id: str) -> dict:
        """
        Retourne les nœuds IntentSignal liés à une Company (par apollo_id),
        plus le résumé company_intent sur le nœud Company.
        """
        if not apollo_id:
            return {"company_intent": None, "signals": []}

        query = """
        MATCH (c:Company {apollo_id: $apollo_id})
        OPTIONAL MATCH (c)-[:HAS_INTENT_SIGNAL]->(s:IntentSignal)
        RETURN c.company_intent AS company_intent,
               collect(properties(s)) AS signals
        """
        try:
            with self.driver.session() as session:
                record = session.run(query, apollo_id=apollo_id.strip()).single()
                if not record:
                    return {"company_intent": None, "signals": []}
                signals = [
                    signal
                    for signal in (record.get("signals") or [])
                    if isinstance(signal, dict) and signal
                ]
                return {
                    "company_intent": record.get("company_intent"),
                    "signals": signals,
                }
        except Exception as e:
            print(f"[ERROR] Lecture IntentSignal pour apollo_id {apollo_id} : {e}")
            return {"company_intent": None, "signals": []}

    def get_personas_by_apollo_ids(self, persona_apollo_ids: list) -> list:
        """
        Charge les nœuds Persona par leur Apollo ID (propriété `id`).
        Utile pour vérifier email/téléphone déjà enrichis avant un appel Apollo.
        """
        if not persona_apollo_ids:
            return []

        clean_ids = [str(pid).strip() for pid in persona_apollo_ids if pid]
        if not clean_ids:
            return []

        query = """
        MATCH (p:Persona)
        WHERE p.id IN $persona_ids
        RETURN properties(p) AS persona
        """
        try:
            with self.driver.session() as session:
                result = session.run(query, persona_ids=clean_ids)
                return [
                    record["persona"]
                    for record in result
                    if record.get("persona")
                ]
        except Exception as e:
            print(f"[ERROR] Lecture personas par IDs : {e}")
            return []

    def close(self):
        self.driver.close()