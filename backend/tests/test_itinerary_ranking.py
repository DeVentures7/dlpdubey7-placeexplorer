"""
Tests for the Temples & Spiritual category and the distance+popularity
ranking added to the itinerary pipeline.

All MCP, routing and Gemini interactions come from tests/fakes.py - no
real backend service is contacted.
"""

import asyncio

import pytest

from app.schemas.outing import Interest, OutingRequest
from app.services import itinerary_generator as ig

from tests.fakes import (
    FakeMcpSession,
    FakeRouteMatrix,
    GeminiModelFake,
    patch_mcp,
    patch_route_matrix,
)


@pytest.fixture(autouse=True)
def _isolated_gather_cache():
    """Keep the cross-request gather cache from leaking between tests."""
    from tests.fakes import clear_gather_cache

    clear_gather_cache()
    yield
    clear_gather_cache()


@pytest.fixture(autouse=True)
def _isolated_gather_cache():
    """Keep the cross-request gather cache from leaking between tests:
    tests share the same interests + start coordinates cache key, so a
    smaller earlier result would otherwise satisfy a later test."""
    from tests.fakes import clear_gather_cache

    clear_gather_cache()
    yield
    clear_gather_cache()


def _temple(index, name, distance_km=None, wikipedia=False, osm_type="node"):
    """A live-shaped temple place around Pune (start 18.5204, 73.8567)."""
    # Move roughly distance_km south-east of the start.
    lat = 18.5204 - (distance_km or 0.0) / 111.0
    lon = 73.8567 + (distance_km or 0.0) / 111.0
    return {
        "id": f"node/{index}",
        "name": name,
        "category": "temples_and_spiritual",
        "latitude": lat,
        "longitude": lon,
        "address": f"{name}, Pune",
        "opening_hours": "06:00-20:00",
        "distance_km": distance_km,
        "wikipedia": "https://en.wikipedia.org/wiki/Temple" if wikipedia else None,
        "osm_type": osm_type,
    }


def _mosque(index, name, distance_km=2.0):
    return {
        "id": f"node/{index}",
        "name": name,
        "category": "temples_and_spiritual",
        "latitude": 18.52,
        "longitude": 73.86,
        "address": f"{name}, Pune",
        "opening_hours": None,
        "distance_km": distance_km,
        "wikipedia": None,
        "osm_type": "node",
    }


def _pipeline(monkeypatch, places, **request_kwargs):
    session = FakeMcpSession(
        search_results={
            "total_results": len(places),
            "category": "temples_and_spiritual",
            "places": places,
        }
    )
    patch_mcp(monkeypatch, session)
    patch_route_matrix(monkeypatch, FakeRouteMatrix())
    # No Nominatim call: the destination resolves to the test center.
    from tests.fakes import patch_destination_geocode

    patch_destination_geocode(monkeypatch)

    return asyncio.run(
        ig.generate_itinerary(
            request=OutingRequest(
                duration="FULL_DAY",
                time_of_day="MORNING",
                interests=["TEMPLES"],
                start_location={
                    "name": "Pune",
                    "latitude": 18.5204,
                    "longitude": 73.8567,
                },
                **request_kwargs,
            ),
            client=GeminiModelFake(),
            model="fake-model",
        )
    )


# ---------------------------------------------------------------------------
# Temples & Spiritual: temples only
# ---------------------------------------------------------------------------


def test_temples_interest_excludes_mosques_and_other_non_temples(monkeypatch):
    """A mosque/church/gurudwara that slips through MCP search must never
    appear under the TEMPLES interest."""
    places = [
        _temple(1, "Dagdusheth Ganpati Temple", distance_km=2.0),
        _mosque(2, "Jama Masjid"),
        _temple(3, "Shiva Mandir", distance_km=5.0, wikipedia=True),
        _temple(4, "Pataleshwar Cave Temple", distance_km=8.0),
    ]

    itinerary = _pipeline(monkeypatch, places)

    names = [stop.place.name for stop in itinerary.stops]
    all_names = names + [
        place.name for place in itinerary.optional_attractions
    ] if itinerary.optional_attractions else names

    assert "Jama Masjid" not in all_names
    assert any("Temple" in name or "Mandir" in name for name in all_names)


def test_temples_interest_keeps_mandir_named_places(monkeypatch):
    """A temple named '...Mandir' (no 'temple' substring) must still be
    recognised - the old keyword match dropped real temples."""
    mandir = _temple(1, "Siddhivinayak Mandir", distance_km=1.0)

    assert ig._place_matches_interests(mandir, [Interest.TEMPLES]) is True


def test_non_temple_name_helper():
    assert ig._is_non_temple_name("Jama Masjid")
    assert ig._is_non_temple_name("Sacred Heart Church")
    assert ig._is_non_temple_name("Gurudwara Bangla Sahib")
    assert not ig._is_non_temple_name("Kasba Ganpati Mandir")
    assert not ig._is_non_temple_name("Parvati Hill Temple")


# ---------------------------------------------------------------------------
# Ranking: distance + popularity
# ---------------------------------------------------------------------------


def test_ranking_prefers_nearest_then_famous(monkeypatch):
    """Near unknowns rank before far unknowns; a famous place two bands
    away outranks a nearby unknown, but a nearby famous place wins."""
    near_unknown = _temple(1, "Near Unknown", distance_km=1.0)
    near_famous = _temple(2, "Near Famous", distance_km=2.0, wikipedia=True)
    far_famous = _temple(3, "Far Famous", distance_km=30.0, wikipedia=True)
    very_far = _temple(4, "Very Far", distance_km=60.0)

    ranked = ig._rank_by_distance_and_fame(
        [very_far, far_famous, near_unknown, near_famous]
    )

    names = [place["name"] for place in ranked]
    assert names == ["Near Famous", "Near Unknown", "Far Famous", "Very Far"]


def test_itinerary_shows_five_to_ten_recommendations(monkeypatch):
    """With 12 real temples available, the itinerary schedules its stop
    budget and fills 'Worth a detour' up to the cap, yielding 5-10
    recommendations in total."""
    places = [
        _temple(index, f"Temple {index}", distance_km=0.5 + index)
        for index in range(1, 13)
    ]

    itinerary = _pipeline(monkeypatch, places)

    total = len(itinerary.stops) + len(itinerary.optional_attractions)
    assert len(itinerary.stops) > 0
    assert 5 <= total <= 10

    # No duplicates between stops and optional attractions.
    stop_ids = {stop.place.id for stop in itinerary.stops}
    optional_ids = {place.id for place in itinerary.optional_attractions}
    assert stop_ids.isdisjoint(optional_ids)


def test_optional_attractions_keep_rank_order(monkeypatch):
    places = [
        _temple(index, f"Temple {index}", distance_km=index)
        for index in range(1, 13)
    ]

    itinerary = _pipeline(monkeypatch, places)

    optional = itinerary.optional_attractions
    assert optional, "expected optional attractions with 12 temples"
    # Distances in the optional list are non-decreasing (rank order is
    # distance-first within equal fame).
    distances = [
        ((p.latitude - 18.5204) ** 2 + (p.longitude - 73.8567) ** 2) ** 0.5
        for p in optional
    ]
    assert distances == sorted(distances)
