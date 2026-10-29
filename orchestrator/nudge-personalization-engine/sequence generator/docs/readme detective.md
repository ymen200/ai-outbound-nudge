# 🕵️ Detective - ICP-Based Company Targeting with LangGraph

A comprehensive LLM-powered pipeline for Ideal Customer Profile (ICP) extraction, company matching, intent signal collection, and persona ranking. Built with **LangGraph** for robust state management and orchestration.

## 🌟 Key Features

- **🎯 ICP Extraction**: LLM-powered extraction of target industries, company sizes, countries, and roles from natural language ICP descriptions
- **🏢 Company Matching**: Intelligent matching of companies against ICP criteria using Groq LLM
- **📍 Geo-Filtering**: City-based proximity filtering using OpenRouteService API (optional)
- **📊 Intent Collection**: MCP server integration for collecting funding, partnerships, and news signals
- **📈 Similarity Ranking**: Gemini embeddings-based ranking of companies by ICP similarity
- **⭐ Final Scoring**: Combined similarity + intent boost scoring
- **👤 Persona Ranking**: LLM-based scoring and selection of target personas per company
- **🔄 LangGraph Orchestration**: State-managed pipeline with conditional branching and error handling

## 🏗️ Architecture

### 6-Step LangGraph Pipeline

```
┌─────────────────┐
│  STEP 1:       │
│  Extract ICP   │  → Extract industries, sizes, countries, roles
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 2:       │
│  Match Companies│  → LLM-based industry matching
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 2b:      │
│  Geo Filter     │  → City proximity (optional, requires ORS_API_KEY)
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 3:       │
│  Collect Intent │  → MCP server for funding/news/partnerships
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 4:       │
│  Filter & Rank  │  → Employee count, country filter + similarity ranking
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 5:       │
│  Final Scoring  │  → Similarity + intent boost
└────────┬────────┘
         ↓
┌─────────────────┐
│  STEP 6:       │
│  Rank Personas  │  → LLM-based persona selection
└─────────────────┘
```

## 📁 Project Structure

```
detective/
├── main.py                     # Entry point - calls LangGraph pipeline
├── detective_graph.py          # LangGraph pipeline definition (6 nodes)
├── brain/                      # LLM agents for ICP and matching
│   ├── icp_agent.py           # ICP extraction agent
│   ├── company_matcher.py     # Company matching agent
│   ├── geo_agent.py           # Geo-filtering agent (OpenRouteService)
│   └── __init__.py
├── ranking/                    # Ranking and scoring modules
│   ├── company_ranker.py      # Similarity ranking with embeddings
│   ├── company_filter.py      # Employee/country filtering
│   ├── final_scorer.py        # Intent boost scoring
│   ├── persona_ranker.py     # LLM-based persona selection
│   └── __init__.py
├── requirements.txt           # Dependencies
├── .env                       # Environment variables
└── README.md                  # This file
```

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Activate virtual environment
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Keys

Create/edit `.env` file:

```env
# Required: Groq API for LLM operations
GROQ_API_KEY=your_groq_api_key_here

# Optional: OpenRouteService for geo-filtering
ORS_API_KEY=your_ors_api_key_here

# Model configuration (optional)
GROQ_MODEL=llama-3.1-8b-instant
GROQ_TEMPERATURE=0.1
```

Get API keys:
- **Groq**: https://console.groq.com/
- **OpenRouteService**: https://openrouteservice.org/

### 3. Run the Pipeline

```bash
python main.py
```

The pipeline will:
1. Extract ICP from the example text in `main.py`
2. Match companies from `../inject_collect_project/merged_profiles/`
3. Collect intent signals via MCP server
4. Filter, rank, and score companies
5. Select target personas per company
6. Output comprehensive results

## 📋 Pipeline Steps Explained

### STEP 1: ICP Extraction (`node_extract_icp`)

**Purpose**: Parse natural language ICP description into structured attributes

**Input**: Raw ICP text (e.g., "I want IT companies with 50-500 employees...")

**Output**: `ICPAttributes` with:
- `industry`: List of target industries (e.g., ["IT", "SaaS"])
- `company_size`: Min/max employee count
- `revenue_range`: Min/max revenue
- `target_countries`: List of countries
- `target_roles`: List of job roles to target
- `dynamic_attributes`: Tech stack, funding stage, etc.

**LLM Model**: `llama-3.1-8b-instant`

**Output File**: `{output_name}_icp.json`

### STEP 2: Company Matching (`node_match_companies`)

**Purpose**: Find companies matching ICP industries

**Process**:
1. Load all company profiles from `merged_profiles/`
2. For each company, use LLM to check industry match
3. Return companies with match confidence > 0.5

**Output**: `matched_companies_{output_name}/` folder with `_MATCHED.json` files

**LLM Model**: `llama-3.1-8b-instant`

### STEP 2b: Geo-Filtering (`node_geo_filter`) - Optional

**Purpose**: Filter companies by city proximity

**Requirements**: `ORS_API_KEY` in `.env`

**Process**:
1. Parse city from ICP text
2. Geocode city to lat/lon using OpenRouteService
3. Calculate driving distance to each company
4. Keep companies within specified range (default 100km)

**Output**: Geo-filtered company dictionary

**Note**: Skips if no ORS_API_KEY or no city specified

### STEP 3: Intent Collection (`node_collect_intent`)

**Purpose**: Collect buying intent signals via MCP server

**MCP Server**: `../agentic_intent/mcp_server/mcp_server.py`

**Tools Available**:
- `search_company_funding`: Funding rounds and investment data
- `search_company_news`: Recent news and press releases
- `search_company_partnerships`: Partnership announcements
- `retrieve_company_intent`: Combined intent score

**Process**:
1. Start MCP server subprocess
2. Connect via stdio transport
3. For each company, call funding/news/partnership tools
4. LLM extracts structured intent signals
5. Save to `../agentic_intent/output/intent_results.json`

**Output**: Intent data for final scoring boost

**Note**: Requires `agentic_intent` module. Falls back to saved company list if rate limited.

### STEP 4: Filter & Rank (`node_filter_and_rank`)

**Purpose**: Apply ICP criteria filters and rank by similarity

**Sub-steps**:

#### 4a. Company Filtering (`CompanyFilter`)
- **Employee Filter**: Keep companies within min/max employee range
- **Country Filter**: Keep companies in target countries

#### 4b. Similarity Ranking (`CompanyRanker`)
- Embed ICP text using Gemini embeddings
- Embed each company profile
- Calculate cosine similarity
- Rank by similarity score

**Output Files**:
- `ranking/{output_name}_filtered_ranking.json`
- `ranking/{output_name}_filtered_ranking_detailed.json`

### STEP 5: Final Scoring (`node_final_scoring`)

**Purpose**: Combine similarity scores with intent signals

**Formula**:
```
Final Score = Similarity Score + (Intent Score × Intent Boost)
```

Where:
- `Similarity Score`: From embedding cosine similarity (0-1)
- `Intent Score`: Calculated from funding/news confidence
- `Intent Boost`: 0.05 (5% max boost)

**Intent Score Calculation**:
- High confidence funding (>0.7): +0.05
- High confidence news (>0.7): +0.03
- Multiple signals: Additional boost

**Output File**: `ranking/{output_name}_final_ranking.json`

### STEP 6: Persona Ranking (`node_rank_personas`)

**Purpose**: Select the best target persona per company

**Process**:
1. Load personas from `../inject_collect_project/personas_discovered/`
2. For each company, score all personas with LLM:
   - **Seniority Score**: Based on job level (0-1)
   - **Department Score**: Sales=1.0, CEO=0.9, Other=0.5
   - **Role Match Score**: Match against ICP target roles (0-1)
   - **Final Score**: Weighted combination
3. Select highest scoring persona
4. Fallback: If no sales persona, select CEO/Founder

**Scoring Weights**:
- Department: 30%
- Seniority: 50%
- Role Match: 20%

**LLM Model**: `llama-3.1-8b-instant`

**Output File**: `ranking/{output_name}_personas.json`

## 📊 Output Files

### Generated Files

| File | Description |
|------|-------------|
| `{name}_icp.json` | Extracted ICP attributes |
| `matched_companies_{name}/` | Industry-matched company profiles |
| `ranking/{name}_filtered_ranking.json` | Post-filter similarity rankings |
| `ranking/{name}_final_ranking.json` | Final scores with intent boost |
| `ranking/{name}_personas.json` | Selected personas per company |
| `brain.log` | Detailed execution logs |
| `matched_companies_for_intent.json` | Fallback company list for manual intent |

### Persona Output Format

```json
{
  "icp_description": "...",
  "timestamp": "...",
  "results": [
    {
      "company_key": "bosch_us",
      "company_name": "Bosch in the USA",
      "company_rank": 1,
      "company_final_score": 0.706,
      "selected_persona": {
        "full_name": "Jessica Katterheinrich",
        "job_title": "Sales Manager",
        "email": "jessica.katterheinrich@bosch.com",
        "linkedin_url": "...",
        "city": "Detroit",
        "country": "United States"
      },
      "persona_score": {
        "final_score": 0.93,
        "is_sales": true,
        "is_ceo": false,
        "reasoning": "As a Sales Manager..."
      },
      "target_roles_matched": ["Sales Manager", "CTO", "Heads of Product"]
    }
  ]
}
```

## 🛠️ Modules Reference

### `brain/` - LLM Agents

#### `ICPExtractionAgent`
- **Method**: `extract_icp_attributes(icp_text: str) -> ICPAttributes`
- **Purpose**: Parse natural language to structured ICP

#### `CompanyMatcher`
- **Method**: `find_matching_companies(industries: List[str]) -> Dict`
- **Purpose**: LLM-based industry matching

#### `GeoAgent`
- **Method**: `filter_companies_by_proximity(companies, city, country, range_km)`
- **Purpose**: City-based proximity filtering
- **API**: OpenRouteService

### `ranking/` - Scoring & Ranking

#### `CompanyRanker`
- **Method**: `rank_companies(companies_folder) -> List[Dict]`
- **Embedding**: Gemini (`models/embedding-001`)
- **Metric**: Cosine similarity

#### `CompanyFilter`
- **Methods**: `filter_by_employees()`, `filter_by_country()`
- **Purpose**: ICP criteria filtering

#### `FinalScorer`
- **Method**: `calculate_final_scores(ranking_file, intent_file)`
- **Boost**: Intent signals add up to 5% to similarity score

#### `PersonaRanker`
- **Method**: `rank_personas_for_companies(companies, target_roles)`
- **LLM Scoring**: Seniority, department, role match
- **Selection**: Best persona per company with sales priority

## ⚙️ Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | ✅ Yes | Groq API for LLM operations |
| `ORS_API_KEY` | ❌ No | OpenRouteService for geo-filtering |
| `GROQ_MODEL` | ❌ No | Model name (default: llama-3.1-8b-instant) |
| `GROQ_TEMPERATURE` | ❌ No | LLM temperature (default: 0.1) |

### ICP Text Format

Edit the ICP text in `main.py`:

```python
example_icp = """
I want IT companies with 50-500 employees and annual revenue between $10M - $100M.
Target companies should be in United States, Canada, United Kingdom, and Germany.

We want to connect with Sales Managers, CTOs, and Heads of Product.

Must-have traits:
- Using modern tech stack (React, Python, AWS)
- In growth stage with Series B or C funding
- Product-led growth model

Exclude:
- Consulting companies
- Digital marketing agencies
"""
```

## 🐛 Troubleshooting

### Common Issues

#### 1. "No module named 'graph.funding_graph'"
**Cause**: Naming conflict with `graph.py`
**Fix**: Renamed to `detective_graph.py` - pull latest code

#### 2. Groq Rate Limit (429 errors)
**Cause**: Daily token limit (100,000 tokens)
**Fix**: 
- Wait ~5-15 minutes for rate limit reset
- Use cheaper model: `llama-3.1-8b-instant` (already default)
- Upgrade Groq account

#### 3. "ORS_API_KEY not found"
**Cause**: Geo-filtering requires API key
**Fix**: Add `ORS_API_KEY` to `.env` or disable geo-filtering

#### 4. MCP Server Connection Failed
**Cause**: `agentic_intent` module not found
**Fix**: Ensure `../agentic_intent/` exists and has `mcp_server/mcp_server.py`

#### 5. No Personas Found
**Cause**: Company doesn't have persona file in `personas_discovered/`
**Note**: This is expected - not all companies have personas

### Debug Mode

Enable detailed logging:

```python
# In main.py or graph.py
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## 📈 Performance Tips

1. **Use cheaper models** for company matching to save tokens
2. **Run intent collection separately** if rate limited:
   ```bash
   cd ../agentic_intent
   python main.py
   ```
3. **Cache embeddings** by reusing `ranking/` JSON files
4. **Filter early** - geo-filter before LLM matching to reduce API calls

## 🔗 Integration with Other Modules

### `inject_collect_project/`
- **Input**: `merged_profiles/` - Company profiles
- **Input**: `personas_discovered/` - Persona JSON files

### `agentic_intent/`
- **MCP Server**: Provides intent collection tools
- **Output**: `output/intent_results.json` - Intent signals

## 📚 Dependencies

```
langgraph>=0.0.50
groq>=0.5.0
google-generativeai>=0.5.4
requests>=2.31.0
pydantic>=2.5.3
python-dotenv>=1.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
```

## 📝 Changelog

### v2.0 - LangGraph Migration
- ✅ Migrated from procedural to LangGraph orchestration
- ✅ Added 6-step state-managed pipeline
- ✅ Added intent collection with MCP server
- ✅ Added geo-filtering with OpenRouteService
- ✅ Added persona ranking with LLM scoring
- ✅ Added final scoring with intent boost

### v1.0 - Initial Release
- Basic ICP extraction
- LLM-based company matching

## 🤝 Contributing

This is part of the `outbound_project` ecosystem. Coordinate changes with:
- `inject_collect_project/` - Data source
- `agentic_intent/` - Intent collection
- `personalized_outbound/` - Email generation (future)

## 📄 License

Part of the outbound_project - follows same licensing terms.
