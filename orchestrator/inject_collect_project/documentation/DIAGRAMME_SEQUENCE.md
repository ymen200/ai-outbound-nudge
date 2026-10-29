# Sequence Diagram - Inject & Collect

This document presents a simplified sequence diagram for the Inject & Collect project using only the principal actors.

The diagram assumes the target architecture where:

- Apify lead scraping is integrated into the Persona & Leads module.
- `Intent_search.py` and `intent_signals_scraper.py` are integrated into the Intent Signals module.
- Companies, merged profiles, personas, leads, and intent signals are persisted in the database.

## Main Sequence Diagram

```mermaid
sequenceDiagram
    actor User
    participant Main as Main Orchestrator<br/>main_discovery.py
    participant Discovery as Company Discovery<br/>ApolloScraper
    participant Research as AI Web Research<br/>SmartScraperAI + Gemini
    participant Persona as Persona & Leads<br/>persona_search_enrich.py + Apify
    participant Intent as Intent Signals<br/>Intent_search + intent_signals_scraper
    participant Files as Local Files
    participant DB as Database<br/>Neo4jManager

    User->>Main: Start the enrichment pipeline
    Main->>Discovery: Search companies by industry and location
    Discovery-->>Main: Candidate company list

    loop For each company
        Main->>Discovery: Enrich company profile
        Discovery-->>Main: Apollo company data

        alt Website is available
            Main->>Research: Analyze company website
            Research->>Research: Scrape pages, analyze PDFs,<br/>extract structured data with AI
            Research->>Files: Save raw text and AI JSON
            Research-->>Main: AI-enriched company profile

            Main->>Main: Merge Apollo data with AI data
            Main->>Files: Save merged company profile
        else Website is missing
            Main->>Main: Use Apollo profile as fallback
        end

        alt Domain is available
            Main->>Persona: Discover and enrich personas
            Persona->>Persona: Search decision-makers,<br/>enrich contacts, collect Apify leads
            Persona->>Files: Save persona and lead data
            Persona-->>Main: Enriched personas and leads
        end

        alt Intent signal collection is enabled
            Main->>Intent: Collect intent signals
            Intent->>Intent: Get jobs/news from APIs<br/>and extract signals from website
            Intent->>Files: Save intent signal data
            Intent-->>Main: Company intent signals
        end
    end

    Main->>DB: Store company profiles
    Main->>DB: Store merged profiles
    Main->>DB: Store personas and leads
    Main->>DB: Store intent signals
    DB-->>Main: Data persisted successfully
    Main-->>User: Pipeline completed
```

## Principal Actors

| Actor | Includes | Responsibility |
|---|---|---|
| User | Analyst / operator | Starts the pipeline and defines the target market |
| Main Orchestrator | `main_discovery.py` | Coordinates all project phases |
| Company Discovery | `ApolloScraper` | Finds and enriches companies through Apollo |
| AI Web Research | `SmartScraperAI`, Gemini | Scrapes websites, analyzes PDFs, extracts structured company data |
| Persona & Leads | `persona_search_enrich.py`, Apify | Discovers people, enriches contacts, and collects lead data |
| Intent Signals | `Intent_search.py`, `intent_signals_scraper.py` | Collects hiring, news, expansion, and business intent signals |
| Local Files | `scraped_data`, `merged_profiles`, `personas_discovered`, `intent_signals_data` | Stores intermediate and final JSON/TXT artifacts |
| Database | `Neo4jManager`, Neo4j | Persists companies, profiles, personas, leads, and intent signals |

