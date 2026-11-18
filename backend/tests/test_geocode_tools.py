"""
Tests for the Nominatim geocoding tools and the GET /api/geocode endpoint.

Every HTTP interaction is mocked with httpx.MockTransport - no live
Nominatim calls are made. The mock transport is installed by patching
geocode_tools._create_client, the single point where an httpx.Client is
created. The request throttle is patched to a no-op for speed, except
in the dedicated rate-limit tests.
"""

import time

import pytest

from app.tools import geocode_tools
from app.tools.geocode_tools import (
    clear_cache,
    normalize_query,
    search_location,
)

# Captured at import time, before the autouse fixture replaces the
# throttle - rate-limit tests restore this real implementation.
_REAL_RATE_LIMITER = geocode_tools._respect_rate_limit


# ---------------------------------------------------------------------------
# Mock transport plumbing
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Skip the 1 rps wait in every test; rate-limit tests re-enable it."""
    monkeypatch.setattr(geocode_tools, "_respect_rate_limit", lambda: None)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def patch_transport(monkeypatch, handler):
    import httpx

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=5,
            headers={"User-Agent": geocode_tools.USER_AGENT},
        )

    monkeypatch.setattr(geocode_tools, "_create_client", factory)


def nominatim_hit(place_id=123, name="Pune", display=None, address=None):
    raw = {
        "place_id": place_id,
        "display_name": display or f"{name}, Maharashtra, India",
        "lat": "18.5204",
        "lon": "73.8567",
        "type": "city",
    }
    if address is not None:
        raw["address"] = address
    return raw


def capture_handler(payload, status_code=200, captured=None):
    from httpx import Response

    def handler(request):
        if captured is not None:
            captured["url"] = str(request.url)
            captured["user_agent"] = request.headers.get("user-agent")
            captured["accept"] = request.headers.get("accept")
        if status_code != 200:
            return Response(status_code, text="error", request=request)
        return Response(200, json=payload, request=request)

    return handler


# ---------------------------------------------------------------------------
# search_location - successful searches
# ---------------------------------------------------------------------------


def test_successful_city_search(monkeypatch):
    captured = {}
    patch_transport(
        monkeypatch,
        capture_handler(
            [nominatim_hit(name="Pune", display="Pune, Maharashtra, India")],
            captured=captured,
        ),
    )

    result = search_location("Pune")

    assert "error" not in result
    assert result["query"] == "Pune"
    assert len(result["results"]) == 1

    place = result["results"][0]
    assert place["id"] == "nominatim_123"
    assert place["name"] == "Pune"
    assert place["displayName"] == "Pune, Maharashtra, India"
    assert place["latitude"] == 18.5204
    assert place["longitude"] == 73.8567
    assert isinstance(place["latitude"], float)

    # Provider request shape.
    assert "q=Pune" in captured["url"]
    assert "format=jsonv2" in captured["url"]
    assert "addressdetails=1" in captured["url"]
    assert "limit=5" in captured["url"]
    assert "RAAHIGO" in captured["user_agent"]
    assert captured["accept"] == "application/json"


def test_locality_search(monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler(
            [
                nominatim_hit(
                    place_id=456,
                    name="Kalyani Nagar",
                    display="Kalyani Nagar, Pune, Maharashtra, India",
                    address={
                        "suburb": "Kalyani Nagar",
                        "city": "Pune",
                        "state": "Maharashtra",
                        "country": "India",
                    },
                )
            ]
        ),
    )

    result = search_location("Kalyani Nagar Pune")

    place = result["results"][0]
    assert place["name"] == "Kalyani Nagar"
    assert place["address"] == "Pune, Maharashtra, India"


def test_landmark_search(monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler(
            [
                nominatim_hit(
                    place_id=789,
                    name="Shaniwar Wada",
                    display="Shaniwar Wada, Shaniwar Peth, Pune, Maharashtra, India",
                    address={
                        "road": "Shaniwar Peth",
                        "city": "Pune",
                        "state": "Maharashtra",
                        "country": "India",
                    },
                )
            ]
        ),
    )

    result = search_location("Shaniwar Wada")

    assert result["results"][0]["name"] == "Shaniwar Wada"
    assert result["results"][0]["address"] == "Pune, Maharashtra, India"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_empty_query_rejected(monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP call must not happen for empty query")

    patch_transport(monkeypatch, handler)

    for query in ("", "   "):
        result = search_location(query)
        assert "error" in result
        assert "empty" in result["error"]


def test_result_limit_validation(monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP call must not happen for invalid limit")

    patch_transport(monkeypatch, handler)

    assert "limit must" in search_location("Pune", limit=0)["error"]
    assert "limit must" in search_location("Pune", limit=-3)["error"]
    assert "limit must" in search_location("Pune", limit=11)["error"]
    assert "limit must" in search_location("Pune", limit=2.5)["error"]

    # Valid boundary limits are accepted (mocked so no HTTP).
    patch_transport(monkeypatch, capture_handler([nominatim_hit()]))
    assert "error" not in search_location("Pune", limit=1)
    assert "error" not in search_location("Pune", limit=10)


# ---------------------------------------------------------------------------
# Empty and malformed provider responses
# ---------------------------------------------------------------------------


def test_no_results_returns_empty_list(monkeypatch):
    patch_transport(monkeypatch, capture_handler([]))

    result = search_location("Xyzzy Nowhere City")

    assert "error" not in result
    assert result["results"] == []


def test_missing_optional_address_fields_are_none(monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler([nominatim_hit(address={"country": "India"})]),
    )

    result = search_location("Somewhere in India")

    place = result["results"][0]
    assert place["address"] == "India"


def test_result_without_coordinates_is_skipped(monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler(
            [
                {"place_id": 1, "display_name": "Broken", "lat": "abc", "lon": "0"},
                nominatim_hit(place_id=2, name="Good"),
            ]
        ),
    )

    result = search_location("mixed quality")

    # The malformed entry is skipped; the good one survives.
    assert len(result["results"]) == 1
    assert result["results"][0]["name"] == "Good"


def test_invalid_provider_response_shape(monkeypatch):
    # Nominatim returns a list; a dict means something is wrong upstream.
    patch_transport(monkeypatch, capture_handler({"error": "oops"}))

    result = search_location("Pune")
    assert "unexpected shape" in result["error"]


def test_invalid_provider_json(monkeypatch):
    from httpx import Response

    def handler(request):
        return Response(200, text="<html>bad</html>", request=request)

    patch_transport(monkeypatch, handler)

    result = search_location("Pune")
    assert "invalid JSON" in result["error"]


# ---------------------------------------------------------------------------
# Provider failures
# ---------------------------------------------------------------------------


def test_provider_timeout(monkeypatch):
    import httpx

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    patch_transport(monkeypatch, handler)

    result = search_location("Pune")
    assert "timed out" in result["error"]


def test_provider_http_error(monkeypatch):
    patch_transport(monkeypatch, capture_handler([], status_code=500))

    result = search_location("Pune")
    assert "HTTP 500" in result["error"]


def test_provider_rate_limit_http_429(monkeypatch):
    patch_transport(monkeypatch, capture_handler([], status_code=429))

    result = search_location("Pune")
    assert "429" in result["error"]
    assert "rate limiting" in result["error"]


def test_provider_failures_are_not_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(500, text="down", request=request)

    patch_transport(monkeypatch, handler)

    search_location("Pune")
    search_location("Pune")

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_cache_hit_on_repeated_query(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(
            200,
            json=[nominatim_hit(name="Pune")],
            request=request,
        )

    patch_transport(monkeypatch, handler)

    first = search_location("Pune")
    second = search_location("Pune")   # same case
    third = search_location("  PUNE ")  # different spacing/case

    assert len(calls) == 1  # all three served from one provider call
    assert first == second == third


def test_cache_key_uses_normalized_query(monkeypatch):
    assert normalize_query("  Pune   City ") == "pune city"
    assert normalize_query("PUNE") == normalize_query("pune")


def test_cache_expires_after_ttl(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(
            200, json=[nominatim_hit(name="Pune")], request=request
        )

    patch_transport(monkeypatch, handler)

    search_location("Pune")

    key = next(iter(geocode_tools._cache))
    stored_at, value = geocode_tools._cache[key]
    geocode_tools._cache[key] = (
        stored_at - geocode_tools.CACHE_TTL_SECONDS - 1, value
    )

    search_location("Pune")
    assert len(calls) == 2


def test_different_limit_is_cache_miss(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(200, json=[nominatim_hit()], request=request)

    patch_transport(monkeypatch, handler)

    search_location("Pune", limit=5)
    search_location("Pune", limit=10)

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Rate limiting (the throttle itself)
# ---------------------------------------------------------------------------


def test_rate_limit_enforces_minimum_interval(monkeypatch):
    """Two provider calls back to back are separated by >= the interval."""
    real_throttle = _REAL_RATE_LIMITER

    monkeypatch.setattr(
        geocode_tools, "MIN_REQUEST_INTERVAL_SECONDS", 0.2
    )
    monkeypatch.setattr(geocode_tools, "_last_request_monotonic", 0.0)

    requested = []

    def handler(request):
        requested.append(time.monotonic())
        from httpx import Response

        return Response(200, json=[nominatim_hit()], request=request)

    patch_transport(monkeypatch, handler)

    # Real throttle is restored for this test only.
    monkeypatch.setattr(geocode_tools, "_respect_rate_limit", real_throttle)

    search_location("Pune")
    search_location("Pune City")  # different key -> real provider call

    assert len(requested) == 2
    gap = requested[1] - requested[0]
    assert gap >= geocode_tools.MIN_REQUEST_INTERVAL_SECONDS


def test_rate_limit_shared_across_limits(monkeypatch):
    """The throttle budget is process-wide, not per cache key."""
    real_throttle = _REAL_RATE_LIMITER
    monkeypatch.setattr(geocode_tools, "MIN_REQUEST_INTERVAL_SECONDS", 0.15)
    monkeypatch.setattr(geocode_tools, "_last_request_monotonic", 0.0)

    requested = []

    def handler(request):
        requested.append(time.monotonic())
        from httpx import Response

        return Response(200, json=[nominatim_hit()], request=request)

    patch_transport(monkeypatch, handler)
    monkeypatch.setattr(geocode_tools, "_respect_rate_limit", real_throttle)

    search_location("Pune", limit=5)
    search_location("Mumbai", limit=5)

    assert requested[1] - requested[0] >= 0.15


# ---------------------------------------------------------------------------
# REST endpoint GET /api/geocode
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    gemini_fake = _GeminiStub()
    monkeypatch.setattr("app.main.client", gemini_fake)
    with TestClient(app) as test_client:
        yield test_client


class _GeminiStub:
    """app.main imports require a Gemini client; stub it for tests."""

    class models:  # noqa: N801
        @staticmethod
        def generate_content(*args, **kwargs):
            raise AssertionError("not used in geocode tests")


def test_endpoint_success(api_client, monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler(
            [
                nominatim_hit(
                    place_id=1,
                    name="Pune",
                    display="Pune, Maharashtra, India",
                    address={"city": "Pune", "state": "Maharashtra", "country": "India"},
                )
            ]
        ),
    )

    response = api_client.get("/api/geocode", params={"q": "Pune"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Pune"
    assert len(body["results"]) == 1

    # camelCase contract fields.
    result = body["results"][0]
    assert result["id"] == "nominatim_1"
    assert result["name"] == "Pune"
    assert result["displayName"] == "Pune, Maharashtra, India"
    assert result["latitude"] == 18.5204
    assert result["longitude"] == 73.8567
    assert result["address"] == "Pune, Maharashtra, India"


def test_endpoint_custom_limit(api_client, monkeypatch):
    patch_transport(
        monkeypatch,
        capture_handler([nominatim_hit(place_id=i) for i in range(3)]),
    )

    response = api_client.get("/api/geocode", params={"q": "Pune", "limit": 3})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


def test_endpoint_limit_out_of_range(api_client, monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("must not reach the provider")

    patch_transport(monkeypatch, handler)

    response = api_client.get("/api/geocode", params={"q": "Pune", "limit": 20})
    assert response.status_code == 422  # FastAPI Query validation


def test_endpoint_missing_query(api_client):
    response = api_client.get("/api/geocode")
    assert response.status_code == 422


def test_endpoint_empty_query(api_client, monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("must not reach the provider")

    patch_transport(monkeypatch, handler)

    response = api_client.get("/api/geocode", params={"q": "   "})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_endpoint_no_results(api_client, monkeypatch):
    patch_transport(monkeypatch, capture_handler([]))

    response = api_client.get("/api/geocode", params={"q": "Xyzzy Nowhere"})
    assert response.status_code == 200
    assert response.json() == {"query": "Xyzzy Nowhere", "results": []}


def test_endpoint_provider_failure_is_502(api_client, monkeypatch):
    patch_transport(monkeypatch, capture_handler([], status_code=503))

    response = api_client.get("/api/geocode", params={"q": "Pune"})
    assert response.status_code == 502
    assert "503" in response.json()["detail"]
