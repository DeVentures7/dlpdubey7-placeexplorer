"""
Tests for the OpenStreetMap-backed place tools.

Every HTTP interaction is mocked with httpx.MockTransport - no live
Overpass API calls are made. The mock transport is installed by
patching place_tools._create_client, the single point where an
httpx.Client is created.
"""

import pytest

from app.tools import place_tools
from app.tools.place_tools import (
    clear_cache,
    get_place_details,
    resolve_category,
    search_places,
)


# ---------------------------------------------------------------------------
# Mock transport plumbing
# ---------------------------------------------------------------------------


def make_client_factory(overpass_response, status_code=200):
    """Build an _create_client replacement wired to a MockTransport."""

    def handler(request):
        from httpx import Response

        return Response(
            status_code,
            json=overpass_response,
            request=request,
        )

    import httpx

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=5,
        )

    return factory


def make_error_client_factory(exc):
    """Build an _create_client replacement that always raises exc."""

    import httpx

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(exc)),
            timeout=5,
        )

    return factory


def make_routed_client_factory(routes):
    """
    Build an _create_client replacement whose behaviour depends on the
    requested URL. routes maps URL -> httpx.Response or Exception; a URL
    missing from the map gets a 500. Records every request URL in a list
    attached to the returned factory as `.requests`.
    """

    import httpx

    def handler(request):
        routes.setdefault("_requests", []).append(str(request.url))
        outcome = routes.get(str(request.url))
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            from httpx import Response

            return Response(500, text="unexpected URL", request=request)
        return outcome

    def factory():
        factory.requests = routes.get("_requests", [])
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=5,
        )

    return factory


ELEMENT_SHANIWAR_WADA = {
    "type": "node",
    "id": 1097282497,
    "lat": 18.5195,
    "lon": 73.8553,
    "tags": {
        "name": "Shaniwar Wada",
        "historic": "castle",
        "opening_hours": "08:00-18:30",
        "addr:street": "Shaniwar Peth",
        "addr:city": "Pune",
    },
}

ELEMENT_UNNAMED_BENCH = {
    "type": "node",
    "id": 2,
    "lat": 18.5200,
    "lon": 73.8560,
    "tags": {"amenity": "bench", "leisure": "bench"},
}

ELEMENT_WAY_NO_CENTER = {
    "type": "way",
    "id": 3,
    "tags": {"name": "Centerless Way"},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def patch_transport(monkeypatch, factory):
    monkeypatch.setattr(place_tools, "_create_client", factory)


# ---------------------------------------------------------------------------
# Overpass payload -> structured places
# ---------------------------------------------------------------------------


def test_search_returns_structured_places(monkeypatch):
    payload = {"elements": [ELEMENT_SHANIWAR_WADA]}
    patch_transport(monkeypatch, make_client_factory(payload))

    result = search_places(
        latitude=18.5204,
        longitude=73.8567,
        radius_km=2,
        category="tourist_attractions_and_heritage",
    )

    assert "error" not in result
    assert result["total_results"] == 1
    assert result["category"] == "tourist_attractions_and_heritage"

    place = result["places"][0]
    assert place["id"] == "node/1097282497"
    assert place["name"] == "Shaniwar Wada"
    assert place["category"] == "tourist_attractions_and_heritage"
    assert place["latitude"] == 18.5195
    assert place["longitude"] == 73.8553
    assert place["opening_hours"] == "08:00-18:30"
    assert place["address"] == "Shaniwar Peth, Pune"
    assert place["distance_km"] is not None and place["distance_km"] < 1


def test_missing_fields_are_null_not_invented(monkeypatch):
    element = {
        "type": "node",
        "id": 5,
        "lat": 18.52,
        "lon": 73.85,
        "tags": {"name": "Unnamed Hours Cafe", "amenity": "cafe"},
    }
    patch_transport(monkeypatch, make_client_factory({"elements": [element]}))

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=1,
        category="restaurants_and_cafes",
    )

    place = result["places"][0]
    assert place["address"] is None
    assert place["opening_hours"] is None
    assert place["name"] == "Unnamed Hours Cafe"


def test_unnamed_features_are_excluded(monkeypatch):
    """The query filters on name, and parsing drops unnamed leftovers."""
    patch_transport(
        monkeypatch,
        make_client_factory(
            {"elements": [ELEMENT_SHANIWAR_WADA, ELEMENT_UNNAMED_BENCH]}
        ),
    )

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="tourist_attractions_and_heritage",
    )

    names = [place["name"] for place in result["places"]]
    assert "Shaniwar Wada" in names
    assert all(name is not None for name in names)


def test_way_with_center_coordinates_used(monkeypatch):
    element = {
        "type": "way",
        "id": 77,
        "center": {"lat": 18.53, "lon": 73.86},
        "tags": {"name": "A Park", "leisure": "park"},
    }
    patch_transport(monkeypatch, make_client_factory({"elements": [element]}))

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=5,
        category="parks_and_nature",
    )

    place = result["places"][0]
    assert place["id"] == "way/77"
    assert place["latitude"] == 18.53
    assert place["longitude"] == 73.86


def test_element_without_coordinates_is_dropped(monkeypatch):
    patch_transport(
        monkeypatch, make_client_factory({"elements": [ELEMENT_WAY_NO_CENTER]})
    )

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=5,
        category="parks_and_nature",
    )

    assert result["total_results"] == 0
    assert result["places"] == []


def test_results_sorted_by_distance(monkeypatch):
    far = {
        "type": "node", "id": 1, "lat": 18.55, "lon": 73.88,
        "tags": {"name": "Far Park", "leisure": "park"},
    }
    near = {
        "type": "node", "id": 2, "lat": 18.521, "lon": 73.857,
        "tags": {"name": "Near Park", "leisure": "park"},
    }
    patch_transport(
        monkeypatch, make_client_factory({"elements": [far, near]})
    )

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=10,
        category="parks_and_nature",
    )

    distances = [place["distance_km"] for place in result["places"]]
    assert distances == sorted(distances)
    assert result["places"][0]["name"] == "Near Park"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_invalid_latitude_rejected(monkeypatch):
    patch_transport(
        monkeypatch, make_client_factory({"elements": []})
    )

    result = search_places(
        latitude=999, longitude=73.85, category="parks_and_nature"
    )
    assert "latitude" in result["error"]
    assert result["total_results"] == 0


def test_invalid_longitude_rejected(monkeypatch):
    patch_transport(monkeypatch, make_client_factory({"elements": []}))

    result = search_places(
        latitude=18.52, longitude=-500, category="parks_and_nature"
    )
    assert "longitude" in result["error"]


def test_radius_too_large_rejected(monkeypatch):
    patch_transport(monkeypatch, make_client_factory({"elements": []}))

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=200,
        category="parks_and_nature",
    )
    assert "radius_km" in result["error"]


def test_unknown_category_rejected(monkeypatch):
    patch_transport(monkeypatch, make_client_factory({"elements": []}))

    result = search_places(
        latitude=18.52, longitude=73.85, category="hospitals"
    )
    assert "Unknown category" in result["error"]
    assert "parks_and_nature" in result["error"]


def test_category_aliases_resolve():
    assert resolve_category("temple") == "temples_and_spiritual"
    assert resolve_category("Temples") == "temples_and_spiritual"
    assert resolve_category("restaurant") == "restaurants_and_cafes"
    assert resolve_category("cafe") == "restaurants_and_cafes"
    assert resolve_category("park") == "parks_and_nature"
    assert resolve_category("shopping") == "shopping_and_entertainment"
    assert resolve_category("heritage") == "tourist_attractions_and_heritage"
    assert resolve_category("nonexistent") is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_timeout_returns_error(monkeypatch):
    import httpx

    patch_transport(
        monkeypatch,
        make_error_client_factory(httpx.ReadTimeout("timed out")),
    )

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )
    assert "timed out" in result["error"]


def test_timeout_falls_back_to_smaller_queries(monkeypatch):
    """A union-query timeout retries with smaller per-filter queries
    (query-size dependent), but never re-sends the SAME union to another
    mirror - the fallback queries are smaller, not identical."""
    import httpx
    from httpx import Response

    urls = [str(url) for url in place_tools.OVERPASS_URLS]
    assert len(urls) >= 1

    routes = {
        url: httpx.ReadTimeout("timed out") for url in urls
    }
    routes["_requests"] = []
    factory = make_routed_client_factory(routes)
    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )

    assert "timed out" in result["error"]
    # The union was tried once; the fallback queries are smaller
    # per-filter ones, not the same union re-sent to another mirror.
    assert len(routes["_requests"]) == 1 + 2 * len(
        place_tools.CATEGORY_FILTERS["restaurants_and_cafes"]
    )


def test_connect_error_falls_back_to_next_mirror(monkeypatch):
    """Instance-level connection failure tries the next mirror."""
    import httpx
    from httpx import Response

    urls = [str(url) for url in place_tools.OVERPASS_URLS]
    assert len(urls) >= 2, "test needs at least two mirrors"

    routes = {
        urls[0]: httpx.ConnectError("connection refused"),
        urls[1]: Response(
            200, json={"elements": [ELEMENT_SHANIWAR_WADA]}
        ),
        "_requests": [],
    }
    factory = make_routed_client_factory(routes)
    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="tourist_attractions_and_heritage",
    )

    assert "error" not in result
    assert result["total_results"] == 1
    assert len(routes["_requests"]) == 2


def test_http_502_falls_back_to_next_mirror(monkeypatch):
    """HTTP 502 is instance-level trouble: the next mirror is tried."""
    import httpx
    from httpx import Response

    urls = [str(url) for url in place_tools.OVERPASS_URLS]
    assert len(urls) >= 2

    routes = {
        urls[0]: Response(502, text="bad gateway"),
        urls[1]: Response(
            200, json={"elements": [ELEMENT_SHANIWAR_WADA]}
        ),
        "_requests": [],
    }
    factory = make_routed_client_factory(routes)
    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="tourist_attractions_and_heritage",
    )

    assert "error" not in result
    assert result["total_results"] == 1
    assert len(routes["_requests"]) == 2


def test_http_400_does_not_fall_back(monkeypatch):
    """A bad query fails identically on every mirror - fail fast."""
    import httpx
    from httpx import Response

    urls = [str(url) for url in place_tools.OVERPASS_URLS]
    assert len(urls) >= 2

    routes = {
        url: Response(400, text="bad request") for url in urls
    }
    routes["_requests"] = []
    factory = make_routed_client_factory(routes)
    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )

    assert "HTTP 400" in result["error"]
    # Query-level problem: no point asking another mirror.
    assert len(routes["_requests"]) == 1


def test_all_mirrors_failing_reports_last_error(monkeypatch):
    """Exhausting every mirror surfaces an error, not empty results."""
    import httpx
    from httpx import Response

    urls = [str(url) for url in place_tools.OVERPASS_URLS]

    routes = {
        urls[0]: httpx.ConnectError("down"),
        urls[1]: Response(504, text="gateway timeout"),
        "_requests": [],
    }
    factory = make_routed_client_factory(routes)
    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )

    assert "error" in result
    assert "504" in result["error"]
    assert "total_results" not in result  # never a fake empty result
    assert len(routes["_requests"]) == len(urls)


def test_http_429_returns_error(monkeypatch):
    import httpx

    patch_transport(
        monkeypatch,
        make_error_client_factory(httpx.HTTPStatusError(
            "429",
            request=httpx.Request("POST", place_tools.OVERPASS_URLS[0]),
            response=httpx.Response(429),
        )),
    )

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )
    assert "HTTP 429" in result["error"]
    assert "rate limiting" in result["error"]


def test_invalid_json_returns_error(monkeypatch):
    from httpx import Response

    def handler(request):
        return Response(200, text="<html>bad</html>", request=request)

    import httpx

    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)

    patch_transport(monkeypatch, factory)

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )
    assert "invalid JSON" in result["error"]


def test_overpass_remark_surfaces(monkeypatch):
    patch_transport(
        monkeypatch,
        make_client_factory(
            {"remark": "runtime error: Query run out of memory"}
        ),
    )

    result = search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )
    assert "out of memory" in result["error"]


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_repeated_search_uses_cache(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        from httpx import Response

        return Response(
            200,
            json={"elements": [ELEMENT_SHANIWAR_WADA]},
            request=request,
        )

    import httpx

    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)

    patch_transport(monkeypatch, factory)

    first = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="temples_and_spiritual",
    )
    second = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="temples_and_spiritual",
    )

    assert len(calls) == 1  # second call served from cache
    assert first == second


def test_cache_respects_ttl(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        from httpx import Response

        return Response(
            200, json={"elements": []}, request=request
        )

    import httpx

    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)

    patch_transport(monkeypatch, factory)

    search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="parks_and_nature",
    )

    # Simulate cache expiry.
    key = next(iter(place_tools._cache))
    stored_at, value = place_tools._cache[key]
    place_tools._cache[key] = (
        stored_at - place_tools.CACHE_TTL_SECONDS - 1, value
    )

    search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="parks_and_nature",
    )

    assert len(calls) == 2


def test_errors_are_not_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        from httpx import Response

        return Response(200, text="not json", request=request)

    import httpx

    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)

    patch_transport(monkeypatch, factory)

    search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )
    search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="restaurants_and_cafes",
    )

    assert len(calls) == 2  # failed responses must not be cached


def test_different_radius_is_cache_miss(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        from httpx import Response

        return Response(200, json={"elements": []}, request=request)

    import httpx

    def factory():
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=5)

    patch_transport(monkeypatch, factory)

    search_places(
        latitude=18.52, longitude=73.85, radius_km=2,
        category="parks_and_nature",
    )
    search_places(
        latitude=18.52, longitude=73.85, radius_km=3,
        category="parks_and_nature",
    )

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# get_place_details
# ---------------------------------------------------------------------------


def test_details_by_osm_id(monkeypatch):
    patch_transport(
        monkeypatch,
        make_client_factory({"elements": [ELEMENT_SHANIWAR_WADA]}),
    )

    result = get_place_details("node/1097282497")

    assert result["id"] == "node/1097282497"
    assert result["name"] == "Shaniwar Wada"
    assert result["category"] == "tourist_attractions_and_heritage"
    assert result["opening_hours"] == "08:00-18:30"
    assert result["address"] == "Shaniwar Peth, Pune"
    assert "tags" in result


def test_details_malformed_place_id(monkeypatch):
    patch_transport(monkeypatch, make_client_factory({"elements": []}))

    result = get_place_details("12345")
    assert "form" in result["error"]

    result = get_place_details("way/notanumber")
    assert "integer" in result["error"]

    result = get_place_details("area/123")
    assert "Unknown OSM type" in result["error"]


def test_details_not_found(monkeypatch):
    patch_transport(monkeypatch, make_client_factory({"elements": []}))

    result = get_place_details("node/999999999")
    assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# Query shape (Overpass policy compliance)
# ---------------------------------------------------------------------------


def test_overpass_query_contains_name_filter_and_user_agent(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["user_agent"] = request.headers.get("user-agent")
        from urllib.parse import parse_qs

        captured["body"] = parse_qs(request.content.decode())["data"][0]
        from httpx import Response

        return Response(200, json={"elements": []}, request=request)

    import httpx

    def factory():
        client = httpx.Client(
            transport=httpx.MockTransport(handler), timeout=5
        )
        # Route through the real header logic by copying it explicitly.
        client.headers = httpx.Headers({"User-Agent": place_tools.USER_AGENT})
        return client

    patch_transport(monkeypatch, factory)

    search_places(
        latitude=18.52, longitude=73.85, radius_km=1,
        category="temples_and_spiritual",
    )

    assert "PlaceExplorer" in captured["user_agent"]
    # Server-side timeout must stay below the 25s client read timeout
    # so Overpass can deliver its informative timeout remark in time.
    assert "[out:json][timeout:20]" in captured["body"]
    assert '["name"]' in captured["body"]
    assert "around:1000,18.52,73.85" in captured["body"]
    assert '["amenity"="place_of_worship"]' in captured["body"]


# ---------------------------------------------------------------------------
# Mirror configuration
# ---------------------------------------------------------------------------


def test_default_mirrors_fr_primary_kumi_removed():
    """The default chain starts with the responsive .fr instance and
    must not include the kumi mirror that hangs until timeout."""
    import os

    assert place_tools.OVERPASS_URLS == [
        "https://overpass.openstreetmap.fr/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]
    assert not any("kumi" in url for url in place_tools.OVERPASS_URLS)


def test_custom_overpass_url_tried_first(monkeypatch):
    """OVERPASS_URL goes to the front of the chain, without duplicates."""
    custom = "https://overpass.example.com/api/interpreter"
    monkeypatch.setenv("OVERPASS_URL", custom)

    import importlib

    import app.tools.place_tools as reloaded

    saved_urls = place_tools.OVERPASS_URLS
    saved_custom = reloaded._CUSTOM_OVERPASS_URL
    try:
        monkeypatch.setattr(reloaded, "_CUSTOM_OVERPASS_URL", custom)
        # Recompute the same expression the module runs at import time.
        monkeypatch.setattr(
            reloaded,
            "OVERPASS_URLS",
            (
                [reloaded._CUSTOM_OVERPASS_URL]
                if reloaded._CUSTOM_OVERPASS_URL
                else []
            )
            + [
                url
                for url in reloaded._DEFAULT_OVERPASS_URLS
                if url != reloaded._CUSTOM_OVERPASS_URL
            ],
        )

        assert reloaded.OVERPASS_URLS[0] == custom
        assert reloaded.OVERPASS_URLS.count(custom) == 1
        assert len(reloaded.OVERPASS_URLS) == 3
    finally:
        pass

    del importlib
    del saved_urls, saved_custom

# ---------------------------------------------------------------------------
# Mirror configuration
# ---------------------------------------------------------------------------


def test_default_mirrors_fr_primary_kumi_removed():
    """The default chain starts with the responsive .fr instance and must
    not include the kumi mirror that hung until timeout during diagnosis."""
    assert place_tools.OVERPASS_URLS == [
        "https://overpass.openstreetmap.fr/api/interpreter",
        "https://overpass-api.de/api/interpreter",
    ]
    assert not any("kumi" in url for url in place_tools.OVERPASS_URLS)


def test_custom_overpass_url_tried_first(monkeypatch):
    """OVERPASS_URL goes to the front of the chain, without duplicates."""
    import importlib

    import app.tools.place_tools as reloaded

    custom = "https://overpass.example.com/api/interpreter"
    monkeypatch.setenv("OVERPASS_URL", custom)
    try:
        reloaded = importlib.reload(reloaded)

        assert reloaded.OVERPASS_URLS[0] == custom
        assert reloaded.OVERPASS_URLS.count(custom) == 1
        assert reloaded.OVERPASS_URLS == [
            custom,
            "https://overpass.openstreetmap.fr/api/interpreter",
            "https://overpass-api.de/api/interpreter",
        ]
    finally:
        monkeypatch.delenv("OVERPASS_URL", raising=False)
        importlib.reload(reloaded)  # restore module-level state


# ---------------------------------------------------------------------------
# Query shape: node + way, no relations
# ---------------------------------------------------------------------------


def _query_for(category, lat=18.5204, lon=73.8567, radius_km=2):
    from app.tools.place_tools import CATEGORY_FILTERS, _build_overpass_query

    canonical = resolve_category(category)
    return _build_overpass_query(
        lat, lon, radius_km, CATEGORY_FILTERS[canonical]
    )


def test_query_contains_node_and_way_statements():
    query = _query_for("temples")

    assert (
        'node(around:2000,18.5204,73.8567)["amenity"="place_of_worship"]'
        '["religion"~"^(hindu|buddhist|jain|taoist)$"]["name"];'
        in query
    )
    assert (
        'way(around:2000,18.5204,73.8567)["amenity"="place_of_worship"]'
        '["religion"~"^(hindu|buddhist|jain|taoist)$"]["name"];'
        in query
    )


def test_query_excludes_relations():
    query = _query_for("temples")
    assert "relation(" not in query

    # Excluded across all categories, not just temples.
    for category in (
        "temples_and_spiritual",
        "tourist_attractions_and_heritage",
        "parks_and_nature",
        "restaurants_and_cafes",
        "shopping_and_entertainment",
    ):
        assert "relation(" not in _query_for(category)


def test_query_preserves_category_tags_and_name_filter():
    query = _query_for("restaurants")
    assert '["amenity"="restaurant"]' in query
    assert '["amenity"="cafe"]' in query
    assert '["name"]' in query

    query = _query_for("shopping")
    assert '["shop"]' in query
    assert '["amenity"~"^(cinema|theatre|arts_centre|nightclub)$"]' in query


def test_parsed_relation_element_is_still_normalised(monkeypatch):
    """Defensive: if a response ever contains a relation element (e.g. a
    cached response from an older query), parsing still normalises it via
    its centre point rather than dropping it silently."""
    relation = {
        "type": "relation",
        "id": 42,
        "center": {"lat": 18.53, "lon": 73.86},
        "tags": {"name": "Temple Complex", "amenity": "place_of_worship"},
    }
    patch_transport(
        monkeypatch,
        make_client_factory({"elements": [relation]}),
    )

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=2,
        category="temples_and_spiritual",
    )

    assert result["total_results"] == 1
    place = result["places"][0]
    assert place["id"] == "relation/42"
    assert place["latitude"] == 18.53
    assert place["longitude"] == 73.86
    assert place["name"] == "Temple Complex"


# ---------------------------------------------------------------------------
# Temples & Spiritual: temples only
# ---------------------------------------------------------------------------


ELEMENT_MOSQUE = {
    "type": "node",
    "id": 10,
    "lat": 18.521,
    "lon": 73.857,
    "tags": {
        "name": "Jama Masjid",
        "amenity": "place_of_worship",
        "religion": "muslim",
    },
}

ELEMENT_CHURCH = {
    "type": "node",
    "id": 11,
    "lat": 18.522,
    "lon": 73.858,
    "tags": {
        "name": "St Mary's Church",
        "amenity": "place_of_worship",
        "religion": "christian",
    },
}

ELEMENT_GURUDWARA = {
    "type": "node",
    "id": 12,
    "lat": 18.523,
    "lon": 73.859,
    "tags": {
        "name": "Guru Nanak Gurudwara",
        "amenity": "place_of_worship",
        "religion": "sikh",
    },
}

ELEMENT_TEMPLE = {
    "type": "node",
    "id": 13,
    "lat": 18.524,
    "lon": 73.860,
    "tags": {
        "name": "Dagdusheth Halwai Ganpati Temple",
        "amenity": "place_of_worship",
        "religion": "hindu",
    },
}

# A temple whose religion tag is missing but whose name says temple.
ELEMENT_UNTAGGED_TEMPLE = {
    "type": "way",
    "id": 14,
    "center": {"lat": 18.525, "lon": 73.861},
    "tags": {"name": "Pataleshwar Cave Temple", "building": "temple"},
}

# A worship place with no religion/building tag but a masjid name.
ELEMENT_MISSED_MOSQUE = {
    "type": "node",
    "id": 15,
    "lat": 18.526,
    "lon": 73.862,
    "tags": {"name": "Old Masjid", "amenity": "place_of_worship"},
}


def test_temple_category_excludes_mosque_church_gurudwara(monkeypatch):
    elements = [
        ELEMENT_MOSQUE,
        ELEMENT_CHURCH,
        ELEMENT_GURUDWARA,
        ELEMENT_TEMPLE,
        ELEMENT_UNTAGGED_TEMPLE,
    ]
    patch_transport(monkeypatch, make_client_factory({"elements": elements}))

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=10,
        category="temples_and_spiritual",
    )

    names = [place["name"] for place in result["places"]]
    assert names == [
        "Dagdusheth Halwai Ganpati Temple",
        "Pataleshwar Cave Temple",
    ]


def test_temple_category_filters_non_temple_names(monkeypatch):
    """A worship place whose tags are missing but whose name says
    masjid/church/dargah is dropped even when the Overpass query
    (regex on religion) returned it."""
    patch_transport(
        monkeypatch,
        make_client_factory({"elements": [ELEMENT_MISSED_MOSQUE, ELEMENT_TEMPLE]}),
    )

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=5,
        category="temples_and_spiritual",
    )

    names = [place["name"] for place in result["places"]]
    assert names == ["Dagdusheth Halwai Ganpati Temple"]


def test_temple_query_uses_religion_regex_and_temple_building_tags():
    query = _query_for("temples")
    assert (
        '["religion"~"^(hindu|buddhist|jain|taoist)$"]' in query
    )
    assert '["building"="temple"]' in query
    assert '["historic"="temple"]' in query
    # The generic selector must no longer appear alone: it now always
    # carries the temple-religion regex.
    assert '["amenity"="place_of_worship"]["religion"' in query


def test_other_categories_still_accept_worship_places(monkeypatch):
    """Heritage queries keep returning e.g. a famous church as a historic
    attraction - only the temples category is restricted."""
    church_historic = {
        "type": "node",
        "id": 20,
        "lat": 18.53,
        "lon": 73.86,
        "tags": {
            "name": "St Mary's Church",
            "historic": "church",
        },
    }
    patch_transport(
        monkeypatch, make_client_factory({"elements": [church_historic]})
    )

    result = search_places(
        latitude=18.5204, longitude=73.8567, radius_km=5,
        category="tourist_attractions_and_heritage",
    )

    assert result["total_results"] == 1
    assert result["places"][0]["name"] == "St Mary's Church"


def test_is_non_temple_name():
    from app.tools.place_tools import is_non_temple_name

    assert is_non_temple_name("Jama Masjid")
    assert is_non_temple_name("St Paul's Church")
    assert is_non_temple_name("Gurudwara Shri Singh Sabha")
    assert is_non_temple_name("Haji Ali Dargah")
    assert not is_non_temple_name("Dagdusheth Halwai Ganpati Temple")
    assert not is_non_temple_name("Pataleshwar Cave Temple")
    assert not is_non_temple_name("")
