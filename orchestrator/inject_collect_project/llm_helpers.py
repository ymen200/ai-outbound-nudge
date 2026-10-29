"""
LangChain helpers for LLM *prompt quality* (templates + structured invoke).

Does NOT add orchestration graphs — LangGraph already owns that.
Keeps the existing ESPRIT / Groq router in llm_provider.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from llm_provider import get_llm_client, get_llm_model

# ---------------------------------------------------------------------------
# ChatPromptTemplates (system + user) — one task = one template
# ---------------------------------------------------------------------------

COMPANY_FULL_DESCRIPTION = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert B2B data enrichment engineer. Your goal is to write a "
            "comprehensive, professional, and impactful company description in English "
            "based on raw data points. Do not include any introductory or concluding "
            "remarks like 'Here is the description'.",
        ),
        (
            "human",
            "Write a complete, detailed, and highly professional corporate overview "
            "(full_description) in English for '{name}'.\n"
            "Synthesize all the following raw attributes into a natural, cohesive "
            "paragraph (4 to 7 sentences maximum).\n"
            "Do not just list the facts; weave them together to present the company's "
            "scale, market position, and technological footprint.\n\n"
            "--- Raw Data Profile ---\n"
            "[Identity & Web]\n"
            "- Company Name: {name}\n"
            "- Domain / Website: {domain} / {website_url}\n"
            "- Industry: {industry}\n"
            "- Founded Year: {founded_year}\n"
            "- Headquarters: {city}, {country}\n\n"
            "[Performance & Scale]\n"
            "- Estimated Annual Revenue: {revenue}\n"
            "- Estimated Employees: {employees}\n"
            "- Total Funding & Stage: {total_funding} ({funding_stage})\n"
            "- Web Popularity (Alexa Ranking): {alexa_ranking}\n"
            "- Major Departments (Headcount): {deps_str}\n\n"
            "[Market & Technology]\n"
            "- Short Description: {short_desc}\n"
            "- SEO Description: {seo_desc}\n"
            "- Top Industry Keywords: {kws_str}\n"
            "- Key Technologies Used: {techs_str}\n"
            "- Known Competitors: {comps_str}\n\n"
            "[Contact Presence]\n"
            "- LinkedIn: {linkedin_url}\n"
            "- Phone: {phone}\n\n"
            "Respond ONLY with the final generated text paragraph.",
        ),
    ]
)

COMPANY_INTENT_SUMMARY = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert B2B sales intelligence writer. Return only one concise "
            "English paragraph. No preamble.",
        ),
        (
            "human",
            "Write a short, professional, and natural English summary of the commercial "
            "intent of '{company_name}' based on these signals:\n"
            "{signal_text}\n\n"
            "The summary should describe whether the company is hiring, expanding, "
            "launching products, or showing other growth signals.\n"
            "Return only one concise paragraph in English.",
        ),
    ]
)

PERSONA_INTENT_SUMMARY = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert B2B Sales Analyst. Return only the generated text in English.",
        ),
        (
            "human",
            "I have collected recent LinkedIn activity signals from a prospect named "
            "'{persona_name}'.\n"
            "Based on the list of signals below (Business Signals, Interests, and Key "
            "Takeaways from their recent posts), write a concise, powerful 3-4 sentence "
            "summary of their current INTENT.\n"
            "What are they currently focused on? What problems are they trying to solve? "
            "How should a sales rep approach them?\n\n"
            "Write the response in English. Do not include introductory phrases, just "
            "the summary.\n\n"
            "--- Recent Signals ---\n"
            "{joined_signals}",
        ),
    ]
)

EMAIL_PRO_CHECK = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a data validation assistant. Reply ONLY with the exact word 'True' "
            "or 'False'. Do not add any punctuation or explanation.",
        ),
        (
            "human",
            "Is the following email address a professional/corporate email (True) or a "
            "personal/generic free email like gmail, yahoo, hotmail, outlook, etc. "
            "(False)? Email: {email}",
        ),
    ]
)

PERSONA_POST_ANALYSIS = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are an expert in B2B Sales Intelligence.\n"
            "Analyze the provided LinkedIn post and extract high-value prospecting insights.\n"
            "You MUST respond STRICTLY with a valid JSON object containing exactly these 3 keys:\n"
            "- 'businessSignal': The commercial trigger identified in the post "
            "(e.g., Hiring, Tech Innovation, Funding, Scalability Issues).\n"
            "- 'personaInterest': What the core interest or passion of the target persona "
            "is at the moment based on the text.\n"
            "- 'keyTakeaway': A concise, one-sentence strategic summary tailored for a "
            "sales representative.\n\n"
            "CRITICAL: The values for all fields MUST be written entirely in English. "
            "Return ONLY the JSON block, without any markdown formatting wrappers, text, "
            "or explanations before or after.",
        ),
        (
            "human",
            'Here is the LinkedIn post content to analyze:\n"""\n{content}\n"""',
        ),
    ]
)

CONTINENT_COUNTRIES = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a B2B geography assistant. Reply ONLY with a pure JSON array of "
            "English country names. No markdown, no explanation.",
        ),
        (
            "human",
            "Return the main economic countries for this continent as a pure JSON array "
            "of English country names (standard casing, e.g. \"Germany\", \"Tunisia\", "
            "\"United States\").\n\n"
            "Continent: {continent}\n\n"
            "Rules:\n"
            "1. Return ONLY a JSON array of strings. No markdown, no explanation.\n"
            "2. Prefer country names that commonly appear in B2B firmographic data.",
        ),
    ]
)

INDUSTRY_TAXONOMY_MATCH = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a B2B industry taxonomy matcher. Reply ONLY with a pure JSON array "
            "of strings copied exactly from the provided catalog.",
        ),
        (
            "human",
            "Given an ICP industry label, select ALL industries from the database catalog "
            "that match or are closely related (same sector, synonyms, parent/child, or "
            "near-equivalent).\n\n"
            "ICP industry: {icp}\n\n"
            "Database industries (choose ONLY from this list, copy strings EXACTLY):\n"
            "{catalog_json}\n\n"
            "Rules:\n"
            "1. Return ONLY a pure JSON array of strings.\n"
            "2. Every string MUST appear exactly in the database list above.\n"
            "3. Prefer precision over recall; skip weakly related industries.\n"
            "4. If nothing matches, return [].",
        ),
    ]
)

COUNTRY_ALIAS_MATCH = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a B2B geography normalizer. Reply ONLY with a pure JSON array of "
            "database country strings. No markdown.",
        ),
        (
            "human",
            "Map these country names to the closest labels that exist in our database.\n"
            "Return a pure JSON array of database country strings only (exact copy from "
            "the catalog).\n"
            "If a name has no match, omit it.\n\n"
            "Requested countries: {requested_json}\n\n"
            "Database countries:\n"
            "{catalog_json}",
        ),
    ]
)

INTENT_NAVIGATION = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "ROLE: Router and autonomous navigation agent specializing in corporate "
            "recruitment and public relations. Reply ONLY with a flat JSON array of URLs.",
        ),
        (
            "human",
            "Select the top 2 URLs from the following list to capture the missing "
            "elements: {missing_fields}.\n\n"
            "🔍 Routing priorities:\n"
            "- For job offers ('job_offers'): Prioritize \"Careers\", \"Jobs\", "
            "\"Rejoignez-nous\", \"Recrutement\", \"Work with us\".{country_hint}\n"
            "- For news ('news'): Search for \"News\", \"Press\", \"Blog\", "
            "\"Newsroom\", \"Actualités\", \"Media\".\n\n"
            "INPUT (JSON):\n"
            "{links_json}\n\n"
            "Return ONLY a flat JSON array containing the selected URLs.",
        ),
    ]
)

INTENT_SIGNALS_EXTRACT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "ROLE:\n"
            "You are an elite B2B Sales Intelligence Agent specializing in tracking and "
            "extracting recent buying intent and growth signals (Intent Signals).\n\n"
            "MISSION:\n"
            "Analyze the scraped text from a company's website to identify and structure "
            "key intent signals:\n"
            "- Open Job Offers (Job Openings)\n"
            "- News, Press Releases, and Strategic Events (Partnerships, Product "
            "Launches, Geographic Expansions)\n\n"
            "CRITICAL ATTENTION ON FILTERS (RECENCY & GEOGRAPHY):\n"
            "1. RECENCY FILTER (DATA FRESHNESS): A \"CURRENT REFERENCE DATE\" will be "
            "provided in the user prompt. You MUST ignore obsolete, archived, or signals "
            "dating from years prior to the reference year. Prioritize only active, "
            "recent elements, or those from the current year.\n"
            "2. JOB OFFER AVAILABILITY: Only retain opportunities that are currently open "
            "and ready to receive applicants.\n"
            "3. STRICT GEOGRAPHIC EXPERTISE FOR JOBS: If a \"TARGET COUNTRY\" is provided, "
            "you are solely responsible for the filtering. You must use your internal "
            "geographic knowledge to analyze every mentioned city.\n"
            "   - If the city ACTUALLY belongs to the target country, extract the offer "
            "and normalize the location field: \"City Name, Country Name\".\n"
            "   - STRICT PROHIBITION: If the city is in another country, completely ignore "
            "the offer. NEVER force the addition of the target country to a foreign city.\n"
            "   - \"Remote\" or global teleworking offers can be kept.\n"
            "4. GLOBAL CONFIDENCE SCORING: For each extracted job offer or news item, "
            "provide ONE overall confidence score and ONE exact source quote that proves "
            "the existence of the signal.\n\n"
            "OUTPUT RULES:\n"
            "- Reply ONLY with valid JSON.\n"
            "- Do not add any explanation before or after the JSON.\n"
            "- If an element or block is not found, return an empty array [].\n"
            "- All extracted content MUST be written in ENGLISH.\n\n"
            "EXPECTED OUTPUT STRUCTURE:\n"
            "{{\n"
            '  "job_offers": [\n'
            "    {{\n"
            '      "intent_type": "job_post",\n'
            '      "title": "Job Title",\n'
            '      "location": "City, Country or Remote",\n'
            '      "department": "Engineering, Sales, HR, etc.",\n'
            '      "date": "YYYY-MM-DD or Not specified",\n'
            '      "confidence": 0.9,\n'
            '      "source": "exact phrase from text proving this job offer"\n'
            "    }}\n"
            "  ],\n"
            '  "news": [\n'
            "    {{\n"
            '      "intent_type": "news",\n'
            '      "title_and_summary": "Title of the news - Brief summary",\n'
            '      "date": "YYYY-MM-DD or Not specified",\n'
            '      "news_type": "Partnership / Product Launch / Acquisition / Funding / '
            'General News",\n'
            '      "confidence": 0.8,\n'
            '      "source": "exact phrase from text proving this news"\n'
            "    }}\n"
            "  ]\n"
            "}}",
        ),
        (
            "human",
            "{user_prompt}",
        ),
    ]
)

INTENT_GEO_FILTER = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "ROLE: You are an uncompromising geographical auditor. You return ONLY JSON.",
        ),
        (
            "human",
            "STRICT TARGET COUNTRY: {target_country}\n\n"
            "Here is a list of job offers in JSON format extracted previously:\n"
            "{job_offers_json}\n\n"
            "MISSION:\n"
            "1. Carefully examine the \"location\" field for each offer.\n"
            "2. Determine geographically if the indicated city/region ACTUALLY belongs "
            "to the country: {target_country}.\n"
            "3. If the location indicates another country, you MUST DELETE the complete "
            "object of the offer.\n"
            "4. Keep the offers if they are explicitly \"Remote\" without country "
            "restriction.\n"
            "5. Return the result as a valid JSON array of the filtered offers. No text "
            "before or after.",
        ),
    ]
)


# ---------------------------------------------------------------------------
# Invoke via existing llm_provider router (ESPRIT / Groq)
# ---------------------------------------------------------------------------

def _messages_to_openai(
    messages: Sequence[BaseMessage],
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            role = getattr(msg, "type", "user")
            if role == "human":
                role = "user"
            elif role == "ai":
                role = "assistant"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        out.append({"role": role, "content": content})
    return out


def format_prompt(
    template: ChatPromptTemplate,
    **variables: Any,
) -> List[BaseMessage]:
    """Render a ChatPromptTemplate into LangChain messages."""
    return template.format_messages(**variables)


def invoke_chat(
    messages: Union[ChatPromptTemplate, Sequence[BaseMessage], Sequence[Dict[str, str]]],
    *,
    variables: Optional[Dict[str, Any]] = None,
    temperature: float = 0.3,
    max_tokens: int = 400,
    fallback: Optional[str] = "Non renseigné",
    operation: str = "llm",
) -> str:
    """
    Format (optional) + call the active LLM provider.

    Accepts a ChatPromptTemplate (+ variables), LangChain messages, or raw
    OpenAI-style dict messages.
    """
    client = get_llm_client()
    model = get_llm_model()

    if isinstance(messages, ChatPromptTemplate):
        lc_messages = format_prompt(messages, **(variables or {}))
        openai_messages = _messages_to_openai(lc_messages)
    elif messages and isinstance(messages[0], BaseMessage):
        openai_messages = _messages_to_openai(messages)  # type: ignore[arg-type]
    else:
        openai_messages = list(messages)  # type: ignore[arg-type]

    try:
        # Prefer operation-tagged completions when available (Groq usage).
        completions = client.chat.completions
        if hasattr(completions, "_operation"):
            completions._operation = operation  # type: ignore[attr-defined]

        response = completions.create(
            model=model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = (response.choices[0].message.content or "").strip()
        return content
    except Exception as e:
        print(f"❌ Erreur lors de l'appel LLM ({getattr(client, 'provider', '?')}) : {e}")
        if fallback is None:
            raise
        return fallback


def invoke_template(
    template: ChatPromptTemplate,
    *,
    temperature: float = 0.3,
    max_tokens: int = 400,
    fallback: Optional[str] = "Non renseigné",
    operation: str = "llm",
    **variables: Any,
) -> str:
    """Shortcut: render template variables then invoke_chat."""
    return invoke_chat(
        template,
        variables=variables,
        temperature=temperature,
        max_tokens=max_tokens,
        fallback=fallback,
        operation=operation,
    )
