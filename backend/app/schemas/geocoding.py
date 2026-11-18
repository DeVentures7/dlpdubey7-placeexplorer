
# Response models for the geocoding REST API.
#
# Field mapping to the Android LocationSearcher result model
# (GeocodePlace in search/LocationSearcher.kt):
#
#   GeocodePlace.id           -> GeoSearchResult.id
#   GeocodePlace.displayName  -> GeoSearchResult.name   (short primary name)
#   GeocodePlace.latitude     -> GeoSearchResult.latitude
#   GeocodePlace.longitude    -> GeoSearchResult.longitude
#   GeocodePlace.address      -> GeoSearchResult.address (nullable)
#
# The full provider display name travels in displayName, which the
# Android UI can use as a subtitle or disambiguation line. GeoSearchResult
# is a superset of GeocodePlace, so Android can keep its existing model
# and pick the fields it needs - no Android change required.

from pydantic import BaseModel, ConfigDict, Field


class GeoSearchResult(BaseModel):
    """One resolved location (city, locality, landmark or address)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str | None = None
    # Full provider display name, e.g.
    # "Kalyani Nagar, Pune, Maharashtra, India". camelCase alias matches
    # the JSON contract; populate_by_name also accepts display_name.
    display_name: str | None = Field(default=None, alias="displayName")
    latitude: float
    longitude: float
    # Compact "city, district, state, country" address; null when the
    # provider breakdown has no usable parts.
    address: str | None = None


class GeoSearchResponse(BaseModel):
    """Response for GET /api/geocode."""

    query: str
    results: list[GeoSearchResult]


class GeoReverseResponse(BaseModel):
    """Response for GET /api/geocode/reverse."""

    latitude: float
    longitude: float
    name: str | None = None
    displayName: str | None = Field(default=None, alias="displayName")
    # City-level component (Pune, not the Maan village inside it); null
    # when the provider breakdown has no city/town/village.
    city: str | None = None
    address: str | None = None

    model_config = ConfigDict(populate_by_name=True)
