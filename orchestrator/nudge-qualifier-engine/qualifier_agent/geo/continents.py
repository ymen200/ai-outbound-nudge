"""
Country → continent resolution for geospatial gating.

Sourcer / Apollo records typically expose `country` but not `continent`.
When ICP is continent-only (e.g. Europe, empty target_countries), we must
infer continent from country so companies are not silently dropped.

Apollo often returns localized country names (e.g. "Maroc" for Morocco).
normalize_country() maps those aliases to a canonical English key used for
both continent lookup and country-equality checks.
"""

from __future__ import annotations

from typing import Dict, Optional

# Localized / alternate spellings → canonical English key (lowercase).
# Canonical keys must exist in _COUNTRY_TO_CONTINENT (or be listed there too).
_COUNTRY_ALIASES: Dict[str, str] = {
    # Morocco & Maghreb (common Apollo FR labels)
    "maroc": "morocco",
    "algérie": "algeria",
    "algerie": "algeria",
    "tunisie": "tunisia",
    "égypte": "egypt",
    "egypte": "egypt",
    "sénégal": "senegal",
    "côte d'ivoire": "ivory coast",
    "cote d'ivoire": "ivory coast",
    "côte d’ivoire": "ivory coast",
    "mauritanie": "mauritania",
    "cameroun": "cameroon",
    "maurice": "mauritius",
    # Europe (FR / common aliases)
    "espagne": "spain",
    "allemagne": "germany",
    "belgique": "belgium",
    "pays-bas": "netherlands",
    "pays bas": "netherlands",
    "suisse": "switzerland",
    "italie": "italy",
    "roumanie": "romania",
    "royaume-uni": "united kingdom",
    "royaume uni": "united kingdom",
    "angleterre": "united kingdom",
    "deutschland": "germany",
    "españa": "spain",
    "italia": "italy",
    # Americas / general
    "états-unis": "united states",
    "etats-unis": "united states",
    "états unis": "united states",
    "etats unis": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "u.s.a": "united states",
    "emirats arabes unis": "united arab emirates",
    "émirats arabes unis": "united arab emirates",
    "brésil": "brazil",
    "bresil": "brazil",
    "chili": "chile",
    "colombie": "colombia",
    # Already-canonical aliases folded through normalize
    "usa": "united states",
    "us": "united states",
    "uk": "united kingdom",
    "uae": "united arab emirates",
    "turkiye": "turkey",
    "türkiye": "turkey",
    "czechia": "czech republic",
    "the netherlands": "netherlands",
}

# Normalized keys: lowercase country names as commonly returned by Apollo.
# Aliases (e.g. "united states" / "usa") map to the same continent.
_COUNTRY_TO_CONTINENT: Dict[str, str] = {
    # Europe
    "albania": "europe",
    "andorra": "europe",
    "austria": "europe",
    "belarus": "europe",
    "belgium": "europe",
    "bosnia and herzegovina": "europe",
    "bulgaria": "europe",
    "croatia": "europe",
    "cyprus": "europe",
    "czech republic": "europe",
    "czechia": "europe",
    "denmark": "europe",
    "estonia": "europe",
    "finland": "europe",
    "france": "europe",
    "germany": "europe",
    "greece": "europe",
    "hungary": "europe",
    "iceland": "europe",
    "ireland": "europe",
    "italy": "europe",
    "kosovo": "europe",
    "latvia": "europe",
    "liechtenstein": "europe",
    "lithuania": "europe",
    "luxembourg": "europe",
    "malta": "europe",
    "moldova": "europe",
    "monaco": "europe",
    "montenegro": "europe",
    "netherlands": "europe",
    "the netherlands": "europe",
    "north macedonia": "europe",
    "macedonia": "europe",
    "norway": "europe",
    "poland": "europe",
    "portugal": "europe",
    "romania": "europe",
    "russia": "europe",
    "san marino": "europe",
    "serbia": "europe",
    "slovakia": "europe",
    "slovenia": "europe",
    "spain": "europe",
    "sweden": "europe",
    "switzerland": "europe",
    "ukraine": "europe",
    "united kingdom": "europe",
    "uk": "europe",
    "great britain": "europe",
    "england": "europe",
    "scotland": "europe",
    "wales": "europe",
    "vatican city": "europe",
    # North America
    "united states": "north america",
    "united states of america": "north america",
    "usa": "north america",
    "us": "north america",
    "canada": "north america",
    "mexico": "north america",
    # South America
    "argentina": "south america",
    "bolivia": "south america",
    "brazil": "south america",
    "chile": "south america",
    "colombia": "south america",
    "ecuador": "south america",
    "guyana": "south america",
    "paraguay": "south america",
    "peru": "south america",
    "suriname": "south america",
    "uruguay": "south america",
    "venezuela": "south america",
    # Asia
    "afghanistan": "asia",
    "armenia": "asia",
    "azerbaijan": "asia",
    "bahrain": "asia",
    "bangladesh": "asia",
    "bhutan": "asia",
    "brunei": "asia",
    "cambodia": "asia",
    "china": "asia",
    "georgia": "asia",
    "hong kong": "asia",
    "india": "asia",
    "indonesia": "asia",
    "iran": "asia",
    "iraq": "asia",
    "israel": "asia",
    "japan": "asia",
    "jordan": "asia",
    "kazakhstan": "asia",
    "kuwait": "asia",
    "kyrgyzstan": "asia",
    "laos": "asia",
    "lebanon": "asia",
    "malaysia": "asia",
    "maldives": "asia",
    "mongolia": "asia",
    "myanmar": "asia",
    "nepal": "asia",
    "north korea": "asia",
    "oman": "asia",
    "pakistan": "asia",
    "palestine": "asia",
    "philippines": "asia",
    "qatar": "asia",
    "saudi arabia": "asia",
    "singapore": "asia",
    "south korea": "asia",
    "korea": "asia",
    "sri lanka": "asia",
    "syria": "asia",
    "taiwan": "asia",
    "tajikistan": "asia",
    "thailand": "asia",
    "turkey": "asia",
    "turkiye": "asia",
    "türkiye": "asia",
    "turkmenistan": "asia",
    "united arab emirates": "asia",
    "uae": "asia",
    "uzbekistan": "asia",
    "vietnam": "asia",
    "yemen": "asia",
    # Africa
    "algeria": "africa",
    "angola": "africa",
    "benin": "africa",
    "botswana": "africa",
    "burkina faso": "africa",
    "burundi": "africa",
    "cameroon": "africa",
    "cape verde": "africa",
    "central african republic": "africa",
    "chad": "africa",
    "comoros": "africa",
    "congo": "africa",
    "democratic republic of the congo": "africa",
    "djibouti": "africa",
    "egypt": "africa",
    "equatorial guinea": "africa",
    "eritrea": "africa",
    "eswatini": "africa",
    "ethiopia": "africa",
    "gabon": "africa",
    "gambia": "africa",
    "ghana": "africa",
    "guinea": "africa",
    "guinea-bissau": "africa",
    "ivory coast": "africa",
    "cote d'ivoire": "africa",
    "kenya": "africa",
    "lesotho": "africa",
    "liberia": "africa",
    "libya": "africa",
    "madagascar": "africa",
    "malawi": "africa",
    "mali": "africa",
    "mauritania": "africa",
    "mauritius": "africa",
    "morocco": "africa",
    "mozambique": "africa",
    "namibia": "africa",
    "niger": "africa",
    "nigeria": "africa",
    "rwanda": "africa",
    "senegal": "africa",
    "seychelles": "africa",
    "sierra leone": "africa",
    "somalia": "africa",
    "south africa": "africa",
    "south sudan": "africa",
    "sudan": "africa",
    "tanzania": "africa",
    "togo": "africa",
    "tunisia": "africa",
    "uganda": "africa",
    "zambia": "africa",
    "zimbabwe": "africa",
    # Oceania
    "australia": "oceania",
    "fiji": "oceania",
    "new zealand": "oceania",
    "papua new guinea": "oceania",
    "samoa": "oceania",
}


def normalize_country(country: Optional[str]) -> Optional[str]:
    """
    Return a canonical lowercase English country key, or None if empty.
    Maps localized Apollo labels (e.g. "Maroc") onto English keys ("morocco").
    """
    if not country:
        return None
    key = str(country).strip().lower()
    if not key:
        return None
    return _COUNTRY_ALIASES.get(key, key)


def countries_equivalent(a: Optional[str], b: Optional[str]) -> bool:
    """True when both resolve to the same canonical country key."""
    na, nb = normalize_country(a), normalize_country(b)
    return bool(na and nb and na == nb)


def continent_for_country(country: Optional[str]) -> Optional[str]:
    """Return lowercase continent name for a country, or None if unknown."""
    key = normalize_country(country)
    if not key:
        return None
    return _COUNTRY_TO_CONTINENT.get(key)


def resolve_company_continent(company: dict) -> Optional[str]:
    """
    Prefer an explicit continent field; otherwise infer from country.
    Returns a lowercase continent string or None.
    """
    explicit = (company.get("continent") or "").strip().lower()
    if explicit:
        return explicit
    return continent_for_country(company.get("country"))
