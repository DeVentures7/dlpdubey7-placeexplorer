package com.dev.placeexplorer.presentation.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.core.OutingSession
import com.dev.placeexplorer.data.remote.ApiException
import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.OutingDuration
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.domain.model.StartLocation
import com.dev.placeexplorer.domain.model.TimeOfDay
import com.dev.placeexplorer.location.DeviceLocationProvider
import com.dev.placeexplorer.location.DeviceLocationResult
import com.dev.placeexplorer.search.LocationSearcher
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Immutable UI state for the home questionnaire. */
data class HomeUiState(
    /** Destination city; defaults to the device's current city once known. */
    val destination: String = "",
    /** True until the current city has been resolved (or failed). */
    val isResolvingCurrentCity: Boolean = false,
    val duration: OutingDuration = OutingDuration.HALF_DAY,
    val timeOfDay: TimeOfDay = TimeOfDay.MORNING,
    val interests: Set<Interest> = setOf(Interest.TEMPLES), // default: temples
    val foodPreference: FoodPreference = FoodPreference.VEGETARIAN, // default: Veg
    /** Device fix; always the starting point of the outing. */
    val currentLocationFix: StartLocation? = null,
    val isLocating: Boolean = false,
    val needsPermissionRequest: Boolean = false, // Compose launches the system dialog
    val locationPermissionDenied: Boolean = false,
    val locationError: String? = null,
    /** "Change" button opens the destination search. */
    val isDestinationSearchActive: Boolean = false,
    val destinationSearchQuery: String = "",
    val destinationSearchResults: List<Place> = emptyList(),
    val isSearchingDestination: Boolean = false,
    val isGenerating: Boolean = false,
    val error: String? = null
) {
    /** The outing always starts from the device's current location. */
    val hasCurrentLocation: Boolean
        get() = currentLocationFix != null
}

class HomeViewModel(
    private val repository: com.dev.placeexplorer.domain.repository.OutingRepository = AppContainer.outingRepository,
    private val locationProvider: DeviceLocationProvider = AppContainer.locationProvider,
    private val locationSearcher: LocationSearcher = AppContainer.locationSearcher,
    private val reverseGeocoder: suspend (Double, Double) -> com.dev.placeexplorer.data.remote.ApiGeoReverseResponse =
        { lat, lng -> AppContainer.planApi.reverseGeocode(lat, lng) }
) : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    init {
        // Auto-plan-from-here: resolve the device location (and, from it,
        // the default destination city) as soon as the home screen opens.
        beginCurrentLocationFlow()
    }

    fun onDurationSelected(duration: OutingDuration) = _uiState.update { it.copy(duration = duration) }

    fun onTimeOfDaySelected(timeOfDay: TimeOfDay) = _uiState.update { it.copy(timeOfDay = timeOfDay) }

    /**
     * Single-selection interest picker: choosing an interest replaces the
     * previous one. There is always exactly one interest selected — the
     * default is TEMPLES (see HomeUiState).
     */
    fun onInterestToggled(interest: Interest) = _uiState.update { state ->
        state.copy(interests = setOf(interest))
    }

    fun onFoodPreferenceSelected(preference: FoodPreference) = _uiState.update { it.copy(foodPreference = preference) }

    fun onUseCurrentLocationAgain() = beginCurrentLocationFlow()

    // ------------------------------------------------------------------
    // Destination change flow
    // ------------------------------------------------------------------

    fun onChangeDestinationClicked() = _uiState.update {
        it.copy(
            isDestinationSearchActive = true,
            destinationSearchQuery = "",
            destinationSearchResults = emptyList(),
            locationError = null
        )
    }

    fun onDestinationSearchDismissed() = _uiState.update {
        it.copy(
            isDestinationSearchActive = false,
            destinationSearchQuery = "",
            destinationSearchResults = emptyList()
        )
    }

    fun onDestinationSearchQueryChanged(query: String) {
        _uiState.update { it.copy(destinationSearchQuery = query) }
        searchJob?.cancel()
        if (query.isBlank()) {
            _uiState.update { it.copy(destinationSearchResults = emptyList(), isSearchingDestination = false) }
        } else {
            searchJob = viewModelScope.launch {
                kotlinx.coroutines.delay(300) // debounce
                _uiState.update { it.copy(isSearchingDestination = true) }
                runCatching { locationSearcher.search(query) }
                    .onSuccess { results ->
                        _uiState.update {
                            it.copy(
                                destinationSearchResults = results.map { hit ->
                                    // Reuse the existing Place list UI: hits
                                    // carry real geocoder coordinates.
                                    Place(
                                        id = hit.id,
                                        name = hit.displayName,
                                        shortDescription = hit.address ?: "",
                                        fullDescription = hit.address ?: "",
                                        address = hit.address ?: hit.displayName,
                                        latitude = hit.latitude,
                                        longitude = hit.longitude,
                                        interests = emptySet(),
                                        suggestedVisitMinutes = 0,
                                        openingHours = ""
                                    )
                                },
                                isSearchingDestination = false
                            )
                        }
                    }
                    .onFailure { e ->
                        _uiState.update {
                            it.copy(isSearchingDestination = false, error = e.message)
                        }
                    }
            }
        }
    }

    fun onDestinationSelected(place: Place) = _uiState.update {
        it.copy(
            destination = place.name,
            isDestinationSearchActive = false,
            destinationSearchQuery = "",
            destinationSearchResults = emptyList(),
            error = null
        )
    }

    // ------------------------------------------------------------------
    // Current-location acquisition (outside the Compose UI, per MVVM)
    // ------------------------------------------------------------------

    private fun beginCurrentLocationFlow() {
        if (locationProvider.isPermissionGranted()) {
            locateDevice()
        } else {
            // Compose observes this flag and launches the system dialog.
            _uiState.update { it.copy(needsPermissionRequest = true) }
        }
    }

    /** Called by Compose with the outcome of the system permission dialog. */
    fun onLocationPermissionResult(granted: Boolean) {
        _uiState.update { it.copy(needsPermissionRequest = false) }
        if (granted) {
            _uiState.update { it.copy(locationPermissionDenied = false) }
            locateDevice()
        } else {
            // No permission: no fix will ever arrive, so stop retrying.
            locationRetryJob?.cancel()
            _uiState.update {
                it.copy(
                    locationPermissionDenied = true,
                    locationError = "Location permission is needed to plan from your current location. You can still choose a destination manually."
                )
            }
        }
    }

    private fun locateDevice() {
        if (_uiState.value.isLocating) return
        _uiState.update { it.copy(isLocating = true, isResolvingCurrentCity = true, locationError = null) }
        viewModelScope.launch {
            when (val result = locationProvider.getCurrentLocation()) {
                is DeviceLocationResult.Success -> {
                    // Fix arrived: stop any pending background retry.
                    locationRetryJob?.cancel()
                    _uiState.update {
                        it.copy(
                            isLocating = false,
                            currentLocationFix = StartLocation(
                                name = "Current Location",
                                isCurrentLocation = true,
                                latitude = result.latitude,
                                longitude = result.longitude
                            ),
                            locationError = null
                        )
                    }
                    resolveCurrentCity(result.latitude, result.longitude)
                }
                is DeviceLocationResult.GpsDisabled -> {
                    _uiState.update {
                        it.copy(
                            isLocating = false,
                            isResolvingCurrentCity = false,
                            locationError = result.message
                        )
                    }
                    scheduleLocationRetry()
                }
                is DeviceLocationResult.Unavailable -> {
                    _uiState.update {
                        it.copy(
                            isLocating = false,
                            isResolvingCurrentCity = false,
                            locationError = result.message
                        )
                    }
                    scheduleLocationRetry()
                }
            }
        }
    }

    /**
     * Keep trying in the background when no fix could be obtained: GPS
     * chips (and emulators) often produce a fix shortly after the first
     * attempt fails. When one lands, the destination auto-fills with the
     * current city. Skipped while permission is denied (retrying cannot
     * help) and stopped as soon as a fix exists.
     */
    private fun scheduleLocationRetry() {
        if (locationRetryJob?.isActive == true) return
        locationRetryJob = viewModelScope.launch {
            kotlinx.coroutines.delay(LOCATION_RETRY_INTERVAL_MS)
            val state = _uiState.value
            if (state.currentLocationFix == null && !state.locationPermissionDenied) {
                locateDevice()
            }
        }
    }

    /** Reverse-geocode the fix into the default destination city. */
    private suspend fun resolveCurrentCity(latitude: Double, longitude: Double) {
        try {
            val place = reverseGeocoder(latitude, longitude)
            // Prefer the provider's city-level component (Pune, not the
            // Maan village inside it); fall back through progressively
            // coarser labels. Only set when the user has not already
            // chosen a destination themselves.
            val city = place.city
                ?: place.address?.split(",")?.firstOrNull()?.trim()
                ?: place.name
                ?: place.displayName?.split(",")?.firstOrNull()?.trim()
            if (city != null) {
                _uiState.update {
                    if (it.destination.isBlank()) it.copy(destination = city) else it
                }
            }
        } catch (e: Exception) {
            // Non-fatal: the user can type a destination; never block planning.
            _uiState.update {
                it.copy(locationError = it.locationError ?: "We couldn't detect your city. Please choose a destination manually.")
            }
        } finally {
            _uiState.update { it.copy(isResolvingCurrentCity = false) }
        }
    }

    fun dismissLocationError() = _uiState.update { it.copy(locationError = null) }

    fun generateOuting() {
        val state = _uiState.value
        if (state.isGenerating) return

        if (state.destination.isBlank()) {
            _uiState.update {
                it.copy(
                    error = if (state.locationPermissionDenied || state.currentLocationFix == null) {
                        "Location not available yet and no destination selected. " +
                            "Please pick a destination using the Change button."
                    } else {
                        "Please select a destination to continue."
                    }
                )
            }
            return
        }

        // The outing always starts from the device's current location; no
        // hardcoded fallback coordinates exist. If the fix isn't there yet,
        // acquire it now — the button shows the progress — and continue
        // planning automatically once it lands.
        viewModelScope.launch {
            val fix = state.currentLocationFix ?: waitForCurrentLocation() ?: run {
                _uiState.update {
                    it.copy(
                        isGenerating = false,
                        error = if (state.locationPermissionDenied) {
                            "Location access is needed to plan from where you are. Enable it in Settings and try again."
                        } else {
                            "We couldn't determine your location. Please check that location services are on and try again."
                        }
                    )
                }
                return@launch
            }

            _uiState.update { it.copy(isGenerating = true, error = null) }
            runCatching {
                repository.generateOuting(
                    OutingRequest(
                        destination = state.destination,
                        duration = state.duration,
                        timeOfDay = state.timeOfDay,
                        interests = state.interests,
                        foodPreference = state.foodPreference,
                        startLocation = fix
                    )
                )
            }.onSuccess { itinerary ->
                OutingSession.set(itinerary)
                _uiState.update { it.copy(isGenerating = false) }
                _events.emit(Event.OutingReady)
            }.onFailure { e ->
                _uiState.update { it.copy(isGenerating = false, error = e.message ?: "Something went wrong") }
            }
        }
    }

    /**
     * Acquire a fresh device fix while the user waits (Generate tapped).
     * Returns null when acquisition fails; failures also surface through
     * [locationError] via [locateDevice]'s regular path.
     */
    private suspend fun waitForCurrentLocation(): StartLocation? {
        if (locationProvider.isPermissionGranted()) {
            locateDevice()
            // locateDevice runs in viewModelScope; wait for it to finish.
            while (_uiState.value.isLocating) {
                kotlinx.coroutines.delay(100)
            }
            return _uiState.value.currentLocationFix
        }
        // No permission: ask Compose to show the system dialog and stop.
        _uiState.update { it.copy(needsPermissionRequest = true) }
        return null
    }

    /** One-shot UI events emitted by the ViewModel. */
    sealed class Event {
        data object OutingReady : Event()
    }

    private val _events = MutableSharedFlow<Event>()
    val events: SharedFlow<Event> = _events.asSharedFlow()

    fun dismissError() = _uiState.update { it.copy(error = null) }

    private var searchJob: kotlinx.coroutines.Job? = null

    private var locationRetryJob: kotlinx.coroutines.Job? = null

    private companion object {
        const val LOCATION_RETRY_INTERVAL_MS = 15_000L
    }
}
