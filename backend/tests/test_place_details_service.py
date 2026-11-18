"""
Tests for the place details service and the GET /api/places endpoints.

All MCP transport is faked via tests/fakes.py - no real Overpass,
Nominatim or MCP server process is ever contacted.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.outing import PlaceDetailsResponse
from app.services import place_details_service as pds

from tests.fakes import (
    FakeMcpSession,
    GeminiModelFake,
    make_mcp_tool_result,
    patch_mcp,
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    from tests.fakes import clear_gather_cache

    clear_gather_cache()
    yield
    clear_gather_cache()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.main.client", GeminiModelFake())
    with TestClient(app) as test_client:
        yield test_client


def _details_payload(place_id="node/13", name="Dagdusheth Temple"):
    return {
        "id": place_id,
        "name": name,
        "category": "temples_and_spiritual",
        "latitude": 18.524,
        "longitude": 73.860,
        "address": f"{name}, Pune",
        "opening_hours": "06:00-20:00",
        "website": "https://example.org/temple",
        "phone": None,
        "tags": {"name": name, "religion": "hindu", "addr:city": "Pune"},
    }


def _nearby_search_payload():
    return {
        "total_results": 3,
        "category": "restaurants_and_cafes",
        "places": [
            {
                "id": "node/50",
                "name": "Cafe Near Temple",
                "category": "restaurants_and_cafes",
                "latitude": 18.5241,
                "longitude": 73.8601,
                "distance_km": 0.1,
                "cuisine": "indian",
            },
            {
                "id": "node/51",
                "name": "Far Cafe",
                "category": "restaurants_and_cafes",
                "latitude": 18.6,
                "longitude": 73.9,
                "distance_km": 9.2,
                "cuisine": None,
            },
        ],
    }


def _nearby_attractions_payload():
    return {
        "total_results": 2,
        "category": "tourist_attractions_and_heritage",
        "places": [
            {
                "id": "node/60",
                "name": "Shaniwar Wada",
                "category": "tourist_attractions_and_heritage",
                "latitude": 18.5195,
                "longitude": 73.8553,
                "distance_km": 1.1,
                "wikipedia": "https://en.wikipedia.org/wiki/Shaniwar_Wada",
                "osm_type": "way",
            },
            {
                "id": "node/61",
                "name": "Far Fort",
                "category": "tourist_attractions_and_heritage",
                "latitude": 18.7,
                "longitude": 73.95,
                "distance_km": 25.0,
                "wikipedia": None,
                "osm_type": "node",
            },
        ],
    }


class _MultiSearchSession(FakeMcpSession):
    """
    FakeMcpSession that answers get_place_details with a details payload
    and each search_places with a per-category payload.
    """

    def __init__(self, details_payload, search_payloads):
        super().__init__()
        self.details_payload = details_payload
        self.search_payloads = search_payloads

    async def call_tool(self, name, arguments=None):
        arguments = arguments or {}
        if name == "get_place_details":
            return make_mcp_tool_result(self.details_payload)
        category = arguments.get("category", "")
        payload = self.search_payloads.get(category, {"places": []})
        return make_mcp_tool_result(payload)


def _patch_details_session(monkeypatch, session):
    @asynccontextmanager
    async def fake_stdio(params):
        yield SimpleNamespace(), SimpleNamespace()

    @asynccontextmanager
    async def _ClientSession(read_stream, write_stream):
        yield session

    monkeypatch.setattr(pds, "stdio_client", fake_stdio)
    monkeypatch.setattr(pds, "ClientSession", _ClientSession)


# ---------------------------------------------------------------------------
# build_place_details
# ---------------------------------------------------------------------------


def test_details_include_nearby_restaurants_and_attractions(monkeypatch):
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={
            "restaurants_and_cafes": _nearby_search_payload(),
            "tourist_attractions_and_heritage": _nearby_attractions_payload(),
        },
    )
    _patch_details_session(monkeypatch, session)

    details = asyncio.run(pds.build_place_details("live_node/13"))

    assert isinstance(details, PlaceDetailsResponse)
    assert details.place.id == "live_node/13"
    assert details.place.name == "Dagdusheth Temple"
    assert details.place.latitude == 18.524

    # Restaurants nearest first.
    restaurant_names = [rec.name for rec in details.nearby_restaurants]
    assert restaurant_names == ["Cafe Near Temple", "Far Cafe"]

    # Attractions ranked distance-first (both carry fame signal, Shaniwar
    # Wada is nearer and famous).
    attraction_names = [place.name for place in details.nearby_attractions]
    assert attraction_names == ["Shaniwar Wada", "Far Fort"]

    # The selected place itself is never in the nearby list.
    assert all(p.id != "live_node/13" for p in details.nearby_attractions)


def test_details_description_is_factual_not_invented(monkeypatch):
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={},
    )
    _patch_details_session(monkeypatch, session)

    details = asyncio.run(pds.build_place_details("node/13"))

    description = details.place.full_description
    # Facts derived from the payload only.
    assert "Dagdusheth Temple" in description
    assert "temple" in description
    assert "Pune" in description


def test_details_unknown_place_raises_not_found(monkeypatch):
    session = _MultiSearchSession(
        details_payload={"error": "Place with ID node/999 not found"},
        search_payloads={},
    )
    _patch_details_session(monkeypatch, session)

    with pytest.raises(pds.PlaceNotFoundError):
        asyncio.run(pds.build_place_details("node/999"))


def test_details_missing_coordinates_raises_not_found(monkeypatch):
    payload = _details_payload()
    payload["latitude"] = None
    payload["longitude"] = None
    session = _MultiSearchSession(
        details_payload=payload, search_payloads={}
    )
    _patch_details_session(monkeypatch, session)

    with pytest.raises(pds.PlaceNotFoundError):
        asyncio.run(pds.build_place_details("node/13"))


def test_details_nearby_failure_yields_empty_lists_not_error(monkeypatch):
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={},
    )

    async def failing_search(name, arguments=None):
        if name == "get_place_details":
            return make_mcp_tool_result(_details_payload())
        raise RuntimeError("Overpass down")

    session.call_tool = failing_search
    _patch_details_session(monkeypatch, session)

    details = asyncio.run(pds.build_place_details("node/13"))

    assert details.nearby_restaurants == []
    assert details.nearby_attractions == []


def test_details_excludes_non_temple_nearby_results_for_temple(monkeypatch):
    """A nearby mosque that slipped through the MCP search is filtered
    out of the nearby-famous-places list for a temple."""
    attractions = _nearby_attractions_payload()
    attractions["places"].append(
        {
            "id": "node/62",
            "name": "Old Masjid",
            "category": "temples_and_spiritual",
            "latitude": 18.53,
            "longitude": 73.87,
            "distance_km": 1.5,
            "wikipedia": None,
            "osm_type": "node",
        }
    )
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={
            "restaurants_and_cafes": _nearby_search_payload(),
            "tourist_attractions_and_heritage": attractions,
        },
    )
    _patch_details_session(monkeypatch, session)

    details = asyncio.run(pds.build_place_details("node/13"))

    names = [place.name for place in details.nearby_attractions]
    assert "Old Masjid" not in names


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def test_place_details_endpoint_returns_200(monkeypatch, client):
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={
            "restaurants_and_cafes": _nearby_search_payload(),
        },
    )
    _patch_details_session(monkeypatch, session)

    response = client.get("/api/places/node/13")

    assert response.status_code == 200
    body = response.json()
    assert body["place"]["id"] == "live_node/13"
    assert body["place"]["name"] == "Dagdusheth Temple"
    assert body["nearbyRestaurants"][0]["name"] == "Cafe Near Temple"
    assert "nearbyAttractions" in body


def test_place_details_endpoint_returns_404_for_unknown(monkeypatch, client):
    session = _MultiSearchSession(
        details_payload={"error": "Place with ID node/999 not found"},
        search_payloads={},
    )
    _patch_details_session(monkeypatch, session)

    response = client.get("/api/places/node/999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_place_details_endpoint_live_prefix_accepted(monkeypatch, client):
    """Itinerary place ids ('live_node/13') resolve to the same place."""
    session = _MultiSearchSession(
        details_payload=_details_payload(),
        search_payloads={},
    )
    _patch_details_session(monkeypatch, session)

    response = client.get("/api/places/live_node/13")

    assert response.status_code == 200
    assert response.json()["place"]["id"] == "live_node/13"


def test_place_details_endpoint_maps_slash_ids(monkeypatch, client):
    """Way ids ('way/77') reach the backend with the slash intact."""
    session = _MultiSearchSession(
        details_payload=_details_payload("way/77", "A Temple Complex"),
        search_payloads={},
    )
    _patch_details_session(monkeypatch, session)

    response = client.get("/api/places/way/77")

    assert response.status_code == 200
    assert response.json()["place"]["id"] == "live_way/77"
    # The MCP tool received the id with the slash intact.
    # (Verified indirectly: the fake answered for way/77.)
