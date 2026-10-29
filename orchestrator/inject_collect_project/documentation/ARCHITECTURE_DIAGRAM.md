# Inject & Collect - Full Architecture Diagram

This document describes the architecture of the current project based on the Python modules, Docker setup, local data folders, and enrichment scripts in this repository.

## 1. System Context

```mermaid
flowchart LR
    User["User / Analyst"] --> CLI["Python CLI<br/>python main_discovery.py"]

    CLI --> App["Inject & Collect Pipeline"]

    App --> Apollo["Apollo.io API<br/>Company search + enrichment"]
    App --> Websites["Company Websites<br/>HTML, links, PDFs"]
    App --> Gemini["Google Gemini API<br/>LLM + vision extraction"]
    App --> PersonaAPIs["Persona Enrichment APIs<br/>Serper, Hunter, Snov.io,<br/>Tomba, AeroLeads"]
    App --> Neo4j["Neo4j AuraDB<br/>Graph database"]

    App --> Files["Local JSON/TXT outputs<br/>scraped_data, merged_profiles,<br/>personas_discovered, comparisons"]

    FullEnrich["test_fullenrich.py<br/>Standalone FullEnrich test"] --> FullEnrichAPI["FullEnrich API<br/>People search + bulk contact enrich"]
    FullEnrich --> FullEnrichFile["bulk_enrich_request.json"]
```

## 2. High-Level Component Architecture

```mermaid
flowchart TB
    subgraph Runtime["Runtime Layer"]
        Main["main_discovery.py<br/>Orchestration engine"]
        Docker["Dockerfile / docker-compose.yml<br/>Container runtime"]
    end

    subgraph Discovery["Company Discovery"]
        ApolloScraper["apollo_scraper.py<br/>ApolloScraper"]
        Search["search_companies()<br/>industry + location filters"]
        Enrich["enrich_organization()<br/>domain enrichment + subsidiary check"]
        Format["format_org_data()<br/>normalize Apollo fields"]
    end

    subgraph AI["AI Web Scraping + Extraction"]
        Smart["smart_scraper_ai.py<br/>SmartScraperAI"]
        Browser["Playwright Chromium<br/>headless browsing + scrolling"]
        Parse["BeautifulSoup + regex<br/>clean HTML + tech signatures"]
        PDF["PyMuPDF + PIL<br/>In-memory PDF financial extraction<br/>PDF bytes kept in RAM"]
        LLM["Gemini models<br/>structured Apollo-style JSON"]
        XAI["XAI metrics<br/>faithfulness, calibration, evidence density"]
    end

    subgraph Fusion["Data Fusion"]
        Merge["generate_merged_report()<br/>Apollo + AI merge"]
        Confidence["Confidence rules<br/>AI wins when confidence >= 0.8"]
        DQS["Data quality score<br/>completeness + source synergy + AI score"]
    end

    subgraph Persona["Persona Discovery + Enrichment"]
        PersonaModule["persona_search_enrich.py"]
        Serper["Serper search<br/>LinkedIn/persona discovery"]
        Cascade["Contact cascade<br/>Hunter -> Snov.io -> Tomba -> AeroLeads"]
        Flatten["Flatten + normalize<br/>email, phone, title, LinkedIn"]
    end

    subgraph Persistence["Persistence Layer"]
        DB["database_manager.py<br/>Neo4jManager"]
        ImportCompany["bulk_import_companies()<br/>Apollo profiles"]
        ImportMerged["import_merged_profiles()<br/>merged profiles"]
        ImportPersona["import_personas()<br/>persona nodes"]
        LocalFiles["Local files<br/>raw text + JSON snapshots"]
    end

    Main --> ApolloScraper
    ApolloScraper --> Search
    ApolloScraper --> Enrich
    ApolloScraper --> Format

    Main --> Smart
    Smart --> Browser
    Smart --> Parse
    Smart --> PDF
    Smart --> LLM
    Smart --> XAI

    Main --> Merge
    Merge --> Confidence
    Merge --> DQS

    Main --> PersonaModule
    PersonaModule --> Serper
    PersonaModule --> Cascade
    Cascade --> Flatten

    Main --> DB
    DB --> ImportCompany
    DB --> ImportMerged
    DB --> ImportPersona

    Smart --> LocalFiles
    Merge --> LocalFiles
    PersonaModule --> LocalFiles
```

## 3. End-to-End Data Flow

```mermaid
flowchart TD
    Start([Start]) --> Config["Load runtime configuration<br/>target industry, location, max companies"]
    Config --> Init["Initialize ApolloScraper,<br/>Neo4jManager, SmartScraperAI"]

    Init --> ApolloSearch["Apollo Search<br/>organizations/search"]
    ApolloSearch --> BasicCompanies["Basic company list"]

    BasicCompanies --> Loop{"For each company"}

    Loop --> DomainCheck{"Valid domain?"}
    DomainCheck -- No --> Fallback["Use basic Apollo data<br/>or generate safe unknown domain"]
    DomainCheck -- Yes --> ApolloEnrich["Apollo Enrichment<br/>organizations/enrich"]

    ApolloEnrich --> SubsidiaryCheck{"HQ matches target location?"}
    SubsidiaryCheck -- Yes --> ApolloProfile["Use enriched Apollo profile"]
    SubsidiaryCheck -- No --> SubOrgSearch["Search suborganizations<br/>for local branch"]
    SubOrgSearch --> LocalBranch{"Local branch found?"}
    LocalBranch -- Yes --> ApolloEnrich
    LocalBranch -- No --> Fallback

    ApolloProfile --> WebsiteCheck{"Valid website URL?"}
    Fallback --> WebsiteCheck

    WebsiteCheck -- Yes --> SmartScrape["SmartScraperAI.scrape_and_save()"]
    WebsiteCheck -- No --> PersonaStart["Persona discovery<br/>if domain exists"]

    SmartScrape --> RawText["scraped_data/*_RAW.txt"]
    SmartScrape --> AIJson["scraped_data/*_APOLLO.json"]
    AIJson --> MergeProfile["generate_merged_report()"]
    MergeProfile --> MergedJson["merged_profiles/*_MERGED.json"]

    MergedJson --> PersonaStart
    PersonaStart --> SerperSearch["Serper LinkedIn search<br/>site:linkedin.com/in"]
    SerperSearch --> EnrichmentCascade["Hunter -> Snov.io -> Tomba -> AeroLeads"]
    EnrichmentCascade --> PersonaJson["personas_discovered/*_personas.json"]

    MergedJson --> BatchPrep["Prepare Neo4j import batches"]
    Fallback --> BatchPrep
    PersonaJson --> PersonaBatch["Prepare persona import batch"]

    BatchPrep --> CompanyImport["Neo4j company/profile import"]
    CompanyImport --> PersonaImport["Neo4j persona import<br/>after companies exist"]
    PersonaBatch --> PersonaImport

    PersonaImport --> Done([Done])
```

## 4. SmartScraperAI Internal Flow

```mermaid
flowchart TD
    In["Website URL + optional target address"] --> BrowserConfig["Gemini selects browser locale/timezone"]
    BrowserConfig --> Launch["Launch Playwright Chromium"]
    Launch --> PageLoad["Open page + accept cookies if possible"]
    PageLoad --> Scroll["Auto-scroll lazy-loaded content"]

    Scroll --> ExtractHTML["Capture raw HTML"]
    Scroll --> TechFP["Collect tech footprint<br/>headers, scripts, JS globals, CSS prefixes"]
    Scroll --> SocialLinks["Extract social links from anchors"]
    Scroll --> Links["Collect internal links + PDF links"]

    ExtractHTML --> Clean["Clean HTML into pseudo-Markdown"]
    TechFP --> PromptContent["Build extraction context"]
    Clean --> PromptContent
    SocialLinks --> PromptContent

    PromptContent --> FirstLLM["Gemini extraction<br/>Apollo-style JSON"]
    FirstLLM --> Missing{"Missing revenue/city?"}

    Missing -- Yes --> NavAI["Gemini selects 1-2 targeted internal links"]
    NavAI --> SubPages["Visit strategic pages<br/>contact, about, investors, legal"]
    SubPages --> PromptContent

    Missing -- PDF needed --> PDFRAM["Download financial PDF into RAM<br/>requests response.content"]
    PDFRAM --> PDFScan["Scan in-memory PDF with PyMuPDF<br/>fitz.open(stream=bytes)"]
    PDFScan --> Vision{"Text extraction poor?"}
    Vision -- Yes --> GeminiVision["Gemini vision reads page images"]
    Vision -- No --> PDFText["Use extracted PDF text"]
    GeminiVision --> PromptContent
    PDFText --> PromptContent

    Missing -- No --> PostProcess["Post-process with Gemini<br/>USD revenue, DQS, competitors"]
    PromptContent --> PostProcess
    PostProcess --> FixSocial["Validate/fix social URLs"]
    FixSocial --> XAI["Inject XAI metrics"]
    XAI --> SaveRaw["Save *_RAW.txt"]
    XAI --> SaveJson["Save *_APOLLO.json"]
```

## 5. Agentic Workflow

The project uses an agentic workflow inside `smart_scraper_ai.py`. Instead of scraping only one page and extracting whatever is immediately visible, `SmartScraperAI` acts like a small autonomous research agent:

1. It opens the target website with Playwright.
2. It collects the homepage content, technical footprint, social links, internal links, and potential financial PDF links.
3. It asks Gemini to extract a structured Apollo-style company profile.
4. It checks whether critical fields are missing or weak, especially exact revenue and targeted location.
5. If important fields are missing, it asks Gemini to choose the next best internal pages to visit, such as `Contact`, `About`, `Investors`, `Financials`, `Annual Report`, or `Legal`.
6. It visits those pages, adds the new evidence to the context, and runs extraction again.
7. If financial PDFs are found and revenue is still missing, it downloads the PDF into RAM, parses it in memory, and adds financial evidence to the extraction context.
8. It post-processes the result with Gemini to normalize revenue into USD, estimate data quality, and infer competitors.
9. It validates social links and injects XAI metrics before saving the final JSON.

```mermaid
flowchart TD
    Goal["Goal<br/>Build a reliable company profile"] --> Observe["Observe<br/>Homepage, links, PDFs, tech footprint, social links"]
    Observe --> Extract["Extract<br/>Gemini creates Apollo-style JSON"]
    Extract --> Evaluate["Evaluate<br/>check_missing_fields()"]

    Evaluate --> Complete{"Critical fields complete?"}
    Complete -- Yes --> Finalize["Finalize<br/>USD revenue, DQS, competitors, XAI"]

    Complete -- No --> Plan["Plan next action<br/>Gemini selects targeted internal URLs"]
    Plan --> Act["Act<br/>Visit selected pages with Playwright"]
    Act --> ObserveMore["Observe more evidence<br/>append page content to context"]
    ObserveMore --> Extract

    Evaluate --> PDFNeeded{"Revenue missing<br/>and PDF available?"}
    PDFNeeded -- Yes --> PDFRAM["Download PDF to RAM"]
    PDFRAM --> PDFParse["Parse in memory<br/>PyMuPDF + optional Gemini Vision"]
    PDFParse --> ObserveMore

    Finalize --> Store["Store<br/>*_RAW.txt and *_APOLLO.json"]
```

Agentic parts in the code:

| Agentic Capability | Implementation |
|---|---|
| Goal-directed extraction | `extract_apollo_json()` uses a strict Apollo-style schema prompt |
| Self-evaluation | `check_missing_fields()` detects weak or missing critical fields |
| Planning next steps | `get_targeted_links_with_ai()` asks Gemini which internal URLs are most useful |
| Acting on the plan | `scrape_and_save()` navigates selected URLs with Playwright |
| Iterative refinement | The extraction loop reruns after new pages are added to context |
| Tool use | Playwright, requests, PyMuPDF, PIL, Gemini text, Gemini vision |
| Evidence-aware output | Each extracted field includes `value`, `confidence`, and `source` |

## 6. XAI In SmartScraperAI

`SmartScraperAI` includes explainability logic so the project can evaluate not only what the AI extracted, but also how trustworthy the extraction is. The prompt asks Gemini to return every important field with:

| Field Metadata | Meaning |
|---|---|
| `value` | The extracted company data |
| `confidence` | Gemini's confidence score from `0.0` to `1.0` |
| `source` | The exact evidence text used to justify the value |

After Gemini returns the structured JSON, `inject_xai_metrics()` recursively adds an `xai_metrics` object to fields that contain confidence and source evidence.

```mermaid
flowchart TD
    AIJson["Gemini extracted JSON<br/>value + confidence + source"] --> XAIInject["inject_xai_metrics()"]
    RawText["Full scraped evidence text"] --> XAIInject

    XAIInject --> Faithfulness["faithfulness_score<br/>Checks if cited source appears in raw text"]
    XAIInject --> Calibration["calibration_error<br/>Compares confidence against value/source similarity"]
    XAIInject --> Density["evidence_density<br/>Ratio of extracted value length to evidence length"]

    Faithfulness --> FinalJSON["Final *_APOLLO.json<br/>with XAI metrics"]
    Calibration --> FinalJSON
    Density --> FinalJSON
```

XAI metrics used:

| Metric | How It Works | Why It Matters |
|---|---|---|
| `faithfulness_score` | Returns `1` if the cited source text is found in the scraped evidence, otherwise `0` | Helps detect unsupported or hallucinated claims |
| `calibration_error` | Compares Gemini confidence to text similarity between extracted value and cited source | Highlights overconfident or under-supported fields |
| `evidence_density` | Measures how compact or broad the cited evidence is relative to the extracted value | Helps identify vague evidence versus precise evidence |

This means the project has an explainable enrichment layer: every AI-enriched field can carry a confidence score, a source citation, and extra quality metrics. Those metrics are later available in the saved `scraped_data/*_APOLLO.json` files and can support reporting, debugging, or quality comparison.

## 7. Persona Enrichment Flow

```mermaid
flowchart TD
    Input["Company domain + country/location + role"] --> Query["Build search query<br/>site:linkedin.com/in company location role"]
    Query --> Serper["Serper API search"]
    Serper --> Results["Top organic LinkedIn/person results"]

    Results --> ForEach{"For each result"}
    ForEach --> NameClean["Clean LinkedIn title<br/>split first/last name"]

    NameClean --> Hunter["Hunter.io email finder"]
    Hunter --> NeedMore1{"Missing email/title?"}
    NeedMore1 -- Yes --> SnovToken["Get Snov.io OAuth token"]
    SnovToken --> Snov["Snov.io fallback"]
    NeedMore1 -- No --> TombaCheck
    Snov --> TombaCheck{"Missing email/title/phone?"}

    TombaCheck -- Yes --> Tomba["Tomba email finder/verifier"]
    TombaCheck -- No --> Aero
    Tomba --> Aero["AeroLeads deep enrichment<br/>LinkedIn URL then name/company"]

    Aero --> Merge["Merge best available contact fields"]
    Merge --> Flatten["Flatten AeroLeads raw data<br/>standard fields override duplicates"]
    Flatten --> Save["Save personas_discovered/*_personas.json"]
    Save --> Return["Return list to main_discovery.py"]
```

## 8. Neo4j Graph Model

```mermaid
erDiagram
    COMPANY ||--o{ VERSION : CURRENT
    COMPANY ||--o{ VERSION : ARCHIVED
    COMPANY ||--o{ COMPANY : OWNS
    COMPANY ||--o{ PERSONA : "has employee via WORKS_AT"

    COMPANY {
        string domain PK
        string uid
        string name
        string apollo_id
    }

    VERSION {
        datetime captured_at
        datetime last_verified_at
        string source
        string name
        string industry
        string annual_revenue
        string estimated_num_employees
        string technologies
        string funding_events
        string suborganizations
        float data_quality_score
    }

    PERSONA {
        string linkedin_url PK
        string full_name
        string title
        string email
        string phone
        string source
        datetime last_updated
    }
```

Relationship semantics:

| Relationship | Direction | Meaning |
|---|---|---|
| `(:Company)-[:CURRENT]->(:Version)` | Company to Version | Latest active profile snapshot |
| `(:Company)-[:ARCHIVED]->(:Version)` | Company to Version | Historical profile snapshot after changes |
| `(:Company)-[:OWNS]->(:Company)` | Parent to child | Parent/subsidiary hierarchy |
| `(:Company)-[:OWNED_BY]->(:Company)` | Child to parent | Reverse hierarchy edge |
| `(:Persona)-[:WORKS_AT]->(:Company)` | Persona to Company | Discovered/enriched person belongs to company |

## 9. Local File Architecture

```mermaid
flowchart LR
    ApolloAPI["Apollo API responses"] --> ApolloData["In-memory Apollo profile"]
    Website["Website + PDFs"] --> Raw["scraped_data/*_RAW.txt"]
    Gemini["Gemini extraction"] --> AIJson["scraped_data/*_APOLLO.json"]

    ApolloData --> Merge["generate_merged_report()"]
    AIJson --> Merge
    Merge --> Merged["merged_profiles/*_MERGED.json"]

    PersonaAPI["Persona APIs"] --> PersonaJson["personas_discovered/*_personas.json"]

    Merged --> Neo4j["Neo4j AuraDB"]
    PersonaJson --> Neo4j
    ApolloData --> Neo4j

    Compare["Comparison/reporting scripts or outputs"] --> Comparisons["comparisons/*_COMPARISON.json<br/>comparisons/*_FULL_REPORT.json"]
```

Folder purpose:

| Folder/File | Role |
|---|---|
| `scraped_data/` | Raw website text and Gemini Apollo-style extraction JSON |
| `merged_profiles/` | Final company profiles after Apollo + AI fusion |
| `personas_discovered/` | Persona/contact enrichment results per company |
| `comparisons/` | Data-quality comparison and report artifacts |
| Financial PDFs | Not stored on disk by default; downloaded into RAM and parsed in memory by `SmartScraperAI.extract_pdf_in_memory()` |
| `archive/` | Historical experiments and vendor-specific tests |
| `gemini_test/` | Gemini model testing utilities |
| `test_fullenrich.py` | Standalone FullEnrich search/bulk-enrichment experiment |
| `Dockerfile` | Python 3.11 runtime with Playwright Chromium support |
| `docker-compose.yml` | App container, mounted output directories, optional local Neo4j template |

## 10. Deployment View

```mermaid
flowchart TB
    subgraph Host["Developer Machine / Server"]
        Env[".env / environment variables"]
        Volumes["Mounted output folders<br/>scraped_data, merged_profiles,<br/>comparisons, personas_discovered"]

        subgraph Container["Docker container: inject_collector"]
            Python["Python 3.11 app"]
            Chromium["Playwright Chromium"]
            MainProc["main_discovery.py"]
        end
    end

    MainProc --> Python
    Python --> Chromium
    Env --> MainProc
    MainProc --> Volumes

    MainProc --> Apollo["Apollo.io API"]
    MainProc --> Gemini["Google Gemini API"]
    MainProc --> PersonaServices["Serper / Hunter / Snov.io / Tomba / AeroLeads"]
    MainProc --> Neo4jAura["Neo4j AuraDB"]

    subgraph OptionalLocalDB["Optional docker-compose service"]
        Neo4jLocal["Local Neo4j community<br/>currently commented out"]
    end
```

## 11. Main Runtime Sequence

```mermaid
sequenceDiagram
    participant User
    participant Main as main_discovery.py
    participant Apollo as ApolloScraper
    participant Smart as SmartScraperAI
    participant Gemini as Gemini API
    participant Persona as persona_search_enrich.py
    participant DB as Neo4jManager
    participant FS as Local files

    User->>Main: Run python main_discovery.py
    Main->>Apollo: search_companies(industry, location, limit)
    Apollo-->>Main: Basic company list

    loop Each company
        Main->>Apollo: enrich_organization(domain, target_location)
        Apollo-->>Main: Enriched Apollo profile or fallback

        alt Valid website URL
            Main->>Smart: scrape_and_save(website_url, target_address)
            Smart->>Gemini: Browser config + extraction + post-processing
            Gemini-->>Smart: Structured JSON
            Smart->>FS: Write *_RAW.txt and *_APOLLO.json
            Smart-->>Main: Path to AI JSON
            Main->>FS: Write merged_profiles/*_MERGED.json
        end

        alt Valid domain
            Main->>Persona: search_and_enrich(domain, country, "Sales")
            Persona-->>Main: Enriched persona list
            Persona->>FS: Write personas_discovered/*_personas.json
        end
    end

    Main->>DB: bulk_import_companies() and/or import_merged_profiles()
    Main->>DB: import_personas()
    DB-->>Main: Import complete
    Main-->>User: Process complete
```

## 12. Notes And Risks

The current project architecture is functional, but there are a few important engineering notes:

| Area | Current State | Recommendation |
|---|---|---|
| Secrets | Several scripts contain hardcoded API keys/credentials | Move all secrets to `.env` and rotate exposed keys |
| Configuration | `TARGET_INDUSTRY`, `TARGET_LOCATION`, and keys are hardcoded in scripts | Centralize config through environment variables or CLI arguments |
| Error handling | Many integrations catch exceptions and continue | Add structured logging and per-provider error reporting |
| Rate limits | Persona cascade calls multiple APIs per result | Add retry/backoff and provider-specific rate-limit controls |
| Data privacy | Persona enrichment stores personal contact data | Add compliance review, retention policy, and access controls |
| Testing | Main pipeline is integration-heavy | Add unit tests for formatting, merge rules, and Neo4j payload preparation |
