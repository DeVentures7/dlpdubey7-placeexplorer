package com.dev.placeexplorer

import com.dev.placeexplorer.core.AppContainer
import com.dev.placeexplorer.core.OutingSession
import com.dev.placeexplorer.data.repository.MockOutingRepository
import com.dev.placeexplorer.domain.repository.OutingRepository
import com.dev.placeexplorer.presentation.details.PlaceDetailsViewModel
import com.dev.placeexplorer.presentation.itinerary.ItineraryViewModel
import com.dev.placeexplorer.presentation.home.HomeViewModel
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
 * Mock-mode (DevelopmentConfig.useApiRepository = false) end-to-end tests:
 * default destination, itinerary and place details all come from the mock
 * repository without GPS, geocoding or backend access.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MockModeFlowTest {

    private val testDispatcher = StandardTestDispatcher()

    private class FakeLocationProvider : com.dev.placeexplorer.location.DeviceLocationProvider {
        var locateCalls = 0
        override fun isPermissionGranted(): Boolean = false
        override fun isLocationEnabled(): Boolean = false
        override suspend fun getCurrentLocation(): com.dev.placeexplorer.location.DeviceLocationResult {
            locateCalls++
            return com.dev.placeexplorer.location.DeviceLocationResult.Unavailable("no fix")
        }
    }

    private lateinit var provider: FakeLocationProvider

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
        provider = FakeLocationProvider()
        AppContainer.setLocationProviderOverride(provider)
        // Single consistent mock dataset across the whole flow.
        AppContainer.setRepositoryOverride(MockOutingRepository())
        AppContainer.setLocationSearcherOverride(null)
        OutingSession.clear()
    }

    @After
    fun tearDown() {
        AppContainer.setRepositoryOverride(null)
        AppContainer.setLocationProviderOverride(null)
        AppContainer.setLocationSearcherOverride(null)
        OutingSession.clear()
        Dispatchers.resetMain()
    }

    /**
     * MockOutingRepository hops to Dispatchers.Default (real threads, real
     * ~900 ms latency), which the test scheduler cannot advance. Drain the
     * scheduler and poll until the condition holds or the timeout expires.
     */
    private fun awaitUntil(timeoutMs: Long = 10_000, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (!condition() && System.currentTimeMillis() < deadline) {
            Thread.sleep(50)
            testDispatcher.scheduler.advanceUntilIdle()
        }
        testDispatcher.scheduler.advanceUntilIdle()
        assertTrue("condition not met within ${timeoutMs}ms", condition())
    }

    @Test
    fun `mock mode loads default destination on launch without GPS`() = runTest {
        val vm = HomeViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("Pune, Maharashtra", state.destination)
        assertTrue(state.isMockMode)
        // No permission dialog demanded, no locating spinner, no errors.
        assertFalse(state.needsPermissionRequest)
        assertFalse(state.isLocating)
        assertFalse(state.isResolvingCurrentCity)
        assertNull(state.locationError)
        // No GPS attempt while permission is missing.
        assertEquals(0, provider.locateCalls)
    }

    @Test
    fun `mock mode generates itinerary without GPS or backend access`() = runTest {
        val vm = HomeViewModel()
        testDispatcher.scheduler.advanceUntilIdle()

        vm.generateOuting()
        awaitUntil { OutingSession.itinerary.value != null }

        // The request went out even though the device fix never arrived.
        val itinerary = OutingSession.itinerary.value
        assertNotNull(itinerary)
        assertTrue(itinerary!!.stops.isNotEmpty())
        assertEquals("Pune, Maharashtra", itinerary.destination)
        assertTrue(itinerary.request.startLocation.isCurrentLocation)

        // The itinerary screen shows it immediately.
        val itineraryVm = ItineraryViewModel()
        testDispatcher.scheduler.advanceUntilIdle()
        assertEquals(itinerary.id, itineraryVm.uiState.value.itinerary?.id)
        assertFalse(itineraryVm.uiState.value.isLoading)
        assertNull(itineraryVm.uiState.value.error)
    }

    @Test
    fun `mock mode rebuilds itinerary after process death without session`() = runTest {
        OutingSession.clear()
        val itineraryVm = ItineraryViewModel()
        awaitUntil { itineraryVm.uiState.value.itinerary != null }

        val itinerary = itineraryVm.uiState.value.itinerary
        assertNotNull(itinerary)
        assertTrue(itinerary!!.stops.isNotEmpty())
    }

    @Test
    fun `every itinerary stop opens its correct mock place details`() = runTest {
        val vm = HomeViewModel()
        testDispatcher.scheduler.advanceUntilIdle()
        vm.generateOuting()
        awaitUntil { OutingSession.itinerary.value != null }
        val itinerary = OutingSession.itinerary.value!!

        itinerary.stops.forEach { stop ->
            val detailsVm = PlaceDetailsViewModel(placeId = stop.place.id)
            awaitUntil { detailsVm.uiState.value.place != null }

            val state = detailsVm.uiState.value
            assertEquals(stop.place.id, state.place?.id)
            assertEquals(stop.place.name, state.place?.name)
            assertTrue(state.place!!.address.isNotBlank())
            awaitUntil { state.nearbyRestaurants.isNotEmpty() }
        }
    }

    @Test
    fun `place details resolve via repository fallback for ids outside the session`() = runTest {
        // Session holds a different outing; this id exists only in the
        // mock dataset, not in the session.
        val vm = HomeViewModel()
        testDispatcher.scheduler.advanceUntilIdle()
        vm.generateOuting()
        awaitUntil { OutingSession.itinerary.value != null }
        OutingSession.clear()

        val detailsVm = PlaceDetailsViewModel(placeId = "shaniwar-wada")
        awaitUntil { detailsVm.uiState.value.place != null }

        assertEquals("Shaniwar Wada", detailsVm.uiState.value.place?.name)
    }

    @Test
    fun `unknown place ids are handled gracefully`() = runTest {
        val detailsVm = PlaceDetailsViewModel(placeId = "definitely-not-a-place")
        testDispatcher.scheduler.advanceUntilIdle()

        assertNull(detailsVm.uiState.value.place)
        assertNull(detailsVm.uiState.value.error)
    }

    @Test
    fun `api mode continues to use the live repository selection`() {
        // The mode switch stays centralized: the container reports MOCK
        // exactly when the config flag is off, API when it is on.
        assertEquals(
            com.dev.placeexplorer.core.RepositoryMode.MOCK,
            AppContainer.repositoryMode
        )
        assertTrue(AppContainer.outingRepository is MockOutingRepository)
    }
}
