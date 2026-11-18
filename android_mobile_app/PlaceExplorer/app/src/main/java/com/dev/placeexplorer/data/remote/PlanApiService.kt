package com.dev.placeexplorer.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface for the PlaceExplorer FastAPI backend.
 */
interface PlanApiService {

    @POST("api/plan")
    suspend fun planOuting(@Body request: ApiOutingRequest): ApiItinerary

    /** Free-text starting-location search (cities, areas, landmarks, addresses). */
    @GET("api/geocode")
    suspend fun geocode(
        @Query("q") query: String,
        @Query("limit") limit: Int = DEFAULT_GEOCODE_LIMIT
    ): ApiGeocodeResponse

    /** Resolve device coordinates into a city / place label. */
    @GET("api/geocode/reverse")
    suspend fun reverseGeocode(
        @Query("latitude") latitude: Double,
        @Query("longitude") longitude: Double
    ): ApiGeoReverseResponse

    @GET("api/places/search")
    suspend fun searchPlaces(@Query("q") query: String): ApiPlacesSearchResponse

    @GET("api/places/{placeId}")
    suspend fun getPlaceDetails(
        @Path(value = "placeId", encoded = true) placeId: String,
        @Query("foodPreference") foodPreference: String? = null
    ): ApiPlaceDetails

    companion object {
        const val DEFAULT_GEOCODE_LIMIT = 5
    }
}

/** Response of GET /api/places/search; mirrors app/main.py places_search. */
@Serializable
data class ApiPlacesSearchResponse(
    val query: String,
    @SerialName("total_results") val totalResults: Int = 0,
    val places: List<ApiPlace> = emptyList()
)

/** Response of GET /api/geocode; mirrors backend schemas/geocoding.py. */
@Serializable
data class ApiGeocodeResponse(
    val query: String,
    val results: List<ApiGeoSearchResult> = emptyList()
)

/** Response of GET /api/geocode/reverse; mirrors GeoReverseResponse. */
@Serializable
data class ApiGeoReverseResponse(
    val latitude: Double,
    val longitude: Double,
    val name: String? = null,
    @SerialName("displayName") val displayName: String? = null,
    // City-level component (Pune, not the Maan village inside it).
    val city: String? = null,
    val address: String? = null
)

@Serializable
data class ApiGeoSearchResult(
    val id: String,
    val name: String? = null,
    @SerialName("displayName") val displayName: String? = null,
    val latitude: Double,
    val longitude: Double,
    val address: String? = null
)

@Serializable
data class ApiPlaceDetails(
    val place: ApiPlace,
    @SerialName("nearbyRestaurants") val nearbyRestaurants: List<ApiNearbyFoodRecommendation> = emptyList(),
    @SerialName("nearbyAttractions") val nearbyAttractions: List<ApiPlace> = emptyList()
)
