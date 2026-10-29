import anyio
import json
import sys
import threading
import time
import uuid
import builtins
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

# MCP stdio uses stdout for JSON-RPC messages only.
# Route all business logs to stderr so MCP Inspector can parse.
_original_print = builtins.print
_original_stdout = sys.stdout
_original_stderr = sys.stderr

class StdoutJsonRoutingWrapper:
    def __init__(self, stdout, stderr):
        self._stdout = stdout
        self._stderr = stderr
        self._buffer = ""
        self.buffer = getattr(stdout, "buffer", None)
        self.encoding = getattr(stdout, "encoding", "utf-8")
        self.errors = getattr(stdout, "errors", "strict")

    def _route_line(self, line: str) -> None:
        if not line:
            return

        stripped = line.rstrip("\n")
        if self._is_json_line(stripped):
            self._stdout.write(line)
        else:
            self._stderr.write(line)

    def _is_json_line(self, text: str) -> bool:
        if not text:
            return False
        try:
            json.loads(text)
            return True
        except Exception:
            return False

    def write(self, text):
        if text is None:
            return 0

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._route_line(line + "\n")

        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        if self._buffer:
            self._route_line(self._buffer)
            self._buffer = ""
        self._stdout.flush()
        self._stderr.flush()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._stdout, name)

sys.stdout = StdoutJsonRoutingWrapper(sys.stdout, sys.stderr)

def _print_to_stderr(*args, **kwargs):
    if "file" not in kwargs:
        kwargs["file"] = _original_stderr
    return _original_print(*args, **kwargs)

builtins.print = _print_to_stderr

# Importation des fonctions de requêtes depuis ton module principal
from main_discovery import (
    request_discover_companies,
    request_enrich_company_intents,
    request_enrich_company_personas,
    request_run_csv_company_workflow,
    request_search_local_companies, 
    request_search_local_companies_by_employees, 
    request_search_companies_by_geo_llm,
    request_company_raw_intent,
    request_company_personas_by_domain,
    request_company_personas_with_signals,
    request_local_persona_contacts,
    request_enrich_persona,
    request_enrich_persona_phone,
    request_enrich_persona_personal_email,
    request_enrich_persona_waterfall_phone,
    request_enrich_persona_waterfall_email,
    request_fetch_intent_signals_for_orchestrator,
    request_fetch_personas_for_orchestrator,
    request_enrich_contacts_for_orchestrator,
)
from persona_search_enrich import SALES_PERSONA_TITLES
from run_usage import (
    build_tool_usage,
    empty_apollo_usage,
    empty_gemini_usage,
    pop_last_orchestrator_usage,
    snapshot_apollo,
    usage_from_apollo_window,
)
import config

# Initialisation du serveur MCP
mcp = FastMCP("B2B_Enrichment_Discovery_Server")

TASKS = {}
TASK_LOCK = threading.Lock()

def _start_background_task(target, *args, name="LeadPulseWorker"):
    worker_thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    worker_thread.start()
    return worker_thread


def _run_csv_workflow_task(task_id: str, csv_filepath: str, limit: int, limit_per_element: int, role: List[str]):
    with TASK_LOCK:
        TASKS[task_id].update({"status": "running", "started_at": time.time(), "error": None})

    try:
        result = request_run_csv_company_workflow(csv_filepath, limit, limit_per_element, role)
        with TASK_LOCK:
            TASKS[task_id].update({"status": "completed", "result": result, "finished_at": time.time()})
    except Exception as e:
        with TASK_LOCK:
            TASKS[task_id].update({"status": "failed", "error": str(e), "finished_at": time.time()})


@mcp.tool()
async def discover_companies(
    industries: List[str], 
    locations: Optional[List[str]] = None, 
    continent: Optional[str] = None,
    employee_ranges: Optional[List[str]] = None,
    limit: int = 2,
    limit_per_element: int = 1
) -> str:
    """
    Découvre et enrichit la structure de base d'entreprises B2B avec Apollo puis SmartScraperAI.
    Génère les rapports de comparaison Apollo vs IA et les profils fusionnés avant injection Neo4j.
    Permet de filtrer intelligemment par Pays, Continent combiné ou par tranche de taille salariale.
    Distribue équitablement l'extraction sur chaque localisation jusqu'à atteindre la limite globale.
    
    PARAMÈTRES :
    - industries (List[str]): Liste des secteurs cibles (ex: ["Software", "Aerospace"]). Obligatoire.
    - locations (List[str]): Liste optionnelle de pays ou villes initiaux (ex: ["Germany"]).
    - continent (str): Un continent complet à fusionner dynamiquement via l'IA d'ESPRIT (ex: "Africa"). Optionnel.
    - employee_ranges (List[str]): Tranches d'effectifs acceptées par Apollo. Optionnel.
      Valeurs recommandées : "1,10", "11,50", "51,200", "201,500", "501,1000", "1001,5000", "5001,10000", "10001,"
      (les formes legacy "1-10" / "10001+" sont converties automatiquement)
    - limit (int): Nombre max TOTAL d'entreprises à extraire sur l'ensemble de la recherche. Défaut à 2.
    - limit_per_element (int): Nombre max d'entreprises à extraire PAR élément (localisation) de la liste. Défaut à 1.

    SORTIES :
    - scraped_data/*_APOLLO.json et *_RAW.txt
    - comparisons/*_COMPARISON.json et *_FULL_REPORT.json
    - merged_profiles/*_MERGED.json
    """
    if not industries:
        return "Erreur : Le paramètre 'industries' ne doit pas être vide."
    if not locations and not continent:
        return "Erreur : Vous devez fournir au moins une localisation dans 'locations' ou un 'continent'."
        
    try:
        results = await anyio.to_thread.run_sync(
            request_discover_companies,
            industries,
            locations,
            continent,
            employee_ranges,
            limit,
            limit_per_element,
        )
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Erreur lors de la découverte de nouvelles entreprises : {str(e)}"


@mcp.tool()
async def enrich_company_intents(company_apollo_ids: List[str], target_country: Optional[str] = None) -> str:
    """
    Extrait et analyse les signaux d'intention globaux (offres d'emploi, actualités) pour une liste d'entreprise Apollo IDs.
    
    UTILISATION :
    Appelle cet outil avec des Apollo IDs. L'outil récupère le domaine correspondant et utilise ce domaine
    uniquement pour le scraping web, tandis que l'Apollo API utilise directement l'Apollo ID.

    PARAMÈTRES :
    - company_apollo_ids (List[str]): Liste des Apollo IDs des entreprises cibles.
    - target_country (Optional[str]): Le pays cible pour contextualiser la recherche de signaux (ex: "France"). Optionnel.

    RETOUR :
    Un rapport d'exécution détaillant le statut d'enrichissement et le nombre de signaux trouvés 
    pour chaque Apollo ID fourni.
    """
    try:
        results = await anyio.to_thread.run_sync(
            request_enrich_company_intents,
            company_apollo_ids,
            target_country,
        )
        formatted_results = "\n".join([f"- {domain}: {data}" for domain, data in results.items()])
        return f"Rapport d'enrichissement des signaux d'intention :\n{formatted_results}"
    except Exception as e:
        return f"Erreur lors de l'enrichissement des intentions : {str(e)}"


@mcp.tool()
async def enrich_company_personas(
    company_apollo_ids: List[str],
    target_country: Optional[str] = None,
    role: List[str] = list(SALES_PERSONA_TITLES),
    limit: int = 10,
    limit_per_element: int = 3,
) -> str:
    """
    Enrichit dynamiquement les décideurs (Personas) d'une entreprise à partir d'Apollo,
    scrape leurs posts LinkedIn et analyse leurs intentions comportementales via le LLM.

    UTILISATION :
    Appelle cet outil avec des Apollo IDs. L'API People Search d'Apollo utilise directement
    organization_ids[] pour trouver les personas. Le domaine est résolu en base uniquement
    pour l'import Neo4j et le scraping LinkedIn.

    PARAMÈTRES :
    - company_apollo_ids (List[str]): Liste des Apollo IDs des entreprises cibles.
    - target_country (Optional[str]): Le pays de localisation souhaité pour les personas (ex: "Germany"). Optionnel.
    - role (List[str]): Titres Apollo person_titles[] (ICP target_roles from orchestrator).
      When omitted, falls back to the sales preset:
      Sales, Sales Manager, Account Executive, Business Development,
      Head of Sales, VP of Sales, SDR, BDR, Commercial.
    - limit (int): Nombre max TOTAL de personas à extraire sur l'ensemble des entreprises. Défaut à 10.
    - limit_per_element (int): Nombre max de personas à extraire PAR entreprise (Apollo ID). Défaut à 3.

    RETOUR :
    Un rapport d'exécution détaillant le statut d'enrichissement et le nombre de personas traités.
    """
    if not company_apollo_ids:
        return "Erreur : La liste 'company_apollo_ids' est obligatoire."
        
    try:
        results = await anyio.to_thread.run_sync(
            request_enrich_company_personas,
            company_apollo_ids,
            target_country,
            list(role),
            limit,
            limit_per_element,
        )
        formatted_results = "\n".join([f"- {apollo_id}: {data}" for apollo_id, data in results.items()])
        return f"Rapport d'enrichissement des personas :\n{formatted_results}"
    except Exception as e:
        return f"Erreur lors de l'enrichissement des personas : {str(e)}"


@mcp.tool()
async def run_csv_company_workflow(
    csv_filepath: str,
    limit: int = 10,
    limit_per_element: int = 1,
    role: List[str] = list(SALES_PERSONA_TITLES),
) -> str:
    """
    Lis un fichier CSV contenant des colonnes 'industry' et 'country', puis exécute successivement
    discover_companies, enrich_company_intents et enrich_company_personas pour chaque combinaison trouvée.

    PARAMÈTRES :
    - csv_filepath (str): Chemin du fichier CSV.
    - limit (int): Nombre maximal d'entreprises à extraire par combo industry/country.
    - limit_per_element (int): Nombre maximal d'entreprises par élément de localisation.
    - role (List[str]): Titres Apollo person_titles[] pour l'enrichissement des personas.
    """
    if not csv_filepath:
        return "Erreur : Le chemin du fichier CSV est obligatoire."

    if not csv_filepath:
        return "Erreur : Le chemin du fichier CSV est obligatoire."

    task_id = str(uuid.uuid4())
    with TASK_LOCK:
        TASKS[task_id] = {
            "status": "pending",
            "result": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    _start_background_task(
        _run_csv_workflow_task,
        task_id,
        csv_filepath,
        limit,
        limit_per_element,
        list(role),
        name=f"run_csv_workflow-{task_id}",
    )

    return json.dumps({"task_id": task_id, "status": "pending"}, indent=2)


@mcp.tool()
def get_csv_company_workflow_status(task_id: str) -> str:
    if not task_id:
        return "Erreur : Le paramètre 'task_id' est obligatoire."

    with TASK_LOCK:
        task = TASKS.get(task_id)

    if not task:
        return f"Erreur : task_id inconnu '{task_id}'."

    return json.dumps(
        {
            "task_id": task_id,
            "status": task["status"],
            "started_at": task["started_at"],
            "finished_at": task["finished_at"],
            "has_result": task["result"] is not None,
            "has_error": task["error"] is not None,
            "error": task["error"],
        },
        indent=2,
        default=str,
    )


@mcp.tool()
def get_csv_company_workflow_result(task_id: str) -> str:
    if not task_id:
        return "Erreur : Le paramètre 'task_id' est obligatoire."

    with TASK_LOCK:
        task = TASKS.get(task_id)

    if not task:
        return f"Erreur : task_id inconnu '{task_id}'."

    if task["status"] == "pending" or task["status"] == "running":
        return json.dumps(
            {"task_id": task_id, "status": task["status"], "message": "Le workflow est toujours en cours."},
            indent=2,
        )

    if task["status"] == "failed":
        return json.dumps(
            {"task_id": task_id, "status": "failed", "error": task["error"]},
            indent=2,
        )

    return json.dumps({"task_id": task_id, "status": "completed", "result": task["result"]}, indent=2, default=str)


@mcp.tool()
def search_local_companies(industry: str, country: str) -> str:
    """
    Recherche dans la base de données interne (graphe Neo4j) les entreprises déjà découvertes 
    et qualifiées filtrées par secteur d'activité (industry) et pays (country).

    UTILISATION :
    Appelle cet outil lorsque l'utilisateur cherche à consulter ou filtrer des données d'entreprises 
    déjà existantes dans son espace de stockage local, sans déclencher de nouvelles requêtes d'extraction API payantes.

    PARAMÈTRES :
    - industry (str): Le secteur global recherché (ex: 'electronics', 'Software').
    - country (str): Le pays ciblé (ex: 'Germany', 'Tunisia').

    RETOUR :
    Une chaîne formatée en JSON contenant l'ensemble complet des attributs des nœuds Company et Version correspondants.
    """
    if not industry or not country:
        return "Erreur : Les paramètres 'industry' et 'country' sont obligatoires pour effectuer la recherche."

    try:
        results = request_search_local_companies(industry, country)
        if not results:
            return f"Aucune entreprise trouvée localement pour l'industrie '{industry}' au pays '{country}'."

        # Retourne les données structurées en JSON pour que le LLM client puisse les exploiter facilement
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Erreur lors de la recherche locale des entreprises : {str(e)}"

@mcp.tool()
def search_local_companies_by_size(industry: str, country: str, min_employees: int, max_employees: int) -> str:
    """
    Recherche les entreprises enregistrées dans Neo4j selon le secteur, le pays et une tranche d'employés obligatoire.
    
    PARAMÈTRES :
    - industry (str): Le secteur global recherché (ex: 'electronics').
    - country (str): Le pays ciblé (ex: 'Germany').
    - min_employees (int): La borne minimale de l'effectif (ex: 10).
    - max_employees (int): La borne maximale de l'effectif (ex: 500).
    """
    if not industry or not country:
        return "Erreur : Les paramètres 'industry' et 'country' sont obligatoires."
        
    try:
        # Appel de ta nouvelle fonction de transition
        results = request_search_local_companies_by_employees(industry, country, min_employees, max_employees)
        if not results:
            return f"Aucune entreprise trouvée pour '{industry}' en '{country}' avec cet effectif ({min_employees}-{max_employees})."
        
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Erreur lors de la recherche par taille : {str(e)}"


@mcp.tool()
def search_companies_by_geo_intel(
    industry: str, 
    country: Optional[str] = None,      
    continent: Optional[str] = None,    
    min_employees: Optional[int] = None,  
    max_employees: Optional[int] = None   
) -> str:
    """
    Recherche locale Neo4j d'entreprises avec matching intelligent d'industrie + géo optionnelle.

    INDUSTRY :
    Filtre sur `v.industry` (spécifique Apollo), PAS `global_industry`.
    L'industrie ICP est élargie via LLM (Groq/ESPRIT) aux labels proches déjà présents en base
    (ex: ICP "Software" → "information technology & services", "computer software", …).

    GEO (optionnel) :
    - country : un pays ICP. Vérifie qu'il existe en base (alias résolus via LLM si besoin).
    - continent : élargi en liste de pays via LLM, puis intersecté avec les pays présents en Neo4j.
    - Si ni country ni continent : pas de filtre géographique.
    Priorité : country > continent si les deux sont fournis.

    SIZE (optionnel) :
    - min_employees / max_employees : tranche d'effectifs.

    RETOUR :
    JSON {matched_industries, countries_present, countries_missing, count, companies:[...]}.
    """
    if not industry:
        return "Erreur : Le paramètre 'industry' est obligatoire."

    try:
        results = request_search_companies_by_geo_llm(
            industry, country, continent, min_employees, max_employees
        )
        if not results:
            return (
                f"Aucune entreprise trouvée dans la base locale pour l'industrie ICP '{industry}' "
                f"avec les critères géo/size fournis "
                f"(country={country}, continent={continent}, "
                f"employees={min_employees}-{max_employees})."
            )

        # Surface match context for callers (orchestrator / agents)
        matched_industries = sorted({
            (row.get("version_industry") or "")
            for row in results
            if row.get("version_industry")
        })
        countries_present = sorted({
            (row.get("version_country") or "")
            for row in results
            if row.get("version_country")
        })
        payload = {
            "icp_industry": industry,
            "matched_industries": matched_industries,
            "country_filter": country,
            "continent_filter": continent,
            "countries_present": countries_present,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "count": len(results),
            "companies": results,
        }
        return json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de l'exécution de la recherche géo-intelligente : {str(e)}"

@mcp.tool()
def get_company_core_intent(apollo_id: str) -> str:
    """
    Récupère directement l'intention principale (company_intent) stockée sur le nœud racine de l'entreprise.
    
    UTILISATION :
    Idéal pour obtenir un résumé textuel ultra-rapide et brut de ce que recherche l'entreprise 
    sans charger l'historique complet ou ses versions.

    PARAMÈTRES :
    - apollo_id (str): L'identifiant Apollo de l'entreprise. Obligatoire.
    """
    if not apollo_id:
        return "Erreur : Le paramètre 'apollo_id' est obligatoire."
        
    try:
        intent_summary = request_company_raw_intent(apollo_id)
        return f"Core Intent pour Apollo ID {apollo_id} :\n{intent_summary}"
    except Exception as e:
        return f"Erreur lors de la récupération de l'intention racine : {str(e)}"


@mcp.tool()
def get_local_company_personas(apollo_id: str) -> str:
    """
    Récupère la liste complète des personas enregistrés localement pour une entreprise,
    avec toutes leurs propriétés Neo4j (sauf show_intent).
    
    UTILISATION :
    À utiliser pour lister instantanément vos contacts cibles (Leads) déjà identifiés 
    au sein d'un compte avant de lancer une campagne d'outbound ou de social selling.

    PARAMÈTRES :
    - apollo_id (str): L'identifiant Apollo de l'entreprise cible. Obligatoire.
    """
    if not apollo_id:
        return "Erreur : Le paramètre 'apollo_id' est obligatoire."
        
    try:
        results = request_company_personas_by_domain(apollo_id)
        if not results:
            return f"Aucun persona trouvé dans la base locale pour l'Apollo ID '{apollo_id}'."
            
        # Retourne la liste des personnes proprement formatée en JSON
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Erreur lors de la récupération des personas pour Apollo ID {apollo_id} : {str(e)}"

@mcp.tool()
def get_local_personas_with_intent_signals(apollo_id: str) -> str:
    """
    Récupère tous les personas d'une entreprise avec l'ensemble de leurs attributs Neo4j,
    y compris les signaux d'intention comportementaux (intent).

    UTILISATION :
    À appeler pour préparer un pitch de prospection ultra-personnalisé (Hyper-Personalization). 
    Cet outil montre précisément ce qui intéresse ou préoccupe chaque décideur individuellement.

    PARAMÈTRES :
    - apollo_id (str): L'identifiant Apollo de l'entreprise cible. Obligatoire.
    """
    if not apollo_id:
        return "Erreur : Le paramètre 'apollo_id' est obligatoire."
        
    try:
        results = request_company_personas_with_signals(apollo_id)
        if not results:
            return f"Aucun décideur ou signal d'intention trouvé localement pour l'Apollo ID '{apollo_id}'."
            
        # Renvoie le tableau JSON structuré des leads enrichis
        return json.dumps(results, indent=2, default=str)
    except Exception as e:
        return f"Erreur lors de la récupération des personas et signaux pour Apollo ID {apollo_id} : {str(e)}"


@mcp.tool()
def get_local_persona_contacts(persona_apollo_ids: List[str]) -> str:
    """
    Vérifie dans Neo4j si des personas ont déjà email et/ou téléphone enrichis
    (has_email, has_phone, sanitized_emails, sanitized_numbers, etc.).

    UTILISATION :
    À appeler AVANT enrich_persona / orchestrator_enrich_contacts pour éviter
    de re-dépenser des crédits Apollo lorsque le contact est déjà en base.

    PARAMÈTRES :
    - persona_apollo_ids (List[str]): IDs Apollo des personas (propriété `id` du nœud Persona).

    RETOUR :
    JSON keyed by persona_id with found, has_email, has_phone, complete, and contact fields.
    """
    if not persona_apollo_ids:
        return "Erreur : Le paramètre 'persona_apollo_ids' est obligatoire."

    try:
        results = request_local_persona_contacts(list(persona_apollo_ids))
        return json.dumps(results, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de la lecture des contacts locaux : {str(e)}"


@mcp.tool()
async def enrich_persona(persona_apollo_id: str) -> str:
    """
    Enrichit un persona individuel via Apollo /people/match pour récupérer son email,
    puis met à jour le nœud Persona correspondant dans Neo4j.

    UTILISATION :
    Appelle cet outil avec l'Apollo ID du persona (champ `id` du nœud Persona, ex: "66ab24bbf5872b00015e7e41").
    L'appel Apollo est effectué sans waterfall ni reveal (coût minimal) :
    waterfall_email=false, waterfall_phone=false, reveal_personal_emails=false, reveal_phone_number=false.

    PARAMÈTRES :
    - persona_apollo_id (str): L'identifiant Apollo du persona cible. Obligatoire.

    RETOUR :
    Rapport JSON avec l'email trouvé et le statut de mise à jour Neo4j.
    """
    if not persona_apollo_id:
        return "Erreur : Le paramètre 'persona_apollo_id' est obligatoire."

    try:
        result = await anyio.to_thread.run_sync(request_enrich_persona, persona_apollo_id)
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de l'enrichissement du persona {persona_apollo_id} : {str(e)}"


@mcp.tool()
async def enrich_persona_phone(persona_apollo_id: str) -> str:
    """
    Enrichit le numéro de téléphone d'un persona individuel via Apollo /people/match,
    puis met à jour le nœud Persona correspondant dans Neo4j.

    UTILISATION :
    Appelle cet outil avec l'Apollo ID du persona (champ `id` du nœud Persona, ex: "66ab24bbf5872b00015e7e41").
    L'appel Apollo utilise reveal_phone_number=true sans waterfall :
    waterfall_email=false, waterfall_phone=false, reveal_personal_emails=false, reveal_phone_number=true.

    PARAMÈTRES :
    - persona_apollo_id (str): L'identifiant Apollo du persona cible. Obligatoire.

    RETOUR :
    Rapport JSON avec les numéros trouvés et le statut de mise à jour Neo4j.
    """
    if not persona_apollo_id:
        return "Erreur : Le paramètre 'persona_apollo_id' est obligatoire."

    try:
        result = await anyio.to_thread.run_sync(request_enrich_persona_phone, persona_apollo_id)
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de l'enrichissement téléphone du persona {persona_apollo_id} : {str(e)}"


@mcp.tool()
async def enrich_persona_personal_email(persona_apollo_id: str) -> str:
    """
    Enrichit l'email personnel d'un persona via Apollo /people/match,
    puis met à jour le nœud Persona correspondant dans Neo4j.

    UTILISATION :
    Appelle cet outil avec l'Apollo ID du persona (champ `id` du nœud Persona).
    L'appel Apollo utilise reveal_personal_emails=true sans waterfall :
    waterfall_email=false, waterfall_phone=false, reveal_personal_emails=true, reveal_phone_number=false.

    PARAMÈTRES :
    - persona_apollo_id (str): L'identifiant Apollo du persona cible. Obligatoire.

    RETOUR :
    Rapport JSON avec les emails personnels trouvés et le statut de mise à jour Neo4j.
    """
    if not persona_apollo_id:
        return "Erreur : Le paramètre 'persona_apollo_id' est obligatoire."

    try:
        result = await anyio.to_thread.run_sync(request_enrich_persona_personal_email, persona_apollo_id)
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors de l'enrichissement email personnel du persona {persona_apollo_id} : {str(e)}"


@mcp.tool()
async def enrich_persona_waterfall_phone(persona_apollo_id: str) -> str:
    """
    Enrichit le téléphone d'un persona via Apollo waterfall phone,
    puis met à jour le nœud Persona correspondant dans Neo4j.

    UTILISATION :
    Appelle cet outil avec l'Apollo ID du persona (champ `id` du nœud Persona).
    L'appel Apollo utilise run_waterfall_phone=true :
    waterfall_email=false, waterfall_phone=true, reveal_personal_emails=false, reveal_phone_number=false.

    PARAMÈTRES :
    - persona_apollo_id (str): L'identifiant Apollo du persona cible. Obligatoire.

    RETOUR :
    Rapport JSON avec les numéros trouvés via waterfall et le statut de mise à jour Neo4j.
    """
    if not persona_apollo_id:
        return "Erreur : Le paramètre 'persona_apollo_id' est obligatoire."

    try:
        result = await anyio.to_thread.run_sync(request_enrich_persona_waterfall_phone, persona_apollo_id)
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors du waterfall téléphone du persona {persona_apollo_id} : {str(e)}"


@mcp.tool()
async def enrich_persona_waterfall_email(persona_apollo_id: str) -> str:
    """
    Enrichit l'email d'un persona via Apollo waterfall email,
    puis met à jour le nœud Persona correspondant dans Neo4j.

    UTILISATION :
    Appelle cet outil avec l'Apollo ID du persona (champ `id` du nœud Persona).
    L'appel Apollo utilise run_waterfall_email=true :
    waterfall_email=true, waterfall_phone=false, reveal_personal_emails=false, reveal_phone_number=false.

    PARAMÈTRES :
    - persona_apollo_id (str): L'identifiant Apollo du persona cible. Obligatoire.

    RETOUR :
    Rapport JSON avec les emails trouvés via waterfall et le statut de mise à jour Neo4j.
    """
    if not persona_apollo_id:
        return "Erreur : Le paramètre 'persona_apollo_id' est obligatoire."

    try:
        result = await anyio.to_thread.run_sync(request_enrich_persona_waterfall_email, persona_apollo_id)
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Erreur lors du waterfall email du persona {persona_apollo_id} : {str(e)}"


# ---------------------------------------------------------------------------
# Orchestrator-facing tools (structured JSON)
# ---------------------------------------------------------------------------

@mcp.tool()
async def orchestrator_fetch_companies(
    industries: List[str],
    locations: Optional[List[str]] = None,
    continent: Optional[str] = None,
    employee_ranges: Optional[List[str]] = None,
    limit: int = 2,
    limit_per_element: int = 1,
    min_employees: Optional[float] = None,
    max_employees: Optional[float] = None,
) -> dict:
    """
    Orchestrator Phase A — fetch companies for ICP filters.
    Local-first: Neo4j geo-intel cache, then Apollo organizations/search for gaps.
    Returns dict: {companies: [...], count: N, usage: {...}}

    min_employees / max_employees post-filter Apollo's open-ended 10001+ bucket
    so mega-corps outside the ICP max (e.g. 363k vs max 200k) are dropped early.
    """
    if not industries:
        return {
            "error": "industries must not be empty",
            "companies": [],
            "count": 0,
            "usage": build_tool_usage(
                tool="sourcer.fetch_companies",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }
    if not locations and not continent:
        return {
            "error": "locations or continent required",
            "companies": [],
            "count": 0,
            "usage": build_tool_usage(
                tool="sourcer.fetch_companies",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }

    try:
        results = await anyio.to_thread.run_sync(
            request_discover_companies,
            industries,
            locations,
            continent,
            employee_ranges,
            limit,
            limit_per_element,
            min_employees,
            max_employees,
        )
        companies = results if isinstance(results, list) else []
        usage = pop_last_orchestrator_usage() or build_tool_usage(
            tool="sourcer.fetch_companies",
            apollo=empty_apollo_usage(),
            gemini=empty_gemini_usage(),
        )
        return {"companies": companies, "count": len(companies), "usage": usage}
    except Exception as e:
        return {
            "error": str(e),
            "companies": [],
            "count": 0,
            "usage": pop_last_orchestrator_usage()
            or build_tool_usage(
                tool="sourcer.fetch_companies",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }


@mcp.tool()
async def orchestrator_fetch_intent(
    company_apollo_ids: List[str],
    target_country: Optional[str] = None,
) -> dict:
    """
    Orchestrator Phase A — fetch intent signals keyed by apollo_id.
    Local-first: reuse Neo4j IntentSignal + company_intent when present.
    Returns dict: {intent_by_apollo_id: {apollo_id: {job_offers, news, ...}}, usage: {...}}
    """
    if not company_apollo_ids:
        return {
            "error": "company_apollo_ids required",
            "intent_by_apollo_id": {},
            "usage": build_tool_usage(
                tool="sourcer.fetch_intent",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }

    initial_apollo = snapshot_apollo(config.APOLLO_API_KEY)
    try:
        results = await anyio.to_thread.run_sync(
            request_fetch_intent_signals_for_orchestrator,
            company_apollo_ids,
            target_country,
        )
        usage = usage_from_apollo_window(
            tool="sourcer.fetch_intent",
            api_key=config.APOLLO_API_KEY,
            initial_report=initial_apollo,
        )
        return {"intent_by_apollo_id": results, "usage": usage}
    except Exception as e:
        usage = usage_from_apollo_window(
            tool="sourcer.fetch_intent",
            api_key=config.APOLLO_API_KEY,
            initial_report=initial_apollo,
        )
        return {"error": str(e), "intent_by_apollo_id": {}, "usage": usage}


@mcp.tool()
async def orchestrator_fetch_personas_with_signals(
    company_apollo_ids: List[str],
    target_country: Optional[str] = None,
    role: Optional[List[str]] = None,
    limit: int = 10,
    limit_per_element: int = 3,
) -> dict:
    """
    Orchestrator Phase A — fetch personas + signals for companies.
    Local-first: reuse Neo4j Persona nodes when present; Apollo only for gaps.

    role: ICP target_roles from the orchestrator (Apollo person_titles[]).
    When omitted/empty, falls back to the built-in sales title preset.

    Returns dict with sourced_personas_by_company keyed by apollo_id, plus usage.
    """
    if not company_apollo_ids:
        return {
            "error": "company_apollo_ids required",
            "sourced_personas_by_company": {},
            "usage": build_tool_usage(
                tool="sourcer.fetch_personas",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }

    cleaned_roles = [
        str(r).strip() for r in (role or []) if str(r).strip()
    ]

    initial_apollo = snapshot_apollo(config.APOLLO_API_KEY)
    try:
        results = await anyio.to_thread.run_sync(
            request_fetch_personas_for_orchestrator,
            company_apollo_ids,
            target_country,
            cleaned_roles if cleaned_roles else list(SALES_PERSONA_TITLES),
            limit,
            limit_per_element,
        )
        payload = results if isinstance(results, dict) else {"sourced_personas_by_company": {}}
        payload["usage"] = usage_from_apollo_window(
            tool="sourcer.fetch_personas",
            api_key=config.APOLLO_API_KEY,
            initial_report=initial_apollo,
        )
        return payload
    except Exception as e:
        return {
            "error": str(e),
            "sourced_personas_by_company": {},
            "usage": usage_from_apollo_window(
                tool="sourcer.fetch_personas",
                api_key=config.APOLLO_API_KEY,
                initial_report=initial_apollo,
            ),
        }


@mcp.tool()
async def orchestrator_enrich_contacts(persona_apollo_ids: List[str]) -> dict:
    """
    Orchestrator Phase A — enrich email + phone for selected personas.

    Strategy:
    0. Local-first via get_local_persona_contacts (has_email + has_phone in Neo4j)
    1. Sync reveal via enrich_persona_phone
    2. If email or phone missing → enrich_persona_waterfall_phone (with webhook poll)

    Returns dict keyed by persona apollo_id, plus usage.
    """
    if not persona_apollo_ids:
        return {
            "error": "persona_apollo_ids required",
            "contacts": {},
            "usage": build_tool_usage(
                tool="sourcer.enrich_contacts",
                apollo=empty_apollo_usage(),
                gemini=empty_gemini_usage(),
            ),
        }

    initial_apollo = snapshot_apollo(config.APOLLO_API_KEY)
    try:
        results = await anyio.to_thread.run_sync(
            request_enrich_contacts_for_orchestrator,
            persona_apollo_ids,
        )
        usage = usage_from_apollo_window(
            tool="sourcer.enrich_contacts",
            api_key=config.APOLLO_API_KEY,
            initial_report=initial_apollo,
        )
        return {"contacts": results, "usage": usage}
    except Exception as e:
        usage = usage_from_apollo_window(
            tool="sourcer.enrich_contacts",
            api_key=config.APOLLO_API_KEY,
            initial_report=initial_apollo,
        )
        return {"error": str(e), "contacts": {}, "usage": usage}


if __name__ == "__main__":
    # L'exécution par un client MCP gère l'orchestration stdio automatiquement via mcp.run().
    mcp.run(transport="stdio")
