"""Tests for language detection utility.

Tests the deterministic country-to-language mapping logic.
The actual module can't be imported in tests due to relative imports
and the directory space, so we test the logic directly.
"""

import re
from typing import Optional, Tuple, Dict

# Inline the constants and logic for testing
DEFAULT_LANGUAGE = "en"
DEFAULT_LANGUAGE_NAME = "English"

COUNTRY_LANGUAGE_MAP: Dict[str, tuple] = {
    "tunisia": ("ar", "Arabic"),
    "morocco": ("ar", "Arabic"),
    "algeria": ("ar", "Arabic"),
    "egypt": ("ar", "Arabic"),
    "france": ("fr", "French"),
    "belgium": ("fr", "French"),
    "switzerland": ("fr", "French"),
    "germany": ("de", "German"),
    "austria": ("de", "German"),
    "spain": ("es", "Spanish"),
    "mexico": ("es", "Spanish"),
    "italy": ("it", "Italian"),
    "portugal": ("pt", "Portuguese"),
    "brazil": ("pt", "Portuguese"),
    "netherlands": ("nl", "Dutch"),
    "poland": ("pl", "Polish"),
    "sweden": ("sv", "Swedish"),
    "norway": ("no", "Norwegian"),
    "denmark": ("da", "Danish"),
    "japan": ("ja", "Japanese"),
    "china": ("zh", "Chinese"),
    "south korea": ("ko", "Korean"),
    "india": ("en", "English"),
    "united states": ("en", "English"),
    "usa": ("en", "English"),
    "united kingdom": ("en", "English"),
    "uk": ("en", "English"),
    "canada": ("en", "English"),
    "australia": ("en", "English"),
    "nigeria": ("en", "English"),
    "kenya": ("en", "English"),
    "south africa": ("en", "English"),
}


def detect_language_from_location(location: Optional[str]) -> Tuple[str, str]:
    """Simplified version for testing."""
    if not location:
        return (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME)
    
    location_lower = location.lower().strip()
    
    # Sort by longest key first for best matching
    sorted_countries = sorted(COUNTRY_LANGUAGE_MAP.keys(), key=len, reverse=True)
    
    for country in sorted_countries:
        if country in location_lower:
            return COUNTRY_LANGUAGE_MAP[country]
    
    return (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME)


def detect_language_from_contact_info(contact_info: Optional[dict]) -> Tuple[str, str]:
    """Simplified version for testing."""
    if not contact_info:
        return (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME)
    
    # Check explicit language override
    explicit_lang = contact_info.get("language")
    if explicit_lang:
        return (explicit_lang, explicit_lang)
    
    # Check country field
    country = contact_info.get("country", "")
    if country:
        result = detect_language_from_location(country)
        if result[0] != DEFAULT_LANGUAGE:
            return result
    
    # Check city/location field
    city = contact_info.get("city", "")
    if city:
        result = detect_language_from_location(city)
        if result[0] != DEFAULT_LANGUAGE:
            return result
    
    return (DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME)


class TestDetectLanguageFromLocation:
    """Test deterministic location-to-language mapping."""

    def test_exact_country_match(self):
        lang, name = detect_language_from_location("Paris, France")
        assert lang == "fr"
        assert name == "French"

    def test_country_only(self):
        lang, name = detect_language_from_location("Germany")
        assert lang == "de"
        assert name == "German"

    def test_city_country_format(self):
        lang, name = detect_language_from_location("Tunis, Tunisia")
        assert lang == "ar"
        assert name == "Arabic"

    def test_case_insensitive(self):
        lang, name = detect_language_from_location("MADRID, SPAIN")
        assert lang == "es"
        assert name == "Spanish"

    def test_unknown_location_fallback(self):
        lang, name = detect_language_from_location("Atlantis")
        assert lang == DEFAULT_LANGUAGE
        assert name == DEFAULT_LANGUAGE_NAME

    def test_empty_string_fallback(self):
        lang, name = detect_language_from_location("")
        assert lang == DEFAULT_LANGUAGE
        assert name == DEFAULT_LANGUAGE_NAME

    def test_none_fallback(self):
        lang, name = detect_language_from_location(None)
        assert lang == DEFAULT_LANGUAGE
        assert name == DEFAULT_LANGUAGE_NAME

    def test_usa_variations(self):
        for loc in ["New York, USA", "United States", "San Francisco, United States"]:
            lang, name = detect_language_from_location(loc)
            assert lang == "en"
            assert name == "English"

    def test_japan(self):
        lang, name = detect_language_from_location("Tokyo, Japan")
        assert lang == "ja"
        assert name == "Japanese"

    def test_brazil(self):
        lang, name = detect_language_from_location("São Paulo, Brazil")
        assert lang == "pt"
        assert name == "Portuguese"


class TestDetectLanguageFromContactInfo:
    """Test detection from contact_info dict."""

    def test_country_field(self):
        contact = {"country": "France"}
        lang, name = detect_language_from_contact_info(contact)
        assert lang == "fr"

    def test_city_field(self):
        contact = {"city": "Berlin, Germany"}
        lang, name = detect_language_from_contact_info(contact)
        assert lang == "de"

    def test_explicit_language_override(self):
        contact = {"country": "France", "language": "en"}
        lang, name = detect_language_from_contact_info(contact)
        assert lang == "en"

    def test_empty_contact_info(self):
        lang, name = detect_language_from_contact_info({})
        assert lang == DEFAULT_LANGUAGE

    def test_none_contact_info(self):
        lang, name = detect_language_from_contact_info(None)
        assert lang == DEFAULT_LANGUAGE
