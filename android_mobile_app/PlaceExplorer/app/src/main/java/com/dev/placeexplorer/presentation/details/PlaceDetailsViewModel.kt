package com.dev.placeexplorer.presentation.details

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.core.OutingSession
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.domain.model.PlaceDetails
import com.dev.placeexplorer.location.DeviceLocationProvider
import com.dev.placeexplorer.location.DeviceLocationResult
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PlaceDetailsUiState(
    /**
     * The place shown immediately. Set synchronously from the itinerary
     * data the user just tapped, so the screen renders instantly; the
     * backend refresh below may replace it with fuller data.
     */
    val place: Place? = null,
    /** Nearby food options, loaded asynchronously after first render. */
    val nearbyRestaurants: List<com.dev.placeexplorer.domain.model.NearbyFoodRecommendation> = emptyList(),
    val isFoodLoading: Boolean = false,
    /** Device fix used for the "distance from your location" labels. */
    val userLocation: Pair<Double, Double>? = null,
    val error: String? = null
)

class PlaceDetailsViewModel(
    private val placeId: String,
    private val repository: com.dev.placeexplorer.domain.repository.OutingRepository = AppContainer.outingRepository,
    private val locationProvider: DeviceLocationProvider? = AppContainer.locationProviderOrNull()
) : ViewModel() {

    private val _uiState = MutableStateFlow(PlaceDetailsUiState())
    val uiState: StateFlow<PlaceDetailsUiState> = _uiState.asStateFlow()

    init {
        seedFromItinerary()
        if (_uiState.value.place == null) loadPlaceFromRepository()
        fetchUserLocation()
        loadNearbyFood()
    }

    fun dismissError() = _uiState.update { it.copy(error = null) }

    /**
     * Render instantly from data the app already holds: the itinerary in
     * OutingSession contains the tapped place with name, description,
     * address and coordinates. No network round trip before first paint.
     */
    private fun seedFromItinerary() {
        val itinerary = OutingSession.itinerary.value
        val seeded = itinerary?.stops
            ?.firstOrNull { it.place.id == placeId }
            ?.place
            ?: itinerary?.optionalAttractions?.firstOrNull { it.id == placeId }
        if (seeded != null && itinerary != null) {
            _uiState.update {
                it.copy(
                    place = seeded,
                    userLocation = itinerary.request.startLocation
                        .takeIf { loc -> loc.isCurrentLocation }
                        ?.let { loc -> loc.latitude to loc.longitude }
                )
            }
        }
    }

    /**
     * Repository fallback for when the place is not in the session (e.g.
     * process death, or an id the repository knows but the current outing
     * does not). "Place not found" only remains when the repository itself
     * does not know the id.
     */
    private fun loadPlaceFromRepository() {
        viewModelScope.launch {
            val preference = OutingSession.itinerary.value
                ?.request
                ?.foodPreference
                ?: com.dev.placeexplorer.domain.model.FoodPreference.BOTH
            runCatching { repository.getPlaceDetails(placeId, preference) }
                .onSuccess { details ->
                    if (details != null) {
                        _uiState.update { it.copy(place = details.place) }
                        // Food could not load earlier (place was unknown
                        // then); kick it off now that the place resolved.
                        loadNearbyFood()
                    }
                }
                // Failure leaves the existing state untouched; the screen
                // keeps its honest "Place not found" handling.
        }
    }

    /**
     * Nearby food loads independently in the background. The screen is
     * already rendered; only this section shows a small spinner while it
     * works, and a failure leaves the section empty (with a quiet inline
     * hint) without ever delaying the screen.
     */
    private fun loadNearbyFood() {
        if (_uiState.value.place == null) return
        _uiState.update { it.copy(isFoodLoading = true) }
        viewModelScope.launch {
            val preference = OutingSession.itinerary.value
                ?.request
                ?.foodPreference
                ?: com.dev.placeexplorer.domain.model.FoodPreference.BOTH
        // (request is non-null whenever the itinerary exists)
        runCatching { repository.getPlaceDetails(placeId, preference) }
                .onSuccess { details ->
                    _uiState.update {
                        it.copy(
                            nearbyRestaurants = details?.nearbyRestaurants ?: emptyList(),
                            isFoodLoading = false
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update {
                        it.copy(
                            isFoodLoading = false,
                            error = e.message ?: "Could not load nearby food options."
                        )
                    }
                }
        }
    }

    /**
     * Best-effort device fix for distance labels: when permission is
     * missing or no fix arrives, the labels show "Distance unavailable"
     * instead of blocking or failing the screen.
     */
    private fun fetchUserLocation() {
        val provider = locationProvider ?: return
        viewModelScope.launch {
            val location = runCatching { provider.getCurrentLocation() }.getOrNull()
            if (location is DeviceLocationResult.Success) {
                _uiState.update {
                    it.copy(userLocation = location.latitude to location.longitude)
                }
            }
        }
    }
}
