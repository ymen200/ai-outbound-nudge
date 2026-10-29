# Database Structure

The project uses **Neo4j**, which means the database is a **graph database**, not a traditional relational SQL database.

The main database logic is implemented in `database_manager.py`, inside the `Neo4jManager` class.

## Database Type

- Database: **Neo4j AuraDB**
- Python driver: `neo4j.GraphDatabase`
- Main database file: `database_manager.py`
- Main injection pipeline: `main_discovery.py`

The connection is created with:

```python
GraphDatabase.driver(uri, auth=(user, password))
```

## Global Graph Overview

```text
(:Company)-[:CURRENT]->(:Version)
(:Company)-[:ARCHIVED]->(:Version)

(:Company)-[:OWNS]->(:Company)
(:Company)-[:OWNED_BY]->(:Company)

(:Persona)-[:WORKS_AT]->(:Company)

(:Company)-[:HAS_INTENT_SIGNAL]->(:IntentSignal)
(:Version)-[:DETECTED_INTENT]->(:IntentSignal)
```

The model is organized around four main node types:

- `Company`: the stable identity of a company.
- `Version`: a detailed historical snapshot of company data.
- `Persona`: a person or contact linked to a company.
- `IntentSignal`: a dated and sourced business intent signal detected for a company.

## Company Node

The `Company` node represents an organization.

It is created or matched with:

```cypher
MERGE (c:Company {domain: safe_domain})
```

### Main Fields

```text
domain
uid
name
apollo_id
```

### Field Description

| Field | Description |
| --- | --- |
| `domain` | Main company identifier. Example: `alten.es`. |
| `uid` | Internal identifier. Usually equal to `apollo_id` or the company domain. |
| `name` | Company name. |
| `apollo_id` | Identifier returned by Apollo. |

### Example

```json
{
  "domain": "alten.es",
  "uid": "601033c2c51abe011a0a7771",
  "name": "ALTEN Spain",
  "apollo_id": "601033c2c51abe011a0a7771"
}
```

### Handling Missing Domains

If a company has no valid domain, the code generates a safe artificial domain to avoid collisions:

```text
unknown_<company_name>_<country>
```

Example:

```text
unknown_example_company_france
```

## Version Node

The `Version` node represents a detailed snapshot of a company's data at a specific point in time.

A company can have:

- one current version through `CURRENT`
- multiple historical versions through `ARCHIVED`

### Related Relationships

```text
(:Company)-[:CURRENT]->(:Version)
(:Company)-[:ARCHIVED]->(:Version)
```

### Main Fields

```text
captured_at
last_verified_at
source

name
industry
founded_year
logo_url
website_url
short_description
seo_description

alexa_ranking
annual_revenue
total_funding
estimated_num_employees
latest_funding_stage
data_quality_score

linkedin_url
twitter_url
facebook_url
crunchbase_url
phone

raw_address
street_address
city
state
postal_code
country

num_suborganizations
owned_by_organization_id
is_subsidiary
parent_company

technologies
departments
funding_events
suborganizations
keywords
competitors
```

### Field Groups

| Group | Fields |
| --- | --- |
| Versioning | `captured_at`, `last_verified_at`, `source` |
| Identity | `name`, `industry`, `founded_year`, `logo_url`, `website_url` |
| Description | `short_description`, `seo_description`, `keywords` |
| Performance | `alexa_ranking`, `annual_revenue`, `total_funding`, `estimated_num_employees`, `latest_funding_stage`, `data_quality_score` |
| Contact/social | `linkedin_url`, `twitter_url`, `facebook_url`, `crunchbase_url`, `phone` |
| Location | `raw_address`, `street_address`, `city`, `state`, `postal_code`, `country` |
| Hierarchy | `num_suborganizations`, `owned_by_organization_id`, `is_subsidiary`, `parent_company`, `suborganizations` |
| Enriched data | `technologies`, `departments`, `funding_events`, `competitors` |

### Complex Fields Serialized As JSON

Neo4j does not directly accept nested dictionaries or complex lists as node properties. The code serializes some fields into JSON strings before insertion.

Fields concerned:

```text
departments
funding_events
suborganizations
technologies
competitors
keywords
```

### Example

```json
{
  "name": "ALTEN Spain",
  "domain": "alten.es",
  "industry": "Engineering and IT Services",
  "country": "Spain",
  "city": "Madrid",
  "annual_revenue": 369360000,
  "estimated_num_employees": "5500",
  "linkedin_url": "http://www.linkedin.com/company/alten-spain",
  "website_url": "http://www.alten.es",
  "data_quality_score": 0.98
}
```

## Persona Node

The `Persona` node represents a discovered person or contact linked to a company.

It is created or matched with:

```cypher
MERGE (p:Persona {
  linkedin_url: COALESCE(p_data.linkedin_url, p_data.full_name + '_' + $domain)
})
```

### Main Identifier

```text
linkedin_url
```

If the LinkedIn URL is missing, the code uses:

```text
full_name + "_" + company_domain
```

### Possible Fields

```text
full_name
clean_name_used
raw_name_from_google
linkedin_url
company
email
title
phone
source
last_updated

education
experience
skills
emails
aeroleads_raw_data
interests
```

### Complex Fields Serialized As JSON

```text
education
experience
skills
emails
aeroleads_raw_data
interests
```

### Example

```json
{
  "clean_name_used": "Fernando Perez Gomez",
  "linkedin_url": "https://es.linkedin.com/in/fernandoperezgomez",
  "company": "Alten",
  "email": "Not found",
  "title": "Not found",
  "phone": "Not found",
  "source": "Serper"
}
```

## IntentSignal Node

The `IntentSignal` node represents a business intent detected for a company.

This should be stored as a separate node, not as a simple property on `Company`.

Intent is usually:

- time-based
- source-based
- confidence-based
- repeated over time
- multi-valued for the same company

For example, the same company can have several intent signals:

- hiring
- market expansion
- cloud migration
- ERP modernization
- new office opening
- technology adoption
- funding or acquisition activity
- demand for sales, IT, marketing, or engineering profiles

### Recommended Relationship

```text
(:Company)-[:HAS_INTENT_SIGNAL]->(:IntentSignal)
```

This is the main relationship to use.

### Optional Relationship To Version

```text
(:Version)-[:DETECTED_INTENT]->(:IntentSignal)
```

This optional relationship is useful when you want to know in which company snapshot the intent was detected.

### Why Intent Should Be A Separate Node

Storing intent directly on `Company` as a property like this:

```text
company.intent = "hiring"
```

is too limited.

It loses important information:

- multiple intent signals for the same company
- detection dates
- source URLs
- confidence scores
- evidence text
- history over time
- expiration or validity period
- filtering by intent type or category

Using a separate `IntentSignal` node keeps the model scalable and queryable.

### Main Fields

```text
id
type
category
signal
description
confidence
relevance_score
source
source_url
detected_at
valid_until
country
raw_evidence
status
created_at
last_verified_at
```

### Field Description

| Field | Description |
| --- | --- |
| `id` | Unique identifier for the signal. |
| `type` | High-level intent type, such as `hiring`, `expansion`, `technology_adoption`, `funding`, `partnership`. |
| `category` | More precise business category. Example: `sales_expansion`, `cloud_migration`, `erp_modernization`. |
| `signal` | Short human-readable signal. |
| `description` | Detailed explanation of the detected intent. |
| `confidence` | Confidence score between `0` and `1`. |
| `relevance_score` | Business relevance score between `0` and `1`. |
| `source` | Source type, such as `job_posting`, `company_website`, `news`, `linkedin`, `intent_scraper`. |
| `source_url` | URL where the signal was detected. |
| `detected_at` | Date/time when the signal was detected. |
| `valid_until` | Optional expiration date for the signal. |
| `country` | Country or market related to the signal. |
| `raw_evidence` | Evidence text or extracted snippet supporting the signal. |
| `status` | Suggested lifecycle status, such as `active`, `expired`, `archived`, `dismissed`. |
| `created_at` | Date/time when the node was created in Neo4j. |
| `last_verified_at` | Last time the signal was checked again. |

### Example

```json
{
  "id": "alten_es_hiring_sales_2026_06_13",
  "type": "hiring",
  "category": "sales_expansion",
  "signal": "ALTEN Spain is recruiting sales profiles",
  "description": "Job postings indicate an intent to strengthen the sales team in Spain.",
  "confidence": 0.84,
  "relevance_score": 0.9,
  "source": "job_posting",
  "source_url": "https://www.alten.es/careers",
  "detected_at": "2026-06-13T00:00:00",
  "valid_until": "2026-09-13T00:00:00",
  "country": "Spain",
  "raw_evidence": "Extracted text proving that sales hiring is active.",
  "status": "active"
}
```

### Recommended Cypher Pattern

```cypher
MATCH (c:Company {domain: $domain})
MERGE (i:IntentSignal {id: $intent_id})
SET i += $intent_data,
    i.last_verified_at = datetime()
MERGE (c)-[:HAS_INTENT_SIGNAL]->(i)
```

If the signal is linked to the current version:

```cypher
MATCH (c:Company {domain: $domain})-[:CURRENT]->(v:Version)
MATCH (i:IntentSignal {id: $intent_id})
MERGE (v)-[:DETECTED_INTENT]->(i)
```

## Relationships

## CURRENT Relationship

```text
(:Company)-[:CURRENT]->(:Version)
```

This relationship points to the active and most recent version of a company profile.

When a company is imported for the first time, a new `Version` is created and linked with `CURRENT`.

## ARCHIVED Relationship

```text
(:Company)-[:ARCHIVED]->(:Version)
```

This relationship keeps historical versions of company data.

When company data changes:

```text
1. The old CURRENT relationship is deleted.
2. The old Version is linked with ARCHIVED.
3. A new Version is created.
4. The new Version becomes CURRENT.
```

## OWNS Relationship

```text
(:Company)-[:OWNS]->(:Company)
```

This relationship indicates that one company owns another company.

Example:

```text
ALTEN Group -[:OWNS]-> ALTEN Spain
```

## OWNED_BY Relationship

```text
(:Company)-[:OWNED_BY]->(:Company)
```

Reverse relationship of `OWNS`.

Example:

```text
ALTEN Spain -[:OWNED_BY]-> ALTEN Group
```

## WORKS_AT Relationship

```text
(:Persona)-[:WORKS_AT]->(:Company)
```

This relationship indicates that a persona works at a company.

Example:

```text
Fernando Perez Gomez -[:WORKS_AT]-> ALTEN Spain
```

## HAS_INTENT_SIGNAL Relationship

```text
(:Company)-[:HAS_INTENT_SIGNAL]->(:IntentSignal)
```

This relationship links a company to one or more detected intent signals.

Example:

```text
ALTEN Spain -[:HAS_INTENT_SIGNAL]-> Hiring sales profiles in Spain
```

## DETECTED_INTENT Relationship

```text
(:Version)-[:DETECTED_INTENT]->(:IntentSignal)
```

This optional relationship links a company snapshot to the intent signals detected during that snapshot.

It is useful for auditing and historical analysis.

## Summary Schema

```text
Company
- domain
- uid
- name
- apollo_id

Version
- captured_at
- source
- name
- industry
- website_url
- linkedin_url
- phone
- country
- city
- annual_revenue
- estimated_num_employees
- technologies
- funding_events
- departments
- keywords
- competitors
- data_quality_score

Persona
- linkedin_url
- full_name / clean_name_used
- company
- email
- title
- phone
- source
- last_updated

IntentSignal
- id
- type
- category
- signal
- description
- confidence
- relevance_score
- source
- source_url
- detected_at
- valid_until
- country
- raw_evidence
- status
```

## Logical Schema

```text
Company
  |
  | CURRENT
  v
Current Version

Company
  |
  | ARCHIVED
  v
Historical Versions

Persona
  |
  | WORKS_AT
  v
Company

Parent Company
  |
  | OWNS
  v
Child Company

Company
  |
  | HAS_INTENT_SIGNAL
  v
IntentSignal

Version
  |
  | DETECTED_INTENT
  v
IntentSignal
```

## Complete Graph Example

```text
(:Company {name: "ALTEN Group"})
    -[:OWNS]->
(:Company {name: "ALTEN Spain", domain: "alten.es"})
    -[:CURRENT]->
(:Version {
    industry: "Engineering and IT Services",
    country: "Spain",
    city: "Madrid",
    annual_revenue: 369360000,
    estimated_num_employees: "5500"
})

(:Persona {
    clean_name_used: "Fernando Perez Gomez",
    linkedin_url: "https://es.linkedin.com/in/fernandoperezgomez"
})
    -[:WORKS_AT]->
(:Company {domain: "alten.es"})

(:Company {domain: "alten.es"})
    -[:HAS_INTENT_SIGNAL]->
(:IntentSignal {
    type: "hiring",
    category: "sales_expansion",
    signal: "ALTEN Spain is recruiting sales profiles",
    confidence: 0.84,
    source: "job_posting",
    detected_at: "2026-06-13T00:00:00",
    status: "active"
})
```

## Example Queries

Find all companies with active hiring intent:

```cypher
MATCH (c:Company)-[:HAS_INTENT_SIGNAL]->(i:IntentSignal)
WHERE i.type = "hiring" AND i.status = "active"
RETURN c.name, c.domain, i.signal, i.confidence, i.source_url
ORDER BY i.confidence DESC
```

Find all intent signals for one company:

```cypher
MATCH (c:Company {domain: "alten.es"})-[:HAS_INTENT_SIGNAL]->(i:IntentSignal)
RETURN i.type, i.category, i.signal, i.detected_at, i.confidence
ORDER BY i.detected_at DESC
```

Find intent signals detected in the current version:

```cypher
MATCH (c:Company)-[:CURRENT]->(v:Version)-[:DETECTED_INTENT]->(i:IntentSignal)
RETURN c.name, v.captured_at, i.type, i.signal
```

## Final Summary

The Neo4j database is designed to store:

- companies discovered through Apollo and enriched by AI
- successive versions of each company profile
- personas and contacts linked to companies
- company hierarchy relationships
- historical changes through `CURRENT` and `ARCHIVED`
- business intent signals through `IntentSignal`

The core model is:

```text
Company -> Version
Persona -> Company
Company -> Company
Company -> IntentSignal
Version -> IntentSignal
```
