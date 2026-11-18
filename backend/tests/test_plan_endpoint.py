"""
Tests for POST /api/plan.

All Gemini and MCP interactions are faked (tests/fakes.py) so no real
Gemini API quota is consumed and no MCP server process is launched.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.outing import (
    Interest,
    Itinerary,
    MealType,
    OutingRequest,
    Place,
)
from app.services import itinerary_generator as ig
from app.services.itinerary_generator import InsufficientPlacesError
from app.tools.route_tools import MAX_TABLE_COORDINATES

from tests.fakes import (
    FakeMcpSession,
    FakeRouteMatrix,
    GeminiModelFake,
    make_mcp_tool_result,
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


@pytest.fixture
def client(monkeypatch):
    """TestClient with Gemini, MCP transport and OSRM routing faked out."""
    gemini_fake = GeminiModelFake()
    monkeypatch.setattr("app.main.client", gemini_fake)
    patch_mcp(monkeypatch, FakeMcpSession())
    patch_route_matrix(monkeypatch, FakeRouteMatrix())
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


def test_valid_request_passes_validation():
    request = OutingRequest()
    assert request.destination == "Pune, Maharashtra"
    assert request.duration.value == "HALF_DAY"


def test_blank_destination_rejected():
    with pytest.raises(ValueError):
        OutingRequest(destination="   ")


def test_blank_start_location_name_rejected():
    with pytest.raises(ValueError):
        OutingRequest(start_location={"name": "  "})


def test_unknown_enum_value_rejected():
    with pytest.raises(ValueError):
        OutingRequest(duration="WEEKEND")


def test_unknown_interest_rejected():
    with pytest.raises(ValueError):
        OutingRequest(interests=["NIGHTLIFE"])


def test_interests_are_deduplicated():
    request = OutingRequest(interests=[Interest.NATURE, Interest.NATURE])
    assert request.interests == [Interest.NATURE]


# ---------------------------------------------------------------------------
# Endpoint contract and honest-error behaviour
# ---------------------------------------------------------------------------


def test_plan_with_unresolvable_destination_returns_400(client, monkeypatch):
    """
    A destination the geocoder cannot resolve is a client-input problem:
    400 with an explanation, never a fabricated plan around some default
    city.
    """
    from app.services import itinerary_generator as ig

    def failing_resolve(destination: str):
        raise ig.DestinationNotFoundError(
            f"Destination '{destination}' could not be found."
        )

    monkeypatch.setattr(ig, "_resolve_destination_center", failing_resolve)

    response = client.post("/api/plan", json={})

    assert response.status_code == 400
    body = response.json()
    assert "could not be found" in body["detail"]


def test_plan_accepts_android_shaped_request(client):
    """
    A request shaped exactly like the Kotlin OutingRequest (camelCase keys,
    enum names) must pass validation.
    """
    payload = {
        "destination": "Pune, Maharashtra",
        "duration": "FULL_DAY",
        "timeOfDay": "MORNING",
        "interests": ["TEMPLES", "HERITAGE"],
        "foodPreference": "VEGETARIAN",
        "startLocation": {
            "name": "Current Location",
            "isCurrentLocation": True,
            "latitude": 18.5204,
            "longitude": 73.8567,
        },
    }

    response = client.post("/api/plan", json=payload)

    # This request carries real coordinates, so the pipeline gets far
    # enough to search; with the fake returning no usable places it must
    # still be the honest 503, never a fabricated 200 itinerary.
    assert response.status_code == 503


def test_existing_chat_endpoints_unchanged(client, monkeypatch):
    """Regression guard: /api/chat and /api/agent/chat keep working."""
    monkeypatch.setattr(
        "app.main.client", GeminiModelFake(text="hello from gemini")
    )

    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code == 200
    assert response.json()["response"] == "hello from gemini"

    monkeypatch.setattr(
        "app.main.run_agent", lambda **kwargs: _async_return("agent says hi")
    )
    response = client.post("/api/agent/chat", json={"message": "hi"})
    assert response.status_code == 200
    assert response.json()["response"] == "agent says hi"


def _async_return(value):
    import asyncio

    future = asyncio.get_event_loop().create_future()
    future.set_result(value)
    return future


# ---------------------------------------------------------------------------
# Generator pipeline with mocked MCP + Gemini
# ---------------------------------------------------------------------------


def _live_place(index, name):
    return {
        "id": f"node/{index}",
        "name": name,
        "category": "tourist_attractions_and_heritage",
        "latitude": 18.52 + index * 0.01,
        "longitude": 73.85 + index * 0.01,
        "address": f"{name}, Pune",
        "description": f"{name} is a well known place in Pune.",
        "opening_hours": "09:00-18:00",
        "suggested_visit_minutes": 60,
    }


def test_successful_structured_response(monkeypatch):
    """
    With live-shaped place data (coordinates + opening hours) the pipeline
    returns a fully structured Itinerary matching the Kotlin models.
    """
    session = FakeMcpSession(
        search_results={
            "total_results": 3,
            "category": "tourist_attractions_and_heritage",
            "places": [
                _live_place(1, "Shaniwar Wada"),
                _live_place(2, "Aga Khan Palace"),
                _live_place(3, "Dagadusheth Temple"),
            ],
        }
    )
    gemini_fake = GeminiModelFake(text="Royal Pune Heritage Walk")
    monkeypatch.setattr(ig, "stdio_client", _noop_stdio)
    monkeypatch.setattr(ig, "ClientSession", _fake_session_cls(session))
    route_matrix_fake = FakeRouteMatrix()
    patch_route_matrix(monkeypatch, route_matrix_fake)

    import asyncio

    itinerary = asyncio.run(
        ig.generate_itinerary(
            request=OutingRequest(
                duration="FULL_DAY",
                time_of_day="MORNING",
                start_location={
                    "name": "Pune",
                    "latitude": 18.5204,
                    "longitude": 73.8567,
                },
            ),
            client=gemini_fake,
            model="fake-model",
        )
    )

    assert isinstance(itinerary, Itinerary)
    assert itinerary.title == "Royal Pune Heritage Walk"
    assert itinerary.destination == "Pune, Maharashtra"
    assert len(itinerary.stops) == 3  # bounded by the 3 available places

    first = itinerary.stops[0]
    assert first.place.id.startswith("live_")
    assert first.travel_to_next is not None

    last = itinerary.stops[-1]
    assert last.travel_to_next is None

    # Stops are ordered by road travel duration from the start (the fake
    # matrix makes candidate 1 nearest).
    assert [stop.place.name for stop in itinerary.stops] == [
        "Shaniwar Wada", "Aga Khan Palace", "Dagadusheth Temple",
    ]

    # Travel legs carry the fake matrix's road values, not haversine.
    # travel_to_next is the leg to the NEXT stop; the start -> first stop
    # leg (5 min in the fake) shows up in the first arrival time.
    assert first.travel_to_next.distance_km == 2.0
    assert first.travel_to_next.duration_minutes == 5
    assert first.arrival_time_minutes == 540 + 5  # 09:00 + road minutes

    # The OSRM matrix was requested exactly once, with start + candidates.
    assert len(route_matrix_fake.calls) == 1
    coordinates = route_matrix_fake.calls[0]
    assert len(coordinates) == 4  # start + 3 candidates
    assert coordinates[0] == (18.5204, 73.8567)

    # Android-compatible serialization.
    payload = itinerary.model_dump(by_alias=True)
    assert "arrivalTimeMinutes" in payload["stops"][0]
    assert "isOptionalAttraction" in payload["stops"][0]["place"]
    assert "distanceKm" in payload["stops"][0]["travelToNext"]
    assert "durationMinutes" in payload["stops"][0]["travelToNext"]


def test_insufficient_places_error_message(monkeypatch):
    """
    Places without coordinates raise InsufficientPlacesError,
    not fabricated output.
    """
    session = FakeMcpSession()  # default: places with null coordinates
    monkeypatch.setattr(ig, "stdio_client", _noop_stdio)
    monkeypatch.setattr(ig, "ClientSession", _fake_session_cls(session))
    patch_route_matrix(monkeypatch, FakeRouteMatrix())

    import asyncio

    with pytest.raises(InsufficientPlacesError) as exc_info:
        asyncio.run(
            ig.generate_itinerary(
                request=OutingRequest(
                    start_location={
                        "name": "Pune",
                        "latitude": 18.5204,
                        "longitude": 73.8567,
                    }
                ),
                client=GeminiModelFake(),
                model="fake-model",
            )
        )

    assert exc_info.value.data_source == "live"
    assert "coordinates" in str(exc_info.value)


def test_mcp_tool_failure_propagates(monkeypatch):
    """An MCP tool failure raises RuntimeError (mapped to HTTP 502 upstream)."""
    session = FakeMcpSession()

    async def failing_call_tool(name, arguments=None):
        return make_mcp_tool_result({}, is_error=True)

    session.call_tool = failing_call_tool
    monkeypatch.setattr(ig, "stdio_client", _noop_stdio)
    monkeypatch.setattr(ig, "ClientSession", _fake_session_cls(session))
    patch_route_matrix(monkeypatch, FakeRouteMatrix())

    import asyncio

    with pytest.raises(RuntimeError, match="MCP tool"):
        asyncio.run(
            ig.generate_itinerary(
                request=OutingRequest(
                    start_location={
                        "name": "Pune",
                        "latitude": 18.5204,
                        "longitude": 73.8567,
                    }
                ),
                client=GeminiModelFake(),
                model="fake-model",
            )
        )


def _noop_stdio(params):
    import contextlib

    @contextlib.asynccontextmanager
    async def _ctx(params):
        yield None, None

    return _ctx(params)


def _fake_session_cls(session):
    import contextlib

    @contextlib.asynccontextmanager
    async def _ClientSession(read_stream, write_stream):
        yield session

    return _ClientSession


# ---------------------------------------------------------------------------
# OSRM route-matrix integration
# ---------------------------------------------------------------------------


import asyncio


def _pipeline_run(monkeypatch, session, route_matrix_fake, **request_kwargs):
    gemini_fake = GeminiModelFake()
    monkeypatch.setattr(ig, "stdio_client", _noop_stdio)
    monkeypatch.setattr(ig, "ClientSession", _fake_session_cls(session))
    patch_route_matrix(monkeypatch, route_matrix_fake)

    return asyncio.run(
        ig.generate_itinerary(
            request=OutingRequest(
                duration="FULL_DAY",
                time_of_day="MORNING",
                start_location={
                    "name": "Pune",
                    "latitude": 18.5204,
                    "longitude": 73.8567,
                },
                **request_kwargs,
            ),
            client=gemini_fake,
            model="fake-model",
        )
    )


def test_routing_unavailable_raises_not_haversine(monkeypatch):
    """OSRM down -> clear error, never straight-line estimates as roads."""
    session = FakeMcpSession(
        search_results={
            "total_results": 2,
            "category": "tourist_attractions_and_heritage",
            "places": [
                _live_place(1, "Shaniwar Wada"),
                _live_place(2, "Aga Khan Palace"),
            ],
        }
    )

    with pytest.raises(InsufficientPlacesError) as exc_info:
        _pipeline_run(
            monkeypatch, session,
            FakeRouteMatrix(error="OSRM request timed out."),
        )

    assert "routing service is unavailable" in str(exc_info.value)
    assert "straight-line" in str(exc_info.value)


def test_missing_distance_annotation_raises(monkeypatch):
    """Matrix without distance annotations cannot produce honest legs."""
    session = FakeMcpSession(
        search_results={
            "total_results": 1,
            "category": "tourist_attractions_and_heritage",
            "places": [_live_place(1, "Shaniwar Wada")],
        }
    )

    with pytest.raises(InsufficientPlacesError) as exc_info:
        _pipeline_run(
            monkeypatch, session,
            FakeRouteMatrix(
                payload={
                    "matrix": {
                        "durations_minutes": [[0, 5], [5, 0]],
                        "distances_km": None,
                    },
                    "coordinates": [],
                }
            ),
        )

    assert "road distances" in str(exc_info.value)


def test_unreachable_place_is_dropped_not_fabricated(monkeypatch):
    """A place OSRM cannot reach is excluded, never given invented legs."""
    session = FakeMcpSession(
        search_results={
            "total_results": 3,
            "category": "tourist_attractions_and_heritage",
            "places": [
                _live_place(1, "Reachable Near"),
                _live_place(2, "Reachable Far"),
                _live_place(3, "Unreachable Island"),
            ],
        }
    )

    # Custom matrix: place 3 (index 3 in coordinates) unreachable from
    # start and from everywhere; candidates 1 and 2 reachable.
    route_matrix_fake = FakeRouteMatrix(
        payload={
            "matrix": {
                "durations_minutes": [
                    #         start  p1     p2     p3
                    [0,       5,     15,    None],   # from start
                    [5,       0,     10,    None],   # from p1
                    [15,      10,    0,     None],   # from p2
                    [None,    None,  None,  0],      # from p3
                ],
                "distances_km": [
                    [0,    2.0,  8.0,  None],
                    [2.0,  0,    5.0,  None],
                    [8.0,  5.0,  0,    None],
                    [None, None, None, 0],
                ],
            },
            "coordinates": [],
        }
    )

    itinerary = _pipeline_run(monkeypatch, session, route_matrix_fake)

    names = [stop.place.name for stop in itinerary.stops]
    assert "Unreachable Island" not in names
    assert names == ["Reachable Near", "Reachable Far"]

    # Legs use the provided road values.
    assert itinerary.stops[0].travel_to_next.distance_km == 5.0
    assert itinerary.stops[0].travel_to_next.duration_minutes == 10


def test_stop_ordering_follows_road_duration_not_geography(monkeypatch):
    """
    The place that is straight-line closest must NOT come first when the
    road network says another place is quicker to reach.
    """
    # Place A: very close geographically to the start but a long road
    # detour; place B: farther straight-line but a short direct road.
    near_but_slow = _live_place(1, "Near But Slow")
    near_but_slow["latitude"] = 18.5210   # ~0.1 km from start
    near_but_slow["longitude"] = 73.8568
    far_but_quick = _live_place(2, "Far But Quick")
    far_but_quick["latitude"] = 18.5600   # several km straight-line
    far_but_quick["longitude"] = 73.8900

    session = FakeMcpSession(
        search_results={
            "total_results": 2,
            "category": "tourist_attractions_and_heritage",
            "places": [near_but_slow, far_but_quick],
        }
    )

    route_matrix_fake = FakeRouteMatrix(
        payload={
            "matrix": {
                "durations_minutes": [
                    #        start  slow  quick
                    [0,        40,    5],   # from start
                    [40,       0,    30],   # from slow
                    [5,       35,     0],   # from quick
                ],
                "distances_km": [
                    [0,   20.0,  2.0],
                    [20.0, 0,   15.0],
                    [2.0, 18.0,  0],
                ],
            },
            "coordinates": [],
        }
    )

    itinerary = _pipeline_run(monkeypatch, session, route_matrix_fake)

    names = [stop.place.name for stop in itinerary.stops]
    # Road duration wins: the far-but-quick place is stop 1.
    assert names == ["Far But Quick", "Near But Slow"]

    # Leg stop1 -> stop2 (quick -> slow) = 18.0 km / 35 min road values.
    assert itinerary.stops[0].travel_to_next.distance_km == 18.0
    assert itinerary.stops[0].travel_to_next.duration_minutes == 35
    # Start -> stop1 arrival reflects the 5-minute road leg.
    assert itinerary.stops[0].arrival_time_minutes == 540 + 5


def test_candidate_limit_respected_in_matrix_request(monkeypatch):
    """More candidates than the OSRM cap: one request, capped size."""
    from app.services.itinerary_generator import (
        MAX_FAME_RANKED_PLACES,
        MAX_ROUTED_CANDIDATES,
    )

    places = [
        _live_place(index, f"Place {index}")
        for index in range(1, MAX_ROUTED_CANDIDATES + 5)  # over the cap
    ]
    session = FakeMcpSession(
        search_results={
            "total_results": len(places),
            "category": "tourist_attractions_and_heritage",
            "places": places,
        }
    )

    route_matrix_fake = FakeRouteMatrix()
    itinerary = _pipeline_run(monkeypatch, session, route_matrix_fake)

    assert len(route_matrix_fake.calls) == 1
    # Fame ranking keeps the top MAX_FAME_RANKED_PLACES first, then the
    # OSRM cap trims further: coordinates never exceed the Table API
    # limit (start + candidates).
    coordinates = route_matrix_fake.calls[0]
    assert len(coordinates) <= MAX_TABLE_COORDINATES
    assert len(coordinates) == min(
        MAX_TABLE_COORDINATES, MAX_FAME_RANKED_PLACES + 1
    )

    # The itinerary still works with the trimmed candidate list.
    assert len(itinerary.stops) > 0


def test_osrm_http_error_maps_to_insufficient_places(monkeypatch):
    """HTTP-level OSRM failures surface as the honest 503-style error."""
    session = FakeMcpSession(
        search_results={
            "total_results": 1,
            "category": "tourist_attractions_and_heritage",
            "places": [_live_place(1, "Shaniwar Wada")],
        }
    )

    with pytest.raises(InsufficientPlacesError) as exc_info:
        _pipeline_run(
            monkeypatch, session,
            FakeRouteMatrix(
                error="OSRM server returned HTTP 502 from <url>. "
                      "The instance is rate limiting or busy."
            ),
        )

    assert "HTTP 502" in str(exc_info.value)


def test_plan_endpoint_returns_503_when_routing_down(client, monkeypatch):
    """End-to-end: OSRM failure maps to the honest HTTP 503 response."""
    # The client fixture's FakeMcpSession returns places without
    # coordinates by default; give it complete places so the pipeline
    # reaches the routing step.
    patch_mcp(monkeypatch, FakeMcpSession(
        search_results={
            "total_results": 1,
            "category": "tourist_attractions_and_heritage",
            "places": [_live_place(1, "Shaniwar Wada")],
        }
    ))
    patch_route_matrix(
        monkeypatch, FakeRouteMatrix(error="OSRM request timed out.")
    )

    response = client.post(
        "/api/plan",
        json={
            "startLocation": {
                "name": "Pune",
                "latitude": 18.5204,
                "longitude": 73.8567,
            },
        },
    )

    assert response.status_code == 503
    body = response.json()
    assert "routing" in body["detail"].lower()
