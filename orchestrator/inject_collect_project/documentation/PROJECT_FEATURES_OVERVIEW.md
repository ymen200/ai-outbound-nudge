# Inject & Collect - Project Features Overview

## 🎯 Project Purpose
An intelligent company data collection and enrichment system that automatically discovers, analyzes, and stores detailed organizational information from multiple sources into a unified Neo4j database.

---

## 📊 Core Features

### 1. **Intelligent Company Discovery**
- Searches and identifies companies via Apollo.io API
- Filters by industry, location, and size criteria
- Retrieves initial company profiles with basic metadata

### 2. **Website Data Extraction & Analysis**
- Autonomous web scraping using Playwright
- Smart lazy-loading and dynamic content handling
- HTML to pseudo-Markdown conversion for better AI comprehension
- Extracts: company names, descriptions, contact info, social links

### 3. **Advanced Technical Fingerprinting**
- Detects HTTP headers and server information
- Identifies external scripts and CDN sources
- Recognizes technologies in use (React, Next.js, Shopify, HubSpot, etc.)
- Analyzes CSS patterns and JavaScript global objects
- Maintains signature database for 17+ popular tools and services

### 4. **AI-Powered Data Extraction & Enrichment**
- Uses Google Gemini models (pro and lite tiers with fallback)
- Extracts structured company data with confidence scoring
- Automatically handles retries and model unavailability
- Validates data against multiple model capabilities
- Returns confidence-scored JSON for every extracted field

### 5. **Financial Data Intelligence**
- Automated PDF detection and download from company websites
- Smart scanning of financial reports and annual statements
- Vision AI for decoding complex financial tables
- Extracts: annual revenue, fiscal year end, funding information
- Handles multiple currencies and regional subsidiaries

### 6. **Data Quality & Explainability (XAI)**
- Assigns confidence scores (0.0-1.0) to every data point
- Tracks evidence sources with exact citations
- Injects XAI metrics: faithfulness, calibration, evidence density
- Generates Data Quality Score (DQS) for profile completeness
- Verifies AI claims against raw text to ensure accuracy

### 7. **Data Merging & Conflict Resolution**
- Intelligently merges Apollo API data with AI-extracted information
- Threshold-based field replacement (AI only replaces if confidence ≥ 0.8)
- Consolidates lists (technologies, funding events, subsidiaries) via union
- Preserves exclusive attributes from both sources
- Recalculates DQS after merging for final profile quality

### 8. **Persona Discovery & Enrichment**
- Automated extraction of decision-makers and key personnel from company websites
- LinkedIn profile detection and recovery
- Multi-source contact enrichment:
  - **Hunter.io** - Email finder and position verification
  - **Snov.io** - Email discovery fallback
  - **Tomba.io** - Advanced email, position, and phone recovery
  - **AeroLeads** - LinkedIn-based enrichment
  - **Serper** - Web search for additional personas

### 9. **Persistent Storage & Querying**
- Neo4j graph database integration
- Stores company profiles with all relationships
- Enables complex queries: revenue range, technology stack, location, etc.
- Supports time-series tracking of company data changes
- Linkage between companies and discovered personas

### 10. **Comparison & Analysis Reports**
- Generates side-by-side competitor comparisons
- Produces full company reports with all enriched data
- Quality metrics and data provenance documentation
- Exportable JSON and structured output formats

---

## 🤖 SmartScraperAI Module - Core Capabilities

### Overview
The `smart_scraper_ai.py` module is the **intelligent data extraction engine** of the system. It orchestrates AI-powered analysis of website content and financial data to extract structured company information with confidence scoring.

### Key Components

#### 1. **Model Management System**
```
PRO_MODELS (Complex Analysis):
- gemini-3-flash-preview
- gemini-2.5-flash
- gemini-2.0-flash
- gemini-flash-latest

FAST_MODELS (Quick Tasks):
- gemini-3.1-flash-lite-preview
- gemini-2.0-flash-lite
- gemini-flash-lite-latest
```
- Automatic fallback when models are unavailable (503, 429, overloaded)
- Smart tier selection based on task complexity
- Handles rate limiting and resource exhaustion gracefully

#### 2. **Smart Content Extraction**
- **HTML Cleaning**: Removes noise (scripts, styles, navigation, iframes)
- **Pseudo-Markdown Conversion**: Converts HTML structure to readable format
- **Text Normalization**: Consolidates whitespace, removes artifacts
- **Semantic Preservation**: Maintains document structure for better AI comprehension

#### 3. **Technical Fingerprinting Engine**
- Analyzes HTTP response headers for server/framework info
- Extracts external script sources and CDNs
- Inspects JavaScript global objects and window scope
- Detects CSS patterns and naming conventions
- Maintains 17+ technology signatures (HubSpot, WordPress, Salesforce, Stripe, etc.)
- Returns confidence-scored technology list

#### 4. **Financial Data Smart-Scan**
- **PDF Download & Processing**: Handles financial reports via URL
- **Intelligent Page Detection**: Identifies financially relevant pages (balance sheets, income statements, key figures)
- **Dual-Path Extraction**:
  - Clean text pages: Direct text extraction
  - Complex/visual pages: Vision AI decoding of tables and charts
- **Data Enrichment**: Recognizes currencies, fiscal years, and regional variations
- **In-Memory Processing**: No temporary files, direct stream handling

#### 5. **Vision AI for Table Analysis**
- Specialized vision model for financial table interpretation
- Transcribes financial tables to structured text
- Extracts revenue, dates, and key metrics from images
- Falls back gracefully when image analysis unavailable

#### 6. **XAI (Explainable AI) Metrics Injection**
Embeds verifiability metrics into every extracted field:

**Faithfulness Score**: Verifies extracted source actually appears in raw text (0 or 1)

**Calibration Error**: Measures deviation between claimed confidence and actual text similarity

**Evidence Density**: Calculates ratio of extracted value length to source evidence length

- Enables transparent, auditable data extraction
- Supports downstream validation and quality control
- Provides regression detection for model performance

#### 7. **Intelligent Retry & Error Handling**
- Exponential backoff strategy for transient failures
- Automatic model switching on unavailability
- Configurable retry limits with detailed logging
- Preserves operation context through failures

#### 8. **Dynamic Page Navigation**
- **Smart Scrolling**: Auto-scroll with lazy-loading detection
- **Missing Field Targeting**: AI-driven link selection to find incomplete data
- **Recursive Navigation**: Follows internal links to gather more information
- **Seen URL Tracking**: Prevents duplicate processing

#### 9. **JSON Apollo Schema Compliance**
Generates structured output matching Apollo.io schema:
- **Identity** (domain, name, industry, founding, descriptions)
- **Performance** (revenue, fiscal year, funding, employees, stage)
- **Contact/Social** (LinkedIn, Twitter, Facebook, phone)
- **Hierarchy** (subsidiary status, parent, suborganizations)
- **Location** (address, city, country - region-aware)
- **Technologies** (categorized with confidence)
- **Funding Events** (dates, types, amounts)
- **Keywords** (business domain tags)

#### 10. **Confidence-Scored Output**
Every extracted field includes:
```json
{
  "field_name": {
    "value": "extracted_data",
    "confidence": 0.85,
    "source": "exact_citation_from_text"
  }
}
```
- Enables quality thresholding in downstream processes
- Identifies fields requiring manual verification
- Tracks data provenance for audit trails

---

## 🔄 Integration Points

### With Other Modules:
- **apollo_scraper.py**: Provides initial company list
- **database_manager.py**: Stores enriched profiles
- **persona_search_enrich.py**: Leverages extracted contact data
- **main_discovery.py**: Orchestrates the full pipeline

### External APIs:
- **Google Gemini API**: AI model access
- **Playwright**: Browser automation
- **BeautifulSoup**: HTML parsing
- **PyMuPDF (fitz)**: PDF processing
- **PIL**: Image handling for vision AI

---

## 📈 Data Flow

```
1. Apollo Discovery → Initial company list
2. SmartScraperAI → Website analysis + financial PDF processing
3. Data Merging → Conflict resolution & confidence-based validation
4. Persona Discovery → Extract decision-makers from content
5. Contact Enrichment → Multi-API persona enrichment
6. Neo4j Storage → Persist unified profiles and relationships
7. Report Generation → Comparisons and quality analysis
```

---

## 💡 Key Strengths

- **Confidence-Based**: Every data point is scored for reliability
- **Multi-Source**: Combines APIs, web scraping, and AI analysis
- **Adaptive**: Handles failures gracefully with fallbacks
- **Explainable**: Tracks evidence and sources for verification
- **Scalable**: Processes multiple companies sequentially
- **Regional Awareness**: Distinguishes between global HQ and local subsidiaries
- **Tech Detection**: Automatically discovers tools and platforms in use
- **Financial Intelligence**: Extracts and interprets financial data from PDFs

---

## 📦 Output Artifacts

- `scraped_data/` → Raw website content and API responses
- `merged_profiles/` → Final enriched company profiles (JSON)
- `personas_discovered/` → Key personnel with contact details
- `comparisons/` → Competitive analysis and quality reports

