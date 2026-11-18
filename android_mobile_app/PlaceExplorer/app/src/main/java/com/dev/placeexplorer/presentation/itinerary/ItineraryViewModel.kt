package com.dev.placeexplorer.presentation.itinerary

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.core.OutingSession
import com.dev.placeexplorer.domain.model.Itinerary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ItineraryUiState(
    val itinerary: Itinerary? = null,
    /** The start location of the request: the user's position for
     *  "distance from your location" labels. */
    val userLocation: Pair<Double, Double>? = null,
    val isLoading: Boolean = false,
    val error: String? = null
)

class ItineraryViewModel(
    private val repository: com.dev.placeexplorer.domain.repository.OutingRepository = AppContainer.outingRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(ItineraryUiState())
    val uiState: StateFlow<ItineraryUiState> = _uiState.asStateFlow()

    init {
        val session = OutingSession.itinerary.value
        if (session != null) {
            _uiState.update {
                it.copy(
                    itinerary = session,
                    userLocation = session.request.startLocation
                        .takeIf { loc -> loc.isCurrentLocation }
                        ?.let { loc -> loc.latitude to loc.longitude }
                )
            }
        } else {
            regenerate()
        }
    }

    /** Re-plan from the original request (used after process death or "regenerate"). */
    fun regenerate() {
        val request = OutingSession.itinerary.value?.request ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            runCatching { repository.generateOuting(request) }
                .onSuccess { itinerary ->
                    OutingSession.set(itinerary)
                    _uiState.update {
                        it.copy(
                            itinerary = itinerary,
                            userLocation = itinerary.request.startLocation
                                .takeIf { loc -> loc.isCurrentLocation }
                                ?.let { loc -> loc.latitude to loc.longitude },
                            isLoading = false
                        )
                    }
                }
                .onFailure { e ->
                    _uiState.update { it.copy(isLoading = false, error = e.message ?: "Failed to load itinerary") }
                }
        }
    }

    fun dismissError() = _uiState.update { it.copy(error = null) }
}
