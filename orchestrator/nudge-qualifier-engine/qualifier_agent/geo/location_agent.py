"""
geo/location_agent.py
────────────────────────
Geo filtering for sourced companies: continent -> country -> city-proximity
(via geocoding + distance matrix).

City proximity is soft: companies farther than max_km from all preferred
cities are KEPT and flagged with geo_radius_mismatch=True so scoring can
apply a penalty. They are not dropped.

If the geocoding/distance API fails for a given target city, that city's
companies fall back to country-level filtering rather than being dropped —
a third-party API outage must never silently zero out a campaign.
"""

import os
import logging
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from geo.continents import normalize_country, resolve_company_continent
from utils.cache import RedisCache

load_dotenv()
logger = logging.getLogger(__name__)


class LocationAgent:
    def __init__(self):
        self.ors_key = os.getenv("ORS_API_KEY")
        self.ps_key = os.getenv("POSITIONSTACK_API_KEY")
        self.base_url = "https://api.heigit.org/openrouteservice"
        self.cache = RedisCache()

    # ==================================
    # GEO LOOKUP (POSITIONSTACK + CACHE)
    # ==================================
    def get_info(self, city_name: str, country_hint: str = "") -> Optional[dict]:
        if not city_name:
            return None

        key = self.cache.key("geo", city_name, country_hint)

        cached = self.cache.get(key)
        if cached:
            logger.debug("geo_cache_hit city=%s country=%s", city_name, country_hint)
            return cached

        if not self.ps_key:
            logger.warning("geo_lookup_skipped reason=missing_positionstack_api_key")
            return None

        logger.info("geo_api_call city=%s country=%s", city_name, country_hint)

        url = "https://api.positionstack.com/v1/forward"
        params = {
            "access_key": self.ps_key,
            "query": f"{city_name}, {country_hint}",
            "limit": 1,
        }

        try:
            res = requests.get(url, params=params, timeout=10).json()

            if "data" in res and len(res["data"]) > 0:
                match = res["data"][0]
                data = {
                    "coords": [match.get("longitude"), match.get("latitude")],
                    "country": match.get("country_code", "").lower() or country_hint.lower(),
                    "city": city_name.lower(),
                }
                self.cache.set(key, data, ttl=30 * 24 * 3600)
                return data

        except Exception as exc:
            logger.warning("geo_lookup_failed city=%s error=%s", city_name, exc)

        return None

    # =========================
    # MATRIX DISTANCE API
    # =========================
    def get_matrix_distances(
        self, origin_coords: list, destinations_coords: list
    ) -> List[Optional[float]]:
        if not destinations_coords:
            return []

        if not self.ors_key:
            logger.warning("distance_matrix_skipped reason=missing_ors_api_key")
            return []

        url = f"{self.base_url}/v2/matrix/driving-car"
        headers = {"Authorization": self.ors_key, "Content-Type": "application/json"}

        body = {
            "locations": [origin_coords] + destinations_coords,
            "sources": [0],
            "destinations": list(range(1, len(destinations_coords) + 1)),
            "metrics": ["distance"],
            "units": "km",
        }

        try:
            res = requests.post(url, json=body, headers=headers, timeout=12).json()
            if "distances" in res and res["distances"]:
                return res["distances"][0]
        except Exception as exc:
            logger.warning("distance_matrix_failed error=%s", exc)

        return []

    @staticmethod
    def _upsert_city_result(
        final: List[Dict[str, Any]],
        seen_company_ids: set,
        company: Dict[str, Any],
        uid: Any,
        dist: Optional[float],
        *,
        within_radius: bool,
        geo_fallback: Optional[str] = None,
    ) -> None:
        """
        Insert/update a company in the city-proximity result list.

        Within-radius wins over a prior radius-mismatch. Among mismatches
        (or among in-radius hits), keep the closest measured distance.
        """
        rounded = round(dist, 1) if dist is not None else None

        if uid not in seen_company_ids:
            seen_company_ids.add(uid)
            comp = company.copy()
            comp["dist"] = rounded
            if within_radius:
                comp["geo_radius_mismatch"] = False
            else:
                comp["geo_radius_mismatch"] = True
            if geo_fallback:
                comp["geo_fallback"] = geo_fallback
            final.append(comp)
            return

        for existing in final:
            existing_uid = existing.get("apollo_id") or existing.get("name")
            if existing_uid != uid:
                continue

            prev_mismatch = bool(existing.get("geo_radius_mismatch"))
            prev_dist = existing.get("dist")

            if within_radius:
                existing["geo_radius_mismatch"] = False
                if prev_dist is None or (rounded is not None and rounded < prev_dist):
                    existing["dist"] = rounded
            elif prev_mismatch:
                if prev_dist is None or (rounded is not None and rounded < prev_dist):
                    existing["dist"] = rounded
            # else: already matched another preferred city within radius
            break

    # =================================
    # MAIN FILTER
    # =================================
    def filter_companies(
        self, icp, db: List[Dict[str, Any]], max_km: float, debug: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Applies continent -> country hard filters, then soft city-proximity.

        Hard drops: continent / country mismatches.
        Soft flag: outside max_km of all preferred cities → kept with
        geo_radius_mismatch=True (scorer applies a penalty).

        Fallback contract: if city-proximity filtering can't run for a
        target city (geocoding failed, distance API failed, or no API
        keys configured), companies in that city's target country are
        KEPT (country-level filtering already applied) rather than
        dropped. A third-party outage degrades precision, it does not
        zero out the campaign.
        """
        results = db

        # Continent filter is only meaningful when no target_countries are set
        # (country is strictly more precise). Infer continent from country when
        # the company record has no explicit continent field (Apollo/sourcer
        # common case) so continent-only ICPs do not zero out the campaign.
        if icp.target_continents and not icp.target_countries:
            targets = {c.lower().strip() for c in icp.target_continents}
            kept = []
            for c in results:
                resolved = resolve_company_continent(c)
                if resolved and resolved in targets:
                    # Stamp resolved continent so downstream scoring/UI see it
                    if not c.get("continent"):
                        c = {**c, "continent": resolved.title()}
                    kept.append(c)
            results = kept
            if debug:
                logger.info("geo_filter_continent remaining=%d", len(results))

        if icp.target_countries:
            targets = {
                normalize_country(c)
                for c in icp.target_countries
                if normalize_country(c)
            }
            results = [
                c for c in results
                if normalize_country(c.get("country")) in targets
            ]
            if debug:
                logger.info("geo_filter_country remaining=%d", len(results))

        if not icp.target_cities or not max_km:
            return results

        # ── City-proximity (soft): keep out-of-radius, flag for penalty ────
        final: List[Dict[str, Any]] = []
        seen_company_ids = set()

        for city_obj in icp.target_cities:
            if isinstance(city_obj, dict):
                city_name = city_obj.get("city") or ""
                city_country = city_obj.get("country") or ""
            else:
                city_name = getattr(city_obj, "city", None) or ""
                city_country = getattr(city_obj, "country", None) or ""
            if not city_name:
                continue
            logger.info("geo_city_mode city=%s country=%s", city_name, city_country)

            city_country_norm = normalize_country(city_country)
            cluster = [
                c for c in results
                if normalize_country(c.get("country")) == city_country_norm
            ]
            if debug:
                logger.info("geo_city_cluster_size city=%s size=%d", city_name, len(cluster))

            if not cluster:
                continue

            origin = self.get_info(city_name, city_country)

            if not origin:
                # Geocoding failed for the ORIGIN city itself — fall back to
                # country-level pass for this cluster instead of dropping it.
                logger.warning(
                    "geo_fallback_to_country_only city=%s reason=origin_geocode_failed", city_name
                )
                for c in cluster:
                    uid = c.get("apollo_id") or c.get("name")
                    self._upsert_city_result(
                        final, seen_company_ids, c, uid, None,
                        within_radius=True,
                        geo_fallback="country_only_origin_geocode_failed",
                    )
                continue

            coords = []
            valid = []
            for c in cluster:
                info = self.get_info(c.get("city") or "", c.get("country") or "")
                if not info:
                    logger.debug("geo_no_destination_geocode company=%s", c.get("name"))
                    continue
                coords.append(info["coords"])
                valid.append(c)

            # Companies whose own city/country couldn't be geocoded still
            # fall back to country-level inclusion, per the no-drop-on-
            # API-failure contract — they just skip the distance check.
            ungeocoded = [c for c in cluster if c not in valid]
            for c in ungeocoded:
                uid = c.get("apollo_id") or c.get("name")
                self._upsert_city_result(
                    final, seen_company_ids, c, uid, None,
                    within_radius=True,
                    geo_fallback="country_only_destination_geocode_failed",
                )

            if not valid:
                continue

            # Build a stable identifier list for the cache key so different
            # company lists with the same count don't collide.
            company_ids = "|".join(
                str(c.get("apollo_id") or c.get("name") or i)
                for i, c in enumerate(valid)
            )
            cache_key = self.cache.key(
                "dist_batch", city_name, city_country, company_ids
            )
            distances = self.cache.get(cache_key)

            if distances:
                logger.debug("distance_cache_hit city=%s", city_name)
            else:
                distances = self.get_matrix_distances(origin["coords"], coords)
                if distances:
                    self.cache.set(cache_key, distances, ttl=30 * 24 * 3600)

            if not distances:
                # Distance matrix API failed entirely for this city — fall
                # back to country-level pass for the geocoded-but-unmeasured
                # companies, rather than dropping them.
                logger.warning(
                    "geo_fallback_to_country_only city=%s reason=distance_matrix_failed", city_name
                )
                for c in valid:
                    uid = c.get("apollo_id") or c.get("name")
                    self._upsert_city_result(
                        final, seen_company_ids, c, uid, None,
                        within_radius=True,
                        geo_fallback="country_only_distance_matrix_failed",
                    )
                continue

            for i, d in enumerate(distances):
                if i >= len(valid):
                    break

                company = valid[i]
                uid = company.get("apollo_id") or company.get("name")

                if d is None:
                    continue

                within = d <= max_km
                if within:
                    self._upsert_city_result(
                        final, seen_company_ids, company, uid, d,
                        within_radius=True,
                    )
                else:
                    logger.debug(
                        "geo_radius_mismatch city=%s company=%s dist=%.1f max_km=%.1f",
                        city_name, company.get("name"), d, max_km,
                    )
                    self._upsert_city_result(
                        final, seen_company_ids, company, uid, d,
                        within_radius=False,
                    )

        # Country survivors never measured against a preferred city still pass
        # through (soft mismatch) so preferred-city ICPs do not silently drop.
        for c in results:
            uid = c.get("apollo_id") or c.get("name")
            if uid in seen_company_ids:
                continue
            self._upsert_city_result(
                final, seen_company_ids, c, uid, None,
                within_radius=False,
                geo_fallback="no_preferred_city_distance",
            )

        return final
