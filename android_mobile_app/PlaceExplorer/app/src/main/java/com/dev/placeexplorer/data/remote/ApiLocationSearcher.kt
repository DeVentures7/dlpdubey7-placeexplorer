package com.dev.placeexplorer.data.remote

import com.dev.placeexplorer.search.GeocodePlace
import com.dev.placeexplorer.search.LocationSearcher

/**
 * [LocationSearcher] backed by the FastAPI backend's GET /api/geocode
 * endpoint through the existing Retrofit stack.
 *
 * The backend resolves the query against OpenStreetMap (Nominatim), so no
 * geocoder is called from the app itself. Coordinates travel through
 * unchanged; failures throw [ApiException] (HTTP) or [IOException]
 * (network) and empty results are a genuine "no matches".
 */
class ApiLocationSearcher(
    private val api: PlanApiService
) : LocationSearcher {

    override suspend fun search(query: String): List<GeocodePlace> {
        val response = try {
            api.geocode(query.trim())
        } catch (http: retrofit2.HttpException) {
            throw ApiException.fromHttpException(http)
        }

        return response.results.map { result ->
            GeocodePlace(
                id = result.id,
                // Prefer the short primary name; fall back to the full
                // display name when the provider returns no separate one.
                displayName = result.name ?: result.displayName ?: result.id,
                latitude = result.latitude,
                longitude = result.longitude,
                // Keep the full display name as a disambiguation line when
                // no compact address breakdown is available.
                address = result.address ?: result.displayName
            )
        }
    }
}
