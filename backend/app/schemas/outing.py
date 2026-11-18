"""
Pydantic models that mirror the Android Kotlin domain models:

- OutingModels.kt  -> OutingRequest, StartLocation, OutingDuration, TimeOfDay,
                      Interest, FoodPreference
- PlaceModels.kt   -> Place, NearbyFoodRecommendation, MealType
- ItineraryModels.kt -> TravelLeg, ItineraryStop, Itinerary

Field names, types, nullable fields and enum names are preserved so the
Android app can deserialize responses directly (kotlinx.serialization emits
enum names, e.g. "HALF_DAY", "TEMPLES", and camelCase property names).
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Serializes with camelCase keys to match the Kotlin property names."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Enums (names match the Kotlin enum entries exactly)
# ---------------------------------------------------------------------------


class OutingDuration(str, Enum):
    HALF_DAY = "HALF_DAY"
    FULL_DAY = "FULL_DAY"

    @property
    def label(self) -> str:
        return "Half Day" if self is OutingDuration.HALF_DAY else "Full Day"

    @property
    def total_hours(self) -> int:
        return 4 if self is OutingDuration.HALF_DAY else 8


class TimeOfDay(str, Enum):
    MORNING = "MORNING"
    EVENING = "EVENING"

    @property
    def label(self) -> str:
        return "Morning" if self is TimeOfDay.MORNING else "Evening"

    @property
    def start_hour(self) -> int:
        return 9 if self is TimeOfDay.MORNING else 16


class Interest(str, Enum):
    TEMPLES = "TEMPLES"
    NATURE = "NATURE"
    HERITAGE = "HERITAGE"
    SHOPPING = "SHOPPING"


INTEREST_LABELS: dict[Interest, str] = {
    Interest.TEMPLES: "Temples & Spiritual",
    Interest.NATURE: "Nature & Scenic",
    Interest.HERITAGE: "Heritage & History",
    Interest.SHOPPING: "Shopping & Entertainment",
}


class FoodPreference(str, Enum):
    VEGETARIAN = "VEGETARIAN"
    NON_VEGETARIAN = "NON_VEGETARIAN"
    BOTH = "BOTH"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    SNACK = "SNACK"
    DINNER = "DINNER"


# ---------------------------------------------------------------------------
# Request models (OutingModels.kt)
# ---------------------------------------------------------------------------


class StartLocation(CamelModel):
    name: str = "Current Location"
    is_current_location: bool = False
    latitude: float = 0.0
    longitude: float = 0.0

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("startLocation.name must not be empty")
        return value


class OutingRequest(CamelModel):
    """Request body of POST /api/plan; mirrors OutingRequest in OutingModels.kt."""

    destination: str = "Pune, Maharashtra"
    duration: OutingDuration = OutingDuration.HALF_DAY
    time_of_day: TimeOfDay = TimeOfDay.MORNING
    interests: list[Interest] = []
    food_preference: FoodPreference = FoodPreference.BOTH
    start_location: StartLocation = StartLocation()

    @field_validator("destination")
    @classmethod
    def destination_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("destination must not be empty")
        return value

    @model_validator(mode="after")
    def dedupe_interests(self) -> "OutingRequest":
        # Android sends a Set<Interest>; deduplicate while preserving order.
        self.interests = list(dict.fromkeys(self.interests))
        return self


# ---------------------------------------------------------------------------
# Response models (PlaceModels.kt and ItineraryModels.kt)
# ---------------------------------------------------------------------------


class Place(CamelModel):
    id: str
    name: str
    short_description: str
    full_description: str
    address: str
    latitude: float
    longitude: float
    interests: list[Interest]
    suggested_visit_minutes: int
    opening_hours: str
    image_url: Optional[str] = None
    is_optional_attraction: bool = False


class NearbyFoodRecommendation(CamelModel):
    name: str
    cuisine: str
    meal_type: MealType
    is_vegetarian_friendly: bool
    distance_km: float
    price_level: int  # 1..4


class TravelLeg(CamelModel):
    distance_km: float
    duration_minutes: int


class ItineraryStop(CamelModel):
    place: Place
    arrival_time_minutes: int  # minutes from midnight
    visit_duration_minutes: int
    travel_to_next: Optional[TravelLeg] = None  # null for the last stop


class Itinerary(CamelModel):
    """Response body of POST /api/plan; mirrors Itinerary in ItineraryModels.kt."""

    id: str
    title: str
    destination: str
    request: OutingRequest
    stops: list[ItineraryStop]
    total_duration_minutes: int
    optional_attractions: list[Place] = []
    food_recommendations: dict[str, list[NearbyFoodRecommendation]] = {}


class PlaceDetailsResponse(CamelModel):
    """
    Response body of GET /api/places/{place_id}; mirrors PlaceDetails in
    PlaceModels.kt plus nearbyAttractions (famous places around the place).
    """

    place: Place
    nearby_restaurants: list[NearbyFoodRecommendation] = []
    nearby_attractions: list[Place] = []
