package com.dev.placeexplorer.domain.model

/**
 * Length of the outing chosen by the user.
 */
enum class OutingDuration(val label: String, val totalHours: Int) {
    HALF_DAY("Half Day", 4),
    FULL_DAY("Full Day", 8)
}

/**
 * Preferred time of day for the outing.
 */
enum class TimeOfDay(val label: String, val startHour: Int) {
    MORNING("Morning", 9),
    EVENING("Evening", 16)
}

/**
 * Interest categories the user can select.
 *
 * "Mixed Experience" and "Famous Attractions" were folded into the
 * remaining categories; an empty selection means "anything".
 */
enum class Interest(val label: String, val emoji: String) {
    TEMPLES("Temples & Spiritual", "🛕"),
    NATURE("Nature & Scenic", "🌿"),
    HERITAGE("Heritage & History", "🏛️"),
    SHOPPING("Shopping & Entertainment", "🛍️")
}

/**
 * Food preference for restaurant recommendations.
 */
enum class FoodPreference(val label: String) {
    VEGETARIAN("Veg"),
    NON_VEGETARIAN("Non-Veg"),
    BOTH("Both")
}

/**
 * Where the outing starts from.
 */
data class StartLocation(
    val name: String,
    val isCurrentLocation: Boolean = false,
    val latitude: Double = 0.0,
    val longitude: Double = 0.0
)

/**
 * The complete request sent to the outing-planning backend.
 *
 * This model is designed to be serialized as the request body of the
 * future FastAPI `POST /outings` call, so the Android side does not need
 * to change when the mock repository is replaced with a Retrofit one.
 */
data class OutingRequest(
    val destination: String = DEFAULT_DESTINATION,
    val duration: OutingDuration = OutingDuration.HALF_DAY,
    val timeOfDay: TimeOfDay = TimeOfDay.MORNING,
    val interests: Set<Interest> = emptySet(),
    val foodPreference: FoodPreference = FoodPreference.BOTH,
    val startLocation: StartLocation = StartLocation(
        name = "Current Location",
        isCurrentLocation = true
    )
) {
    companion object {
        const val DEFAULT_DESTINATION = "Pune, Maharashtra"
    }
}
