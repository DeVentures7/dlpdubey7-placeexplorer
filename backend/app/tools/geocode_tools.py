
# OpenStreetMap Nominatim geocoding tools for the RAAHIGO backend.
#
# search_location resolves manually entered city names, localities,
# landmarks and addresses into real coordinates via the Nominatim
# Search API. Kept deliberately separate from the Overpass-based place
# discovery in place_tools.py: geocoding resolves a free-text query to
# a point; place discovery searches a radius around a point.
#
# Honesty rules:
# - Coordinates come from Nominatim only; failures return {"error": ...}
#   and a valid query with no matches returns an empty list - never
#   mock data, never fabricated coordinates.
# - Provider failures are never cached.
#
# Nominatim usage policy compliance (https://operations.osmfoundation.org/
# policies/nominatim/):
# - Identifiable User-Agent with application name and contact info
#   (configure via NOMINATIM_CONTACT_EMAIL; never hardcode a private one).
# - At most one request per second to the public service (enforced by an
#   in-process throttle).
# - Small in-memory TTL cache with normalized query keys so repeated or
#   re-spelled searches do not re-hit the API. The Android client searches
#   on explicit submission or debounced input - never on every keystroke.

import os
import re
import threading
import time
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NOMINATIM_URL = os.getenv(
    "NOMINATIM_URL",
    "https://nominatim.openstreetmap.org",
)

# Contact info for the User-Agent, per Nominatim policy. Set
# NOMINATIM_CONTACT_EMAIL in the environment; the default keeps the UA
# identifiable without inventing an address.
_CONTACT = os.getenv("NOMINATIM_CONTACT_EMAIL", "unconfigured")

USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    f"RAAHIGO-Backend/0.1 (geocoding; OpenStreetMap Nominatim; contact: {_CONTACT})",
)

REQUEST_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 5.0

# Public Nominatim policy: maximum 1 request per second.
MIN_REQUEST_INTERVAL_SECONDS = 1.0

CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 128

DEFAULT_LIMIT = 5
MAX_LIMIT = 10


# ---------------------------------------------------------------------------
# HTTP helper and rate throttle
# ---------------------------------------------------------------------------

_last_request_monotonic = 0.0
_throttle_lock = threading.Lock()


def _create_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
        ),
        headers={"User-Agent": USER_AGENT},
    )


def _respect_rate_limit():
    """Block until at least MIN_REQUEST_INTERVAL_SECONDS since the last
    actual provider request. One shared budget for the whole process."""
    global _last_request_monotonic
    with _throttle_lock:
        now = time.monotonic()
        wait = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_monotonic)
        if wait > 0:
            time.sleep(wait)
        _last_request_monotonic = time.monotonic()


def _query_nominatim(query: str, limit: int) -> dict:
    """
    GET the Nominatim Search API.

    Returns the parsed JSON list on success, or an {"error": ...} dict
    on any failure. Never raises for expected API problems.
    """
    _respect_rate_limit()

    try:
        with _create_client() as client:
            response = client.get(
                f"{NOMINATIM_URL}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "limit": limit,
                    "addressdetails": 1,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

    except httpx.TimeoutException:
        return {
            "error": (
                "Geocoding service timed out. The Nominatim service may "
                "be busy - try again shortly."
            )
        }
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 429:
            return {
                "error": (
                    "Geocoding service is rate limiting requests "
                    "(HTTP 429). Wait a moment and try again."
                )
            }
        return {"error": f"Geocoding service returned HTTP {status}."}
    except httpx.HTTPError as error:
        return {"error": f"Geocoding request failed: {error}"}
    except ValueError:
        return {"error": "Geocoding service returned an invalid JSON response."}

    if not isinstance(payload, list):
        return {"error": "Geocoding service response has an unexpected shape."}

    return {"results": payload}


# ---------------------------------------------------------------------------
# Cache (successful searches only; errors are never cached)
# ---------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def clear_cache():
    """Empty the geocode cache (used by tests and after config changes)."""
    with _cache_lock:
        _cache.clear()


def normalize_query(query: str) -> str:
    """Canonical form for cache keys and provider requests."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _cache_get(key: tuple) -> Optional[dict]:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if now - stored_at > CACHE_TTL_SECONDS:
            del _cache[key]
            return None
        return value


def _cache_set(key: tuple, value: dict):
    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest]
        _cache[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def _extract_city(address: Optional[dict]) -> Optional[str]:
    """The city-level component of a Nominatim address breakdown, ordered
    most-city-first: city > town > municipality > state_district >
    village. Used for the default destination label, where a
    village/locality inside a city (e.g. Maan inside Pune) must not win:
    rural Nominatim breakdowns carry no 'city' key but name the
    surrounding city in 'state_district'."""
    if not address:
        return None
    for key in ("city", "town", "municipality", "state_district", "village"):
        value = address.get(key)
        if value:
            return value
    return None


def _build_address(address: Optional[dict]) -> Optional[str]:
    """Compact 'city, district, state, country' style address from the
    Nominatim address breakdown, mirroring the Android client's own
    compacting. None when no address parts exist."""
    if not address:
        return None

    parts = [
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality"),
        address.get("state_district") or address.get("county"),
        address.get("state"),
        address.get("country"),
    ]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _normalize_result(raw: dict) -> Optional[dict]:
    """Convert one Nominatim result into our response model."""
    try:
        latitude = float(raw["lat"])
        longitude = float(raw["lon"])
    except (KeyError, TypeError, ValueError):
        # A result without usable coordinates is not a place we can
        # return honestly - skip it.
        return None

    display_name = raw.get("display_name")

    return {
        # Stable provider-scoped id (matches the Android client's
        # "nominatim_<place_id>" convention).
        "id": f"nominatim_{raw.get('place_id')}",
        # Short primary name (first comma-separated part of the display
        # name) - maps to GeocodePlace.displayName on Android.
        "name": display_name.split(",")[0].strip() if display_name else None,
        # Full provider display name for the UI subtitle / disambiguation.
        "displayName": display_name,
        "latitude": latitude,
        "longitude": longitude,
        "address": _build_address(raw.get("address")),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_location(query: str, limit: int = DEFAULT_LIMIT) -> dict:
    """
    Resolve a free-text place query (city, locality, landmark, address)
    into real coordinates using the OSM Nominatim Search API.

    Returns {"query": ..., "results": [...]} where each result has
    id, name, displayName, latitude, longitude and a nullable address.
    A valid query with no matches returns an empty results list.
    Failures return {"error": ...} and are never cached.
    """
    if not query or not query.strip():
        return {"error": "Query must not be empty."}
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        return {"error": f"limit must be a positive integer, got {limit!r}"}
    if limit > MAX_LIMIT:
        return {"error": f"limit must be at most {MAX_LIMIT}, got {limit}"}

    normalized = normalize_query(query)
    cache_key = (normalized, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    payload = _query_nominatim(query.strip(), limit)

    if "error" in payload:
        return payload

    results = []
    for raw in payload["results"]:
        if not isinstance(raw, dict):
            continue
        result = _normalize_result(raw)
        if result is not None:
            results.append(result)

    response = {"query": query.strip(), "results": results}
    _cache_set(cache_key, response)
    return response


def reverse_geocode(latitude: float, longitude: float) -> dict:
    """
    Resolve coordinates into a place description using the OSM Nominatim
    Reverse API. Used to label the device's current location as a city for
    the default destination.

    Returns {"latitude": ..., "longitude": ..., "name": ..., "displayName":
    ..., "address": ...} on success, {"error": ...} on failure. Never
    fabricates a city name when the provider returns nothing.
    """
    if not -90 <= latitude <= 90:
        return {"error": f"latitude must be between -90 and 90, got {latitude}"}
    if not -180 <= longitude <= 180:
        return {"error": f"longitude must be between -180 and 180, got {longitude}"}

    cache_key = ("reverse", round(latitude, 4), round(longitude, 4))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    _respect_rate_limit()

    try:
        with _create_client() as client:
            response = client.get(
                f"{NOMINATIM_URL}/reverse",
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "jsonv2",
                    "addressdetails": 1,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()

    except httpx.TimeoutException:
        return {
            "error": (
                "Geocoding service timed out. The Nominatim service may "
                "be busy - try again shortly."
            )
        }
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status == 429:
            return {
                "error": (
                    "Geocoding service is rate limiting requests "
                    "(HTTP 429). Wait a moment and try again."
                )
            }
        return {"error": f"Geocoding service returned HTTP {status}."}
    except httpx.HTTPError as error:
        return {"error": f"Geocoding request failed: {error}"}
    except ValueError:
        return {"error": "Geocoding service returned an invalid JSON response."}

    if not isinstance(payload, dict) or "error" in payload:
        return {"error": "No place found for these coordinates."}

    normalized = _normalize_result(payload)
    if normalized is None:
        return {"error": "No place found for these coordinates."}

    # Keep the raw Nominatim address breakdown for city extraction.
    raw_address = payload.get("address")

    result = {
        "latitude": latitude,
        "longitude": longitude,
        "name": normalized["name"],
        "displayName": normalized["displayName"],
        "city": _extract_city(raw_address),
        "address": normalized["address"],
    }
    _cache_set(cache_key, result)
    return result
