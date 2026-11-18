package com.dev.placeexplorer

import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.data.remote.ApiGeoReverseResponse
import com.dev.placeexplorer.domain.repository.OutingRepository
import com.dev.placeexplorer.location.DeviceLocationProvider
import com.dev.placeexplorer.location.DeviceLocationResult
import com.dev.placeexplorer.presentation.home.HomeViewModel
import com.dev.placeexplorer.search.GeocodePlace
import com.dev.placeexplorer.search.LocationSearcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * HomeViewModel tests for the plan-from-current-location flow, using a fake
 * DeviceLocationProvider, a fake LocationSearcher and a fake reverse
 * geocoder. No GPS, no Play Services, no network involved.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelLocationTest {

    private val testDispatcher = StandardTestDispatcher()

    private class FakeLocationProvider(
        var permissionGranted: Boolean = false,
        var result: DeviceLocationResult =
            DeviceLocationResult.Success(18.5301, 73.8446)
    ) : DeviceLocationProvider {

        var locateCalls = 0

        override fun isPermissionGranted(): Boolean = permissionGranted

        override fun isLocationEnabled(): Boolean =
            result !is DeviceLocationResult.GpsDisabled

        override suspend fun getCurrentLocation(): DeviceLocationResult {
            locateCalls++
            return result
        }
    }

    private class FakeLocationSearcher(
        var results: List<GeocodePlace> = emptyList(),
        var error: Exception? = null
    ) : LocationSearcher {

        var queries = mutableListOf<String>()

        override suspend fun search(query: String): List<GeocodePlace> {
            queries += query
            error?.let { throw it }
            return results
        }
    }

    private lateinit var provider: FakeLocationProvider
    private lateinit var searcher: FakeLocationSearcher
    private var reverseResult: ApiGeoReverseResponse? =
        ApiGeoReverseResponse(
            latitude = 18.5301,
            longitude = 73.8446,
            name = "Shivajinagar",
            displayName = "Shivajinagar, Pune, Maharashtra, India",
            address = "Pune, Pune, Maharashtra, India"
        )
    private var reverseError: Exception? = null

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        provider = FakeLocationProvider()
        searcher = FakeLocationSearcher(
            listOf(
                GeocodePlace(
                    id = "nominatim_1",
                    displayName = "Kothrud",
                    latitude = 18.5074,
                    longitude = 73.8077,
                    address = "Kothrud, Pune, Maharashtra, India"
                )
            )
        )
        reverseResult = ApiGeoReverseResponse(
            latitude = 18.5301,
            longitude = 73.8446,
            name = "Shivajinagar",
            displayName = "Shivajinagar, Pune, Maharashtra, India",
            address = "Pune, Pune, Maharashtra, India"
        )
        reverseError = null
        AppContainer.setRepositoryOverride(object : OutingRepository {
            override suspend fun generateOuting(request: com.dev.placeexplorer.domain.model.OutingRequest) =
                error("not used here")
            override suspend fun getPlaceDetails(
                placeId: String,
                foodPreference: com.dev.placeexplorer.domain.model.FoodPreference
            ) = null
            override suspend fun searchPlaces(query: String) =
                emptyList<com.dev.placeexplorer.domain.model.Place>()
        })
        AppContainer.setLocationProviderOverride(provider)
        AppContainer.setLocationSearcherOverride(searcher)
    }

    @After
    fun tearDown() {
        AppContainer.setRepositoryOverride(null)
        AppContainer.setLocationProviderOverride(null)
        AppContainer.setLocationSearcherOverride(null)
        Dispatchers.resetMain()
    }

    private fun viewModel() = HomeViewModel(
        reverseGeocoder = { _, _ ->
            reverseError?.let { throw it }
            reverseResult!!
        }
    )

    @Test
    fun `defaults are temples interest and veg food`() {
        val state = com.dev.placeexplorer.presentation.home.HomeUiState()
        assertTrue(
            state.interests == setOf(com.dev.placeexplorer.domain.model.Interest.TEMPLES)
        )
        assertTrue(
            state.foodPreference == com.dev.placeexplorer.domain.model.FoodPreference.VEGETARIAN
        )
    }

    @Test
    fun `init locates device and defaults destination to current city`() = runTest {
        provider.permissionGranted = true
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertNotNull(state.currentLocationFix)
        assertEquals(18.5301, state.currentLocationFix!!.latitude, 0.0001)
        // Destination auto-filled from the reverse geocode (city field
        // or address fallback).
        assertEquals("Pune", state.destination)
        assertFalse(state.isResolvingCurrentCity)
        assertNull(state.locationError)
    }

    @Test
    fun `init does not overwrite a user-chosen destination`() = runTest {
        provider.permissionGranted = true
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        // User picks a different destination after the fix landed.
        vm.onDestinationSelected(
            com.dev.placeexplorer.domain.model.Place(
                id = "d1", name = "Mumbai",
                shortDescription = "", fullDescription = "",
                address = "Mumbai, Maharashtra, India",
                latitude = 19.0760, longitude = 72.8777,
                interests = emptySet(), suggestedVisitMinutes = 0, openingHours = ""
            )
        )
        // A late reverse-geocode response arrives afterwards.
        vm.onUseCurrentLocationAgain()
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals("Mumbai", vm.uiState.value.destination)
    }

    @Test
    fun `permission denied surfaces message and no fix`() = runTest {
        val vm = viewModel() // no permission
        testDispatcher.scheduler.advanceUntilIdle()

        vm.onLocationPermissionResult(granted = false)
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state.locationPermissionDenied)
        assertNull(state.currentLocationFix)
        assertNotNull(state.locationError)
        assertTrue(state.locationError!!.contains("permission"))
        assertFalse(state.isLocating)
    }

    @Test
    fun `permission granted later locates and resolves city`() = runTest {
        val vm = viewModel() // no permission initially
        testDispatcher.scheduler.advanceUntilIdle()
        vm.onLocationPermissionResult(granted = true)
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertNotNull(state.currentLocationFix)
        assertEquals("Pune", state.destination)
    }

    @Test
    fun `gps disabled surfaces error and retries in background`() = runTest {
        provider.permissionGranted = true
        provider.result = DeviceLocationResult.GpsDisabled("Location services are turned off.")
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.isLocating)
        assertNull(state.currentLocationFix)
        assertTrue(state.locationError!!.contains("turned off"))
        assertFalse(state.isResolvingCurrentCity)

        // A background retry is scheduled; when the provider starts
        // returning fixes, the fix and city arrive without user action.
        provider.result = DeviceLocationResult.Success(18.5301, 73.8446)
        testDispatcher.scheduler.advanceTimeBy(20_000)
        testDispatcher.scheduler.advanceUntilIdle()

        assertNotNull(vm.uiState.value.currentLocationFix)
        assertEquals("Pune", vm.uiState.value.destination)
        assertNull(vm.uiState.value.locationError)
    }

    @Test
    fun `gps disabled retry is cancelled when permission is denied`() = runTest {
        provider.permissionGranted = true
        provider.result = DeviceLocationResult.GpsDisabled("Location services are turned off.")
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        // Permission revoked mid-retry: retrying can never help.
        provider.permissionGranted = false
        vm.onLocationPermissionResult(granted = false)
        testDispatcher.scheduler.advanceUntilIdle()

        provider.result = DeviceLocationResult.Success(18.5301, 73.8446)
        testDispatcher.scheduler.advanceTimeBy(60_000)
        testDispatcher.scheduler.advanceUntilIdle()

        assertNull(vm.uiState.value.currentLocationFix) // no retry fired
    }

    @Test
    fun `location unavailable surfaces error and no fix`() = runTest {
        provider.permissionGranted = true
        provider.result = DeviceLocationResult.Unavailable("no fix")
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.isLocating)
        assertNull(state.currentLocationFix)
        assertTrue(state.locationError!!.contains("no fix"))
    }

    @Test
    fun `reverse geocode failure keeps destination blank without blocking`() = runTest {
        provider.permissionGranted = true
        reverseError = java.io.IOException("geocoder down")
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        // Fix is still valid; only the city label failed.
        assertNotNull(state.currentLocationFix)
        assertEquals("", state.destination)
        assertFalse(state.isResolvingCurrentCity)
        assertNotNull(state.locationError)
        assertTrue(state.locationError!!.contains("pick one manually"))
    }

    @Test
    fun `destination search success shows results`() = runTest {
        val vm = viewModel()
        vm.onChangeDestinationClicked()
        vm.onDestinationSearchQueryChanged("Kothrud")
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.isSearchingDestination)
        assertEquals(1, state.destinationSearchResults.size)
        assertEquals("Kothrud", state.destinationSearchResults.first().name)
    }

    @Test
    fun `destination search empty results and errors surface`() = runTest {
        val vm = viewModel()
        searcher.results = emptyList()
        vm.onChangeDestinationClicked()
        vm.onDestinationSearchQueryChanged("zzz nowhere")
        testDispatcher.scheduler.advanceUntilIdle()
        assertTrue(vm.uiState.value.destinationSearchResults.isEmpty())

        searcher.error = java.io.IOException("search down")
        vm.onDestinationSearchQueryChanged("Pune")
        testDispatcher.scheduler.advanceUntilIdle()
        assertNotNull(vm.uiState.value.error)
    }

    @Test
    fun `destination selection updates destination and closes search`() = runTest {
        val vm = viewModel()
        vm.onChangeDestinationClicked()
        vm.onDestinationSearchQueryChanged("Kothrud")
        testDispatcher.scheduler.advanceUntilIdle()

        vm.onDestinationSelected(vm.uiState.value.destinationSearchResults.first())
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("Kothrud", state.destination)
        assertFalse(state.isDestinationSearchActive)
        assertTrue(state.destinationSearchResults.isEmpty())
    }

    @Test
    fun `generateOuting uses device fix as start and chosen destination`() = runTest {
        val repo = RecordingRepository()
        AppContainer.setRepositoryOverride(repo)
        provider.permissionGranted = true
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        vm.onDestinationSelected(
            com.dev.placeexplorer.domain.model.Place(
                id = "d1", name = "Mumbai",
                shortDescription = "", fullDescription = "",
                address = "Mumbai, Maharashtra, India",
                latitude = 19.0760, longitude = 72.8777,
                interests = emptySet(), suggestedVisitMinutes = 0, openingHours = ""
            )
        )
        vm.generateOuting()
        testDispatcher.scheduler.advanceUntilIdle()

        val sent = repo.lastRequest
        assertNotNull(sent)
        assertEquals("Mumbai", sent!!.destination)
        assertTrue(sent.startLocation.isCurrentLocation)
        assertEquals(18.5301, sent.startLocation.latitude, 0.0001)
        assertEquals(73.8446, sent.startLocation.longitude, 0.0001)
        AppContainer.setRepositoryOverride(null)
    }

    @Test
    fun `generateOuting without device fix refuses instead of hardcoding coordinates`() = runTest {
        val repo = RecordingRepository()
        AppContainer.setRepositoryOverride(repo)
        val vm = viewModel() // permission never granted -> no fix
        vm.onLocationPermissionResult(granted = false)
        testDispatcher.scheduler.advanceUntilIdle()
        vm.onDestinationSelected(
            com.dev.placeexplorer.domain.model.Place(
                id = "d1", name = "Mumbai",
                shortDescription = "", fullDescription = "",
                address = "Mumbai, Maharashtra, India",
                latitude = 19.0760, longitude = 72.8777,
                interests = emptySet(), suggestedVisitMinutes = 0, openingHours = ""
            )
        )

        vm.generateOuting()
        testDispatcher.scheduler.advanceUntilIdle()

        assertNull(repo.lastRequest) // never called
        assertTrue(vm.uiState.value.error!!.contains("location access"))
        AppContainer.setRepositoryOverride(null)
    }

    @Test
    fun `generateOuting with blank destination refuses`() = runTest {
        val repo = RecordingRepository()
        AppContainer.setRepositoryOverride(repo)
        provider.permissionGranted = true
        reverseError = java.io.IOException("reverse down") // city never resolved
        val vm = viewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        vm.generateOuting()
        testDispatcher.scheduler.advanceUntilIdle()

        assertNull(repo.lastRequest)
        val message = vm.uiState.value.error!!
        assertTrue(message.contains("destination"))
        assertTrue(message.contains("Change"))
        AppContainer.setRepositoryOverride(null)
    }

    private class RecordingRepository : OutingRepository {
        var lastRequest: com.dev.placeexplorer.domain.model.OutingRequest? = null
        override suspend fun generateOuting(request: com.dev.placeexplorer.domain.model.OutingRequest): com.dev.placeexplorer.domain.model.Itinerary {
            lastRequest = request
            error("stop") // only the captured request matters
        }
        override suspend fun getPlaceDetails(
                placeId: String,
                foodPreference: com.dev.placeexplorer.domain.model.FoodPreference
            ) = null
        override suspend fun searchPlaces(query: String) =
            emptyList<com.dev.placeexplorer.domain.model.Place>()
    }
}
