package com.dev.placeexplorer.data.remote

import com.dev.placeexplorer.data.remote.ApiMappers.toDomain
import com.dev.placeexplorer.data.remote.ApiMappers.toDto
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.domain.model.PlaceDetails
import com.dev.placeexplorer.domain.repository.OutingRepository

/**
 * OutingRepository backed by the FastAPI backend through Retrofit.
 *
 * Failures are never swallowed into mock data: any network/HTTP error
 * propagates as [ApiException] carrying the backend explanation (e.g. the
 * HTTP 503 "insufficient real place data" message) so the UI can show it.
 */
class ApiOutingRepository(
    private val api: PlanApiService
) : OutingRepository {

    override suspend fun generateOuting(request: OutingRequest): Itinerary {
        val itinerary = try {
            api.planOuting(request.toDto())
        } catch (http: retrofit2.HttpException) {
            throw ApiException.fromHttpException(http)
        }
        return itinerary.toDomain()
    }

    /**
     * Free-text place search against the backend's GET /api/places/search,
     * ranked by distance + popularity. An HTTP 400 (unresolvable query) is
     * an honest "no results", not a crash.
     */
    override suspend fun searchPlaces(query: String): List<Place> {
        return try {
            api.searchPlaces(query).places.map { it.toDomain() }
        } catch (http: retrofit2.HttpException) {
            if (http.code() == 400) emptyList() else throw ApiException.fromHttpException(http)
        }
    }

    /**
     * Loads full details for one place from the backend's
     * GET /api/places/{placeId} endpoint, which resolves the exact place
     * id the itinerary passed (never a fresh search) and attaches nearby
     * cafes/restaurants and nearby famous places around its real
     * coordinates.
     */
    override suspend fun getPlaceDetails(
        placeId: String,
        foodPreference: com.dev.placeexplorer.domain.model.FoodPreference
    ): PlaceDetails? {
        return try {
            api.getPlaceDetails(placeId, foodPreference.name).toDomain()
        } catch (http: retrofit2.HttpException) {
            if (http.code() == 404) {
                // A genuinely unknown place id: the UI shows its
                // "not found" state; this is an answer, not an error.
                null
            } else {
                throw ApiException.fromHttpException(http)
            }
        }
    }
}
