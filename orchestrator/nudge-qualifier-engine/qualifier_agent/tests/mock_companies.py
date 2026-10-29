"""
mock_companies.py
──────────────────
Mock raw company data for testing the Strategic Qualifier pipeline.

Shape matches real Apollo-style raw records (see AXA example), including:
  - stringified JSON fields (technologies, competitors, keywords, funding_events)
    exactly as they appear in real raw data, so normalize_company_data_node's
    JSON-parsing/regex-fallback logic gets properly exercised.
  - intent_signals.job_offers and intent_signals.news — two distinct signal
    types consumed by evaluate_company_intent() in scoring.py.

These are designed to fit a test ICP like:
    "We sell fraud-detection software to mid-size insurance companies in
    France and Germany, 100-2000 employees."

3 companies, each tuned to land in a different bucket:
  1. ASSURELIA   — strong fit, strong intent signals -> should score high (Tier A)
  2. NORDVIE      — fits ICP but weak/no intent signals -> should land lower (Tier B/C)
  3. GAMBLEX      — wrong industry (gambling, excluded) -> should be gated out in Node 3
"""

MOCK_COMPANIES = [
    # ── 1. ASSURELIA — strong firmographic + strong intent signals ─────────
    {
        "name": "Assurelia",
        "apollo_id": "mock_apollo_001",
        "domain": "assurelia.fr",
        "website_url": "http://www.assurelia.fr",
        "industry": "Assurance et Services Financiers",
        "estimated_num_employees": 850,
        "annual_revenue": 62000000,
        "founded_year": 2009,
        "city": "Paris",
        "country": "France",
        "state": "Ile-de-France",
        "latest_funding_stage": "Series C",
        "funding_events": (
            '[{"id": "fund_001", "date": "2026-03-15T00:00:00.000+00:00", '
            '"type": "Series C", "amount": "45000000", "currency": "EUR", '
            '"investors": "Eurazeo, Partech"}]'
        ),
        "is_subsidiary": False,
        "parent_company": None,
        "suborganizations": "[]",
        "full_description": (
            "Assurelia is a mid-size insurance provider based in Paris, "
            "specializing in property and casualty coverage for SMEs across "
            "France. The company has been rapidly modernizing its claims "
            "processing infrastructure and is investing heavily in fraud "
            "prevention and risk-scoring capabilities to handle its growing "
            "policyholder base."
        ),
        "short_description": "Mid-size French insurer specializing in SME P&C coverage.",
        "keywords": (
            '["insurance", "claims processing", "fraud prevention", '
            '"risk scoring", "SME insurance", "property and casualty", '
            '"digital transformation", "underwriting", "France insurance market"]'
        ),
        "competitors": '["MAIF", "Matmut", "Groupama", "AXA France"]',
        "departments": (
            '{"information_technology": 62, "sales": 140, "operations": 210, '
            '"finance": 38, "legal": 22, "data_science": 14, "customer_support": 95}'
        ),
        "tech_stack": (
            '[{"name": "Python", "category": "Frameworks and Programming Languages"}, '
            '{"name": "AWS", "category": "Hosting"}, '
            '{"name": "Salesforce", "category": "Customer Relationship Management"}, '
            '{"name": "Tableau", "category": "Business Intelligence"}, '
            '{"name": "PostgreSQL", "category": "Database"}]'
        ),
        "linkedin_url": "http://www.linkedin.com/company/assurelia",
        "data_quality_score": 0.91,
        "intent_signals": {
            "job_offers": [
                {
                    "title": "Senior Fraud Risk Analyst",
                    "department": "Risk & Compliance",
                    "posted_date": "2026-05-20T00:00:00.000+00:00",
                    "description": (
                        "We are looking for a Senior Fraud Risk Analyst to help "
                        "build out our next-generation claims fraud detection "
                        "pipeline, working closely with our data science team "
                        "to reduce false-claim payouts."
                    ),
                },
                {
                    "title": "Data Engineer - Claims Platform",
                    "department": "Engineering",
                    "posted_date": "2026-06-01T00:00:00.000+00:00",
                    "description": (
                        "Join our claims platform team to build real-time "
                        "data pipelines feeding our risk-scoring and fraud "
                        "detection models."
                    ),
                },
            ],
            "news": [
                {
                    "headline": "Assurelia announces partnership to modernize claims fraud detection",
                    "published_date": "2026-05-28T00:00:00.000+00:00",
                    "summary": (
                        "Assurelia revealed a new initiative to deploy AI-driven "
                        "fraud detection across its claims processing operations, "
                        "citing a sharp rise in fraudulent claims volume over the "
                        "past fiscal year."
                    ),
                },
                {
                    "headline": "Assurelia closes Series C to accelerate digital claims transformation",
                    "published_date": "2026-03-16T00:00:00.000+00:00",
                    "summary": (
                        "The Paris-based insurer raised 45M EUR to expand its "
                        "underwriting technology stack and risk management "
                        "capabilities."
                    ),
                },
            ],
        },
    },

    # ── 2. NORDVIE — fits ICP firmographically, but weak intent signals ────
    {
        "name": "NordVie Assurance",
        "apollo_id": "mock_apollo_002",
        "domain": "nordvie.de",
        "website_url": "http://www.nordvie.de",
        "industry": "Versicherung",  # German for "Insurance" — exercises taxonomy mapping
        "estimated_num_employees": 1400,
        "annual_revenue": 78000000,
        "founded_year": 1998,
        "city": "Hamburg",
        "country": "Germany",
        "state": "Hamburg",
        "latest_funding_stage": "Publicly Traded",
        "funding_events": "non renseigné",  # exercises null-placeholder cleanup
        "is_subsidiary": False,
        "parent_company": None,
        "suborganizations": "[]",
        "full_description": (
            "NordVie Assurance is a long-established life and health insurance "
            "provider headquartered in Hamburg, serving customers across "
            "northern Germany. The company has a stable, traditional operating "
            "model with limited recent public activity around technology "
            "modernization."
        ),
        "short_description": "Established German life and health insurer.",
        "keywords": '["life insurance", "health insurance", "Germany", "traditional insurer"]',
        "competitors": '["Allianz", "ERGO", "HUK-Coburg"]',
        "departments": '{"sales": 310, "operations": 480, "finance": 90, "legal": 40}',
        "tech_stack": '[{"name": "SAP", "category": "Customer Relationship Management"}, {"name": "Microsoft Office", "category": "Communication and Collaboration"}]',
        "linkedin_url": "http://www.linkedin.com/company/nordvie",
        "data_quality_score": 0.86,
        "intent_signals": {
            "job_offers": [],  # no active hiring signals at all
            "news": [
                {
                    "headline": "NordVie reports stable Q1 results in line with expectations",
                    "published_date": "2025-11-02T00:00:00.000+00:00",  # >180 days old, will be filtered
                    "summary": "NordVie's quarterly results showed steady performance with no major strategic changes announced.",
                }
            ],
        },
    },

    # ── 3. GAMBLEX — should be gated out in Node 3 (excluded industry) ─────
    {
        "name": "Gamblex Entertainment",
        "apollo_id": "mock_apollo_003",
        "domain": "gamblex.com",
        "website_url": "http://www.gamblex.com",
        "industry": "Gambling",
        "estimated_num_employees": 600,
        "annual_revenue": 40000000,
        "founded_year": 2015,
        "city": "Berlin",
        "country": "Germany",
        "state": "Berlin",
        "latest_funding_stage": "Series B",
        "funding_events": "[]",
        "is_subsidiary": False,
        "parent_company": None,
        "suborganizations": "[]",
        "full_description": (
            "Gamblex Entertainment operates a network of online gaming and "
            "betting platforms across Europe, offering sports betting, "
            "casino games, and poker to a growing user base."
        ),
        "short_description": "Online gambling and betting platform operator.",
        "keywords": '["online gambling", "sports betting", "casino", "poker", "iGaming"]',
        "competitors": '["Bet365", "Betclic", "Winamax"]',
        "departments": '{"sales": 80, "operations": 120, "engineering": 95}',
        "tech_stack": '[{"name": "AWS", "category": "Hosting"}, {"name": "React", "category": "Frameworks and Programming Languages"}]',
        "linkedin_url": "http://www.linkedin.com/company/gamblex",
        "data_quality_score": 0.79,
        "intent_signals": {
            "job_offers": [
                {
                    "title": "Fraud Prevention Specialist",
                    "department": "Trust & Safety",
                    "posted_date": "2026-06-10T00:00:00.000+00:00",
                    "description": "Help us detect fraudulent betting patterns across our platforms.",
                }
            ],
            "news": [],
        },
    },
]