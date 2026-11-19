package com.dev.placeexplorer.data.repository

import com.dev.placeexplorer.data.mock.PunePlaces
import com.dev.placeexplorer.search.GeocodePlace
import com.dev.placeexplorer.search.LocationSearcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Mock implementation of [LocationSearcher] backed by the same sample Pune
 * data as [MockOutingRepository]. Keeps the destination search box usable
 * while running without the live backend.
 */
class MockLocationSearcher : LocationSearcher {

    override suspend fun search(query: String): List<GeocodePlace> = withContext(Dispatchers.Default) {
        if (query.isBlank()) {
            // A few well-known start points.
            listOf(
                PunePlaces.shaniwarWada,
                PunePlaces.agaKhanPalace,
                PunePlaces.korumMall
            ).map { it.toGeocodePlace() }
        } else {
            PunePlaces.all
                .filter {
                    it.name.contains(query, ignoreCase = true) ||
                        it.address.contains(query, ignoreCase = true)
                }
                .map { it.toGeocodePlace() }
        }
    }

    private fun com.dev.placeexplorer.domain.model.Place.toGeocodePlace() = GeocodePlace(
        id = id,
        displayName = name,
        latitude = latitude,
        longitude = longitude,
        address = address
    )
}
