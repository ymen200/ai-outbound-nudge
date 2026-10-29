# Déroulement du projet — de `docker compose up` au message final

---

## 1. Lancement avec Docker Compose

```bash
docker-compose up --build
```

Docker lit le `Dockerfile`, installe les dépendances depuis `requirements.txt`, copie le code source, et démarre le serveur :

```
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

À ce stade, deux choses tournent sur le port 8000 :
- L'API FastAPI → `http://localhost:8000`
- Le serveur MCP (SSE) → `http://localhost:8000/mcp`

---

## 2. Réception de la requête HTTP

Un client (Postman, frontend, autre agent) envoie un `POST /api/generate/simple` :

```json
{
  "target_prospect": "Sarah Chen",
  "target_company": "Ramp",
  "prospect_role": "VP of Sales",
  "channel": "linkedin_dm",
  "stage": "first_touch",
  "intent": "direct_outreach",
  "company_details": {
    "company_name": "SalesForce AI",
    "elevator_pitch": "We help SDR teams double their reply rates using AI personalization."
  },
  "selected_offer": {
    "offer_name": "SDR Efficiency Audit",
    "cta": "15-min chat?"
  }
}
```

`main.py` reçoit la requête, valide le body via le modèle Pydantic `GenerateRequest`, et instancie un `PipelineOrchestrator`.

---

## 3. Initialisation de l'état

`PipelineOrchestrator.__init__` crée un `AgentState` — l'objet central qui voyage à travers tout le pipeline :

```
AgentState {
  task_id: "uuid-généré",
  status: PLANNING,
  target_prospect: "Sarah Chen",
  target_company: "Ramp",
  research_signals: [],   ← vide pour l'instant
  strategy: null,         ← vide pour l'instant
  draft: null,            ← vide pour l'instant
  validation: null,       ← vide pour l'instant
  iteration_count: 0,
  max_iterations: 3
}
```

---

## 4. Entrée dans le graphe LangGraph

`orchestrator.run_full_pipeline()` appelle `graph.run_pipeline()` qui convertit l'`AgentState` en dict et le passe à `pipeline.stream()`.

Le graphe LangGraph prend le relais. Il exécute les nœuds dans l'ordre défini, en routant automatiquement selon le `status` de l'état après chaque nœud.

---

## 5. Nœud 1 — Planner

**Fichier :** `agents.py → AgentNodes.planner()`

Le Planner ne fait aucun appel LLM. Il regarde l'état et décide quoi faire ensuite :

```
research_signals vide ? → status = RESEARCHING
```

Il met à jour le `status` et retourne l'état. LangGraph route vers le nœud suivant : **Researcher**.

---

## 6. Nœud 2 — Researcher

**Fichier :** `agents.py → AgentNodes.researcher()`

Trois choses se passent ici :

**a) Chargement mémoire prospect**
`MemoryService.prospects.get_or_create("Sarah Chen", "Ramp")` — vérifie si on a déjà contacté ce prospect. Si `do_not_contact = true`, le pipeline s'arrête immédiatement avec `status = FAILED`.

**b) Collecte des signaux de recherche**
Trois appels à `tools.py` :
- `ResearchTools.fetch_linkedin_posts()` → posts LinkedIn récents (mock ou API réelle)
- `ResearchTools.fetch_company_news()` → actualités de l'entreprise
- `ResearchTools.get_crm_history()` → historique CRM

**c) Stockage dans l'état**
```
state.research_signals = [Signal(...), Signal(...), Signal(...)]
state.memory["hooks_already_used"] = []
state.memory["times_contacted_before"] = 0
state.status = STRATEGIZING
```

LangGraph route vers **Strategist**.

---

## 7. Nœud 3 — Strategist

**Fichier :** `agents.py → AgentNodes.strategist()`

Deux appels LLM via `llm_service.py` :

**Appel 1 — Analyse des signaux**
`llm_service.analyze_research_signals()` envoie les signaux à Gemini et reçoit :
```json
{
  "primary_hook": "Milestone: doubled revenue via SDR pod approach",
  "secondary_hook": "Ramp named fastest-growing company",
  "confidence": "high"
}
```

**Appel 2 — Construction de la stratégie**
`llm_service.create_strategy()` envoie le hook + contexte à Gemini et reçoit :
```json
{
  "angle": "Amplify their SDR success with AI personalization",
  "reasoning": "Acknowledges win, positions offer as complement not disruption"
}
```

L'état est mis à jour :
```
state.strategy = Strategy(primary_hook=..., angle=..., tone="soft_sell", ...)
state.status = WRITING
```

LangGraph route vers **Writer**.

---

## 8. Nœud 4 — Writer

**Fichier :** `agents.py → AgentNodes.writer()`

Un appel LLM via `llm_service.write_message()`.

Le prompt envoyé à Gemini contient :
- La stratégie (hook, angle, raisonnement)
- Le style (soft_sell, urgency 2/10, humor 3/10)
- Les infos de l'entreprise expéditrice
- L'offre et le CTA
- Les règles du canal (LinkedIn DM : 50-300 chars, conversationnel)
- L'historique de contact (premier contact → ne pas pitcher fort)

Gemini retourne :
```json
{
  "body": "Hey Sarah, congrats on Ramp doubling revenue this quarter! That SDR pod approach caught my eye. We help teams like yours scale replies with AI — open to a quick 15-min chat?",
  "subject": null,
  "sentence_breakdown": [...]
}
```

L'état est mis à jour :
```
state.draft = MessageDraft(body="Hey Sarah...", sentence_attribution=[...])
state.status = VALIDATING
```

LangGraph route vers **Critic**.

---

## 9. Nœud 5 — Critic

**Fichier :** `agents.py → AgentNodes.critic()`

**Étape 1 — Vérifications déterministes (sans LLM)**
Avant tout appel LLM, le Critic vérifie :
- Longueur du message (50-300 chars pour LinkedIn DM)
- Présence de phrases bannies
- Présence de placeholders `[Company]`, `[Name]`, etc.
- Overpersonalisation (phrases "creepy")

Si une de ces règles échoue → `valid = False` immédiatement, le LLM n'est pas appelé (économie de tokens).

**Étape 2 — Scoring LLM (si règles passées)**
`llm_service.validate_message()` envoie le message à Gemini pour évaluation qualitative :
- Clarté du CTA
- Nombre de touchpoints
- Authenticité
- Phrases requises présentes

Gemini retourne :
```json
{
  "score": 87,
  "warnings": [],
  "suggested_fixes": null,
  "valid": true
}
```

**Étape 3 — Décision**

| Situation | Action |
|---|---|
| `valid = true` | `status = COMPLETE` → sauvegarde en mémoire |
| `valid = false` + fixes disponibles + iterations restantes | `status = REVISING` → retour au Writer avec feedback |
| `valid = false` + pas de fixes | `status = PLANNING` → restart complet |
| iterations épuisées | `status = FAILED` → abort |

---

## 10. Boucle de révision (si nécessaire)

Si le Critic renvoie `status = REVISING`, LangGraph route **directement vers le Writer** (pas le Planner).

Le Writer reçoit dans son prompt :
```
REVISION REQUIRED — your previous draft was rejected.
PREVIOUS DRAFT (317 chars): "Hey Sarah..."
FEEDBACK: Too long: 317 chars, max is 300. Shorten by 17 characters.
Fix exactly what the feedback says. Do not change anything else.
```

Ce cycle Writer → Critic peut se répéter jusqu'à `max_iterations` fois (défaut : 3).

---

## 11. Fin du pipeline — Sauvegarde mémoire

Quand `status = COMPLETE`, le Critic enregistre tout dans la mémoire :

```python
MemoryService.prospects.record_outreach(
    name="Sarah Chen", company="Ramp",
    hook_used="Doubled revenue via SDR pod",
    angle_used="Amplify SDR success",
    message_sent="Hey Sarah..."
)
MemoryService.learning.record_generation(score=87, channel="linkedin_dm", ...)
MemoryService.offers.record_usage(offer_name="SDR Efficiency Audit", ...)
```

La prochaine fois que Sarah Chen est ciblée, le Researcher chargera ces données et le Strategist évitera les hooks et angles déjà utilisés.

---

## 12. Retour de la réponse HTTP

`run_pipeline()` retourne la liste de tous les `AgentState` snapshots (un par étape).

`main.py` prend le dernier état et retourne :

```json
{
  "success": true,
  "message": "Hey Sarah, congrats on Ramp doubling revenue this quarter! That SDR pod approach caught my eye. We help teams like yours scale replies with AI — open to a quick 15-min chat?",
  "subject": null,
  "score": 87,
  "warnings": [],
  "attribution": [...]
}
```

---

## Résumé visuel

```
docker-compose up
       │
       ▼
FastAPI démarre (port 8000) + MCP SSE (port 8000/mcp)
       │
POST /api/generate/simple
       │
       ▼
PipelineOrchestrator → AgentState initial
       │
       ▼
LangGraph StateGraph
       │
   ┌───▼────┐
   │Planner │ → décide la prochaine étape
   └───┬────┘
       │
   ┌───▼──────────┐
   │  Researcher  │ → mémoire + LinkedIn + news + CRM
   └───┬──────────┘
       │
   ┌───▼──────────┐
   │  Strategist  │ → 2 appels Gemini → hook + angle
   └───┬──────────┘
       │
   ┌───▼──────────┐
   │    Writer    │◄──────────────────┐
   └───┬──────────┘                   │ REVISING
       │                              │
   ┌───▼──────────┐                   │
   │    Critic    │ → score + valid ? ─┘
   └───┬──────────┘
       │ COMPLETE
       ▼
  Mémoire sauvegardée
       │
       ▼
  Réponse JSON → client
```

---

## Appel via MCP (agent-to-agent)

Un agent externe peut déclencher le même pipeline sans passer par l'API REST :

```json
// Connexion SSE : http://localhost:8000/mcp
// Outil appelé : generate_outreach
{
  "target_prospect": "Sarah Chen",
  "target_company": "Ramp",
  "company_name": "SalesForce AI",
  "offer_name": "SDR Efficiency Audit"
}
```

Le pipeline s'exécute identiquement. Le résultat revient au format MCP `TextContent`.
