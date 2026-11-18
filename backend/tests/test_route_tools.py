"""
Tests for the OSRM-backed routing tools.

Every HTTP interaction is mocked with httpx.MockTransport - no live
OSRM calls are made. The mock transport is installed by patching
route_tools._create_client, the single point where an httpx.Client is
created.
"""

import pytest

from app.tools import route_tools
from app.tools.route_tools import (
    clear_route_cache,
    get_route,
    get_route_matrix,
)


# ---------------------------------------------------------------------------
# Mock transport plumbing
# ---------------------------------------------------------------------------


def patch_transport(monkeypatch, handler):
    import httpx

    def factory():
        return httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=5,
            headers={"User-Agent": route_tools.USER_AGENT},
        )

    monkeypatch.setattr(route_tools, "_create_client", factory)


def ok_route_payload(distance_meters, duration_seconds):
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": distance_meters,
                "duration": duration_seconds,
            }
        ],
    }


def ok_table_payload(durations, distances=None):
    payload = {"code": "Ok", "durations": durations}
    if distances is not None:
        payload["distances"] = distances
    return payload


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_route_cache()
    yield
    clear_route_cache()


# ---------------------------------------------------------------------------
# get_route
# ---------------------------------------------------------------------------


def test_get_route_returns_road_distance_and_duration(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["user_agent"] = request.headers.get("user-agent")
        from httpx import Response

        return Response(
            200, json=ok_route_payload(4200, 600), request=request
        )

    patch_transport(monkeypatch, handler)

    result = get_route(
        start_latitude=18.5204,
        start_longitude=73.8567,
        end_latitude=18.5293,
        end_longitude=73.8744,
    )

    assert "error" not in result
    assert result["distance_km"] == 4.2
    assert result["duration_minutes"] == 10
    assert result["profile"] == "driving"
    assert result["start"]["latitude"] == 18.5204
    assert result["end"]["longitude"] == 73.8744

    # OSRM API shape: route service, lon,lat order, no geometry payload.
    assert "/route/v1/driving/" in captured["url"]
    assert "73.856700,18.520400;73.874400,18.529300" in captured["url"]
    assert "overview=false" in captured["url"]
    assert "steps=false" in captured["url"]
    assert captured["method"] == "GET"
    assert "PlaceExplorer" in captured["user_agent"]


def test_get_route_repeated_call_uses_cache(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(
            200, json=ok_route_payload(4200, 600), request=request
        )

    patch_transport(monkeypatch, handler)

    first = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    second = get_route(18.5204, 73.8567, 18.5293, 73.8744)

    assert first == second
    assert len(calls) == 1


def test_get_route_reversed_endpoints_is_cache_miss(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(
            200, json=ok_route_payload(4200, 600), request=request
        )

    patch_transport(monkeypatch, handler)

    get_route(18.5204, 73.8567, 18.5293, 73.8744)
    get_route(18.5293, 73.8744, 18.5204, 73.8567)

    assert len(calls) == 2  # direction matters


def test_get_route_invalid_coordinates_rejected(monkeypatch):
    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("HTTP call must not happen for invalid input")

    patch_transport(monkeypatch, handler)

    result = get_route(999, 73.8567, 18.5293, 73.8744)
    assert "latitude" in result["error"]

    result = get_route(18.5204, -500, 18.5293, 73.8744)
    assert "longitude" in result["error"]


def test_get_route_osrm_error_code_surfaces(monkeypatch):
    def handler(request):
        from httpx import Response

        return Response(
            200,
            json={
                "code": "NoRoute",
                "message": "No route found between points",
            },
            request=request,
        )

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "NoRoute" in result["error"]
    assert "No route found" in result["error"]


def test_get_route_empty_routes_surfaces(monkeypatch):
    def handler(request):
        from httpx import Response

        return Response(200, json={"code": "Ok", "routes": []}, request=request)

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "no route" in result["error"]


def test_get_route_implausible_distance_surfaces(monkeypatch):
    def handler(request):
        from httpx import Response

        return Response(
            200, json=ok_route_payload(900_000_000, 600), request=request
        )

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "implausible" in result["error"]


def test_get_route_timeout_returns_error(monkeypatch):
    import httpx

    def handler(request):
        raise httpx.ReadTimeout("timed out")

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "timed out" in result["error"]


def test_get_route_http_429_returns_error(monkeypatch):
    import httpx
    from httpx import Response

    def handler(request):
        return Response(429, text="rate limited", request=request)

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "429" in result["error"]
    assert "rate limited or overloaded" in result["error"]


def test_get_route_http_500_returns_error(monkeypatch):
    from httpx import Response

    def handler(request):
        return Response(500, text="server error", request=request)

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "HTTP 500" in result["error"]


def test_get_route_invalid_json_returns_error(monkeypatch):
    from httpx import Response

    def handler(request):
        return Response(200, text="<html>bad</html>", request=request)

    patch_transport(monkeypatch, handler)

    result = get_route(18.5204, 73.8567, 18.5293, 73.8744)
    assert "invalid JSON" in result["error"]


def test_get_route_errors_are_not_cached(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(200, text="not json", request=request)

    patch_transport(monkeypatch, handler)

    get_route(18.5204, 73.8567, 18.5293, 73.8744)
    get_route(18.5204, 73.8567, 18.5293, 73.8744)

    assert len(calls) == 2  # failed responses must not be cached


# ---------------------------------------------------------------------------
# get_route_matrix (Table API)
# ---------------------------------------------------------------------------


def test_matrix_returns_durations_and_distances(monkeypatch):
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        from httpx import Response

        return Response(
            200,
            json=ok_table_payload(
                durations=[[0, 600], [600, 0]],
                distances=[[0, 4200], [4200, 0]],
            ),
            request=request,
        )

    patch_transport(monkeypatch, handler)

    result = get_route_matrix(
        [(18.5204, 73.8567), (18.5293, 73.8744)]
    )

    assert "error" not in result
    assert result["matrix"]["durations_minutes"] == [[0, 10], [10, 0]]
    assert result["matrix"]["distances_km"] == [[0, 4.2], [4.2, 0]]
    assert len(result["coordinates"]) == 2

    assert "/table/v1/driving/" in captured["url"]
    assert "annotations=duration,distance" in captured["url"]
    assert "73.856700,18.520400;73.874400,18.529300" in captured["url"]


def test_matrix_null_entries_preserved(monkeypatch):
    """OSRM returns null for unreachable pairs; never fabricate a value."""

    def handler(request):
        from httpx import Response

        return Response(
            200,
            json=ok_table_payload(
                durations=[[0, None], [None, 0]],
                distances=[[0, None], [None, 0]],
            ),
            request=request,
        )

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])

    assert result["matrix"]["durations_minutes"] == [[0, None], [None, 0]]
    assert result["matrix"]["distances_km"] == [[0, None], [None, 0]]


def test_matrix_missing_distance_annotation_is_none(monkeypatch):
    """Older OSRM builds omit distance annotations - report only what
    the server provided, do not invent distances from durations."""

    def handler(request):
        from httpx import Response

        return Response(
            200,
            json=ok_table_payload(durations=[[0, 600], [600, 0]]),
            request=request,
        )

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])

    assert result["matrix"]["durations_minutes"] == [[0, 10], [10, 0]]
    assert result["matrix"]["distances_km"] is None


def test_matrix_too_many_coordinates_rejected(monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP call must not happen for oversized input")

    patch_transport(monkeypatch, handler)

    coordinates = [(18.0 + i * 0.01, 73.0 + i * 0.01) for i in range(26)]
    result = get_route_matrix(coordinates)
    assert "Too many coordinates" in result["error"]


def test_matrix_empty_coordinates_rejected(monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP call must not happen for empty input")

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([])
    assert "non-empty" in result["error"]


def test_matrix_invalid_coordinate_rejected(monkeypatch):
    def handler(request):  # pragma: no cover
        raise AssertionError("HTTP call must not happen for invalid input")

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([(18.52, 73.85), (999, 73.86)])
    assert "Invalid coordinate 1" in result["error"]


def test_matrix_repeated_call_uses_cache(monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        from httpx import Response

        return Response(
            200,
            json=ok_table_payload(durations=[[0, 600], [600, 0]]),
            request=request,
        )

    patch_transport(monkeypatch, handler)

    first = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])
    second = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])

    assert first == second
    assert len(calls) == 1


def test_matrix_osrm_error_code_surfaces(monkeypatch):
    def handler(request):
        from httpx import Response

        return Response(
            200,
            json={"code": "NoTable", "message": "No table found"},
            request=request,
        )

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])
    assert "NoTable" in result["error"]


def test_matrix_missing_durations_surfaces(monkeypatch):
    def handler(request):
        from httpx import Response

        return Response(200, json={"code": "Ok"}, request=request)

    patch_transport(monkeypatch, handler)

    result = get_route_matrix([(18.52, 73.85), (48.85, 2.35)])
    assert "no duration table" in result["error"]
