# Inject & Collect - Agentic System Architecture

This document reframes the project from `ARCHITECTURE_DIAGRAM.md` as an agentic data-enrichment system. Instead of showing only modules and infrastructure, it highlights the goal loop, reasoning components, tool use, memory/state, evaluation, and handoffs between specialized agents.

## 1. Agentic System Context

```mermaid
flowchart LR
    User["User / Analyst<br/>sets target industry, location, max companies"] --> Supervisor["Supervisor Agent<br/>main_discovery.py"]

    Supervisor --> DiscoveryAgent["Company Discovery Agent<br/>ApolloScraper"]
    Supervisor --> WebResearchAgent["Web Research Agent<br/>SmartScraperAI"]
    Supervisor --> FusionAgent["Profile Fusion Agent<br/>generate_merged_report()"]
    Supervisor --> PersonaAgent["Persona Agent<br/>persona_search_enrich.py"]
    Supervisor --> PersistenceAgent["Persistence Agent<br/>Neo4jManager"]

    DiscoveryAgent --> Apollo["Apollo.io API"]
    WebResearchAgent --> Websites["Company websites<br/>HTML, internal links, PDFs"]
    WebResearchAgent --> Gemini["Google Gemini<br/>planning, extraction, vision, post-processing"]
    PersonaAgent --> PersonaTools["Serper, Hunter, Snov.io,<br/>Tomba, AeroLeads"]
    PersistenceAgent --> Neo4j["Neo4j AuraDB"]

    Supervisor --> Memory["Working Memory / Artifacts<br/>scraped_data, merged_profiles,<br/>personas_discovered, comparisons"]
    WebResearchAgent --> Memory
    FusionAgent --> Memory
    PersonaAgent --> Memory
    PersistenceAgent --> Memory
```

## 2. Agent Roles And Responsibilities

| Agentic Component | Code Owner | Goal | Tools | Output |
|---|---|---|---|---|
| Supervisor Agent | `main_discovery.py` | Orchestrate the full enrichment mission for a target market | Python runtime, config, all downstream modules | Completed company/persona import workflow |
| Company Discovery Agent | `apollo_scraper.py` / `ApolloScraper` | Find and validate companies matching industry/location criteria | Apollo search and organization enrichment APIs | Normalized Apollo company profiles |
| Web Research Agent | `smart_scraper_ai.py` / `SmartScraperAI` | Autonomously inspect websites and extract Apollo-style company facts | Playwright, BeautifulSoup, requests, PyMuPDF, PIL, Gemini text and vision | `*_RAW.txt` and `*_APOLLO.json` |
| Profile Fusion Agent | `generate_merged_report()` | Merge Apollo and AI evidence into one trusted profile | Confidence rules, data quality score logic | `*_MERGED.json` |
| Persona Agent | `persona_search_enrich.py` | Discover likely people and enrich their contact data | Serper, Hunter, Snov.io, Tomba, AeroLeads | `*_personas.json` |
| Persistence Agent | `database_manager.py` / `Neo4jManager` | Convert enriched profiles into graph entities and relationships | Neo4j driver, Cypher import methods | `Company`, `Version`, `Persona`, and relationship nodes |

## 3. Agentic Control Loop

```mermaid
flowchart TD
    Goal["Goal<br/>Build reliable company and persona intelligence"] --> Plan["Plan<br/>Supervisor chooses next company and workflow branch"]
    Plan --> Act["Act<br/>Call Apollo, scrape website, enrich personas, merge data"]
    Act --> Observe["Observe<br/>API responses, HTML, links, PDFs, social URLs, extracted text"]
    Observe --> Reason["Reason<br/>Gemini extraction, page selection, confidence scoring"]
    Reason --> Evaluate["Evaluate<br/>missing fields, location fit, evidence quality, confidence"]
    Evaluate --> Decide{"Enough evidence?"}

    Decide -- "No" --> Replan["Re-plan<br/>visit targeted pages or parse financial PDFs"]
    Replan --> Act

    Decide -- "Yes" --> Persist["Persist<br/>save JSON/TXT artifacts and import into Neo4j"]
    Persist --> Done["Done<br/>company profile and personas available for analysis"]
```

The strongest agentic loop lives inside `SmartScraperAI`: it observes a website, extracts facts, evaluates missing or weak fields, asks Gemini to plan targeted navigation, acts by visiting new pages or PDFs, then reruns extraction with better evidence.

## 4. Multi-Agent Pipeline

```mermaid
flowchart TB
    Start([Mission Start]) --> Config["Runtime Mission Config<br/>industry, location, max companies"]
    Config --> Supervisor["Supervisor Agent<br/>main_discovery.py"]

    Supervisor --> Discover["Company Discovery Agent"]
    Discover --> CandidateMemory["Candidate Company Memory<br/>basic Apollo profiles"]

    CandidateMemory --> CompanyLoop{"For each company"}
    CompanyLoop --> Validate["Validate Domain + Location<br/>enrichment and subsidiary checks"]

    Validate --> WebDecision{"Website available?"}
    WebDecision -- Yes --> WebAgent["Web Research Agent<br/>agentic website investigation"]
    WebDecision -- No --> ApolloOnly["Apollo-only fallback profile"]

    WebAgent --> EvidenceMemory["Evidence Memory<br/>raw text, social links, tech footprint, PDFs"]
    EvidenceMemory --> Extraction["Structured Extraction<br/>Gemini Apollo-style JSON"]
    Extraction --> WebEval["Self-Evaluation<br/>missing revenue, city, location, weak evidence"]
    WebEval --> MoreResearch{"Need more evidence?"}
    MoreResearch -- Yes --> TargetedNav["Targeted Navigation Planner<br/>Gemini selects useful internal links"]
    TargetedNav --> WebAgent
    MoreResearch -- "PDF needed" --> PDFTool["Financial PDF Tool<br/>download into RAM, PyMuPDF, Gemini Vision"]
    PDFTool --> EvidenceMemory
    MoreResearch -- No --> AIProfile["AI Profile Memory<br/>scraped_data/*_APOLLO.json"]

    AIProfile --> Fusion["Profile Fusion Agent"]
    ApolloOnly --> Fusion
    Validate --> Fusion
    Fusion --> MergedMemory["Merged Profile Memory<br/>merged_profiles/*_MERGED.json"]

    MergedMemory --> PersonaDecision{"Domain available?"}
    PersonaDecision -- Yes --> PersonaAgent["Persona Agent<br/>LinkedIn discovery + contact cascade"]
    PersonaDecision -- No --> ImportPrep["Prepare company import batch"]
    PersonaAgent --> PersonaMemory["Persona Memory<br/>personas_discovered/*_personas.json"]

    MergedMemory --> ImportPrep
    PersonaMemory --> PersonaImportPrep["Prepare persona import batch"]
    ImportPrep --> Persist["Persistence Agent<br/>Neo4j import"]
    PersonaImportPrep --> Persist
    Persist --> End([Mission Complete])
```

## 5. Web Research Agent Internals

```mermaid
flowchart TD
    Input["Input<br/>company website + optional target address"] --> BrowserPlanner["Browser Context Planner<br/>Gemini selects locale/timezone"]
    BrowserPlanner --> BrowserTool["Browser Tool<br/>Playwright Chromium"]
    BrowserTool --> Homepage["Observe Homepage<br/>HTML, rendered text, anchors, scripts"]

    Homepage --> Perception["Perception Layer"]
    Perception --> CleanText["Clean content<br/>BeautifulSoup + pseudo-Markdown"]
    Perception --> LinkMap["Link map<br/>internal URLs + PDF URLs"]
    Perception --> TechSignals["Tech footprint<br/>headers, scripts, JS globals, CSS prefixes"]
    Perception --> SocialSignals["Social link extraction"]

    CleanText --> ContextBuilder["Evidence Context Builder"]
    LinkMap --> ContextBuilder
    TechSignals --> ContextBuilder
    SocialSignals --> ContextBuilder

    ContextBuilder --> Extractor["Extractor<br/>extract_apollo_json() with Gemini"]
    Extractor --> SchemaMemory["Structured Working Memory<br/>value, confidence, source per field"]

    SchemaMemory --> Critic["Critic<br/>check_missing_fields()"]
    Critic --> Missing{"Critical fields missing?"}

    Missing -- Yes --> Planner["Planner<br/>get_targeted_links_with_ai()"]
    Planner --> BrowserTool

    Missing -- "Revenue missing + PDFs found" --> PDFAgent["PDF Evidence Tool<br/>extract_pdf_in_memory()"]
    PDFAgent --> ContextBuilder

    Missing -- No --> PostProcessor["Post-Processor<br/>normalize revenue, competitors, DQS"]
    PostProcessor --> SocialFix["Social URL Validator"]
    SocialFix --> XAI["XAI Injector<br/>inject_xai_metrics()"]
    XAI --> Output["Final AI Profile<br/>*_RAW.txt + *_APOLLO.json"]
```

## 6. Agent Memory Model

```mermaid
flowchart LR
    subgraph ShortTerm["Short-Term Working Memory"]
        CurrentCompany["Current company object"]
        EvidenceContext["Current website evidence context"]
        MissingFields["Missing field list"]
        SeenURLs["Seen URL set"]
        CandidateLinks["Candidate internal links"]
    end

    subgraph ArtifactMemory["Artifact Memory"]
        RawFiles["scraped_data/*_RAW.txt"]
        AIJson["scraped_data/*_APOLLO.json"]
        MergedJson["merged_profiles/*_MERGED.json"]
        PersonaJson["personas_discovered/*_personas.json"]
        Comparisons["comparisons/*"]
    end

    subgraph GraphMemory["Long-Term Graph Memory"]
        Company["Company nodes"]
        Version["Version nodes"]
        Persona["Persona nodes"]
        Edges["CURRENT, ARCHIVED, OWNS, WORKS_AT"]
    end

    ShortTerm --> ArtifactMemory
    ArtifactMemory --> GraphMemory
```

## 7. Tool Registry

| Tool Class | Concrete Tool | Used By | Agentic Purpose |
|---|---|---|---|
| Search API | Apollo organization search | Company Discovery Agent | Find candidate companies |
| Enrichment API | Apollo organization enrichment | Company Discovery Agent | Validate domain, HQ, size, revenue, ownership |
| Browser | Playwright Chromium | Web Research Agent | Act on the web like a research worker |
| HTML Parser | BeautifulSoup + regex | Web Research Agent | Convert noisy pages into usable evidence |
| LLM Text Reasoner | Gemini text models | Web Research Agent | Extract schema, choose pages, post-process fields |
| Vision Reasoner | Gemini vision | Web Research Agent | Read low-text PDF page images |
| PDF Parser | requests + PyMuPDF + PIL | Web Research Agent | Extract financial evidence without storing PDFs on disk |
| People Search | Serper LinkedIn query | Persona Agent | Discover likely employee/persona records |
| Contact Enrichment | Hunter, Snov.io, Tomba, AeroLeads | Persona Agent | Fill email, phone, title, LinkedIn fields |
| Graph Store | Neo4j AuraDB | Persistence Agent | Persist enriched intelligence as connected entities |
| File Store | Local JSON/TXT folders | All agents | Share state and audit evidence between stages |

## 8. Evaluation And Guardrails

```mermaid
flowchart TD
    ExtractedField["Extracted field<br/>value + confidence + source"] --> EvidenceCheck["Faithfulness Check<br/>source appears in raw evidence"]
    ExtractedField --> CalibrationCheck["Calibration Check<br/>confidence compared with value/source similarity"]
    ExtractedField --> DensityCheck["Evidence Density Check<br/>value length vs evidence length"]

    EvidenceCheck --> XAIResult["XAI metrics"]
    CalibrationCheck --> XAIResult
    DensityCheck --> XAIResult

    XAIResult --> MergeDecision["Fusion Decision<br/>Apollo vs AI"]
    MergeDecision --> ConfidenceRule["AI can win when confidence >= 0.8"]
    MergeDecision --> DQS["Data Quality Score<br/>completeness + source synergy + AI score"]
    ConfidenceRule --> FinalProfile["Merged company profile"]
    DQS --> FinalProfile
```

Agentic safeguards already present in the project:

| Guardrail | Implementation | Why It Matters |
|---|---|---|
| Missing-field critique | `check_missing_fields()` | Prevents stopping after weak homepage evidence |
| Targeted page planning | `get_targeted_links_with_ai()` | Directs the browser toward useful pages instead of crawling blindly |
| Evidence-carrying fields | Gemini schema prompt asks for `value`, `confidence`, and `source` | Makes extracted facts auditable |
| XAI injection | `inject_xai_metrics()` | Adds field-level trust signals |
| Confidence-based merge | `generate_merged_report()` | Reduces blind overwrites between Apollo and AI data |
| PDF in-memory processing | `extract_pdf_in_memory()` | Avoids storing financial PDFs by default |
| Fallback profiles | `main_discovery.py` fallback branches | Keeps the mission running when a provider or website fails |

## 9. Agentic Sequence Diagram

```mermaid
sequenceDiagram
    participant User
    participant Supervisor as "Supervisor Agent<br/>main_discovery.py"
    participant Apollo as Company Discovery Agent
    participant Web as "Web Research Agent<br/>SmartScraperAI"
    participant Gemini as Gemini Reasoner
    participant Fusion as Profile Fusion Agent
    participant Persona as Persona Agent
    participant DB as Persistence Agent
    participant Memory as Artifact Memory

    User->>Supervisor: Start mission with target industry/location
    Supervisor->>Apollo: Search matching companies
    Apollo-->>Supervisor: Candidate company list

    loop Each company
        Supervisor->>Apollo: Enrich and validate organization
        Apollo-->>Supervisor: Apollo profile or fallback data

        alt Website exists
            Supervisor->>Web: Investigate website
            Web->>Gemini: Select browser context
            Gemini-->>Web: Locale/timezone
            Web->>Web: Browse, scroll, parse, collect links/PDFs
            Web->>Gemini: Extract structured company profile
            Gemini-->>Web: Apollo-style JSON
            Web->>Web: Check missing fields

            alt More evidence needed
                Web->>Gemini: Pick targeted internal pages
                Gemini-->>Web: Best URLs to visit
                Web->>Web: Visit pages or parse PDFs
                Web->>Gemini: Re-extract with expanded evidence
                Gemini-->>Web: Refined JSON
            end

            Web->>Web: Inject XAI metrics
            Web->>Memory: Save raw text and AI JSON
        end

        Supervisor->>Fusion: Merge Apollo + AI evidence
        Fusion->>Memory: Save merged profile

        alt Domain exists
            Supervisor->>Persona: Discover and enrich personas
            Persona->>Memory: Save persona JSON
        end
    end

    Supervisor->>DB: Import companies, versions, personas
    DB-->>Supervisor: Graph import complete
    Supervisor-->>User: Mission complete
```

## 10. Agentic Components Summary

| Agentic Layer | Project Implementation |
|---|---|
| Goal | Build reliable company and persona profiles for a target market |
| Supervisor | `main_discovery.py` controls the mission, loops, fallbacks, and imports |
| Perception | Playwright page rendering, HTML parsing, link extraction, PDF parsing, social link extraction |
| Reasoning | Gemini extraction, browser context selection, targeted link planning, post-processing |
| Action | API calls, browser navigation, PDF download into RAM, provider cascade calls, Neo4j writes |
| Memory | In-process company objects, seen URLs, evidence context, JSON/TXT artifacts, Neo4j graph |
| Evaluation | Missing-field checks, confidence scores, source evidence, XAI metrics, data quality score |
| Handoffs | Apollo profile -> AI profile -> merged profile -> personas -> graph import |

## 11. Improvement Opportunities For A More Explicit Agent System

| Area | Current State | Possible Agentic Upgrade |
|---|---|---|
| Planning | Planning exists mainly inside website navigation | Add a mission planner that records step plans per company |
| Memory | Artifacts are stored as files and Neo4j nodes | Add a run/session memory object with trace IDs across all stages |
| Tool registry | Tools are called directly by modules | Create a typed tool interface for browser, APIs, PDF, and database operations |
| Critic | Critique focuses on missing fields and XAI metrics | Add a final verifier agent that checks contradictions across Apollo, website, and persona evidence |
| Observability | Logs are mostly print/error handling | Add structured agent traces: goal, action, observation, decision, confidence |
| Human review | User starts the process and reads outputs | Add optional review gates for low-confidence profiles or personal contact data |
