
# OSRM-backed routing tools for the PlaceExplorer MCP server.
#
# get_route queries an OSRM Route API server for actual road distance and
# duration between two coordinates. get_route_matrix queries the Table API
# for duration/distance matrices between many coordinates at once (used
# for efficiently comparing candidate stops and choosing stop order).
#
# Honesty rules:
# - No fabricated route data: failures return {"error": ...}, never a
#   Haversine estimate masquerading as road distance. Straight-line
#   distance remains the itinerary scheduler's own rough estimator and is
#   never presented as a route.
# - Errors are never cached.
#
# Public OSRM demo server etiquette (https://router.project-osrm.org):
# - It is a free, rate-limited demo instance: requests are cached
#   in-process, the Table API coordinate count is capped, and a
#   recognizable User-Agent is sent. Point OSRM_URL at a self-hosted or
#   commercial instance for production use.

import os
import threading
import time
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Demo server by default; override with OSRM_URL for production.
OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")

# OSRM profile baked into the URL path. The demo server only serves "driving".
OSRM_PROFILE = os.getenv("OSRM_PROFILE", "driving")

USER_AGENT = os.getenv(
    "OSRM_USER_AGENT",
    "PlaceExplorerBackend/0.1 (MCP routing; OSRM)",
)

REQUEST_TIMEOUT_SECONDS = 15.0
CONNECT_TIMEOUT_SECONDS = 10.0

# Public demo server policy: keep matrices small.
MAX_TABLE_COORDINATES = 25

ROUTE_CACHE_TTL_SECONDS = 300
ROUTE_CACHE_MAX_ENTRIES = 256

# Itinerary legs are short; if OSRM claims longer than this something is
# wrong (e.g. profile mismatch) - reported, not silently accepted.
MAX_PLAUSIBLE_ROUTE_KM = 500.0


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


def _create_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
        ),
        headers={"User-Agent": USER_AGENT},
    )


def _format_coordinate(latitude: float, longitude: float) -> str:
    # OSRM wants "lon,lat" order.
    return f"{longitude:.6f},{latitude:.6f}"


def _query_osrm(url: str) -> dict:
    """
    GET an OSRM API URL.

    Returns the parsed JSON payload on success (payload["code"] == "Ok"),
    or an {"error": ...} dict on any failure. Never raises for expected
    API problems.
    """
    try:
        with _create_client() as client:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()

    except httpx.TimeoutException:
        return {
            "error": (
                "OSRM request timed out. The routing server may be "
                "overloaded - try again later."
            )
        }
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (429, 503):
            return {
                "error": (
                    f"OSRM server returned HTTP {status}: rate limited or "
                    "overloaded. Wait before retrying."
                )
            }
        return {"error": f"OSRM server returned HTTP {status}."}
    except httpx.HTTPError as error:
        return {"error": f"OSRM request failed: {error}"}
    except ValueError:
        return {"error": "OSRM server returned an invalid JSON response."}

    if not isinstance(payload, dict):
        return {"error": "OSRM response has an unexpected shape."}

    code = payload.get("code")
    if code != "Ok":
        message = payload.get("message") or "no message provided"
        return {"error": f"OSRM could not process the request ({code}): {message}"}

    return payload


# ---------------------------------------------------------------------------
# Cache (successful routes only; errors are never cached)
# ---------------------------------------------------------------------------

_route_cache: dict[tuple, tuple[float, dict]] = {}
_route_cache_lock = threading.Lock()


def clear_route_cache():
    """Empty the route cache (used by tests and after config changes)."""
    with _route_cache_lock:
        _route_cache.clear()


def _cache_get(key: tuple) -> Optional[dict]:
    now = time.monotonic()
    with _route_cache_lock:
        entry = _route_cache.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if now - stored_at > ROUTE_CACHE_TTL_SECONDS:
            del _route_cache[key]
            return None
        return value


def _cache_set(key: tuple, value: dict):
    with _route_cache_lock:
        if len(_route_cache) >= ROUTE_CACHE_MAX_ENTRIES:
            oldest = min(_route_cache, key=lambda k: _route_cache[k][0])
            del _route_cache[oldest]
        _route_cache[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# Public tool API
# ---------------------------------------------------------------------------


def _validate_coordinate(latitude: float, longitude: float) -> Optional[str]:
    if not -90 <= latitude <= 90:
        return f"latitude must be between -90 and 90, got {latitude}"
    if not -180 <= longitude <= 180:
        return f"longitude must be between -180 and 180, got {longitude}"
    return None


def _meters_to_km(meters) -> float:
    return round(meters / 1000.0, 2)


def _seconds_to_minutes(seconds) -> int:
    if seconds <= 0:
        # Same point or unreachable: report zero, never round up to 1.
        return 0
    return max(1, round(seconds / 60.0))


def get_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
) -> dict:
    """
    Route between two coordinates using the OSRM Route API.

    Returns actual road distance (km) and duration (minutes) from the
    routing engine - never a straight-line estimate.
    """
    for label, latitude, longitude in (
        ("start", start_latitude, start_longitude),
        ("end", end_latitude, end_longitude),
    ):
        problem = _validate_coordinate(latitude, longitude)
        if problem:
            return {"error": f"Invalid {label} coordinate: {problem}"}

    start = _format_coordinate(start_latitude, start_longitude)
    end = _format_coordinate(end_latitude, end_longitude)

    cache_key = (start, end, OSRM_PROFILE)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"{OSRM_URL}/route/v1/{OSRM_PROFILE}/{start};{end}"
        "?overview=false&alternatives=false&steps=false"
    )
    payload = _query_osrm(url)

    if "error" in payload:
        return payload

    routes = payload.get("routes") or []
    if not routes:
        return {"error": "OSRM returned no route between the coordinates."}

    route = routes[0]

    distance_km = _meters_to_km(route.get("distance", 0.0))
    duration_minutes = _seconds_to_minutes(route.get("duration", 0.0))

    if distance_km > MAX_PLAUSIBLE_ROUTE_KM:
        return {
            "error": (
                f"OSRM reported an implausible route ({distance_km} km). "
                "Check the coordinates and routing profile."
            )
        }

    result = {
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "start": {"latitude": start_latitude, "longitude": start_longitude},
        "end": {"latitude": end_latitude, "longitude": end_longitude},
        "profile": OSRM_PROFILE,
    }
    _cache_set(cache_key, result)
    return result


def get_route_matrix(coordinates: list) -> dict:
    """
    Duration/distance matrix between many coordinates using the OSRM
    Table API - one request instead of n*(n-1) route calls, for
    efficiently comparing candidate stops and choosing stop order.

    coordinates is a list of (latitude, longitude) pairs, capped at
    MAX_TABLE_COORDINATES. Returns {"matrix": {"durations": [[...]],
    "distances": [[...]]}, "coordinates": [...]} where durations are in
    minutes and distances in km, entry [i][j] going from coordinate i
    to coordinate j.
    """
    if not coordinates or not isinstance(coordinates, list):
        return {"error": "coordinates must be a non-empty list of (lat, lon) pairs"}
    if len(coordinates) > MAX_TABLE_COORDINATES:
        return {
            "error": (
                f"Too many coordinates ({len(coordinates)}); the public "
                f"OSRM demo server allows small tables (max "
                f"{MAX_TABLE_COORDINATES})."
            )
        }

    for index, (latitude, longitude) in enumerate(coordinates):
        problem = _validate_coordinate(latitude, longitude)
        if problem:
            return {"error": f"Invalid coordinate {index}: {problem}"}

    coord_string = ";".join(
        _format_coordinate(latitude, longitude)
        for latitude, longitude in coordinates
    )

    cache_key = (coord_string, OSRM_PROFILE)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url = (
        f"{OSRM_URL}/table/v1/{OSRM_PROFILE}/{coord_string}"
        "?annotations=duration,distance"
    )
    payload = _query_osrm(url)

    if "error" in payload:
        return payload

    durations_seconds = payload.get("durations")
    distances_meters = payload.get("distances")

    if not durations_seconds:
        return {"error": "OSRM returned no duration table."}

    def to_minutes_rows(rows):
        return [
            [None if value is None else _seconds_to_minutes(value) for value in row]
            for row in rows
        ]

    def to_km_rows(rows):
        if rows is None:
            # Older OSRM builds omit distance annotations; report only
            # what the server actually provided.
            return None
        return [
            [None if value is None else _meters_to_km(value) for value in row]
            for row in rows
        ]

    result = {
        "matrix": {
            "durations_minutes": to_minutes_rows(durations_seconds),
            "distances_km": to_km_rows(distances_meters),
        },
        "coordinates": [
            {"latitude": latitude, "longitude": longitude}
            for latitude, longitude in coordinates
        ],
    }
    _cache_set(cache_key, result)
    return result
