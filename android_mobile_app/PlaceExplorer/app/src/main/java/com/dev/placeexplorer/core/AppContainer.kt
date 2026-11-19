package com.dev.placeexplorer.core

import android.content.Context
import com.dev.placeexplorer.data.remote.ApiLocationSearcher
import com.dev.placeexplorer.data.remote.ApiOutingRepository
import com.dev.placeexplorer.data.remote.ApiClient
import com.dev.placeexplorer.data.remote.PlanApiService
import com.dev.placeexplorer.data.repository.MockLocationSearcher
import com.dev.placeexplorer.data.repository.MockOutingRepository
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.repository.OutingRepository
import com.dev.placeexplorer.location.DeviceLocationProvider
import com.dev.placeexplorer.location.FusedDeviceLocationProvider
import com.dev.placeexplorer.search.LocationSearcher
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Which OutingRepository implementation the app runs with.
 *
 * Selected explicitly via [DevelopmentConfig.useApiRepository] — the app
 * never silently falls back to mock data when an API request fails.
 */
enum class RepositoryMode(val label: String) {
    MOCK("Mock data"),
    API("Live backend")
}

/**
 * Explicit development configuration. Flip [useApiRepository] to true once
 * the backend is reachable from the device/emulator. Intentionally NOT
 * inferred from build type: a debug build talking to a live backend and a
 * release build on mock data are both valid states during development.
 */
object DevelopmentConfig {
    const val API_BASE_URL: String = com.dev.placeexplorer.BuildConfig.API_BASE_URL
    var useApiRepository: Boolean = false
}

/**
 * Minimal service locator. When Hilt is introduced this becomes an
 * @Module with @Provides methods and screens receive ViewModels via
 * constructor injection instead.
 */
object AppContainer {

    @Volatile
    private var repositoryOverride: OutingRepository? = null

    @Volatile
    private var locationProviderOverride: DeviceLocationProvider? = null

    @Volatile
    private var locationSearcherOverride: LocationSearcher? = null

    private var appContext: Context? = null

    /** Called once from MainActivity.onCreate so providers can use app context. */
    fun init(context: Context) {
        appContext = context.applicationContext
    }

    val repositoryMode: RepositoryMode
        get() = if (DevelopmentConfig.useApiRepository) RepositoryMode.API else RepositoryMode.MOCK

    val outingRepository: OutingRepository
        get() = repositoryOverride ?: createRepository()

    val locationProvider: DeviceLocationProvider
        get() = locationProviderOverride
            ?: appContext?.let { FusedDeviceLocationProvider(it) }
            ?: error("AppContainer.init(context) must be called before use")

    /**
     * Null-safe variant of [locationProvider] for screens that treat the
     * device fix as optional (distance labels degrade to "unavailable").
     * Returns null when init has not run or no provider can be created.
     */
    fun locationProviderOrNull(): DeviceLocationProvider? =
        locationProviderOverride
            ?: appContext?.let { FusedDeviceLocationProvider(it) }

    /**
     * Shared Retrofit service for the backend (plan, geocode, reverse).
     */
    val planApi: PlanApiService
        get() = ApiClient.planApiService(DevelopmentConfig.API_BASE_URL)

    /**
     * Manual destination search, backed by the backend's
     * GET /api/geocode endpoint through the shared Retrofit stack.
     */
    val locationSearcher: LocationSearcher
        get() = locationSearcherOverride ?: if (DevelopmentConfig.useApiRepository) {
            ApiLocationSearcher(planApi)
        } else {
            MockLocationSearcher()
        }

    private fun createRepository(): OutingRepository =
        if (DevelopmentConfig.useApiRepository) {
            ApiOutingRepository(ApiClient.planApiService(DevelopmentConfig.API_BASE_URL))
        } else {
            MockOutingRepository()
        }

    /** For unit tests: inject fakes without touching the config flags. */
    fun setRepositoryOverride(repository: OutingRepository?) {
        repositoryOverride = repository
    }

    /** For unit tests: inject a fake location provider. */
    fun setLocationProviderOverride(provider: DeviceLocationProvider?) {
        locationProviderOverride = provider
    }

    /** For unit tests: inject a fake location searcher. */
    fun setLocationSearcherOverride(searcher: LocationSearcher?) {
        locationSearcherOverride = searcher
    }
}

/**
 * Holds the most recently generated itinerary in memory so the Home and
 * Itinerary screens share it. Replaced by navigation arguments or a
 * database cache when the real backend lands.
 */
object OutingSession {

    private val _itinerary = MutableStateFlow<Itinerary?>(null)
    val itinerary: StateFlow<Itinerary?> = _itinerary.asStateFlow()

    fun set(itinerary: Itinerary) {
        _itinerary.value = itinerary
    }

    fun clear() {
        _itinerary.value = null
    }
}
