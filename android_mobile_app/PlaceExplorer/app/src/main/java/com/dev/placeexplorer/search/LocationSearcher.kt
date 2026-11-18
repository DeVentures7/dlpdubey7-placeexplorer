package com.dev.placeexplorer.search

/**
 * One manually searchable starting location (city, area, landmark, address).
 */
data class GeocodePlace(
    val id: String,
    val displayName: String,
    val latitude: Double,
    val longitude: Double,
    val address: String?
)

/**
 * Capability for resolving free-text starting locations to real
 * coordinates. Implementations talk to a geocoding source (currently the
 * backend's GET /api/geocode endpoint) so ViewModels and UI stay
 * provider-agnostic and tests can inject fakes.
 */
interface LocationSearcher {

    /**
     * Returns matching places for the query; an empty list means no
     * matches. Never returns fabricated coordinates.
     */
    suspend fun search(query: String): List<GeocodePlace>
}
