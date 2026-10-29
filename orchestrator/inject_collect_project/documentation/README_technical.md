# Inject & Collect Project - Technical Documentation

## 🎯 Project Overview

**Inject & Collect** is an advanced enterprise data aggregation and enrichment system that combines multiple data sources to create comprehensive company profiles. The system automates the discovery, scraping, AI-powered enrichment, and warehousing of organizational intelligence.

### Key Objectives
- 🔍 **Discover** companies using Apollo.io API with location and industry filters
- 🤖 **Enrich** company data with AI-powered website scraping and analysis
- 📊 **Merge** multi-source data with confidence scoring and conflict resolution
- 💾 **Store** versioned profiles in Neo4j graph database with full audit trail

---

## 🏗️ Architecture Overview

### System Workflow
```
┌─────────────────────────────────────────────────────────────┐
│  Discovery Phase (apollo_scraper.py)                        │
│  - Search companies by industry + location                  │
│  - Enrich with Apollo.io API                                │
│  - Resolve subsidiaries to target locations                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Smart Scraping Phase (smart_scraper_ai.py)                │
│  - Fetch website content with Playwright                    │
│  - Extract technical fingerprints                           │
│  - Smart auto-scrolling for dynamic content                 │
│  - Vision-based PDF financial analysis                      │
│  - Agentic navigation to missing data                       │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  AI Enrichment Phase (smart_scraper_ai.py)                 │
│  - Google Gemini Pro/Flash models                           │
│  - Structured JSON extraction (Apollo schema)               │
│  - Technology stack detection                               │
│  - Confidence scoring for all fields                        │
│  - Automatic data quality assessment                        │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Data Fusion Phase (main_discovery.py)                      │
│  - Merge Apollo + AI data with conflict resolution          │
│  - Apply confidence thresholds (0.8+)                       │
│  - Generate unified company profiles                        │
│  - Save merged profiles to JSON                             │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Persona Discovery Phase (persona_search_enrich.py)        │
│  - Search for key decision-makers on company websites       │
│  - Extract LinkedIn profiles and names                      │
│  - Enrich with multiple data sources                        │
│  - Aggregate contact information                            │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Storage Phase (database_manager.py)                        │
│  - Bulk import company profiles to Neo4j AuraDB             │
│  - Store personas with enriched contact details             │
│  - Version tracking with snapshots                          │
│  - Change detection and archival                            │
│  - Hierarchical relationship mapping                        │
└─────────────────────────────────────────────────────────────┘
```

### Component Breakdown

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| `apollo_scraper.py` | Apollo.io API client | Search + Enrich, double-mapping, subsidiary resolution |
| `smart_scraper_ai.py` | Web scraping + AI extraction | Playwright automation, Gemini integration, vision analysis |
| `persona_search_enrich.py` | Persona discovery & enrichment | Search decision-makers, multi-API enrichment, contact aggregation |
| `database_manager.py` | Neo4j database management | Versioning, change detection, bulk imports, persona storage |
| `main_discovery.py` | Orchestration engine | Coordinates all phases, data fusion, persona discovery, reporting |
| `gemini_models.py` | Model availability checker | Lists available Gemini models |

---

## 📋 System Requirements

### Hardware
- **RAM**: 4GB minimum (8GB+ recommended)
- **Storage**: 2GB minimum (depends on dataset size)
- **Network**: Stable internet connection required

### Software
- **Python**: 3.8+
- **Node.js** (optional): For development tooling
- **Playwright Browsers**: Auto-installed on first run

### External Services
- **Apollo.io** API access (requires API key)
- **Google Generative AI** (Gemini) API access (requires API key)
- **Neo4j AuraDB** instance (cloud or self-hosted)

---

## 🚀 Installation & Setup

### 1. Clone and Initialize
```bash
cd c:\Users\aymen\OneDrive\Desktop\inject_collect_project
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
.\venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

**Core Dependencies:**
- `requests` - HTTP client for Apollo.io API
- `playwright` - Browser automation for web scraping
- `beautifulsoup4` - HTML parsing
- `google-generativeai` - Gemini API client
- `neo4j` - Neo4j driver
- `python-dotenv` - Environment variable management
- `fake-useragent` - User-Agent rotation
- `pillow` - Image processing for vision analysis

### 4. Install Playwright Browsers
```bash
playwright install chromium
```

---

## ⚙️ Configuration

### Environment Variables (.env file)
Create a `.env` file in the project root with:

```env
# Apollo.io API
APOLLO_API_KEY=your_apollo_key_here

# Google Generative AI
GEMINI_API_KEY=your_gemini_api_key_here

# Neo4j AuraDB
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=your_username
NEO4J_PASSWORD=your_password

# Persona Enrichment APIs
SERPER_API_KEY=your_serper_key_here              # Search engine for persona discovery
HUNTER_API_KEY=your_hunter_key_here              # Email finding service
SNOVIO_CLIENT_ID=your_snovio_client_id           # Fallback email search
SNOVIO_CLIENT_SECRET=your_snovio_client_secret
TOMBA_API_KEY=your_tomba_key_here                # Email verification service
TOMBA_API_SECRET=your_tomba_secret_here
AEROLEADS_API_KEY=your_aeroleads_key_here        # LinkedIn & contact enrichment

# Optional: Proxy configuration
HTTP_PROXY=
HTTPS_PROXY=
```

### Model Configuration (smart_scraper_ai.py)

#### Pro-Tier Models (for complex extraction)
```python
PRO_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemma-3-27b-it"
]
```

#### Fast-Tier Models (for lightweight tasks)
```python
FAST_MODELS = [
    "gemini-3.1-flash-lite-preview",
    "gemini-2.0-flash-lite",
    "gemma-3-4b-it"
]
```

### Apollo Schema Mapping

The system extracts data according to the Apollo.io schema with confidence scoring:

```json
{
  "identity": {
    "domain": "Primary website domain",
    "name": "Organization name",
    "industry": "Primary industry classification",
    "founded_year": "Year of establishment"
  },
  "performance": {
    "annual_revenue": "Annual revenue with currency",
    "fiscal_year_end": "FY closure month",
    "estimated_num_employees": "Employee count estimate",
    "total_funding": "Lifetime funding amount"
  },
  "contact_social": {
    "linkedin_url": "LinkedIn organization URL",
    "twitter_url": "Twitter/X handle",
    "facebook_url": "Facebook page",
    "phone": "Contact phone number"
  },
  "location_detailed": {
    "raw_address": "Full address",
    "city": "City",
    "country": "Country"
  },
  "hierarchy": {
    "is_subsidiary": "Is subsidiary entity",
    "parent_company": "Parent organization name",
    "num_suborganizations": "Number of subsidiaries"
  }
}
```

---

## 📖 Usage Guide

### Basic Usage: Single Company Enrichment
```bash
python main_discovery.py
```

### Configuration Parameters (main_discovery.py)
```python
TARGET_INDUSTRY = "human resources"      # Industry filter (Apollo schema)
TARGET_LOCATION = "Germany"              # Geographic focus
MAX_COMPANIES_TO_GET = 2                 # Number of companies to process
CONFIDENCE_THRESHOLD = 0.8               # AI confidence requirement for merge
```

### Advanced: Standalone Components

#### 1. Search Companies via Apollo
```python
from apollo_scraper import ApolloScraper

scraper = ApolloScraper("YOUR_API_KEY")
companies = scraper.search_companies(
    industries=["human resources"],
    locations=["Germany"],
    limit=10
)
```

#### 2. Enrich with Target Location
```python
full_data = scraper.enrich_organization(
    domain="example.com",
    target_location="Germany"  # Resolves subsidiaries
)
```

#### 3. AI-Powered Website Scraping
```python
from smart_scraper_ai import SmartScraperAI

ai_scraper = SmartScraperAI()
json_path = ai_scraper.scrape_and_save(
    url="https://example.com",
    target_address="Berlin, Germany"  # Geographic hint for AI
)
```

#### 4. Merge Apollo + AI Data
```python
from main_discovery import generate_merged_report

generate_merged_report(
    apollo_data=full_data,
    ai_json_path="path/to/ai_output.json",
    output_dir="merged_profiles"
)
```

#### 5. Store in Neo4j
```python
from database_manager import Neo4jManager

db = Neo4jManager()
db.bulk_import_companies(enriched_batch)
db.close()
```

#### 6. Discover & Enrich Personas
```python
from persona_search_enrich import search_and_enrich

# Search for decision-makers at a company
personas = search_and_enrich(
    domain="example.com",
    location="San Francisco",
    role="Sales"  # Target role: Sales, Marketing, Tech, etc.
)

# Returns list with enriched contact information:
# [
#   {
#     "name": "John Smith",
#     "title": "VP of Sales",
#     "linkedin_url": "https://linkedin.com/in/johnsmith",
#     "email": "john@example.com",
#     "phone": "+1-555-0123",
#     "company": "Example Inc."
#   },
#   ...
# ]
```

#### 7. Store Personas in Database
```python
from database_manager import Neo4jManager

db = Neo4jManager()
db.import_personas(personas_list, company_domain="example.com")
db.close()
```

## 📁 Project Structure

```
inject_collect_project/
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── .env                               # Environment configuration (git-ignored)
│
├── Core Scripts
├── apollo_scraper.py                  # Apollo.io API client
├── smart_scraper_ai.py                # Web scraping + Gemini integration
├── persona_search_enrich.py           # Persona discovery & contact enrichment
├── database_manager.py                # Neo4j operations
├── main_discovery.py                  # Orchestration engine
├── gemini_models.py                   # Model availability checker
│
├── Data Directories
├── scraped_data/                      # Raw website content & API responses
│   ├── *_RAW.txt                     # Cleaned HTML text
│   └── *_APOLLO.json                 # Apollo API responses
│
├── merged_profiles/                   # Unified company data
│   └── *_MERGED.json                 # Apollo + AI fusion output
│
├── personas_discovered/               # Discovered key personnel
│   └── *_personas.json               # Personnel data with contact info
│
├── comparisons/                       # Data quality analysis
│   ├── *_COMPARISON.json             # Field-by-field diffs
│   └── *_FULL_REPORT.json            # Complete analysis
│
└── archive/                           # Historical & test data
    ├── test_gemini.py                # Model testing utilities
    ├── bulk_test.py                  # Batch processing examples
    └── companies.csv                 # Sample company dataset
```

---

## 🔌 API Integration Details

### Apollo.io API

**Search Endpoint** (`/v1/organizations/search`)
- **Purpose**: Discover companies by filters
- **Rate Limit**: Depends on plan
- **Request Parameters**:
  - `organization_locations`: List of countries/regions
  - `q_organization_keyword_tags`: Industry keywords
  - `per_page`: Results per page (max 25)

**Enrich Endpoint** (`/v1/organizations/enrich`)
- **Purpose**: Get detailed company profile
- **Rate Limit**: Depends on plan
- **Request Parameters**:
  - `domain`: Company website domain

**Features in This Project**:
- Automatic subsidiary resolution
- Target location filtering
- Multi-location company handling

### Google Generative AI (Gemini)

**Models Used**:
- **Pro-tier**: Gemini 2.5/3-Flash, Gemma-3-27B
  - Used for: Complex data extraction, PDF analysis, financial parsing
  - Latency: 2-5 seconds
  - Cost: Standard pricing

- **Fast-tier**: Gemini 2.0/3.1-Flash-Lite, Gemma-3-4B
  - Used for: Lightweight extraction, link selection, tech detection
  - Latency: <1 second
  - Cost: Lower cost

**Vision Capabilities**:
- PDF financial report extraction
- Table recognition and transscription
- Logo/branding identification

### Neo4j AuraDB

**Connection**: SSL/TLS encrypted (`neo4j+s://` protocol)

**Data Model**:
- **Company Node**: Represents an organization
- **Version Node**: Snapshots of company data with timestamps
- **Persona Node**: Key personnel with contact information
- **Relationships**:
  - `CURRENT`: Points to latest version
  - `ARCHIVED`: Historical versions
  - `OWNS`: Parent-subsidiary relationships
  - `OWNED_BY`: Reverse subsidiary relationship
  - `WORKS_AT`: Links personas to companies
  - `ROLE_IS`: Links personas to their job titles

### Persona Enrichment APIs

**Serper API**
- **Purpose**: Search engine for discovering personas on company websites
- **Usage**: Initial search for decision-makers by role/keyword
- **Rate Limit**: Depends on plan

**Hunter.io**
- **Purpose**: Email finder for discovered personas
- **Usage**: Primary email verification service
- **Rate Limit**: Rate-limited by subscription tier

**Snov.io**
- **Purpose**: Secondary email search and verification
- **Usage**: Fallback when Hunter.io doesn't find results
- **Rate Limit**: OAuth token-based

**Tomba.io**
- **Purpose**: Email verification and data validation
- **Usage**: Verify and enrich email addresses
- **Rate Limit**: API key based
- **Returns**: Email, position, phone number

**AeroLeads**
- **Purpose**: LinkedIn enrichment and phone number extraction
- **Usage**: Deep enrichment with LinkedIn data and contact details
- **Rate Limit**: API key based
- **Returns**: Email, phone, position, LinkedIn profile details

**Enrichment Priority Chain**:
```
Search (Serper) → Hunter → Snov.io → Tomba → AeroLeads
```
Each API is attempted in order; if one fails or returns incomplete data, 
the next one is tried. The system aggregates data from all sources.

---

## 🧠 Key Features

### 1. Two-Phase Discovery
- **Phase 1**: Apollo.io search + enrichment
- **Phase 2**: AI verification + website analysis

### 2. Intelligent Subsidiary Resolution
```
Query: "IBM in Germany"
Result: If main HQ is in USA, automatically finds IBM Germany (subsidiary)
        and extracts local data (revenue, employees, address)
```

### 3. Agentic Navigation
- System identifies missing data fields
- Uses Gemini to select optimal navigation paths
- Automatically revisits relevant pages
- Extracts financial data from reports

### 4. Smart Web Scraping
- **Dynamic content**: Auto-scroll for lazy-loaded pages
- **User-Agent rotation**: Avoids bot detection
- **Technical fingerprinting**: Detects tech stack
  - JavaScript frameworks (React, Next.js)
  - Marketing tools (HubSpot, Marketo)
  - Analytics (Google Analytics, Datadog)
  - Payment processing (Stripe)

### 5. Data Fusion with Confidence Scoring
```
For each field:
- Apollo value + confidence score
- AI value + confidence score
- Merge rule: AI wins if confidence >= 0.8, else Apollo wins
- Result: Single value with source attribution
```

### 6. Versioning & Change Tracking
- Every data update creates a new Version snapshot
- Previous versions archived with timestamps
- Full audit trail: who changed what and when
- Supports time-series analysis

### 7. Persona Discovery & Multi-Source Enrichment
- **Search Phase**: Uses Serper API to find decision-makers on company websites
- **Cascade Enrichment**: Tries multiple email/contact APIs in priority order
  - Hunter.io: Primary email finder
  - Snov.io: Secondary email search with fallback
  - Tomba.io: Email verification
  - AeroLeads: LinkedIn enrichment + phone number extraction
- **Data Aggregation**: Combines data from multiple sources with preference rules
- **Conflict Resolution**: Selects most reliable contact information
- **Storage**: Links personas to companies in Neo4j

## 🔄 Data Processing Flow

### Input Data Format (Apollo Response)
```json
{
  "domain": "example.com",
  "name": "Example Inc.",
  "website_url": "https://example.com",
  "location": {
    "city": "San Francisco",
    "country": "United States"
  },
  "industry": "Technology",
  "annual_revenue": "$100M - $500M"
}
```

### Processing Steps
1. **Validation**: Check required fields
2. **Subsidiary Check**: If multi-national, find target location branch
3. **Website Fetch**: Use Playwright to get full HTML
4. **Content Cleaning**: Convert HTML to semantic pseudo-Markdown
5. **Technical Analysis**: Extract tech stack from headers/scripts/CSS
6. **Vision Analysis**: Parse PDF reports with Gemini Vision
7. **LLM Extraction**: Use Gemini Pro to extract Apollo schema
8. **Quality Scoring**: Assess confidence and completeness
9. **Competitor Detection**: AI infers direct competitors
10. **Data Fusion**: Merge with Apollo results
11. **Database Insert**: Store versioned profile in Neo4j

### Output Data Format (Merged Profile)
```json
{
  "domain": "example.com",
  "name": "Example Inc.",
  "annual_revenue": "$100M - $500M",
  "annual_revenue_USD": 300000000,
  "estimated_num_employees": 500,
  "data_quality_score": 0.92,
  "confidence_summary": {
    "annual_revenue": 0.85,
    "employees": 0.78
  },
  "competitors": ["CompetitorA", "CompetitorB"],
  "technologies": [
    {"name": "React", "confidence": 0.99},
    {"name": "Node.js", "confidence": 0.95}
  ],
  "source": "Apollo + AI Enrichment"
}
```

---

## 📊 Database Schema

### Neo4j Nodes

**Company Node**
```cypher
(:Company {
  domain: "example.com",
  name: "Example Inc.",
  apollo_id: "org_12345"
})
```

**Version Node**
```cypher
(:Version {
  captured_at: datetime(),
  name: "Example Inc.",
  annual_revenue: "$100M - $500M",
  estimated_num_employees: 500,
  technologies: "[...]",  // JSON string
  funding_events: "[...]",
  keywords: ["ai", "startups", "saas"]
})
```

### Relationships
```
Company -[:CURRENT]-> Version (latest snapshot)
Company -[:ARCHIVED]-> Version (historical)
Company -[:OWNS]-> Company (parent has subsidiaries)
Company -[:OWNED_BY]-> Company (subsidiary relationship)
```

---

## 🛠️ Troubleshooting

### Issue: "GEMINI_API_KEY not found"
**Solution**: Ensure `.env` file exists with correct key
```bash
# Check .env file
type .env
```

### Issue: "Apollo Search returns empty results"
**Solutions**:
1. Verify API key and rate limits
2. Check industry/location spelling match Apollo schema
3. Increase `MAX_COMPANIES_TO_GET` for more results

### Issue: "Playwright installation fails"
**Solution**:
```bash
# Force reinstall
pip install --upgrade playwright
playwright install
```

### Issue: "Neo4j connection timeout"
**Solutions**:
1. Verify connection string format: `neo4j+s://instance.databases.neo4j.io`
2. Check firewall allows outbound HTTPS (port 7687)
3. Verify credentials in `.env`

### Issue: "Website scraping returns no content"
**Possible causes**:
- Site blocking Playwright (User-Agent spoofing active)
- JavaScript rendering required (auto-scroll enabled)
- Page requires authentication
- Cloudflare/WAF blocking

**Debug**:
```python
# Check raw HTML
path = ai_scraper.scrape_and_save(url)
with open(f"{path.replace('_APOLLO.json', '_RAW.txt')}", 'r') as f:
    print(f.read()[:500])
```

### Issue: "Data fusion losing information"
**Check merge logic**:
```python
# Confidence threshold settings
CONFIDENCE_THRESHOLD = 0.8  # Increase to favor Apollo data
```

---

## 📈 Performance Optimization

### API Rate Limiting
- Apollo.io: Check your plan's rate limit
- Gemini: Batch requests, use fast models for non-critical data
- Neo4j: Use bulk imports (batch of 100+ records)

### Database Optimization
```cypher
// Create indexes for faster queries
CREATE INDEX FOR (c:Company) ON (c.domain)
CREATE INDEX FOR (v:Version) ON (v.captured_at)
```

### Scraping Optimization
- Reuse playwright context across multiple domains
- Cache HTML snapshots locally before AI processing
- Use fast models for preliminary extraction

---

## 🔐 Security Considerations

### Credential Management
- Never commit `.env` file
- Rotate API keys regularly
- Use environment variables in production

### Data Privacy
- Ensure compliance with data protection regulations (GDPR, CCPA)
- Sanitize logs that may contain sensitive data
- Implement access controls for Neo4j database

### Web Scraping Ethics
- Respect `robots.txt` and Terms of Service
- Implement appropriate delays between requests
- Use proper User-Agent identification
- Avoid overloading target servers

---

## 📝 Logging & Monitoring

### Current Implementation
- Console output with emoji indicators:
  - ✅ Success
  - ❌ Error
  - ⚠️ Warning
  - 🔄 Processing
  - 📊 Data operation

### Recommended Enhancements
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('project.log'),
        logging.StreamHandler()
    ]
)
```

---

## 🚀 Deployment

### Local Execution
```bash
python main_discovery.py
```

### Docker (Future Enhancement)
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main_discovery.py"]
```

### Scheduled Execution (Windows Task Scheduler)
```batch
@echo off
cd C:\Users\aymen\OneDrive\Desktop\inject_collect_project
call venv\Scripts\activate.ps1
python main_discovery.py
```

---

## 📚 Additional Resources

- [Apollo.io API Documentation](https://docs.apollo.io/)
- [Google Generative AI SDK](https://ai.google.dev/tutorials)
- [Neo4j Documentation](https://neo4j.com/docs/)
- [Playwright Documentation](https://playwright.dev/python/)
- [BeautifulSoup Documentation](https://www.crummy.com/software/BeautifulSoup/)

---

## 📄 License & Attribution

This project uses:
- Apollo.io (3rd party API)
- Google Generative AI (3rd party API)
- Neo4j (3rd party database)
- Open-source libraries per `requirements.txt`

---

## 📞 Support & Contribution

For issues, questions, or contributions:
1. Check existing error logs in `.logs/`
2. Verify `.env` configuration
3. Run `gemini_models.py` to confirm API access
4. Test individual components in isolation

---

**Last Updated**: April 2026
**Python Version**: 3.8+
**Status**: Active Development
