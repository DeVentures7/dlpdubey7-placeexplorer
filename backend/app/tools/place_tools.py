
# OpenStreetMap-backed place discovery tools for the PlaceExplorer MCP server.
#
# search_places queries the public Overpass API (https://overpass-api.de)
# around a coordinate for a given category, and returns structured place
# information. get_place_details fetches one place by its OSM type and ID.
#
# Honesty rules:
# - Fields the data does not provide are null, never invented.
# - Failures (network, timeout, Overpass errors) are returned as an
#   {"error": ...} payload instead of fabricated results.
#
# Overpass usage policy compliance:
# - Identifiable User-Agent (override with OVERPASS_USER_AGENT).
# - Request timeout on both the HTTP client and the Overpass query itself.
# - In-process TTL cache so repeated searches do not re-hit the API.
# - Radius is capped to keep queries cheap.

import concurrent.futures
import math
import os
import threading
import time
from typing import Optional

import httpx


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Endpoints tried in order. The French instance is the default primary:
# during diagnosis (2026-11) overpass-api.de answered HTTP 502 instantly
# and the kumi.systems mirror hung until the client timeout, while the
# French instance answered correctly. A custom endpoint can be configured
# through the OVERPASS_URL environment variable; it is tried first and the
# responsive defaults stay behind it as fallbacks.
_DEFAULT_OVERPASS_URLS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

_CUSTOM_OVERPASS_URL = os.getenv("OVERPASS_URL")

OVERPASS_URLS = (
    ([_CUSTOM_OVERPASS_URL] if _CUSTOM_OVERPASS_URL else [])
    + [
        url
        for url in _DEFAULT_OVERPASS_URLS
        if url != _CUSTOM_OVERPASS_URL
    ]
)

# Overpass policy asks for an identifiable User-Agent.
USER_AGENT = os.getenv(
    "OVERPASS_USER_AGENT",
    "PlaceExplorerBackend/0.1 (MCP place discovery; OpenStreetMap data)",
)

REQUEST_TIMEOUT_SECONDS = 25.0
CONNECT_TIMEOUT_SECONDS = 10.0

CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 256

MAX_RADIUS_KM = 80.0
MAX_RESULTS = 100


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

# Temple identification. "Temples & Spiritual" must return temples only -
# mosques, churches, gurudwaras and other non-temple places of worship share
# the generic ["amenity"="place_of_worship"] tag, so the category needs
# temple-specific tag selectors plus a parse-time exclusion.
TEMPLE_RELIGIONS = ("hindu", "buddhist", "jain", "taoist")

# Religions whose worship places are never temples.
NON_TEMPLE_RELIGIONS = ("muslim", "christian", "sikh", "jewish")

# Building types that are never temples.
NON_TEMPLE_BUILDINGS = (
    "mosque", "church", "cathedral", "chapel", "gurudwara", "synagogue",
)

# Name keywords of non-temple worship places, used as a last-resort filter
# for OSM entries whose religion/building tags are missing or wrong. These
# are generic place-type words, not hardcoded place names.
NON_TEMPLE_NAME_KEYWORDS = (
    "masjid", "mosque", "church", "gurudwara", "gurdwara",
    "cathedral", "synagogue", "dargah", "basilica",
)


def _is_temple(tags: dict) -> bool:
    """
    True when OSM tags/name identify a temple rather than another place of
    worship. Tag evidence wins over name evidence; a place is excluded when
    any signal says mosque/church/gurudwara/etc.
    """
    religion = (tags.get("religion") or "").lower()
    if religion in NON_TEMPLE_RELIGIONS:
        return False

    building = (tags.get("building") or "").lower()
    if building in NON_TEMPLE_BUILDINGS:
        return False

    if is_non_temple_name(tags.get("name") or ""):
        return False

    return True


def is_non_temple_name(name: str) -> bool:
    """
    True when a place NAME itself identifies a non-temple worship place
    (masjid, church, gurudwara, ...). Shared with the itinerary pipeline
    as a defensive filter for entries that slip past the Overpass query.
    """
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in NON_TEMPLE_NAME_KEYWORDS)


# Overpass tag selectors per supported category. A selector is a tag filter
# string appended to node/way/relation statements.
CATEGORY_FILTERS = {
    "temples_and_spiritual": [
        # Hindu/Buddhist/Jain worship places - the temple religions in the
        # regions the app serves. Sikh gurudwaras (religion=sikh) are
        # deliberately excluded per product requirements.
        '["amenity"="place_of_worship"]["religion"~"^(hindu|buddhist|jain|taoist)$"]',
        # Temples tagged by building/historic type even without a religion tag.
        '["building"="temple"]',
        '["historic"="temple"]',
    ],
    "tourist_attractions_and_heritage": [
        '["tourism"="attraction"]',
        '["historic"]',
    ],
    "parks_and_nature": [
        '["leisure"="park"]',
        '["leisure"="garden"]',
    ],
    "restaurants_and_cafes": [
        '["amenity"="restaurant"]',
        '["amenity"="cafe"]',
    ],
    "shopping_and_entertainment": [
        '["shop"]',
        '["amenity"~"^(cinema|theatre|arts_centre|nightclub)$"]',
    ],
}

CATEGORY_ALIASES = {
    # temples and spiritual places
    "temples_and_spiritual": "temples_and_spiritual",
    "temple": "temples_and_spiritual",
    "temples": "temples_and_spiritual",
    "spiritual": "temples_and_spiritual",
    "place_of_worship": "temples_and_spiritual",
    # tourist attractions and heritage
    "tourist_attractions_and_heritage": "tourist_attractions_and_heritage",
    "tourist_attractions": "tourist_attractions_and_heritage",
    "attraction": "tourist_attractions_and_heritage",
    "attractions": "tourist_attractions_and_heritage",
    "heritage": "tourist_attractions_and_heritage",
    "tourist": "tourist_attractions_and_heritage",
    "landmark": "tourist_attractions_and_heritage",
    # parks and nature
    "parks_and_nature": "parks_and_nature",
    "park": "parks_and_nature",
    "parks": "parks_and_nature",
    "nature": "parks_and_nature",
    "garden": "parks_and_nature",
    "gardens": "parks_and_nature",
    # restaurants and cafes
    "restaurants_and_cafes": "restaurants_and_cafes",
    "restaurant": "restaurants_and_cafes",
    "restaurants": "restaurants_and_cafes",
    "cafe": "restaurants_and_cafes",
    "cafes": "restaurants_and_cafes",
    "food": "restaurants_and_cafes",
    "dining": "restaurants_and_cafes",
    # shopping and entertainment
    "shopping_and_entertainment": "shopping_and_entertainment",
    "shopping": "shopping_and_entertainment",
    "entertainment": "shopping_and_entertainment",
    "mall": "shopping_and_entertainment",
}

SUPPORTED_CATEGORIES = sorted(CATEGORY_FILTERS.keys())


def resolve_category(category: str) -> Optional[str]:
    """Map a free-form category name to a canonical category key."""
    normalized = category.strip().lower().replace("-", "_").replace(" ", "_")
    return CATEGORY_ALIASES.get(normalized)


def _category_from_tags(tags: dict) -> Optional[str]:
    """Best-effort canonical category derived from raw OSM tags."""
    if tags.get("amenity") == "place_of_worship":
        # Only temple-tagged worship places count as temples; a mosque or
        # church with these tags belongs to no supported category.
        return "temples_and_spiritual" if _is_temple(tags) else None
    if "historic" in tags or tags.get("tourism") == "attraction":
        return "tourist_attractions_and_heritage"
    if tags.get("leisure") in ("park", "garden"):
        return "parks_and_nature"
    if tags.get("amenity") in ("restaurant", "cafe"):
        return "restaurants_and_cafes"
    if "shop" in tags or tags.get("amenity") in (
        "cinema", "theatre", "arts_centre", "nightclub"
    ):
        return "shopping_and_entertainment"
    return None


# ---------------------------------------------------------------------------
# Overpass query helpers
# ---------------------------------------------------------------------------


def _build_overpass_query(
    latitude: float,
    longitude: float,
    radius_km: float,
    tag_filters: list[str],
) -> str:
    around = f"around:{radius_km * 1000:.0f},{latitude},{longitude}"

    # The ["name"] filter keeps unnamed map features (benches, ATMs, minor
    # shops) out of the results: they carry no usable name for a UI.
    #
    # Node and way searches only, no relation searches: relations carry
    # multipolygon geometry whose evaluation dominated the query cost on
    # the degraded .fr instance (2026-11 live test: the node+way+relation
    # temple query for Pune timed out server-side, while node+way
    # variants complete; relation place-of-worship results are rare and
    # nearly always duplicate an existing node/way). Re-add relations
    # only if a real coverage gap shows up.
    statements = []
    for tag_filter in tag_filters:
        for element_type in ("node", "way"):
            statements.append(
                f'{element_type}({around}){tag_filter}["name"];'
            )

    body = "\n".join(statements)

    # Server-side timeout (20s) sits below the client read timeout
    # (25s) so Overpass always manages to answer - with results or with
    # its informative "Query timed out" remark - inside the client's
    # window. Measured on the degraded French instance (2026-11), a
    # server-side timeout answer arrived at ~30s, which the old 25s
    # client timeout cut off, turning an informative error into an
    # opaque read timeout.
    return (
        "[out:json][timeout:20];\n"
        "(\n"
        f"{body}\n"
        ");\n"
        "out center tags;"
    )


def _build_single_filter_query(
    latitude: float,
    longitude: float,
    radius_km: float,
    tag_filter: str,
    element_type: str,
) -> str:
    """One tag filter, one element type - the query shape the Overpass
    instance can always answer. Heavy unions time out server-side
    (2026-11 live test: historic node+way completes with 128 results in
    Mumbai while the tourism+historic union times out), so
    search_places issues one of these per filter/type and merges."""
    around = f"around:{radius_km * 1000:.0f},{latitude},{longitude}"
    return (
        "[out:json][timeout:20];\n"
        f"{element_type}({around}){tag_filter}[\"name\"];\n"
        "out center tags;"
    )


def _build_details_query(osm_type: str, osm_id: int) -> str:
    # Same timeout reasoning as _build_overpass_query: server answers
    # (result or remark) inside the 25s client read timeout.
    return (
        "[out:json][timeout:20];\n"
        f"({osm_type}({osm_id}););\n"
        "out center tags;"
    )


def _create_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(
            REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
        ),
        headers={"User-Agent": USER_AGENT},
    )


# Status codes where another mirror may genuinely have the answer
# (instance overloaded / rate limiting / upstream trouble). Any other
# HTTP error means the request itself is wrong, so falling back to
# another mirror would just repeat a doomed request.
_FALLBACK_HTTP_STATUSES = frozenset({502, 429, 504})


def _query_overpass(query: str) -> dict:
    """
    POST a query to the Overpass API, trying each configured mirror in turn.

    Fallback policy:
    - Connection errors and HTTP 502/429/504 (instance-level trouble)
      fall through to the next mirror immediately.
    - A read timeout fails fast: the instance accepted the connection
      but cannot answer in time, and the next mirror would most likely
      burn another full timeout on the same load. No retry storms.
    - Other HTTP errors mean the query itself is wrong, so there is no
      point asking another mirror.

    Returns the parsed JSON payload on success, or an {"error": ...} dict
    on any failure. Never raises for expected API problems. Errors are
    never cached (the caller handles that) and never masquerade as
    empty results.
    """
    last_error = None

    for url in OVERPASS_URLS:
        try:
            with _create_client() as client:
                response = client.post(
                    url,
                    data={"data": query},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()

            # A "remark" can arrive alongside an EMPTY "elements" array
            # (e.g. "runtime error: Query timed out"), which used to be
            # mistaken for a successful zero-result answer. Any remark
            # means the query did not fully complete: it is an error.
            remark = payload.get("remark") if isinstance(payload, dict) else None
            if isinstance(payload, dict) and "elements" in payload and not remark:
                return payload

            last_error = {
                "error": (
                    f"Overpass API could not complete the query: {remark}"
                    if remark
                    else "Overpass API response is missing place elements."
                )
            }
            # A remark is a completed server answer, not an instance
            # outage: another mirror would time out the same way.
            break

        except httpx.ConnectError:
            # Instance-level failure, cheap to detect: try next mirror.
            last_error = {
                "error": (
                    f"Could not connect to {url}. The Overpass "
                    "instance may be down."
                )
            }
            continue

        except httpx.TimeoutException as error:
            if isinstance(error, httpx.ConnectTimeout):
                # Connection never established: instance-level failure,
                # cheap to detect, try the next mirror.
                last_error = {
                    "error": (
                        f"Could not connect to {url}. The Overpass "
                        "instance may be down."
                    )
                }
                continue

            # Read timeout: fail fast, do not wait on another slow mirror.
            last_error = {
                "error": (
                    "Overpass API request timed out. Try a smaller radius "
                    "or a less dense category."
                )
            }
            break

        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in _FALLBACK_HTTP_STATUSES:
                last_error = {
                    "error": (
                        f"Overpass API returned HTTP {status} from {url}. "
                        "The instance is rate limiting or busy."
                    )
                }
                continue  # instance-level trouble: next mirror

            hint = "Check the query parameters."
            last_error = {
                "error": f"Overpass API returned HTTP {status}. {hint}"
            }
            break  # query-level problem: other mirrors will fail too

        except httpx.HTTPError as error:
            last_error = {"error": f"Overpass API request failed: {error}"}
            break

        except ValueError:
            last_error = {
                "error": "Overpass API returned an invalid JSON response."
            }
            break

    return last_error or {
        "error": "All Overpass API mirrors failed to respond."
    }


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, o1, r2, o2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (
        math.sin((r2 - r1) / 2) ** 2
        + math.cos(r1) * math.cos(r2) * math.sin((o2 - o1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _format_address(tags: dict) -> Optional[str]:
    """Build an address from OSM addr:* tags, or None when unavailable."""
    street_line = ""
    if tags.get("addr:street"):
        street_line = " ".join(
            part
            for part in (tags.get("addr:housenumber"), tags["addr:street"])
            if part
        )

    locality = ", ".join(
        tags[key]
        for key in ("addr:suburb", "addr:city")
        if tags.get(key)
    )

    lines = [line for line in (street_line, locality) if line]
    if tags.get("addr:postcode"):
        if lines:
            lines[-1] = f"{lines[-1]} {tags['addr:postcode']}"
        else:
            lines.append(tags["addr:postcode"])

    return ", ".join(lines) if lines else None


def _parse_element(
    element: dict,
    category: Optional[str],
    origin: Optional[tuple[float, float]],
) -> Optional[dict]:
    """Convert one Overpass element into structured place data."""
    tags = element.get("tags") or {}
    center = element.get("center") or {}

    # The query already filters on ["name"]; drop unnamed leftovers
    # defensively - a nameless place is useless for the UI.
    if not tags.get("name"):
        return None

    # Temples & Spiritual must list temples only: mosques, churches,
    # gurudwaras and other non-temple worship places are excluded here as
    # well, so an OSM entry that slipped through the query regex (missing
    # religion tag, mixed selectors) is still classified correctly.
    if category == "temples_and_spiritual" and not _is_temple(tags):
        return None

    latitude = element.get("lat", center.get("lat"))
    longitude = element.get("lon", center.get("lon"))

    if latitude is None or longitude is None:
        return None

    place_id = f"{element.get('type', 'node')}/{element.get('id')}"

    distance_km = None
    if origin is not None:
        distance_km = round(
            _haversine_km(origin[0], origin[1], latitude, longitude), 2
        )

    return {
        "id": place_id,
        "name": tags.get("name"),
        "category": category,
        "latitude": latitude,
        "longitude": longitude,
        "address": _format_address(tags),
        "opening_hours": tags.get("opening_hours"),
        "distance_km": distance_km,
        # Fame signals used for popularity-aware selection upstream:
        # a Wikipedia/Wikidata link means the place is documented and
        # widely recognised; the element type reflects OSM mapping
        # detail (ways = area features, usually larger attractions).
        "wikipedia": tags.get("wikipedia") or tags.get("wikidata"),
        # Food-tagged cuisine (e.g. "indian", "pizza") when present;
        # null - never invented - when OSM does not say.
        "cuisine": tags.get("cuisine"),
        "osm_type": element.get("type"),
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def clear_cache():
    """Empty the search cache (used by tests and after policy changes)."""
    with _cache_lock:
        _cache.clear()


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
            # Drop the oldest entry; keeps memory bounded.
            oldest = min(_cache, key=lambda k: _cache[k][0])
            del _cache[oldest]
        _cache[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# Public tool API
# ---------------------------------------------------------------------------


def _invalid_request(message: str) -> dict:
    return {
        "error": message,
        "supported_categories": SUPPORTED_CATEGORIES,
        "total_results": 0,
        "places": [],
    }


def search_places(
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    category: str = "tourist_attractions_and_heritage",
) -> dict:
    """
    Search places around a coordinate using OpenStreetMap data.

    Returns {"total_results": n, "category": ..., "places": [...]} where
    each place carries id (OSM type/ID), name, category, latitude,
    longitude and, when available, address and opening_hours. Missing
    information is null, never invented.
    """
    if not -90 <= latitude <= 90:
        return _invalid_request(
            f"latitude must be between -90 and 90, got {latitude}"
        )
    if not -180 <= longitude <= 180:
        return _invalid_request(
            f"longitude must be between -180 and 180, got {longitude}"
        )
    if not 0 < radius_km <= MAX_RADIUS_KM:
        return _invalid_request(
            f"radius_km must be between 0 and {MAX_RADIUS_KM}, "
            f"got {radius_km}"
        )

    canonical = resolve_category(category) if category else None
    if canonical is None:
        return _invalid_request(
            f"Unknown category '{category}'. Supported categories: "
            + ", ".join(SUPPORTED_CATEGORIES)
        )

    cache_key = (
        round(latitude, 4),
        round(longitude, 4),
        round(radius_km, 2),
        canonical,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # First try the single union query (one request on healthy
    # instances). A union can time out server-side when any one
    # statement is heavy (the tourism=attraction ways scan), which used
    # to zero out the whole category; in that case retry per filter
    # and element type so one heavy statement no longer erases the
    # results the lighter statements would have returned.
    origin = (latitude, longitude)
    elements: list[dict] = []
    union_failed = False

    query = _build_overpass_query(
        latitude, longitude, radius_km, CATEGORY_FILTERS[canonical]
    )
    payload = _query_overpass(query)
    union_error = payload.get("error") if "error" in payload else None
    if union_error is None:
        elements.extend(payload.get("elements", []))
    elif union_error.startswith("Overpass API request timed out") or "could not complete the query" in union_error:
        # A timeout (client read timeout or server remark) is
        # query-size dependent: smaller per-filter queries can still
        # answer where the union could not (2026-11 live test: the
        # tourism+historic union timed out in Mumbai while the
        # historic-only query returned 128 results). Retry per filter
        # and element type; if EVERY part fails too, surface the
        # original union error. Other error kinds (HTTP 4xx/5xx,
        # connection failures) are instance- or query-wide - fail fast.
        # The fail-fast rule for mirrors still holds inside
        # _query_overpass: each per-filter query is a SMALLER query,
        # not the same doomed request re-sent.
        all_parts_failed = True

        def run_part(tag_filter: str, element_type: str) -> tuple[str, dict]:
            query = _build_single_filter_query(
                latitude, longitude, radius_km, tag_filter, element_type
            )
            return f"{element_type}{tag_filter}", _query_overpass(query)

        # The per-filter queries are independent - run them concurrently
        # so the fallback costs one query's latency, not the sum of all.
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(CATEGORY_FILTERS[canonical]) * 2
        ) as executor:
            futures = [
                executor.submit(run_part, tag_filter, element_type)
                for tag_filter in CATEGORY_FILTERS[canonical]
                for element_type in ("node", "way")
            ]
            for future in concurrent.futures.as_completed(futures):
                _, payload = future.result()
                if "error" in payload:
                    continue
                all_parts_failed = False
                elements.extend(payload.get("elements", []))

        if all_parts_failed:
            # Do not cache failures: the next call may succeed.
            return {"error": union_error}
    else:
        # Do not cache failures: the next call may succeed.
        return {"error": union_error}

    # Dedupe by OSM identity: the same element can come back from more
    # than one filter/type query.
    seen_ids = set()
    places = []
    for element in elements:
        key = (element.get("type"), element.get("id"))
        if key in seen_ids:
            continue
        seen_ids.add(key)
        place = _parse_element(element, canonical, origin)
        if place is not None:
            places.append(place)

    places.sort(key=lambda place: place["distance_km"] or 0.0)
    places = places[:MAX_RESULTS]

    result = {
        "total_results": len(places),
        "category": canonical,
        "places": places,
    }
    _cache_set(cache_key, result)
    return result


def get_place_details(place_id: str) -> dict:
    """
    Retrieve details of a place by its OpenStreetMap ID.

    place_id has the form "<osm_type>/<osm_id>", e.g. "node/123456789",
    exactly the id values returned by search_places.
    """
    if not isinstance(place_id, str) or place_id.count("/") != 1:
        return {
            "error": (
                "place_id must have the form '<osm_type>/<osm_id>', "
                'for example "node/123456789"'
            )
        }

    # Accept the data-source-prefixed ids the /api/plan response uses
    # ("live_node/123") as well as bare OSM ids ("node/123"): the plan
    # pipeline prefixes ids with the data source, and the Android client
    # passes them back verbatim when opening place details.
    if place_id.startswith(("live_", "mock_")):
        place_id = place_id.split("_", 1)[1]

    osm_type, raw_id = place_id.split("/")
    if osm_type not in ("node", "way", "relation"):
        return {"error": f"Unknown OSM type '{osm_type}' in place_id"}
    try:
        osm_id = int(raw_id)
    except ValueError:
        return {"error": f"OSM id must be an integer, got '{raw_id}'"}

    payload = _query_overpass(_build_details_query(osm_type, osm_id))

    if "error" in payload:
        return payload

    elements = payload.get("elements", [])
    if not elements:
        return {"error": f"Place with ID {place_id} not found"}

    element = elements[0]
    tags = element.get("tags") or {}
    center = element.get("center") or {}

    latitude = element.get("lat", center.get("lat"))
    longitude = element.get("lon", center.get("lon"))

    return {
        "id": f"{element.get('type', osm_type)}/{element.get('id', osm_id)}",
        "name": tags.get("name"),
        "category": _category_from_tags(tags),
        "latitude": latitude,
        "longitude": longitude,
        "address": _format_address(tags),
        "opening_hours": tags.get("opening_hours"),
        "website": tags.get("website") or tags.get("contact:website"),
        "phone": tags.get("phone") or tags.get("contact:phone"),
        "tags": tags,
    }
