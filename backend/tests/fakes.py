"""
Shared fakes for /api/plan tests.

No real Gemini API calls and no real MCP server launches happen here:
- GeminiModelFake mimics the google.genai client surface used by the code.
- FakeMcpSession mimics the mcp ClientSession surface, and tests patch
  itinerary_generator.stdio_client / itinerary_generator.ClientSession so
  no MCP server process is ever started.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

class GeminiModelFake:
    """Stands in for the google.genai client in tests (never hits the API)."""

    def __init__(self, text="A stroll through Pune"):
        self.text = text
        self.generate_content_calls = 0

    @property
    def models(self):
        return self

    def generate_content(self, model, contents=None, config=None, **kwargs):
        self.generate_content_calls += 1
        return SimpleNamespace(text=self.text)

    def embed_content(self, model, contents=None, config=None, **kwargs):
        count = len(contents) if isinstance(contents, list) else 1
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3])] * count
        )


def make_mcp_tool_result(payload: dict, is_error: bool = False):
    return SimpleNamespace(
        isError=is_error,
        content=[SimpleNamespace(text=json.dumps(payload))],
    )


class FakeMcpSession:
    """
    Mimics mcp.ClientSession just enough for itinerary_generator.
    By default returns places without coordinates or opening hours, which
    the pipeline must reject with InsufficientPlacesError (the same honest
    behaviour the real Overpass-backed tools can produce for incomplete
    OSM entries).
    """

    def __init__(self, search_results=None):
        self.search_results = search_results or {
            "total_results": 2,
            "category": "restaurants_and_cafes",
            "places": [
                {
                    "id": "node/1",
                    "name": "The Urban Kitchen",
                    "category": "restaurants_and_cafes",
                    "latitude": None,
                    "longitude": None,
                    "address": None,
                    "opening_hours": None,
                    "distance_km": 2.1,
                },
                {
                    "id": "node/5",
                    "name": "Green Valley Restaurant",
                    "category": "restaurants_and_cafes",
                    "latitude": None,
                    "longitude": None,
                    "address": None,
                    "opening_hours": None,
                    "distance_km": 4.5,
                },
            ],
        }
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self):
        pass

    async def list_tools(self):
        return SimpleNamespace(tools=[])

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, dict(arguments or {})))
        return make_mcp_tool_result(self.search_results)


def patch_mcp(monkeypatch, session: FakeMcpSession):
    """Patch the itinerary_generator module so no real MCP server starts."""
    from app.services import itinerary_generator as ig

    import contextlib

    @contextlib.asynccontextmanager
    async def fake_stdio_client(params):
        yield SimpleNamespace(), SimpleNamespace()

    import contextlib

    @contextlib.asynccontextmanager
    async def _ClientSession(read_stream, write_stream):
        yield session

    monkeypatch.setattr(ig, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(ig, "ClientSession", _ClientSession)


class FakeRouteMatrix:
    """
    Stands in for app.tools.route_tools.get_route_matrix in tests
    (never hits the OSRM server).

    Builds a matrix from the first coordinate (the start) and the rest
    (candidates) so that travel time grows with candidate index - the
    ordering tests can rely on the nearest place being ordered first.
    """

    def __init__(self, payload=None, error=None):
        self.error = error
        self.payload = payload
        self.calls: list[list] = []

    def __call__(self, coordinates):
        self.calls.append(list(coordinates))

        if self.error is not None:
            return {"error": self.error}

        if self.payload is not None:
            return self.payload

        # Synthetic default: travel from coordinate i to coordinate j
        # takes 5*j minutes (so later candidates are always farther) and
        # 2*j km. Index 0 is the start. Keep values small and plausible
        # so scheduling budgets behave like real data.
        n = len(coordinates)
        durations = [
            [max(0, 5 * (j - i)) for j in range(n)] for i in range(n)
        ]
        distances = [
            [max(0, 2.0 * (j - i)) for j in range(n)] for i in range(n)
        ]
        return {
            "matrix": {
                "durations_minutes": durations,
                "distances_km": distances,
            },
            "coordinates": [
                {"latitude": lat, "longitude": lon}
                for lat, lon in coordinates
            ],
        }


def patch_route_matrix(monkeypatch, fake: FakeRouteMatrix):
    """Patch the OSRM matrix call so no real routing server is contacted."""
    from app.services import itinerary_generator as ig

    monkeypatch.setattr(ig, "get_route_matrix", fake)


def patch_destination_geocode(monkeypatch, name: str = "Pune"):
    """Patch destination geocoding so no Nominatim call happens in tests."""
    from app.services import itinerary_generator as ig
    from app.schemas.outing import StartLocation

    def fake_resolve(destination: str) -> StartLocation:
        return StartLocation(
            name=name,
            is_current_location=False,
            latitude=18.5204,
            longitude=73.8567,
        )

    monkeypatch.setattr(ig, "_resolve_destination_center", fake_resolve)


def clear_gather_cache():
    """Empty the cross-request gather cache (isolation between tests)."""
    from app.services import itinerary_generator as ig

    ig._GATHER_CACHE.clear()
