package com.dev.placeexplorer.domain.model

/**
 * Travel information between two consecutive stops of an itinerary.
 */
data class TravelLeg(
    val distanceKm: Double,
    val durationMinutes: Int
)

/**
 * One ordered stop of a generated outing.
 */
data class ItineraryStop(
    val place: Place,
    val arrivalTimeMinutes: Int, // minutes from midnight
    val visitDurationMinutes: Int,
    val travelToNext: TravelLeg? // null for the last stop
)

/**
 * The complete generated outing, geographically ordered.
 */
data class Itinerary(
    val id: String,
    val title: String,
    val destination: String,
    val request: OutingRequest,
    val stops: List<ItineraryStop>,
    val totalDurationMinutes: Int,
    val optionalAttractions: List<Place>,
    /** Food recommendations keyed by the place id of the stop they belong to. */
    val foodRecommendations: Map<String, List<NearbyFoodRecommendation>> = emptyMap()
) {
    val endTimeMinutes: Int
        get() = stops.lastOrNull()
            ?.let { it.arrivalTimeMinutes + it.visitDurationMinutes }
            ?: 0
}
