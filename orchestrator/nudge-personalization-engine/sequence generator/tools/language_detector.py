"""
Language detection utility for the outreach sequence generator.

Detects the prospect's primary language from location/country data provided
by the Detective module or manual input. Uses a deterministic country-to-language
mapping as the primary strategy, with an optional Gemini fallback for ambiguous
or missing locations.
"""

import os
import re
import json
import time
import requests
from typing import Dict, Optional, Tuple

from ..config.constants import (
    COUNTRY_LANGUAGE_MAP,
    COUNTRY_TIMEZONE_MAP,
    DEFAULT_LANGUAGE,
    DEFAULT_LANGUAGE_NAME,
    DEFAULT_TIMEZONE_OFFSET,
    DEFAULT_TIMEZONE_NAME,
)
from ..observability.logging_config import logger
from ..observability.observability_store import prompt_store, PromptRecord


def detect_language_from_location(location: Optional[str]) -> Tuple[str, str]:
    """
    Detect the primary outreach language from a free-text location string.

    Strategy:
      1. Normalize the location string to lowercase.
      2. Search for any country name present in COUNTRY_LANGUAGE_MAP.
      3. If found, return (iso_code, display_name).
      4. If not found or location is empty, return the default (en, English).

    Args:
        location: Free-text location, e.g. "Tunis, Tunisia", "Paris, France",
                  "San Francisco, USA", or None.

    Returns:
        Tuple of (iso_code, display_name), e.g. ("fr", "French").
    """
    if not location or not location.strip():
        logger.info(
            "Language detection: no location provided, defaulting to "
            f"{DEFAULT_LANGUAGE} ({DEFAULT_LANGUAGE_NAME})."
        )
        return DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME

    normalized = location.strip().lower()

    # Search for country names — longest matches first to avoid partial hits
    # (e.g., "south africa" before "south").
    sorted_countries = sorted(COUNTRY_LANGUAGE_MAP.keys(), key=len, reverse=True)

    for country in sorted_countries:
        if country in normalized:
            iso_code, display_name = COUNTRY_LANGUAGE_MAP[country]
            logger.info(
                f"Language detection: matched country '{country}' in "
                f"location '{location}' → {iso_code} ({display_name}).",
                extra={
                    "location": location,
                    "matched_country": country,
                    "detected_language": iso_code,
                    "detected_language_name": display_name,
                },
            )
            return iso_code, display_name

    # No match found — use default
    logger.info(
        f"Language detection: no country match in '{location}', "
        f"defaulting to {DEFAULT_LANGUAGE} ({DEFAULT_LANGUAGE_NAME}).",
        extra={"location": location},
    )
    return DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME


def detect_language_from_contact_info(contact_info: Dict) -> Tuple[str, str]:
    """
    Extract language from structured contact_info dict.

    Checks the following fields in priority order:
      - contact_info["country"]
      - contact_info["city"] / contact_info["location"]
      - contact_info["language"] (explicit override from caller)

    Args:
        contact_info: Dict with prospect contact details.

    Returns:
        Tuple of (iso_code, display_name).
    """
    # Explicit language override — highest priority
    explicit_lang = contact_info.get("language")
    if explicit_lang and isinstance(explicit_lang, str) and len(explicit_lang) >= 2:
        # Accept either an ISO code ("fr") or a full name ("French")
        lang_lower = explicit_lang.strip().lower()
        # Check if it matches a known ISO code
        for _country, (iso, name) in COUNTRY_LANGUAGE_MAP.items():
            if lang_lower == iso or lang_lower == name.lower():
                logger.info(
                    f"Language detection: explicit override '{explicit_lang}' "
                    f"→ {iso} ({name})."
                )
                return iso, name
        # If it looks like a valid 2-letter ISO code, use it directly
        if len(lang_lower) == 2 and lang_lower.isalpha():
            logger.info(
                f"Language detection: explicit ISO code '{lang_lower}' "
                "(not in map, using as-is)."
            )
            return lang_lower, explicit_lang.strip().capitalize()

    # Try country field
    country = contact_info.get("country")
    if country:
        result = detect_language_from_location(country)
        if result[0] != DEFAULT_LANGUAGE or DEFAULT_LANGUAGE in (country or "").lower():
            return result

    # Try city / location fields
    for field in ("location", "city"):
        value = contact_info.get(field)
        if value:
            return detect_language_from_location(value)

    return DEFAULT_LANGUAGE, DEFAULT_LANGUAGE_NAME


def detect_language_with_gemini_fallback(
    location: Optional[str],
    contact_info: Optional[Dict] = None,
) -> Tuple[str, str]:
    """
    Detect language with an optional Gemini API fallback for ambiguous locations.

    If the deterministic mapping fails to find a match AND a GOOGLE_API_KEY is
    configured, asks Gemini to identify the country/language from the location.

    This is an optional enhancement — the deterministic path is always tried first.

    Args:
        location: Free-text location string.
        contact_info: Optional structured contact dict.

    Returns:
        Tuple of (iso_code, display_name).
    """
    # Try deterministic path first
    if contact_info:
        iso_code, display_name = detect_language_from_contact_info(contact_info)
    else:
        iso_code, display_name = detect_language_from_location(location)

    # If we got a real match (not default), return immediately
    if iso_code != DEFAULT_LANGUAGE or not location:
        return iso_code, display_name

    # Gemini fallback — only if API key is available
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return iso_code, display_name

    try:
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        prompt = (
            f"Given this location: '{location}', identify the country and its "
            f"primary language for business communication. "
            f"Return ONLY a JSON object: {{\"country\": \"...\", \"iso_language_code\": \"xx\", "
            f"\"language_name\": \"...\"}}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        resp_data = response.json()
        text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
        # Strip markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        gemini_iso = result.get("iso_language_code", "").lower().strip()
        gemini_name = result.get("language_name", "").strip()
        if gemini_iso and len(gemini_iso) == 2:
            # ── Record actual provider token usage (not estimation) ──
            usage = resp_data.get("usageMetadata", {})
            prompt_store.record(PromptRecord(
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                module="sequence_generator",
                agent_step="language_detector",
                prompt=prompt[:5000],
                response=text[:5000],
                tokens_in=usage.get("promptTokenCount", 0),
                tokens_out=usage.get("candidatesTokenCount", 0),
                model_used="primary",
                latency_ms=0.0,
                success=True,
            ))
            logger.info(
                f"Language detection: Gemini fallback identified '{location}' "
                f"→ {gemini_iso} ({gemini_name}).",
                extra={
                    "location": location,
                    "gemini_result": result,
                },
            )
            return gemini_iso, gemini_name or gemini_iso.upper()
    except Exception as e:
        logger.warning(
            f"Language detection: Gemini fallback failed for '{location}': {e}"
        )

    return iso_code, display_name


# ── Timezone Detection ──


def detect_timezone_from_location(location: Optional[str]) -> Tuple[int, str]:
    """
    Detect timezone (UTC offset in hours) from a free-text location string.

    Strategy:
      1. Normalize location to lowercase.
      2. Search for country in COUNTRY_TIMEZONE_MAP (longest match first).
      3. Return (utc_offset_hours, tz_name) or (0, 'UTC') if no match.
    """
    if not location or not location.strip():
        return DEFAULT_TIMEZONE_OFFSET, DEFAULT_TIMEZONE_NAME

    normalized = location.strip().lower()
    sorted_countries = sorted(COUNTRY_TIMEZONE_MAP.keys(), key=len, reverse=True)

    for country in sorted_countries:
        if country in normalized:
            offset, tz_name = COUNTRY_TIMEZONE_MAP[country]
            logger.info(
                f"Timezone detection: matched country '{country}' in "
                f"location '{location}' → UTC{offset:+d} ({tz_name})."
            )
            return offset, tz_name

    return DEFAULT_TIMEZONE_OFFSET, DEFAULT_TIMEZONE_NAME


def detect_timezone_from_contact_info(contact_info: Dict) -> Tuple[int, str]:
    """
    Detect timezone from structured contact_info dict.

    Checks in priority order:
      - contact_info['country']
      - contact_info['city'] / contact_info['location']
    """
    # Try country field
    country = contact_info.get("country")
    if country:
        offset, tz_name = detect_timezone_from_location(country)
        if offset != DEFAULT_TIMEZONE_OFFSET or (country or "").lower() in (
            "utc", "gmt"
        ):
            return offset, tz_name

    # Try city / location fields
    for field in ("location", "city"):
        value = contact_info.get(field)
        if value:
            return detect_timezone_from_location(value)

    return DEFAULT_TIMEZONE_OFFSET, DEFAULT_TIMEZONE_NAME


def detect_timezone_with_fallback(
    location: Optional[str],
    contact_info: Optional[Dict] = None,
) -> Tuple[int, str]:
    """
    Detect timezone with deterministic mapping, falling back to Gemini if needed.
    Same pattern as detect_language_with_gemini_fallback.
    """
    if contact_info:
        offset, tz_name = detect_timezone_from_contact_info(contact_info)
    else:
        offset, tz_name = detect_timezone_from_location(location)

    # If we got a real match (not default), return immediately
    if offset != DEFAULT_TIMEZONE_OFFSET or not location:
        return offset, tz_name

    # Gemini fallback — only if API key is available
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return offset, tz_name

    try:
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
        prompt = (
            f"Given this location: '{location}', identify the country and its "
            f"timezone as a UTC offset in hours (integer). "
            f"Return ONLY a JSON object: {{\"country\": \"...\", \"utc_offset_hours\": <int>, "
            f"\"timezone_name\": \"...\"}}"
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
        }
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        resp_data = response.json()
        text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        result = json.loads(text)
        gemini_offset = int(result.get("utc_offset_hours", 0))
        gemini_name = result.get("timezone_name", "UTC")
        # ── Record actual provider token usage (not estimation) ──
        usage = resp_data.get("usageMetadata", {})
        prompt_store.record(PromptRecord(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            module="sequence_generator",
            agent_step="timezone_detector",
            prompt=prompt[:5000],
            response=text[:5000],
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            model_used="primary",
            latency_ms=0.0,
            success=True,
        ))
        logger.info(
            f"Timezone detection: Gemini fallback identified '{location}' "
            f"→ UTC{gemini_offset:+d} ({gemini_name})."
        )
        return gemini_offset, gemini_name
    except Exception as e:
        logger.warning(
            f"Timezone detection: Gemini fallback failed for '{location}': {e}"
        )

    return offset, tz_name
