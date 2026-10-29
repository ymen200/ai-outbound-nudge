# 🔍 Inject & Collect

**An intelligent company data collection and enrichment system that automatically discovers, analyzes, and stores detailed organizational information from multiple sources into a unified Neo4j database.**

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

---

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [API Integrations](#api-integrations)
- [Database Setup](#database-setup)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

**Inject & Collect** is an enterprise-grade data aggregation platform that combines multiple intelligence sources to create comprehensive company profiles with verified data. The system automates:

- 🔍 **Company Discovery** via Apollo.io API
- 🤖 **Intelligent Web Scraping** with Playwright
- 🧠 **AI-Powered Data Extraction** using Google Gemini
- 📊 **Financial Report Analysis** with Vision AI
- 👥 **Persona Discovery & Enrichment** from multiple sources
- 💾 **Graph Database Storage** with Neo4j
- 📈 **Data Quality Scoring** with explainability metrics

Think of it as a **smart robot** that finds companies matching your criteria, visits their websites, analyzes financial reports, detects their tech stack, discovers key decision-makers, and enriches all data with contact information—all automatically.

---

## ✨ Key Features

### 1. **Intelligent Company Discovery**
- Search and identify companies via Apollo.io API
- Filter by industry, location, and size criteria
- Retrieve initial company profiles with rich metadata
- Resolve subsidiaries to target locations

### 2. **Advanced Web Scraping & Analysis**
- Autonomous web scraping using Playwright
- Smart lazy-loading and dynamic content handling
- HTML to pseudo-Markdown conversion for AI comprehension
- Automatic cookie/popup handling
- Extracts company names, descriptions, contact info, social links

### 3. **Technical Fingerprinting**
- HTTP headers and server information detection
- External scripts and CDN source identification
- Technology stack recognition (React, Next.js, Shopify, HubSpot, etc.)
- CSS patterns and JavaScript global object analysis
- Signature database for 17+ popular tools and services

### 4. **AI-Powered Data Extraction & Enrichment**
- Multiple Google Gemini models (Pro and Lite tiers with fallback)
- Structured company data extraction with confidence scoring
- Automatic retries and model unavailability handling
- Data validation across multiple model capabilities
- Confidence-scored JSON for every extracted field

### 5. **Financial Data Intelligence**
- Automated PDF detection and download from company websites
- Smart scanning of financial reports and annual statements
- Vision AI for decoding complex financial tables
- Extracts: annual revenue, fiscal year end, funding information
- Handles multiple currencies and regional subsidiaries

### 6. **Data Quality & Explainability (XAI)**
- Confidence scores (0.0-1.0) for every data point
- Evidence sources tracked with exact citations
- XAI metrics: faithfulness, calibration, evidence density
- Data Quality Score (DQS) for profile completeness
- AI claims verified against raw text for accuracy

### 7. **Intelligent Data Merging**
- Merges Apollo API data with AI-extracted information
- Threshold-based field replacement (AI replaces if confidence ≥ 0.8)
- Consolidates lists (technologies, funding, subsidiaries) via union
- Preserves exclusive attributes from both sources
- Recalculates DQS after merging

### 8. **Persona Discovery & Enrichment**
- Automated extraction of decision-makers from company websites
- LinkedIn profile detection and recovery
- Multi-source contact enrichment:
  - **Hunter.io** - Email finder and position verification
  - **Snov.io** - Email discovery fallback
  - **Tomba.io** - Advanced email, position, and phone recovery
  - **AeroLeads** - LinkedIn-based enrichment
  - **Serper** - Web search for additional personas

### 9. **Graph Database Integration**
- Neo4j integration for persistent storage
- Complex querying capabilities (revenue range, tech stack, location)
- Time-series tracking of company data changes
- Linkage between companies and discovered personas
- Version control with full audit trail

### 10. **Reporting & Analysis**
- Side-by-side competitor comparisons
- Comprehensive company reports with enriched data
- Quality metrics and data provenance documentation
- Exportable JSON and structured output formats

---

## 🏗️ Architecture

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
│  - Bulk import company profiles to Neo4j                    │
│  - Store personas with enriched contact details             │
│  - Version tracking with snapshots                          │
│  - Change detection and archival                            │
│  - Hierarchical relationship mapping                        │
└─────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Purpose | Key Features |
|-----------|---------|--------------|
| `apollo_scraper.py` | Apollo.io API client | Company search, enrichment, subsidiary resolution |
| `smart_scraper_ai.py` | Web scraping + AI extraction | Playwright automation, Gemini integration, vision analysis |
| `persona_search_enrich.py` | Persona discovery & enrichment | Decision-maker extraction, multi-API enrichment |
| `database_manager.py` | Neo4j database management | Versioning, change detection, bulk imports |
| `main_discovery.py` | Orchestration engine | Coordinates all phases, data fusion, reporting |
| `Intent_search.py` | Intent signal detection | Identifies buying/growth signals from web data |
| `intent_signals_scraper.py` | Intent data aggregation | Collects intent signals from multiple sources |

---

## 📋 Prerequisites

### System Requirements
- **Python**: 3.8 or higher
- **RAM**: 4GB minimum (8GB+ recommended)
- **Storage**: 2GB minimum (depends on dataset size)
- **Network**: Stable internet connection

### External Services & API Keys
You'll need accounts and API keys for:

1. **Apollo.io** - Company discovery and enrichment
2. **Google Generative AI (Gemini)** - AI-powered data extraction
3. **Neo4j AuraDB** - Graph database (cloud or self-hosted)
4. **Hunter.io** *(optional)* - Email discovery
5. **Snov.io** *(optional)* - Email enrichment
6. **Tomba.io** *(optional)* - Advanced email/phone recovery
7. **AeroLeads** *(optional)* - LinkedIn enrichment
8. **Serper** *(optional)* - Web search for personas

---

## 🚀 Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/yourusername/inject-collect.git
cd inject-collect
```

### Step 2: Create Virtual Environment
```bash
# On Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# On macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

This will install:
- `httpx` - HTTP client for API calls
- `playwright` - Browser automation
- `google-generativeai` - Google Gemini API
- `neo4j` - Neo4j database driver
- `python-dotenv` - Environment variable management
- `openai` - OpenAI client (for LLM fallback)
- And other required dependencies

### Step 4: Install Playwright Browsers
```bash
playwright install chromium
```

---

## ⚙️ Configuration

### Create `.env` File

Create a `.env` file in the project root directory with your API keys:

```env
# Apollo.io API
APOLLO_API_KEY=your_apollo_api_key_here

# Google Gemini AI
GEMINI_API_KEY=your_gemini_api_key_here

# Neo4j Database
NEO4J_URI=neo4j+s://your-auradb-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password

# Optional: Contact Enrichment APIs
HUNTER_API_KEY=your_hunter_io_key
SNOV_API_KEY=your_snov_io_key
TOMBA_API_KEY=your_tomba_io_key
AEROLEADS_API_KEY=your_aeroleads_key
SERPER_API_KEY=your_serper_api_key

# Optional: LLM Fallback (Token Factory / ESPRIT)
ESPRIT_TOKEN_FACTORY_KEY=your_token_factory_key
```

### API Key Setup Instructions

#### Apollo.io
1. Sign up at [https://apollo.io](https://apollo.io)
2. Navigate to Settings → API Keys
3. Generate a new API key
4. Copy to `.env`

#### Google Gemini API
1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Click "Get API Key"
3. Create a new API key
4. Copy to `.env`

#### Neo4j AuraDB
1. Create account at [https://neo4j.com/cloud/aura/](https://neo4j.com/cloud/aura/)
2. Create a new database instance
3. Copy connection URI and credentials to `.env`

---

## 💻 Usage

### Basic Usage

#### 1. Run Company Discovery Pipeline
```bash
python main_discovery.py
```

This will:
- Discover companies matching your criteria
- Scrape and analyze their websites
- Extract financial data
- Enrich profiles with AI
- Store everything in Neo4j
- Discover and enrich personas

#### 2. Discover Companies by Apollo.io
```bash
from apollo_scraper import ApolloScraper

scraper = ApolloScraper(api_key="your_key")
companies = scraper.search_companies(
    industry="HR Tech",
    location="Germany",
    company_size=["11-50", "51-200"]
)
```

#### 3. Scrape and Enrich a Company Website
```bash
from smart_scraper_ai import SmartScraperAI

scraper = SmartScraperAI()
company_data = scraper.extract_company_data(
    website_url="https://example.com",
    company_name="Example Corp"
)
```

#### 4. Store Companies in Neo4j
```bash
from database_manager import Neo4jManager

db = Neo4jManager(
    uri="neo4j+s://your-instance.databases.neo4j.io",
    username="neo4j",
    password="password"
)
db.bulk_import_companies(company_profiles)
```

#### 5. Search and Enrich Personas
```bash
from persona_search_enrich import search_and_enrich

personas = search_and_enrich(
    company_url="https://example.com",
    company_name="Example Corp"
)
```

### Advanced Usage Examples

#### Generate Competitor Comparison
```bash
python -c "
from database_manager import Neo4jManager
db = Neo4jManager('uri', 'user', 'pass')
comparison = db.compare_companies(['Company1', 'Company2'])
print(comparison)
"
```

#### Query Companies by Technology Stack
```bash
python -c "
from database_manager import Neo4jManager
db = Neo4jManager('uri', 'user', 'pass')
results = db.query('MATCH (c:Company) WHERE c.technologies CONTAINS \"React\" RETURN c')
for company in results:
    print(company['name'])
"
```

#### Export Company Profiles
```bash
import json
from database_manager import Neo4jManager

db = Neo4jManager('uri', 'user', 'pass')
companies = db.get_all_companies()

with open('export.json', 'w') as f:
    json.dump(companies, f, indent=2)
```

---

## 📁 Project Structure

```
inject_collect_project/
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── Dockerfile                          # Docker containerization
├── docker-compose.yml                  # Docker Compose configuration
│
├── # Core Modules
├── main_discovery.py                   # Orchestration engine
├── apollo_scraper.py                   # Apollo.io integration
├── smart_scraper_ai.py                 # Web scraping + AI extraction
├── persona_search_enrich.py            # Persona discovery & enrichment
├── database_manager.py                 # Neo4j database management
├── Intent_search.py                    # Intent signal detection
├── intent_signals_scraper.py           # Intent data aggregation
├── apify_leads_tester.py               # Apify integration testing
│
├── # Supporting Modules
├── gemini_test/                        # Gemini model testing
│   ├── model_test.py
│   └── gemini_models.py
│
├── # Documentation
├── documentation/
│   ├── PROJECT_FEATURES_OVERVIEW.md    # Detailed feature documentation
│   ├── README_HighLevel.md             # High-level project overview
│   ├── README_technical.md             # Technical documentation
│   ├── ARCHITECTURE_DIAGRAM.md         # System architecture
│   ├── ACTIVITY_DIAGRAM.md             # Activity flow diagram
│   ├── DIAGRAMME_SEQUENCE.md           # Sequence diagrams
│   ├── API_COST_TIME_ANALYSIS.md       # Cost and performance analysis
│   ├── STRUCTURE_BASE_DONNEES.md       # Database structure
│   └── AGENTIC_ARCHITECTURE_DIAGRAM.md # Agentic workflow diagram
│
├── # Output Directories
├── merged_profiles/                    # Merged company profiles (JSON)
├── personas_discovered/                # Extracted personas
├── intent_results/                     # Intent signal analysis results
├── intent_signals_data/                # Raw intent signal data
├── scraped_data/                       # Raw website scraping data
├── comparisons/                        # Competitor comparisons
├── reuslat_execution/                  # Execution results
│
├── # Archive & Testing
└── archive/                            # Old scripts and test files
    ├── bulk_test.py
    ├── test_*.py                       # Various API test scripts
    └── companies.csv                   # Sample company data
```

---

## 🔌 API Integrations

### Supported Data Sources

| API | Purpose | Priority | Status |
|-----|---------|----------|--------|
| **Apollo.io** | Company discovery and enrichment | Primary | ✅ Active |
| **Google Gemini** | AI-powered data extraction | Primary | ✅ Active |
| **Neo4j** | Graph database storage | Primary | ✅ Active |
| **Hunter.io** | Email discovery | Secondary | ✅ Active |
| **Snov.io** | Email enrichment | Secondary | ✅ Active |
| **Tomba.io** | Email/phone recovery | Secondary | ✅ Active |
| **AeroLeads** | LinkedIn enrichment | Tertiary | ✅ Active |
| **Serper** | Web search | Tertiary | ✅ Active |

### Data Quality & Fallback Strategy

The system implements intelligent fallback mechanisms:

1. **Model Fallback**: Uses Gemini Pro/Flash with automatic fallback to Lite versions
2. **API Fallback**: Multiple email discovery sources (Hunter → Snov → Tomba)
3. **Data Validation**: Confidence scoring prevents low-quality data storage
4. **Error Handling**: Automatic retries with exponential backoff

---

## 💾 Database Setup

### Neo4j AuraDB Setup

1. **Create Account**
   ```
   Visit: https://neo4j.com/cloud/aura/
   Sign up and create a free instance
   ```

2. **Create Database**
   - Instance name: `inject-collect`
   - DBMS: Neo4j 5.x (or latest)

3. **Get Connection Details**
   - Copy URI from dashboard
   - Note username (default: `neo4j`)
   - Set secure password

4. **Update `.env`**
   ```env
   NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=your_password
   ```

5. **Initialize Database** *(Optional)*
   ```bash
   python -c "
   from database_manager import Neo4jManager
   db = Neo4jManager('uri', 'user', 'pass')
   db.create_constraints()  # Set up indexes
   "
   ```

### Database Schema

**Nodes:**
- `Company` - Stores company profiles with all enriched data
- `Persona` - Stores decision-makers and key personnel
- `Technology` - Tech stack items
- `Location` - Geographic locations
- `Funding` - Funding events

**Relationships:**
- `USES_TECHNOLOGY` - Company uses technology
- `LOCATED_IN` - Company location
- `HAS_SUBSIDIARY` - Parent/subsidiary relationships
- `WORKS_AT` - Persona employed at company
- `RECEIVED_FUNDING` - Company received funding

---

## 🐳 Docker Deployment

### Build Docker Image
```bash
docker build -t inject-collect:latest .
```

### Run with Docker Compose
```bash
docker-compose up -d
```

This will:
- Start Python application
- Initialize Playwright
- Connect to Neo4j (update DB connection in docker-compose.yml)

### Environment Configuration
Update `docker-compose.yml` with your API keys:
```yaml
environment:
  APOLLO_API_KEY: ${APOLLO_API_KEY}
  GEMINI_API_KEY: ${GEMINI_API_KEY}
  NEO4J_URI: ${NEO4J_URI}
  # ... other keys
```

---

## 📊 Real-World Example

**Scenario**: Researching HR Tech companies in Germany

**System performs**:
```
1. Finds 10 HR companies in Germany (Apollo Search)
2. For each company:
   - Visits website and extracts content
   - Reads PDF annual reports (if available)
   - Identifies tech stack (React, Node.js, etc.)
   - Extracts revenue, headcount, address
   - Finds LinkedIn, Twitter, Facebook profiles
   - Calculates data accuracy (0-100%)
   - Discovers key decision-makers from company website
   - Enriches personas with email and phone contacts
3. Creates unified profiles
4. Stores in searchable database
```

**You can now**:
- Query all HR companies with $100M+ revenue
- Find companies using specific technologies
- Compare competitors side-by-side
- Track company data changes over time
- Find and contact decision-makers by role/title
- Export persona lists with enriched contact data

---

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

### Code Style
- Use Python 3.8+ features
- Follow PEP 8 naming conventions
- Add type hints to functions
- Include docstrings for all functions

### Testing
- Test changes locally before submitting
- Update relevant documentation
- Ensure all APIs are working with your keys

### Pull Request Process
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request with clear description

### Reporting Issues
- Check existing issues first
- Include detailed reproduction steps
- Provide API response examples (without keys!)
- Include Python version and OS information

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🆘 Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'playwright'`
```bash
# Solution: Install playwright and browsers
pip install playwright
playwright install chromium
```

**Issue**: `Neo4j Connection Failed`
```bash
# Solution: Verify credentials in .env
# Check URI format: neo4j+s://host:port
# Verify username and password
```

**Issue**: `Gemini API Rate Limit Exceeded`
```bash
# Solution: Add delays between requests or upgrade API quota
# System has automatic retry logic with exponential backoff
```

**Issue**: `Playwright timeout during scraping`
```bash
# Solution: Increase timeout or check target website availability
# Some websites may require additional delay time
```

---

## 📞 Support

- 📧 **Email**: your-email@example.com
- 🐛 **Issues**: [GitHub Issues](https://github.com/yourusername/inject-collect/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/yourusername/inject-collect/discussions)

---

## 🙏 Acknowledgments

- **Apollo.io** - Company database and discovery API
- **Google Gemini** - Advanced AI models for data extraction
- **Neo4j** - Graph database platform
- **Playwright** - Browser automation framework

---

**Made with ❤️ for B2B data intelligence**
