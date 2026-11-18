package com.dev.placeexplorer.domain.model

/**
 * A place that can appear in an outing itinerary.
 */
data class Place(
    val id: String,
    val name: String,
    val shortDescription: String,
    val fullDescription: String,
    val address: String,
    val latitude: Double,
    val longitude: Double,
    val interests: Set<Interest>,
    val suggestedVisitMinutes: Int,
    val openingHours: String,
    val imageUrl: String? = null,
    val isOptionalAttraction: Boolean = false
)

/**
 * A nearby food recommendation attached to an itinerary stop.
 */
data class NearbyFoodRecommendation(
    val name: String,
    val cuisine: String,
    val mealType: MealType,
    val isVegetarianFriendly: Boolean,
    val distanceKm: Double,
    val priceLevel: Int // 1..4
)

enum class MealType(val label: String) {
    BREAKFAST("Breakfast"),
    LUNCH("Lunch"),
    SNACK("Snacks"),
    DINNER("Dinner")
}

/**
 * Full details of a single place, shown on the Place Details screen.
 */
data class PlaceDetails(
    val place: Place,
    val nearbyRestaurants: List<NearbyFoodRecommendation>,
    /** Other popular attractions around this place. */
    val nearbyAttractions: List<Place> = emptyList()
)
