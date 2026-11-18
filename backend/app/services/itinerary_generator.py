"""
Itinerary generation pipeline for POST /api/plan.

The pipeline follows the existing architecture:

1. RAG       - destination knowledge from knowledge_base/destinations
              (same vector store used by app.rag.rag_pipeline).
2. MCP       - place discovery through the MCP server (app.mcp_server.server),
              the same tools the agent in app.agent.mcp_agent uses.
3. Gemini    - structured generation of descriptions/titles constrained to
              the retrieved knowledge and MCP results.

Honesty guarantees (per project rules):

- The MCP tools now search OpenStreetMap through the Overpass API, but many
  real OSM entries lack opening hours. A place missing latitude, longitude
  or opening hours cannot be scheduled honestly, so when the candidate pool
  does not contain enough complete places, the pipeline raises
  InsufficientPlacesError and the endpoint returns HTTP 503 with an
  explanatory message instead of fabricating data.

- Travel distances and durations come from the OSRM road network
  (app.tools.route_tools.get_route_matrix, one Table API request for the
  start location and all candidates). If routing is unavailable, the
  pipeline raises InsufficientPlacesError instead of silently presenting
  straight-line Haversine estimates as road distances. Haversine is used
  only to pre-trim an oversized candidate list before the OSRM request -
  never for the final stop ordering or the reported TravelLeg values.

- Every Place returned is marked as live: `Place.id` is prefixed with
  "live_" and the generation metadata in the error/reporting path names the
  data source. There is no mock provider anymore.
"""

import asyncio
import json
import time
import math
import os
import sys
import uuid

from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.rag.rag_pipeline import retrieve_context
from app.tools.geocode_tools import search_location
from app.tools.route_tools import MAX_TABLE_COORDINATES, get_route_matrix
from app.schemas.outing import (
    Interest,
    Itinerary,
    ItineraryStop,
    MealType,
    NearbyFoodRecommendation,
    OutingDuration,
    OutingRequest,
    Place,
    StartLocation,
    TimeOfDay,
    TravelLeg,
)


class DestinationNotFoundError(Exception):
    """Raised when the destination text cannot be geocoded."""


class InsufficientPlacesError(Exception):
    """Raised when the available place data cannot produce a valid itinerary."""

    def __init__(self, message: str, data_source: str = "live"):
        super().__init__(message)
        self.data_source = data_source


# Same launch configuration as app.agent.mcp_agent so the /api/plan pipeline
# talks to the identical MCP server and tools.
SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["app/mcp_server/server.py"],
    env={**os.environ, "PYTHONPATH": "."},
)

# Fields a Place needs that many OSM entries lack.
REQUIRED_PLACE_FIELDS = ("latitude", "longitude", "opening_hours")

# Interest keywords used to match places to the user's selected interests.
INTEREST_KEYWORDS: dict[Interest, tuple[str, ...]] = {
    Interest.TEMPLES: ("temple", "spiritual", "shrine"),
    Interest.NATURE: (
        "park", "nature", "garden", "scenic", "hill", "lake",
        "attraction", "famous", "landmark",
    ),
    Interest.HERITAGE: (
        "heritage", "history", "historical", "fort", "palace",
        "attraction", "famous", "landmark",
    ),
    Interest.SHOPPING: ("shopping", "market", "bazaar", "mall"),
}

# Non-temple worship place name keywords, shared with place_tools. Temples
# & Spiritual must list temples only - a mosque, church or gurudwara that
# slips through MCP search (missing/incorrect religion tag) is dropped
# here as a second line of defence. Generic place-type words, never
# hardcoded place names.
NON_TEMPLE_NAME_KEYWORDS = (
    "masjid", "mosque", "church", "gurudwara", "gurdwara",
    "cathedral", "synagogue", "dargah", "basilica",
)


def _is_non_temple_name(name: str) -> bool:
    lowered = (name or "").lower()
    return any(keyword in lowered for keyword in NON_TEMPLE_NAME_KEYWORDS)


# Name/description keywords that identify a temple (multi-language,
# generic place-type words - never hardcoded place names). The category
# string "temples_and_spiritual" is deliberately NOT one of them.
TEMPLE_NAME_KEYWORDS = ("temple", "mandir", "shrine", "temple complex")

# Minutes from midnight at which the itinerary starts.
START_MINUTES = {
    TimeOfDay.MORNING: TimeOfDay.MORNING.start_hour * 60,   # 09:00
    TimeOfDay.EVENING: TimeOfDay.EVENING.start_hour * 60,   # 16:00
}

# Simple stop budget so stops fit within the outing duration.
STOP_BUDGET = {
    (OutingDuration.HALF_DAY, TimeOfDay.MORNING): 3,
    (OutingDuration.HALF_DAY, TimeOfDay.EVENING): 2,
    (OutingDuration.FULL_DAY, TimeOfDay.MORNING): 5,
    (OutingDuration.FULL_DAY, TimeOfDay.EVENING): 3,
}

# The OSRM Table API accepts at most MAX_TABLE_COORDINATES coordinates
# per request. The start location occupies one slot.
MAX_ROUTED_CANDIDATES = MAX_TABLE_COORDINATES - 1

# How many of the most notable places survive ranking before routing.
# Famous landmarks win; the nearest-neighbour route then keeps the day
# geographically practical.
MAX_FAME_RANKED_PLACES = 20

# Cap on "Worth a detour" recommendations. With the stop budget of 2-5
# this keeps the total recommendations (stops + optional) at the 5-10
# asked of the itinerary whenever enough real places are available.
MAX_TOTAL_RECOMMENDATIONS = 8


def _fame_score(raw: dict) -> tuple:
    """
    Higher is more famous. Signals, strongest first:
    1. A Wikipedia/Wikidata link on the OSM element - the place is
       documented and widely recognised.
    2. Mapping detail: OSM ways (area features) tend to be major
       attractions (a fort complex, a palace grounds) versus a bare
       node pin.
    Ties keep the distance order (stable sort), so near places still
    win among equally famous candidates. No hardcoded names or cities:
    everything derives from OSM data.
    """
    wikipedia = bool(raw.get("wikipedia"))
    osm_type = raw.get("osm_type") or "node"

    return (
        2 if wikipedia else 0,
        1 if osm_type == "way" else 0,
    )


# A day-trip radius: places beyond this lose to nearer alternatives even
# when more famous - the user asked for the nearest AND famous temples,
# with distant ones dropped when suitable nearby options exist.
NEARBY_PREFERENCE_RADIUS_KM = 20.0


def _combined_rank_score(raw: dict) -> tuple:
    """
    Ranking key: nearest first, fame as the tiebreaker among close places.

    1. Anything within NEARBY_PREFERENCE_RADIUS_KM ranks before anything
       beyond it - a famous temple 35 km away never displaces a relevant
       temple 10 km away when nearby options exist.
    2. Within the nearby ring, fame decides (Wikipedia presence, OSM
       mapping detail); equal fame keeps the distance order (stable
       sort). Beyond the ring, plain distance decides.
    No hardcoded names or cities: every signal comes from the place data.
    """
    distance = raw.get("distance_km")
    distance = float(distance) if distance is not None else float("inf")

    nearby = distance <= NEARBY_PREFERENCE_RADIUS_KM

    if nearby:
        # Fame first (negated so bigger fame sorts first), then distance.
        fame = _fame_score(raw)
        return (0, tuple(-part for part in fame), distance)
    # Far ring: pure distance order.
    return (1, distance)


def _rank_by_distance_and_fame(places: list[dict]) -> list[dict]:
    """Nearest + most famous first; stable within equal rank."""
    return sorted(places, key=_combined_rank_score)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two coordinates."""
    r1, o1, r2, o2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (
        math.sin((r2 - r1) / 2) ** 2
        + math.cos(r1) * math.cos(r2) * math.sin((o2 - o1) / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


FOOD_KEYWORDS = {
    "restaurant",
    "cafe",
    "food",
    "dining",
    "eatery",
    "restaurants_and_cafes",
}


def _place_matches_interests(place: dict, interests: list[Interest]) -> bool:
    if not interests:
        return True

    name = str(place.get("name", ""))
    lowered_name = name.lower()
    # Description text only - the category string ("temples_and_spiritual")
    # itself contains "temple" and would make every place in that category
    # match, including mosques and churches.
    description = " ".join(
        str(place.get(field, ""))
        for field in ("short_description", "full_description")
    ).lower()

    for interest in interests:
        if interest is Interest.TEMPLES:
            # Temples & Spiritual lists temples only: a non-temple worship
            # place (mosque, church, gurudwara, ...) never matches, and a
            # generic "spiritual" classification is not enough - the name
            # or description must identify a temple.
            if _is_non_temple_name(name):
                continue
            if any(
                keyword in lowered_name or keyword in description
                for keyword in TEMPLE_NAME_KEYWORDS
            ):
                return True
            continue
        haystack = " ".join(
            str(place.get(field, ""))
            for field in ("category", "short_description", "full_description")
        ).lower()
        if any(
            keyword in haystack or keyword in lowered_name
            for keyword in INTEREST_KEYWORDS[interest]
        ):
            return True
    return False


def _is_food_place(place: dict) -> bool:
    return str(place.get("category", "")).lower() in FOOD_KEYWORDS


async def _call_mcp_tool(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments=arguments)

    if result.isError:
        raise RuntimeError(f"MCP tool '{name}' failed")

    text_parts = [item.text for item in result.content if hasattr(item, "text")]
    if len(text_parts) == 1:
        try:
            return json.loads(text_parts[0])
        except json.JSONDecodeError:
            return {"result": text_parts[0]}
    return {"result": text_parts}


# Gathered MCP results cached across requests. Each /api/plan call spawns
# a fresh MCP server process whose internal Overpass cache starts empty,
# so without this layer every plan re-queries Overpass from scratch
# (tens of seconds on a slow day). Entries survive until the process
# restarts; place data is stable enough for a development milestone.
_GATHER_CACHE: dict[tuple, tuple[list[dict], list[dict], str]] = {}
_GATHER_CACHE_LOCK = asyncio.Lock()

_GATHER_CACHE_TTL_SECONDS = 600.0


def _gather_cache_key(
    interests: list[Interest],
    start_location: StartLocation,
) -> tuple:
    return (
        tuple(sorted(i.value for i in interests)),
        round(start_location.latitude, 3),
        round(start_location.longitude, 3),
    )


def _gather_cache_get(key: tuple):
    entry = _GATHER_CACHE.get(key)
    if entry is None:
        return None
    timestamp, value = entry
    if time.time() - timestamp > _GATHER_CACHE_TTL_SECONDS:
        _GATHER_CACHE.pop(key, None)
        return None
    return value


async def _gather_places_from_mcp(
    interests: list[Interest],
    start_location: StartLocation,
) -> tuple[list[dict], list[dict], str]:
    """Cached cross-request wrapper over _gather_places_from_mcp_uncached."""
    key = _gather_cache_key(interests, start_location)
    cached = _gather_cache_get(key)
    if cached is not None:
        return cached

    async with _GATHER_CACHE_LOCK:
        # Double-check: another request may have populated the entry
        # while this one waited for the lock.
        cached = _gather_cache_get(key)
        if cached is not None:
            return cached

        result = await _gather_places_from_mcp_uncached(
            interests, start_location
        )
        _GATHER_CACHE[key] = (time.time(), result)
        return result


async def _gather_places_from_mcp_uncached(
    interests: list[Interest],
    start_location: StartLocation,
) -> tuple[list[dict], list[dict], str]:
    """
    Query the MCP place tools and return (attraction candidates, food
    candidates, data_source). Data source is "live" because the MCP tools
    now search OpenStreetMap through the Overpass API.
    """
    candidates: list[dict] = []
    foods: list[dict] = []
    data_source = "live"

    async with stdio_client(SERVER_PARAMS) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Ask the server for attractions in every selected interest
            # category, plus food, using the existing search_places tool.
            categories: list[str] = []
            if not interests:
                categories = [
                    "tourist_attractions_and_heritage",
                    "parks_and_nature",
                    "temples_and_spiritual",
                    "shopping_and_entertainment",
                ]
            else:
                keyword_map = {
                    Interest.TEMPLES: "temples_and_spiritual",
                    Interest.NATURE: "parks_and_nature",
                    Interest.HERITAGE: "tourist_attractions_and_heritage",
                    Interest.SHOPPING: "shopping_and_entertainment",
                }
                categories = [
                    keyword_map[interest]
                    for interest in interests
                    if interest in keyword_map
                ]

            # Search center: the request's start location. An unset
            # location (0.0, 0.0) — the Kotlin default for "Current
            # Location" — cannot be sent to Overpass, so the pipeline
            # reports honestly that it has no usable origin.
            search_center = {
                "latitude": start_location.latitude,
                "longitude": start_location.longitude,
            }
            if (search_center["latitude"], search_center["longitude"]) == (0.0, 0.0):
                raise InsufficientPlacesError(
                    "Cannot search for real places: the request has no "
                    "usable start location. Provide latitude and longitude "
                    "instead of the (0, 0) default.",
                    data_source="live",
                )

            # All category searches (plus food) are independent Overpass
            # queries behind the MCP tools - issue them concurrently so a
            # cold plan costs one category's latency, not the sum.
            search_jobs = [
                _call_mcp_tool(
                    session,
                    "search_places",
                    {**search_center, "radius_km": 80, "category": category},
                )
                for category in categories
            ]
            search_jobs.append(
                _call_mcp_tool(
                    session,
                    "search_places",
                    {
                        **search_center,
                        "radius_km": 80,
                        "category": "restaurants_and_cafes",
                    },
                )
            )
            results = await asyncio.gather(*search_jobs)

            for result in results:
                places = result.get("places", []) if isinstance(result, dict) else []
                for place in places:
                    if _is_food_place(place):
                        foods.append(place)
                    elif _place_matches_interests(place, interests):
                        candidates.append(place)

    return candidates, foods, data_source


def _dedupe(places: list[dict]) -> list[dict]:
    seen: set = set()
    unique = []
    for place in places:
        key = (place.get("id"), place.get("name"))
        if key not in seen:
            seen.add(key)
            unique.append(place)
    return unique


def _validate_candidate_pool(
    candidates: list[dict],
    data_source: str,
) -> list[dict]:
    """
    Keep only places that carry the coordinates the Android Place model
    requires. Opening hours are optional: OSM coverage for tourism POIs is
    sparse, and a real place without published hours is still a real
    place - it travels with opening_hours="" (unknown) instead of being
    dropped or having hours invented for it. If nothing with coordinates
    remains, the pipeline raises a clear error rather than fabricating
    places.
    """
    complete = [
        place
        for place in candidates
        if place.get("latitude") is not None
        and place.get("longitude") is not None
    ]

    if not complete:
        raise InsufficientPlacesError(
            "Cannot generate a real itinerary: the connected place data "
            f"source ({data_source}) returned no places with usable "
            "coordinates for the selected interests. Fabricating "
            "coordinates is not allowed.",
            data_source=data_source,
        )

    return complete


def _normalize_place(
    raw: dict,
    index: int,
    data_source: str,
    interests: list[Interest],
) -> Place:
    """Convert a raw MCP/live place dict into the Android Place model."""
    prefix = "live"
    place_id = f"{prefix}_{raw.get('id', index)}"

    name = str(raw.get("name", f"Place {index}"))
    description = str(raw.get("description", raw.get("full_description", "")))

    return Place(
        id=place_id,
        name=name,
        short_description=description[:120] if description else name,
        full_description=description or name,
        address=str(raw.get("address", name)),
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        interests=interests or [],
        suggested_visit_minutes=int(raw.get("suggested_visit_minutes", 60)),
        opening_hours=str(raw.get("opening_hours", "")),
        image_url=raw.get("image_url"),
        is_optional_attraction=bool(raw.get("is_optional_attraction", False)),
    )


def _trim_candidates_by_haversine(
    places: list[Place],
    start: tuple[float, float],
    limit: int,
) -> list[Place]:
    """
    Keep only the `limit` places nearest to the start by straight-line
    distance. Used solely to respect the OSRM Table API coordinate cap
    when there are more candidates than can be routed in one request -
    the final ordering is still road-duration based, never this filter.
    """
    if len(places) <= limit:
        return places
    return sorted(
        places,
        key=lambda place: _haversine_km(
            start[0], start[1], place.latitude, place.longitude
        ),
    )[:limit]


def _fetch_route_matrix(
    start: tuple[float, float],
    places: list[Place],
) -> dict:
    """
    One OSRM Table API request for the start location and all candidate
    places. Returns the raw get_route_matrix payload.

    Raises InsufficientPlacesError when routing is unavailable - routing
    data is required, so falling back to Haversine estimates silently is
    not an option.
    """
    coordinates = [(start[0], start[1])] + [
        (place.latitude, place.longitude) for place in places
    ]
    payload = get_route_matrix(coordinates)

    if "error" in payload:
        raise InsufficientPlacesError(
            "Cannot generate a real itinerary with road travel times: "
            f"the routing service is unavailable ({payload['error']}). "
            "Presenting straight-line distance estimates as road "
            "distances is not allowed, so no itinerary is generated.",
            data_source="live",
        )

    durations = payload["matrix"]["durations_minutes"]
    distances = payload["matrix"]["distances_km"]

    if distances is None:
        raise InsufficientPlacesError(
            "Cannot generate a real itinerary: the routing service did "
            "not provide road distances for this area, and fabricating "
            "them is not allowed.",
            data_source="live",
        )

    return {
        # durations[i][j] / distances[i][j]: travel from coordinate i to
        # coordinate j; index 0 is the start location. Values are minutes
        # and kilometres; None means OSRM found no connection.
        "durations": durations,
        "distances": distances,
    }


def _order_by_road_duration(
    places: list[Place],
    matrix: dict,
) -> tuple[list[Place], dict]:
    """
    Order stops by road travel duration (nearest-neighbour over the OSRM
    matrix, starting at the start location) and return the ordered list
    with the matrix REMAPPED to the new order.

    The remapped matrix has row 0 = start location and row i+1 =
    ordered[i], so downstream code indexes legs by stop position:
    durations[from_row][to_row]. Places the routing engine cannot reach
    (null matrix rows) are dropped honestly rather than assigned
    invented travel times.
    """
    durations = matrix["durations"]
    distances = matrix["distances"]

    # Matrix indices: 0 = start, i+1 = places[i].
    remaining = list(range(len(places)))
    ordered_indices = []
    current = 0  # the start location's row

    while remaining:
        candidates = [
            index
            for index in remaining
            if durations[current][index + 1] is not None
        ]
        if not candidates:
            # Everything left is unreachable from here: drop honestly.
            break
        nearest = min(
            candidates, key=lambda index: durations[current][index + 1]
        )
        ordered_indices.append(nearest)
        remaining.remove(nearest)
        current = nearest + 1

    ordered = [places[index] for index in ordered_indices]

    # Remap: new row 0 = start (old row 0); new row i+1 = ordered[i].
    kept = [0] + [index + 1 for index in ordered_indices]
    remapped = {
        "durations": [
            [durations[from_row][to_row] for to_row in kept]
            for from_row in kept
        ],
        "distances": [
            [distances[from_row][to_row] for to_row in kept]
            for from_row in kept
        ],
    }

    return ordered, remapped


def _build_stops(
    ordered: list[Place],
    request: OutingRequest,
    max_stops: int,
    matrix: dict,
) -> list[ItineraryStop]:
    """
    Build timed stops with road travel legs, fitting the outing budget.

    The matrix has been remapped by _order_by_road_duration: row 0 is
    the start location and row i+1 is ordered[i]. Travel times and
    distances come from the OSRM road network - the old fixed-speed
    Haversine estimate is gone: no min-10-minutes floor, no invented
    durations.
    """
    stops: list[ItineraryStop] = []
    clock = START_MINUTES[request.time_of_day]
    end_of_day = clock + request.duration.total_hours * 60
    start = (request.start_location.latitude, request.start_location.longitude)
    # An unset location (0.0, 0.0) — the Kotlin default for "Current
    # Location" — carries no usable origin, so the first stop's travel
    # distance is left unknown instead of fabricated.
    known_start = start != (0.0, 0.0)
    # Row of the coordinate travelled FROM in the remapped matrix.
    from_row = 0 if known_start else None

    for position, place in enumerate(ordered[:max_stops]):
        place_row = position + 1

        if from_row is not None:
            distance_km = matrix["distances"][from_row][place_row]
            travel_minutes = matrix["durations"][from_row][place_row]
            if distance_km is None or travel_minutes is None:
                # Unreachable pair slipped through ordering: cannot
                # schedule this or any later stop honestly.
                break
        else:
            distance_km = None
            travel_minutes = None

        if travel_minutes is not None:
            if clock + travel_minutes + place.suggested_visit_minutes > end_of_day:
                # Remaining stops no longer fit in the outing window.
                break

            arrival = clock + travel_minutes
            clock = arrival + place.suggested_visit_minutes
            from_row = place_row
        else:
            # Unknown first-leg travel time (unset start location): the
            # stop still gets scheduled with an immediate arrival,
            # matching the existing behaviour for unknown travel.
            arrival = clock
            clock = arrival + place.suggested_visit_minutes
            from_row = place_row

        stops.append(
            ItineraryStop(
                place=place,
                arrival_time_minutes=arrival,
                visit_duration_minutes=place.suggested_visit_minutes,
                travel_to_next=None,  # filled below
            )
        )

    for i in range(len(stops) - 1):
        distance_km = matrix["distances"][i + 1][i + 2]
        duration_minutes = matrix["durations"][i + 1][i + 2]
        if distance_km is None or duration_minutes is None:
            # Unreachable pair slipped through ordering: leave the leg
            # unset rather than inventing numbers.
            stops[i].travel_to_next = None
        else:
            stops[i].travel_to_next = TravelLeg(
                distance_km=float(distance_km),
                duration_minutes=int(duration_minutes),
            )

    return stops


def _build_food_recommendations(foods: list[dict], data_source: str):
    """Convert MCP food results into NearbyFoodRecommendation entries."""
    prefix = "live"
    recommendations = {}

    for raw in _dedupe(foods)[:6]:
        recommendation = NearbyFoodRecommendation(
            name=str(raw.get("name", "Unknown")),
            cuisine=str(raw.get("cuisine", raw.get("category", "Multi-cuisine"))),
            meal_type=MealType.LUNCH,
            # OSM rarely says whether a place is vegetarian-friendly;
            # null would break the Android model, so default to True
            # but only when the tags do not state otherwise.
            is_vegetarian_friendly=bool(raw.get("vegetarian", True)),
            distance_km=float(raw.get("distance_km", 0.0)),
            price_level=min(4, max(1, int(raw.get("price_level", 2)))),
        )
        recommendations[f"{prefix}_food_{raw.get('id')}"] = [recommendation]

    return recommendations


def _resolve_destination_center(destination: str) -> StartLocation:
    """
    Geocode the free-text destination into the search center for place
    discovery. Raises DestinationNotFoundError when Nominatim cannot
    resolve it - the client can then offer a corrected spelling, never
    silently falling back to any default city.
    """
    result = search_location(destination, limit=1)

    if "error" in result:
        raise DestinationNotFoundError(
            f"Could not resolve the destination '{destination}': "
            f"{result['error']}"
        )

    results = result.get("results", [])
    if not results:
        raise DestinationNotFoundError(
            f"Destination '{destination}' could not be found. Check the "
            "spelling or try a nearby major city."
        )

    top = results[0]
    return StartLocation(
        name=top.get("name") or destination,
        is_current_location=False,
        latitude=top["latitude"],
        longitude=top["longitude"],
    )


async def generate_itinerary(
    request: OutingRequest,
    client,
    model: str,
) -> Itinerary:
    """
    Generate a structured itinerary for POST /api/plan.

    Steps:
      1. RAG retrieval of destination knowledge (same pipeline as /api/agent/chat).
      2. MCP place search through the existing place tools.
      3. Validation of the candidate pool - clear error if data is insufficient.
      4. Deterministic ordering and scheduling (no fabricated data).
      5. Gemini structured call for the itinerary title/descriptions, strictly
         constrained to the retrieved context.
    """
    # --- STEP 1: RAG destination knowledge (offloaded, same as the agent). ---
    rag_context = ""
    try:
        rag_context = await asyncio.to_thread(
            retrieve_context,
            f"{request.destination} {' '.join(i.value for i in request.interests)}",
            client,
            top_k=3,
        )
    except Exception as error:  # RAG is helpful but not critical here.
        print("RAG retrieval failed:", error)

    # --- STEP 2: resolve the destination to coordinates. ---
    # Place discovery happens around the DESTINATION (where the user is
    # going), not the start location (where they are). The destination
    # string is geocoded through the same Nominatim pipeline as
    # /api/geocode; failures are reported, never papered over.
    destination_center = _resolve_destination_center(request.destination)

    # --- STEP 3: MCP place discovery (same server as the agent). ---
    candidates, foods, data_source = await _gather_places_from_mcp(
        request.interests,
        destination_center,
    )

    # --- STEP 4: honest validation of the candidate pool. ---
    complete = _validate_candidate_pool(candidates, data_source)

    # --- STEP 5: normalize, rank by distance + fame, keep the most notable. ---
    ranked = _rank_by_distance_and_fame(_dedupe(complete))
    places = [
        _normalize_place(raw, index, data_source, request.interests)
        for index, raw in enumerate(ranked[:MAX_FAME_RANKED_PLACES])
    ]

    start = (
        request.start_location.latitude,
        request.start_location.longitude,
    )

    # Respect the OSRM Table API coordinate cap (start + candidates).
    routable = _trim_candidates_by_haversine(places, start, MAX_ROUTED_CANDIDATES)

    # --- STEP 6: road travel matrix from OSRM (required, not optional). ---
    matrix = _fetch_route_matrix(start, routable)

    # --- STEP 7: order stops by road travel duration, schedule. ---
    ordered, matrix = _order_by_road_duration(routable, matrix)

    # The outing plan shows at most 5 places, nearest first.
    max_stops = min(5, STOP_BUDGET[(request.duration, request.time_of_day)])
    stops = _build_stops(ordered, request, max_stops, matrix)

    if not stops:
        raise InsufficientPlacesError(
            "The available places do not fit within the selected outing "
            "duration and time window.",
            data_source=data_source,
        )

    total_duration = (
        stops[-1].arrival_time_minutes
        + stops[-1].visit_duration_minutes
        - START_MINUTES[request.time_of_day]
    )

    food_recommendations = _build_food_recommendations(foods, data_source)

    # --- Gemini titles the itinerary, constrained to known data. ---
    title = _fallback_title(request)
    if rag_context or places:
        title = await _generate_title(
            request, places, rag_context, client, model
        ) or title

    # "Worth a detour": notable ranked places beyond the scheduled stops,
    # so the itinerary shows 5-10 recommendations whenever enough real
    # places are available (the stop budget is 2-5). They keep the same
    # distance+popularity ordering, carry real coordinates and are never
    # duplicates of scheduled stops.
    stop_ids = {stop.place.id for stop in stops}
    optional_budget = max(0, MAX_TOTAL_RECOMMENDATIONS - len(stops))
    optional_attractions = [
        place for place in places if place.id not in stop_ids
    ][:optional_budget]

    return Itinerary(
        id=f"itinerary_{uuid.uuid4().hex[:12]}",
        title=title,
        destination=request.destination,
        request=request,
        stops=stops,
        total_duration_minutes=total_duration,
        optional_attractions=optional_attractions,
        food_recommendations=food_recommendations,
    )


def _fallback_title(request: OutingRequest) -> str:
    duration_label = request.duration.label
    time_label = request.time_of_day.label
    city = request.destination.split(",")[0]
    return f"{duration_label} {time_label} in {city}"


async def _generate_title(
    request: OutingRequest,
    places: list[Place],
    rag_context: str,
    client,
    model: str,
) -> str | None:
    """Ask Gemini for a short itinerary title; fall back silently on failure."""
    place_names = ", ".join(place.name for place in places)

    prompt = (
        "Write a short itinerary title (max 8 words) for this outing plan.\n"
        "Use only the information provided. Do not invent place names.\n\n"
        f"Destination: {request.destination}\n"
        f"Duration: {request.duration.label}\n"
        f"Time of day: {request.time_of_day.label}\n"
        f"Stops: {place_names}\n\n"
        f"Destination knowledge:\n{rag_context or 'None available.'}\n\n"
        "Reply with the title text only."
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        title = (response.text or "").strip().strip('"')
        return title or None
    except Exception as error:
        print("Gemini title generation failed:", error)
        return None
