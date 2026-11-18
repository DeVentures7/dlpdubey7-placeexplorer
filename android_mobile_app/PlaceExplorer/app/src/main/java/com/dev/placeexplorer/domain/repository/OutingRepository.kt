package com.dev.placeexplorer.domain.repository

import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.PlaceDetails
import com.dev.placeexplorer.domain.model.Place

/**
 * Contract for the outing-planning backend.
 *
 * The production implementation will be a Retrofit client talking to the
 * FastAPI + Gemini backend; the current implementation is
 * [com.dev.placeexplorer.data.repository.MockOutingRepository].
 */
interface OutingRepository {

    /**
     * Generates a geographically sensible itinerary for the given request.
     */
    suspend fun generateOuting(request: OutingRequest): Itinerary

    /**
     * Loads full details (including nearby restaurants) for one place.
     */
    suspend fun getPlaceDetails(
        placeId: String,
        foodPreference: FoodPreference = FoodPreference.BOTH
    ): PlaceDetails?

    /**
     * Lists all known places (used by the start-location search).
     */
    suspend fun searchPlaces(query: String): List<Place>
}
