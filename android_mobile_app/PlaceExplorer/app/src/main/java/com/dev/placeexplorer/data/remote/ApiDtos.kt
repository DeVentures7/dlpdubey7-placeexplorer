package com.dev.placeexplorer.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * DTOs mirroring the FastAPI POST /api/plan contract
 * (backend/app/schemas/outing.py, all camelCase keys, enum names as strings).
 *
 * These are transport-layer types only; mapping to the domain models happens
 * in [com.dev.placeexplorer.data.repository.ApiOutingRepository].
 */
@Serializable
data class ApiOutingRequest(
    val destination: String = "Pune, Maharashtra",
    val duration: String = "HALF_DAY",
    @SerialName("timeOfDay") val timeOfDay: String = "MORNING",
    val interests: List<String> = emptyList(),
    @SerialName("foodPreference") val foodPreference: String = "BOTH",
    @SerialName("startLocation") val startLocation: ApiStartLocation = ApiStartLocation()
)

@Serializable
data class ApiStartLocation(
    val name: String = "Current Location",
    @SerialName("isCurrentLocation") val isCurrentLocation: Boolean = false,
    val latitude: Double = 0.0,
    val longitude: Double = 0.0
)

@Serializable
data class ApiItinerary(
    val id: String,
    val title: String,
    val destination: String,
    val request: ApiOutingRequest,
    val stops: List<ApiItineraryStop>,
    @SerialName("totalDurationMinutes") val totalDurationMinutes: Int,
    @SerialName("optionalAttractions") val optionalAttractions: List<ApiPlace> = emptyList(),
    @SerialName("foodRecommendations") val foodRecommendations: Map<String, List<ApiNearbyFoodRecommendation>> = emptyMap()
)

@Serializable
data class ApiItineraryStop(
    val place: ApiPlace,
    @SerialName("arrivalTimeMinutes") val arrivalTimeMinutes: Int,
    @SerialName("visitDurationMinutes") val visitDurationMinutes: Int,
    @SerialName("travelToNext") val travelToNext: ApiTravelLeg? = null
)

@Serializable
data class ApiPlace(
    val id: String,
    val name: String,
    @SerialName("shortDescription") val shortDescription: String,
    @SerialName("fullDescription") val fullDescription: String,
    val address: String,
    val latitude: Double,
    val longitude: Double,
    val interests: List<String>,
    @SerialName("suggestedVisitMinutes") val suggestedVisitMinutes: Int,
    @SerialName("openingHours") val openingHours: String,
    @SerialName("imageUrl") val imageUrl: String? = null,
    @SerialName("isOptionalAttraction") val isOptionalAttraction: Boolean = false
)

@Serializable
data class ApiNearbyFoodRecommendation(
    val name: String,
    val cuisine: String,
    @SerialName("mealType") val mealType: String,
    @SerialName("isVegetarianFriendly") val isVegetarianFriendly: Boolean,
    @SerialName("distanceKm") val distanceKm: Double,
    @SerialName("priceLevel") val priceLevel: Int
)

@Serializable
data class ApiTravelLeg(
    @SerialName("distanceKm") val distanceKm: Double,
    @SerialName("durationMinutes") val durationMinutes: Int
)

/** Body of a backend error response: {"detail": "..."} */
@Serializable
data class ApiError(
    val detail: String? = null
)
