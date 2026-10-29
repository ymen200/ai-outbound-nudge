# Inject & Collect - Quick Start Guide

## 🎯 What Is This Project?

**Inject & Collect** is an intelligent company data collection and enrichment system. It automatically finds, analyzes, and stores detailed information about organizations from multiple sources into a unified database.

Think of it as a **smart robot** that:
- 🔍 Finds companies matching your criteria
- 🤖 Visits their websites and extracts key information
- 🧠 Uses AI to understand and verify the data
- 💾 Stores everything in an organized database

---

## 🚀 What Does It Do?

### Input
You provide:
- **Industry** (e.g., "Human Resources")
- **Location** (e.g., "Germany")
- **How many companies** to research

### Process
The system automatically:
1. Searches for matching companies
2. Gathers data from company websites
3. Analyzes financial reports with AI
4. Detects technologies used by the company
5. Merges information from multiple sources
6. Assigns confidence scores to every data point
7. Discovers key personas (decision-makers) from companies
8. Enriches personas with contact information and social profiles

### Output
You get:
- Complete company profiles with:
  - Company name, website, industry
  - Revenue, employee count, funding
  - Contact information (phone, socials)
  - Technologies and tools they use
  - Competitors and market position
  - Fully searchable in a graph database
- Discovered decision-makers (personas) with:
  - Name, title, LinkedIn profile
  - Email addresses and phone numbers
  - Company affiliation
  - Data enriched from multiple sources (Hunter, Snov.io, Tomba, AeroLeads)

---

## 📊 Real-World Example

**Scenario**: You're researching HR tech companies in Germany

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

## ⚡ Quick Start (5 Minutes)

### Step 1: Installation
```bash
# Navigate to project folder
cd c:\Users\aymen\OneDrive\Desktop\inject_collect_project

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configuration
Create a `.env` file with your API keys:
```
APOLLO_API_KEY=your_key_here
GEMINI_API_KEY=your_key_here
NEO4J_URI=your_database_url
NEO4J_USER=your_username
NEO4J_PASSWORD=your_password
```

### Step 3: Run
```bash
python main_discovery.py
```

**That's it!** The system will:
- Search for companies ✅
- Scrape and analyze their websites ✅
- Store results in your database ✅
- Generate organized company profiles ✅

---

## 📁 What Gets Generated?

After running, you'll have:

| Folder | Contains | Format |
|--------|----------|--------|
| `scraped_data/` | Raw website content & API data | `.txt` & `.json` |
| `merged_profiles/` | Final enriched company profiles | `.json` |
| `personas_discovered/` | Discovered key personnel with contacts | `.json` |
| `comparisons/` | Data quality analysis reports | `.json` |

### Example Profile Output
```json
{
  "name": "Example Company",
  "domain": "example.com",
  "industry": "Technology",
  "annual_revenue": "$50 Million",
  "employees": 150,
  "country": "Germany",
  "linkedin": "https://linkedin.com/company/example",
  "technologies": ["React", "Node.js", "AWS"],
  "data_quality_score": 0.92
}
```

---

## 🔧 Key Features (Simple Explanation)

### 1. **Smart Location Detection**
If a company's headquarters is in USA but you want the Germany branch, the system automatically finds and uses the local subsidiary data.

### 2. **AI-Powered Extraction**
Uses Google's Gemini AI to read and understand:
- Website content
- Financial reports (PDF)
- Product descriptions
- Technology stack

### 3. **Confidence Scoring**
Every piece of data comes with a quality score (0-100%):
- ✅ 95% = Very reliable
- 🟡 70% = Needs verification
- ❌ 40% = Uncertain

### 4. **Version Control**
Tracks all changes to company data over time, so you can see what's updated and when.

### 5. **Conflict Resolution**
When multiple sources give different data, the system intelligently decides which version to use based on reliability.

### 6. **Technology Detection**
Automatically identifies what tools companies use:
- Web frameworks (React, Vue.js)
- Databases (PostgreSQL, MongoDB)
- Analytics (Google Analytics, Mixpanel)
- CRM (Salesforce, HubSpot)

### 7. **Persona Discovery & Enrichment**
Extracts decision-makers and key personnel from companies:
- Automatically discovers LinkedIn profiles
- Finds email addresses from multiple sources
- Enriches with phone numbers and verified contacts
- Links personas to their companies
- Maintains contact history and updates

---

## 📈 Who Is This For?

✅ **Sales Teams**: Find and research target accounts + contact decision-makers
✅ **Market Researchers**: Analyze industry trends with company & personnel data
✅ **Investors**: Evaluate company fundamentals and leadership teams
✅ **Competitive Intelligence**: Monitor competitors and key personnel movements
✅ **Data Scientists**: Get clean, structured company and persona data
✅ **Business Development**: Identify partnership opportunities and key contacts
✅ **Recruitment**: Find potential candidates from target companies

---

## 🎮 How It Works (Visual)

```
START
  │
  ├─ Search Phase
  │  ├─ Find companies by industry & location
  │  └─ Get basic Apollo data
  │
  ├─ Scraping Phase
  │  ├─ Visit company website
  │  ├─ Download & read PDF reports
  │  └─ Extract all visible content
  │
  ├─ AI Analysis Phase
  │  ├─ Ask Gemini AI to extract structured data
  │  ├─ Detect technologies used
  │  ├─ Identify revenue & headcount
  │  └─ Assess data quality
  │
  ├─ Merge Phase
  │  ├─ Compare Apollo + AI data
  │  ├─ Keep most reliable version
  │  └─ Create unified profile
  │
  ├─ Persona Discovery Phase
  │  ├─ Search for key decision-makers
  │  ├─ Extract names and LinkedIn profiles
  │  └─ Find email addresses & phone numbers
  │
  ├─ Storage Phase
  │  ├─ Save company profiles to Neo4j database
  │  ├─ Store personas with contact details
  │  ├─ Create versioned snapshots
  │  └─ Link parent/subsidiary relationships
  │
  └─ DONE ✅
     └─ Access searchable profiles & personas
```

---

## 📊 Data Quality Assurance

The system doesn't just grab data—it validates it:

| Data Field | Check | Confidence |
|-----------|-------|-----------|
| Company Name | Confirmed from website | 98% |
| Revenue | Found in report + AI extraction | 85% |
| Employee Count | Estimated from LinkedIn + sources | 72% |
| Address | From contact page + metadata | 91% |
| Technologies | Detected from website code | 99% |

If confidence is low, the system flags it for manual review.

---

## 🔐 Data Privacy & Ethics

✅ **Respects robots.txt** - Follows website guidelines  
✅ **Proper User-Agent** - Identifies as a bot  
✅ **Rate Limiting** - Doesn't overload servers  
✅ **GDPR Compliant** - Handles personal data carefully  
✅ **Transparent** - Clear logging of all actions  

---

## 🛠️ Troubleshooting Basics

### "Nothing is happening"
→ Check `.env` file has all API keys

### "Getting fewer results than expected"
→ Change search filters in `main_discovery.py`
→ Increase `MAX_COMPANIES_TO_GET`

### "Website scraping is slow"
→ That's normal! AI analysis takes time
→ Grab a ☕ while it runs

### "Error: Cannot connect to database"
→ Verify Neo4j connection string
→ Check internet connection

---

## 📚 Customization Options

Want to change what the system searches for?

Open `main_discovery.py` and modify:

```python
# Change the industry
TARGET_INDUSTRY = "human resources"  # → Change to "technology", "finance", etc.

# Change the location
TARGET_LOCATION = "Germany"  # → Change to "United States", "France", etc.

# Change how many companies
MAX_COMPANIES_TO_GET = 2  # → Change to 5, 10, 20, etc.

# Save and run
# python main_discovery.py
```

---

## 🎯 Next Steps

1. **First Run**: Execute with default settings to see how it works
2. **Review Results**: Check the `merged_profiles/` folder for output
3. **Verify Data**: Open a JSON profile and verify it looks correct
4. **Customize**: Adjust `TARGET_INDUSTRY` and `TARGET_LOCATION` for your needs
5. **Scale Up**: Increase `MAX_COMPANIES_TO_GET` once you're comfortable

---

## 📱 Integration Points

This system can integrate with:
- **CRM Systems** (Salesforce, HubSpot) - Feed enriched company data
- **Business Intelligence** (Tableau, Power BI) - Visualize company data
- **Data Warehouses** (Snowflake, BigQuery) - Store profiles at scale
- **Custom APIs** - Build applications on top of data

---

## 💡 Real Business Value

| Use Case | Benefit |
|----------|---------|
| **Sales Prospecting** | 10x faster account research + pre-qualified contacts |
| **Competitive Analysis** | Real-time competitor monitoring with personnel insights |
| **Market Expansion** | Identify high-potential markets and key decision-makers |
| **Partnership Finding** | Discover complementary companies and contact right people |
| **Due Diligence** | Automated company screening with team composition |
| **Trend Analysis** | Spot industry patterns and talent movements |
| **Talent Acquisition** | Identify and research candidates from target companies |

---

## 📞 Need Help?

### Check These Files:
1. **README.md** - Detailed technical documentation
2. **requirements.txt** - List of all dependencies
3. **.env.example** - Template for configuration

### Common Fixes:
- Rerun `playwright install` if browser issues occur
- Update API keys if you get authentication errors
- Clear `scraped_data/` folder if you want fresh results

---

## ⏱️ Processing Time Expectations

| Operation | Duration |
|-----------|----------|
| Search & Find Companies | 5-10 seconds |
| Fetch One Website | 3-5 seconds |
| AI Analysis (Per Company) | 10-30 seconds |
| Database Storage | 2-5 seconds |
| **Total for 2 Companies** | **2-3 minutes** |
| **Total for 10 Companies** | **10-15 minutes** |

---

## 🚀 You're All Set!

Everything is ready to go. Run `python main_discovery.py` and watch as the system automatically:
- 🔍 Finds companies
- 🤖 Analyzes their websites
- 🧠 Extracts structured data
- 💾 Stores organized profiles

**Enjoy your enriched company data!**

---

**Version**: 1.0  
**Last Updated**: April 2026  
**Status**: Ready to Use
