from mcp.server.fastmcp import FastMCP

from app.tools.place_tools import (
    search_places as search_places_function,
    get_place_details as get_place_details_function
)
from app.tools.route_tools import (
    get_route as get_route_function,
    get_route_matrix as get_route_matrix_function
)


# Create an MCP server
mcp = FastMCP("PlaceExplorer")


# Expose the place search function as an MCP tool
@mcp.tool()
def search_places(
    latitude: float,
    longitude: float,
    radius_km: float = 5,
    category: str = "tourist_attractions_and_heritage"
) -> dict:
    """
    Search places around a coordinate using OpenStreetMap data.

    Supported categories: temples_and_spiritual,
    tourist_attractions_and_heritage, parks_and_nature,
    restaurants_and_cafes, shopping_and_entertainment.

    Returns structured place data: id (OSM type/ID), name, category,
    latitude, longitude, address and opening_hours when available.
    Missing information is null, never invented.
    """

    return search_places_function(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=category
    )


# Expose the place details function as another MCP tool
@mcp.tool()
def get_place_details(place_id: str) -> dict:
    """
    Retrieve details of a place by its OpenStreetMap ID.

    place_id has the form "<osm_type>/<osm_id>" (e.g. "node/123456789"),
    exactly the id values returned by search_places.
    """

    return get_place_details_function(place_id)


# Expose the routing function as an MCP tool
@mcp.tool()
def get_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float
) -> dict:
    """
    Route between two coordinates using OSRM (OpenStreetMap-based
    routing). Returns actual road distance in km and duration in
    minutes - never a straight-line estimate. Distances come from the
    routing engine's road network.
    """

    return get_route_function(
        start_latitude=start_latitude,
        start_longitude=start_longitude,
        end_latitude=end_latitude,
        end_longitude=end_longitude
    )


# Expose the route matrix function as an MCP tool
@mcp.tool()
def get_route_matrix(coordinates: list) -> dict:
    """
    Duration/distance matrix between up to 25 coordinates in a single
    OSRM Table API request, for efficiently comparing multiple candidate
    places and choosing the stop order. durations_minutes[i][j] and
    distances_km[i][j] describe travel from coordinate i to coordinate j
    (null where the routing engine cannot find a connection).
    """

    return get_route_matrix_function(coordinates)


# Start the MCP server
if __name__ == "__main__":
    mcp.run(transport="stdio")
