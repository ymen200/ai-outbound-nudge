# test_pipeline.py
import os
import sys

# Ensure root workspace directory is visible to Python's import paths
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import json
import logging
from graph.workflow import qualifier_pipeline

# Configure clean logging to monitor execution
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 1. Clean, native Python dictionary maintaining the exact raw data types
AXA_TEST_RECORD = {
    "id": "4:2efebac1-e484-4f28-93ca-ccd8342a9365:268",
    "alexa_ranking": 38580,
    "annual_revenue": 31644000000,
    "apollo_id": "556936c873696421ab590d00",
    "captured_at": "2026-06-14T17:40:57.686000000Z",
    "city": "Nanterre",
    "competitors": '["Allianz France", "Generali France", "Groupama", "Swiss Life France", "CNP Assurances"]',
    "country": "France",
    "continent": "Europe",
    "data_quality_score": 0.94,
    "departments": '{"media_and_commmunication": 18, "sales": 423, "information_technology": 25, "legal": 14, "consulting": 113, "operations": 104, "administrative": 24, "human_resources": 88, "finance": 49, "arts_and_design": 4, "support": 267, "engineering": 24, "data_science": 19, "marketing": 22, "product_management": 5, "accounting": 15, "business_development": 43, "education": 0, "entrepreneurship": 0}',
    "domain": "metro.fr",
    "estimated_num_employees": 9000,
    "fiscal_year_end": "December",
    "founded_year": 1971,
    "full_description": "AXA (Entité Nanterre) is a leading operational hub and technical expertise center for insurance activities, situated in France. As a prominent player in the Assurance et Services Financiers industry, the company leverages cutting-edge technologies such as GIS, .NET, 24-7 Media, AI, and Adobe to drive innovation and excellence. With an estimated 9,000 employees and annual revenue of approximately \u20ac31.644 billion, AXA (Entité Nanterre) plays a significant role in shaping the wholesale distribution landscape in France, with a focus on sustainability, inventory management, and B2B commerce.",
    "funding_events": '[{"id": "693558c29bf5f9000165070a", "date": "2021-01-01T00:00:00.000+00:00", "type": "Other", "amount": "Non renseign\\u00e9", "currency": "$", "investors": "Non renseign\\u00e9"}]',
    "industry": "Assurance et Services Financiers",
    "is_subsidiary": True,
    "keywords": '["commerce de gros & distribution b to b", "sustainability", "wholesale distribution france", "inventory management", "wholesale trade", "procurement", "professional food products", "digital platforms", "business growth", "non-food products", "market leader in france", "e-commerce", "operational efficiency", "digital integration", "b2b foodservice supplies", "services", "quality assurance", "market strategy", "french wholesale market", "logistics and delivery", "retail", "market leader", "general line grocery merchant wholesalers", "food industry logistics", "retail supplies", "product quality", "customer support", "supply chain", "strategic headquarters", "business growth support", "food products", "catering equipment", "business services", "customer support services", "strategic procurement", "product quality assurance", "horeca supplies", "multichannel sales", "digital platform integration", "food industry supplier", "professional customer service", "business partnership", "foodservice solutions", "competitive pricing", "competitive prices", "client support", "wholesale", "foodservice industry", "product range diversity", "independent retailers", "food retail supplies", "wholesale distribution", "b2b", "retail and horeca sector", "retail and horeca logistics", "food safety compliance", "wholesale grocery", "food and beverage retail", "multichannel strategy", "product innovation", "food and beverage wholesale", "business-to-business", "customer service", "b2b food supplies", "supply chain management", "large retail network", "fresh produce", "food safety standards", "logistics", "foodservice distribution", "operational excellence", "professional equipment", "professional kitchen equipment", "food and non-food products", "supply chain logistics", "specialized horeca supplies", "foodservice", "wholesale grocery supplies", "product assortment", "customer-centric services", "supply logistics", "sustainable sourcing", "distribution", "consumer products & retail", "transportation & logistics", "environmental services", "renewables & environment", "consumer internet", "consumers", "internet", "information technology & services", "food & beverage retail", "food & beverages", "consumer goods", "logistics & supply chain", "Assurance", "Gestion d\'actifs", "Nanterre HQ", "AXA France", "Expertise Technique"]',
    "latest_funding_stage": "Publicly Traded",
    "linkedin_url": "http://www.linkedin.com/company/metro-france",
    "logo_url": "https://zenprospect-production.s3.amazonaws.com/uploads/pictures/695e0a898a20160001ca56f0/picture",
    "name": "AXA (Entité Nanterre)",
    "num_suborganizations": 0,
    "parent_company": "AXA Group",
    "phone": "+33 825 09 09 09",
    "postal_code": "92000",
    "raw_address": "5 Rue des Grands-Pres, Nanterre, France",
    "short_description": "Siège opérationnel et centre d'expertise technique pour les activités d'assurance",
    "source": "Merged_Apollo_AI",
    "state": "Ile-de-France",
    "street_address": "5 Rue des Grands-Pres",
    "suborganizations": '[{"id": "Non renseign\\u00e9", "name": "AXA France IARD", "domain": "Non renseign\\u00e9"}, {"id": "Non renseign\\u00e9", "name": "AXA France Vie", "domain": "Non renseign\\u00e9"}, {"id": "Non renseign\\u00e9", "name": "AXA Group Operations", "domain": "Non renseign\\u00e9"}]',
    "technologies": '[{"uid": "gis", "name": ".GIS", "category": "Other"}, {"uid": "net", "name": ".NET", "category": "Frameworks and Programming Languages"}, {"uid": "24-7_media", "name": "24-7 Media", "category": "Ad Servers"}, {"uid": "ai", "name": "AI", "category": "Other"}, {"uid": "adobe", "name": "Adobe", "category": "Content Management Platform"}, {"uid": "akamai", "name": "Akamai", "category": "Content Delivery Networks"}, {"uid": "akamai_dns", "name": "Akamai DNS", "category": "Domain Name Services"}, {"uid": "amazon_cloudwatch", "name": "Amazon CloudWatch", "category": "Analytics and Tracking"}, {"uid": "bootstrap_framework", "name": "Bootstrap Framework", "category": "CSS and JavaScript Libraries"}, {"uid": "canva", "name": "Canva", "category": "Content Management Platform"}, {"uid": "cisco_webex_teams", "name": "Cisco WebEx Teams", "category": "Communication and Collaboration"}, {"uid": "conviva_operational_data_platform", "name": "Conviva Operational Data Platform", "category": "Analytics and Tracking"}, {"uid": "create_react_app", "name": "Create React App", "category": "Frameworks and Programming Languages"}, {"uid": "dax", "name": "DAX", "category": "Business Intelligence"}, {"uid": "dell_tablet", "name": "Dell Tablet", "category": "Other"}, {"uid": "doubleclick", "name": "DoubleClick", "category": "Ad Servers"}, {"uid": "dropbox", "name": "Dropbox", "category": "Cloud Services"}, {"uid": "excel4apps", "name": "Excel4Apps", "category": "Business Intelligence"}, {"uid": "eyefinity_officemate", "name": "Eyefinity OfficeMate", "category": "Appointment Scheduling"}, {"uid": "facebook_web_custom_audiences", "name": "Facebook Custom Audiences", "category": "Retargeting"}, {"uid": "facebook_login", "name": "Facebook Login (Connect)", "category": "Social Login"}, {"uid": "facebook_widget", "name": "Facebook Widget", "category": "Widgets"}, {"uid": "freshdesk", "name": "Freshdesk", "category": "Support and Feedback"}, {"uid": "google", "name": "Google", "category": "Other"}, {"uid": "google_maps", "name": "Google Maps", "category": "Other"}, {"uid": "google_maps_non_paid_users", "name": "Google Maps (Non Paid Users)", "category": "Other"}, {"uid": "google_tag_manager", "name": "Google Tag Manager", "category": "Tag Management"}, {"uid": "jira_service_desk", "name": "Jira Service Desk", "category": "Support and Feedback"}, {"uid": "kiosked", "name": "Kiosked", "category": "Advertising Networks"}, {"uid": "linkedin_ads", "name": "LinkedIn Ads", "category": "Advertising Networks"}, {"uid": "microsoft", "name": "Microsoft Azure Hosting", "category": "Hosting"}, {"uid": "microsoft_office", "name": "Microsoft Office", "category": "Communication and Collaboration"}, {"uid": "office_365", "name": "Microsoft Office 365", "category": "Other"}, {"uid": "microsoft_powerpoint", "name": "Microsoft PowerPoint", "category": "Web Presentation Tools"}, {"uid": "microsoft_teams", "name": "Microsoft Teams", "category": "Communication and Collaboration"}, {"uid": "mobile_friendly", "name": "Mobile Friendly", "category": "Other"}, {"uid": "mysql", "name": "MySQL", "category": "Database"}, {"uid": "odoo", "name": "Odoo", "category": "ERP"}, {"uid": "outlook", "name": "Outlook", "category": "Email Providers"}, {"uid": "power_bi_documenter", "name": "Power BI Documenter", "category": "Analytics and Tracking"}, {"uid": "power_query", "name": "Power Query", "category": "Business Intelligence"}, {"uid": "powerbi_tiles", "name": "PowerBI Tiles", "category": "Analytics and Tracking"}, {"uid": "python", "name": "Python", "category": "Frameworks and Programming Languages"}, {"uid": "remote", "name": "Remote", "category": "Other"}, {"uid": "sap", "name": "SAP", "category": "Customer Relationship Management"}, {"uid": "sap_ariba_platform", "name": "SAP Ariba Platform", "category": "Cloud Services"}, {"uid": "sap_businessobjects_business_intelligence_bi", "name": "SAP BusinessObjects Business Intelligence (BI)", "category": "Analytics and Tracking"}, {"uid": "salesforce crm analytics", "name": "Salesforce CRM Analytics", "category": "Analytics and Tracking"}, {"uid": "secured_mvc_forum_on_windows_2012_r2", "name": "Secured MVC Forum on Windows 2012 R2", "category": "CMS"}, {"uid": "sharepoint", "name": "SharePoint", "category": "CMS"}, {"uid": "sitecore_digital_experience_platform", "name": "Sitecore Digital Experience Platform", "category": "Content Management Platform"}, {"uid": "trustpilot", "name": "Trustpilot", "category": "Customer Reviews"}, {"uid": "viewport_meta", "name": "Viewport Meta", "category": "CSS and JavaScript Libraries"}, {"uid": "weboffice", "name": "WebOffice", "category": "CMS"}, {"uid": "wider_planet", "name": "Wider Planet", "category": "Advertising Networks"}, {"uid": "youtube", "name": "YouTube", "category": "Online Video Platforms"}, {"uid": "recaptcha", "name": "reCAPTCHA", "category": "Captcha"}, {"uid": "unknown_waf_/_security_layer", "name": "Unknown WAF / Security Layer", "category": "Security"}, {"uid": "javascript_standard_library", "name": "JavaScript Standard Library", "category": "Programming Framework"}',
    "twitter_url": "https://twitter.com/axafrance",
    "website_url": "http://www.metro.fr"
}

# 2. Package initial graph state
mock_initial_state = {
    "icp_description_text": (
        "Looking for large enterprise insurance companies, financial services firms, "
        "and banking institutions operating in Europe, particularly France. "
        "Must have more than 5,000 employees and significant infrastructure. "
        "Target roles include Chief Information Security Officers (CISOs), VP of Engineering, "
        "and Directors of IT Infrastructure."
    ),
    "user_offering": "Automated multi-agent security compliance auditing and WAF rule patching for enterprise financial applications.",
    "blacklist": {
        "companies": ["exclude-test-domain.com"],
        "personas": []
    },
    "configurable_weights": {
        "tech_fit": 0.5,
        "size_fit": 0.5
    },
    "campaign_id": "camp_axa_validation_2026",
    "sourced_companies": [AXA_TEST_RECORD],
    "sourced_personas": [],
    "filtered_companies": [],
    "nurture_companies": [],
    "ranked_companies": [],
    "ranked_personas": [],
    "disqualification_log": {
        "total_evaluated": 0,
        "total_passed": 0,
        "total_disqualified": 0,
        "records": [],
        "summary": {}
    }
}

if __name__ == "__main__":
    print("🚀 Invoking LangGraph Pipeline Engine with Clean Data Payload...")
    output_state = qualifier_pipeline.invoke(mock_initial_state)
    print("\n--- 🏁 STATE TRANSITION COMPLETE ---")
    
    # Print out attributes extracted by Node 1
    print("\n[NODE 1] Extracted ICP Structured Outputs:")
    icp = output_state.get("extracted_icp")
    if icp:
        print(f"  • Target Industry Taxonomy: {getattr(icp.must_have, 'industry', 'None')}")
        print(f"  • Target Geographies:       {getattr(icp.must_have, 'target_countries', 'None')}")
        print(f"  • Target Roles Specified:   {getattr(icp, 'target_roles', 'None')}")
    else:
        print("  • Warning: extracted_icp is missing from state context.")

    # Print out attributes normalized by Node 2
    print("\n[NODE 2] Post-Normalization Company Inspection:")
    normalized_companies = output_state.get("sourced_companies", [])
    
    if normalized_companies:
        company = normalized_companies[0]
        print(f"  • Legal Name:         {company.get('name')}")
        print(f"  • Employee Count:     {company.get('estimated_num_employees')} (Casted Type: {type(company.get('estimated_num_employees')).__name__})")
        print(f"  • Annual Revenue:     {company.get('annual_revenue')} (Casted Type: {type(company.get('annual_revenue')).__name__})")
        print(f"  • Raw Industry:       {company.get('industry')}")
        print(f"  • Taxonomical Match:  {company.get('mapped_industry')} (Derived via Contextual Matcher)")
        
        print("\n  • Flattened & Cleaned Tech Stack (Array Output):")
        print(f"    {company.get('tech_stack')}")
        
        print("\n  • Sanitized Funding Array:")
        print(f"    {json.dumps(company.get('funding_events'), indent=2)}")
        
        print("\n  • Sanitized Suborganizations Array:")
        print(f"    {json.dumps(company.get('suborganizations'), indent=2)}")
    else:
        print("  • Error: sourced_companies is empty after node execution.")