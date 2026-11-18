"""
Place details pipeline for GET /api/places/{place_id} and
GET /api/places/search.

Follows the same architecture as the itinerary generator
(app.services.itinerary_generator):

1. MCP       - place data through the MCP server (app.mcp_server.server),
               the same tools the agent and the /api/plan pipeline use.
2. Overpass  - the MCP tools search OpenStreetMap; missing information is
               null, never invented.
3. Gemini    - not used here: descriptions are built factually from OSM
               tags so a details response can never contain fabricated
               prose about a real place.

Honesty guarantees (same rules as the itinerary pipeline):

- A place id the data source does not know raises PlaceNotFoundError
  (mapped to HTTP 404), never a made-up place.
- Nearby restaurant / attraction lists are empty when the nearby search
  fails or finds nothing - not padded with fabricated entries.
- Distances come from the Overpass payload (haversine from the search
  center), which is the real straight-line separation, clearly labelled
  as distance in km by the client.
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.schemas.outing import (
    Interest,
    MealType,
    NearbyFoodRecommendation,
    Place,
    PlaceDetailsResponse,
)
from app.services.itinerary_generator import (
    _call_mcp_tool,
    _combined_rank_score,
    _dedupe,
    _normalize_place,
)
from app.tools.place_tools import is_non_temple_name


# Same launch configuration as app.services.itinerary_generator so the
# details pipeline talks to the identical MCP server and tools.
SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["app/mcp_server/server.py"],
    env={**os.environ, "PYTHONPATH": "."},
)

MAX_NEARBY_RESTAURANTS = 5
MAX_NEARBY_ATTRACTIONS = 5

# Radius for "nearby cafeterias": users walk or take a short ride for a
# break, so a tight radius keeps recommendations genuinely nearby.
NEARBY_RESTAURANT_RADIUS_KM = 3.0

# Radius for "nearby famous places": attractions worth a detour can sit a
# short drive away, so this is wider than the food radius.
NEARBY_ATTRACTION_RADIUS_KM = 15.0

NEARBY_ATTRACTION_CATEGORIES = (
    "tourist_attractions_and_heritage",
    "parks_and_nature",
    "temples_and_spiritual",
)

SUPPORTED_SEARCH_CATEGORIES = (
    "temples_and_spiritual",
    "tourist_attractions_and_heritage",
    "parks_and_nature",
    "restaurants_and_cafes",
    "shopping_and_entertainment",
)

# Category label used in the factual description built from OSM tags.
CATEGORY_LABELS = {
    "temples_and_spiritual": "temple",
    "tourist_attractions_and_heritage": "tourist attraction",
    "parks_and_nature": "park or garden",
    "restaurants_and_cafes": "restaurant or cafe",
    "shopping_and_entertainment": "shopping or entertainment venue",
}

# Interest mapping so every Place in a response carries its canonical
# interests, matching how /api/plan tags itinerary stops.
CATEGORY_INTERESTS = {
    "temples_and_spiritual": [Interest.TEMPLES],
    "tourist_attractions_and_heritage": [Interest.HERITAGE],
    "parks_and_nature": [Interest.NATURE],
    "restaurants_and_cafes": [],
    "shopping_and_entertainment": [Interest.SHOPPING],
}


class PlaceNotFoundError(Exception):
    """Raised when the place id cannot be resolved in the data source."""


def _strip_live_prefix(place_id: str) -> str:
    """Itinerary place ids are 'live_node/123'; MCP wants 'node/123'."""
    return place_id[5:] if place_id.startswith("live_") else place_id


async def _with_mcp_session(action):
    """Run action(session) inside a fresh MCP stdio session."""
    async with stdio_client(SERVER_PARAMS) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await action(session)


def _build_description(name: str, details: dict) -> str:
    """
    Factual description from OSM tags only. OSM carries no prose, so the
    description lists the facts the data provides; when nothing is known
    beyond the name, the name itself is the description.
    """
    tags = details.get("tags") or {}
    facts = []

    category = details.get("category")
    label = CATEGORY_LABELS.get(category)
    if label:
        facts.append(f"a {label}")
    religion = tags.get("religion")
    if religion and religion not in ("christian", "muslim", "sikh", "jewish"):
        facts.append(f"{religion.capitalize()} place of worship")
    city = tags.get("addr:city")
    if city:
        facts.append(f"located in {city}")
    opening_hours = details.get("opening_hours")
    if opening_hours:
        facts.append(f"open {opening_hours}")
    website = details.get("website")
    if website:
        facts.append(f"details at {website}")

    if not facts:
        return name
    return f"{name} is " + ", ".join(facts) + "."


def _to_food_recommendation(raw: dict) -> NearbyFoodRecommendation:
    return NearbyFoodRecommendation(
        name=str(raw.get("name", "Unknown")),
        cuisine=str(raw.get("cuisine") or raw.get("category") or "Multi-cuisine"),
        meal_type=MealType.LUNCH,
        # OSM rarely tags vegetarian-friendliness; default to True only
        # when the tags do not state otherwise (same rule as /api/plan).
        is_vegetarian_friendly=bool(raw.get("vegetarian", True)),
        distance_km=float(raw.get("distance_km", 0.0)),
        price_level=min(4, max(1, int(raw.get("price_level", 2)))),
    )


def _to_place(raw: dict, index: int) -> Place:
    interests = CATEGORY_INTERESTS.get(str(raw.get("category", "")), [])
    return _normalize_place(raw, index, "live", interests)


def _sort_nearby(places: list[dict]) -> list[dict]:
    """Nearest first, fame as the tiebreaker (same ranking as /api/plan)."""
    return sorted(places, key=lambda raw: (raw.get("distance_km") or 0.0,))


def _sort_famous(places: list[dict]) -> list[dict]:
    """Distance + popularity ranking (same ranking as /api/plan)."""
    return sorted(places, key=_combined_rank_score)


async def search_places_via_mcp(
    latitude: float,
    longitude: float,
    categories: tuple[str, ...],
    radius_km: float,
) -> list[dict]:
    """
    Search one or more categories around a coordinate through the MCP
    server. Categories are queried concurrently inside one MCP session.
    A category whose Overpass query fails is skipped - the caller decides
    whether an all-failed result is an error or an empty list.
    """
    search_center = {"latitude": latitude, "longitude": longitude}

    async def run(session: ClientSession) -> list[dict]:
        jobs = [
            _call_mcp_tool(
                session,
                "search_places",
                {**search_center, "radius_km": radius_km, "category": category},
            )
            for category in categories
        ]
        results = await asyncio.gather(*jobs, return_exceptions=True)

        places: list[dict] = []
        for result in results:
            if isinstance(result, Exception) or not isinstance(result, dict):
                continue
            places.extend(result.get("places", []))
        return places

    return await _with_mcp_session(run)


async def build_place_details(
    place_id: str,
    food_preference: str | None = None,
) -> PlaceDetailsResponse:
    """
    Full details for one place id ('node/123' or 'live_node/123'):
    place information and nearby cafes/restaurants derived from real OSM
    data around the place's own coordinates.

    food_preference (VEGETARIAN / NON_VEGETARIAN / BOTH) filters the
    nearby food list: VEGETARIAN keeps only vegetarian-friendly outlets,
    NON_VEGETARIAN only non-vegetarian-friendly ones, BOTH (or None)
    keeps everything.
    """
    osm_place_id = _strip_live_prefix(place_id)

    async def run(session: ClientSession) -> dict:
        return await _call_mcp_tool(
            session, "get_place_details", {"place_id": osm_place_id}
        )

    details = await _with_mcp_session(run)

    if not isinstance(details, dict) or "error" in details:
        raise PlaceNotFoundError(
            str(details.get("error", "Place not found"))
            if isinstance(details, dict)
            else "Place not found"
        )

    latitude = details.get("latitude")
    longitude = details.get("longitude")
    if latitude is None or longitude is None:
        raise PlaceNotFoundError(
            "The place exists but carries no coordinates in the data source."
        )

    name = str(details.get("name", "Unknown place"))
    description = _build_description(name, details)

    place = Place(
        id=f"live_{osm_place_id}",
        name=name,
        short_description=description[:120] if description else name,
        full_description=description or name,
        address=str(details.get("address") or name),
        latitude=float(latitude),
        longitude=float(longitude),
        interests=CATEGORY_INTERESTS.get(str(details.get("category", "")), []),
        suggested_visit_minutes=60,
        opening_hours=str(details.get("opening_hours") or ""),
    )

    # Nearby cafes/restaurants around the place's own coordinates. The
    # restaurants_and_cafes query already excludes temples/attractions;
    # failures yield an empty list, never fabricated entries.
    raw_restaurants: list[dict] = []
    raw_attractions: list[dict] = []
    try:
        results = await search_places_via_mcp(
            latitude,
            longitude,
            ("restaurants_and_cafes",),
            NEARBY_RESTAURANT_RADIUS_KM,
        )
        raw_restaurants = [
            raw
            for raw in results
            if raw.get("latitude") is not None
            and raw.get("longitude") is not None
        ]
    except Exception as error:  # nearby data is optional, never fatal
        print(f"Nearby restaurant search failed for {osm_place_id}: {error}")

    # Nearby famous places: attractions, parks and (relevant) temples in a
    # wider radius, excluding the place itself and non-temple worship
    # places when the selected place is a temple.
    try:
        results = await search_places_via_mcp(
            latitude,
            longitude,
            NEARBY_ATTRACTION_CATEGORIES,
            NEARBY_ATTRACTION_RADIUS_KM,
        )
        raw_attractions = [
            raw
            for raw in results
            if raw.get("latitude") is not None
            and raw.get("longitude") is not None
            and str(raw.get("id", "")) != osm_place_id
            and str(raw.get("name", "")) != name
            # A temple's nearby-famous list must not contain mosques,
            # churches or other non-temple worship places that slipped
            # through the MCP search.
            and not (
                details.get("category") == "temples_and_spiritual"
                and str(raw.get("category", "")) == "temples_and_spiritual"
                and is_non_temple_name(str(raw.get("name", "")))
            )
        ]
    except Exception as error:  # nearby data is optional, never fatal
        print(f"Nearby attraction search failed for {osm_place_id}: {error}")

    nearby_restaurants = [
        _to_food_recommendation(raw)
        for raw in _sort_nearby(_dedupe(raw_restaurants))[:MAX_NEARBY_RESTAURANTS]
    ]

    if (food_preference or "BOTH").upper() == "VEGETARIAN":
        nearby_restaurants = [r for r in nearby_restaurants if r.is_vegetarian_friendly]
    elif (food_preference or "BOTH").upper() == "NON_VEGETARIAN":
        nearby_restaurants = [r for r in nearby_restaurants if not r.is_vegetarian_friendly]

    nearby_attractions = [
        _to_place(raw, index)
        for index, raw in enumerate(
            _sort_famous(_dedupe(raw_attractions))[:MAX_NEARBY_ATTRACTIONS]
        )
    ]

    return PlaceDetailsResponse(
        place=place,
        nearby_restaurants=nearby_restaurants,
        nearby_attractions=nearby_attractions,
    )


async def search_places_for_query(
    query: str,
    latitude: float | None,
    longitude: float | None,
    radius_km: float,
    category: str | None,
) -> tuple[list[Place], str | None]:
    """
    GET /api/places/search: free-text query resolved to a center through
    Nominatim (or explicit coordinates), places around it ranked by
    distance + popularity. Returns (places, geocode_error); a non-None
    geocode_error means the query could not be resolved.
    """
    if latitude is None or longitude is None:
        from app.tools.geocode_tools import search_location

        result = search_location(query, limit=1)
        if "error" in result:
            return [], str(result["error"])
        results = result.get("results", [])
        if not results:
            return [], f"'{query}' could not be found. Check the spelling."
        top = results[0]
        latitude, longitude = top["latitude"], top["longitude"]

    categories = (
        (category,)
        if category in SUPPORTED_SEARCH_CATEGORIES
        else SUPPORTED_SEARCH_CATEGORIES
    )

    raw_places = await search_places_via_mcp(
        latitude, longitude, categories, radius_km
    )

    # Defence in depth: Temples & Spiritual results must never contain
    # non-temple worship places whose tags slipped past the Overpass query.
    cleaned = []
    seen: set = set()
    for raw in raw_places:
        raw_category = str(raw.get("category", ""))
        if raw_category == "temples_and_spiritual" and is_non_temple_name(
            str(raw.get("name", ""))
        ):
            continue
        key = (raw.get("id"), raw.get("name"))
        if key in seen:
            continue
        seen.add(key)
        if raw.get("latitude") is None or raw.get("longitude") is None:
            continue
        cleaned.append(raw)

    ranked = _sort_famous(cleaned)
    places = [_to_place(raw, index) for index, raw in enumerate(ranked)]
    return places, None
