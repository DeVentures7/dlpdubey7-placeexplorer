package com.dev.placeexplorer.location

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Looper
import androidx.core.content.ContextCompat
import com.google.android.gms.common.ConnectionResult
import com.google.android.gms.common.GoogleApiAvailabilityLight
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Where the device is right now, or why it could not be determined.
 */
sealed class DeviceLocationResult {
    data class Success(val latitude: Double, val longitude: Double) : DeviceLocationResult()
    data class GpsDisabled(val message: String) : DeviceLocationResult()
    data class Unavailable(val message: String) : DeviceLocationResult()
}

/**
 * Abstraction over device location acquisition so ViewModels never touch
 * Play Services directly and unit tests can supply a fake.
 */
interface DeviceLocationProvider {

    /** True when ACCESS_COARSE_LOCATION or ACCESS_FINE_LOCATION is already granted. */
    fun isPermissionGranted(): Boolean

    /** True when any location provider (GPS/network) is enabled on the device. */
    fun isLocationEnabled(): Boolean

    /**
     * One-shot current location. Call only after [isPermissionGranted] is
     * true (or from a permission-granted callback).
     */
    suspend fun getCurrentLocation(): DeviceLocationResult
}

/**
 * FusedLocationProviderClient-backed implementation.
 *
 * Uses a short requestLocationUpdates stream rather than the one-shot
 * getCurrentLocation: on emulators and cold-started devices the one-shot
 * API often returns null even when a fix arrives a second later, while an
 * update stream picks up any fix the moment it lands (including one
 * injected via the emulator's Extended Controls mid-request). The first
 * update wins; the stream is cancelled immediately after.
 */
class FusedDeviceLocationProvider(
    private val context: Context
) : DeviceLocationProvider {

    override fun isPermissionGranted(): Boolean =
        ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_COARSE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_FINE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED

    override fun isLocationEnabled(): Boolean {
        val locationManager =
            context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
                ?: return false
        return locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
            locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
    }

    @SuppressLint("MissingPermission") // callers must check isPermissionGranted first
    override suspend fun getCurrentLocation(): DeviceLocationResult {
        if (!isPermissionGranted()) {
            return DeviceLocationResult.Unavailable("Location permission is not granted")
        }
        if (!isLocationEnabled()) {
            return DeviceLocationResult.GpsDisabled(
                "Location services are turned off. Enable GPS and try again."
            )
        }
        if (GoogleApiAvailabilityLight.getInstance()
                .isGooglePlayServicesAvailable(context) != ConnectionResult.SUCCESS
        ) {
            return DeviceLocationResult.Unavailable(
                "Google Play Services is not available on this device, " +
                    "so location cannot be determined."
            )
        }

        val fused = LocationServices.getFusedLocationProviderClient(context)
        return try {
            // 1. Race TWO fresh-fix sources against each other:
            //    - GMS fused (best on real devices)
            //    - the platform LocationManager GPS provider, which is
            //      where emulator console `geo fix` injections land.
            //      The fused provider can permanently prefer its cached
            //      network fix (an emulator's boot-time cell position)
            //      and never consult GPS, so the platform provider must
            //      be raced too or injected fixes are never seen.
            //    A cached lastLocation is checked only afterwards: it can
            //    be arbitrarily stale.
            val first = withTimeoutOrNull(FIX_TIMEOUT_MS) {
                raceLocationSources(fused)
            }
                // 2. No fresh fix in time: fall back to the cached fix.
                ?: try {
                    fused.lastLocation.await()
                } catch (_: Exception) {
                    null
                }

            if (first != null) {
                DeviceLocationResult.Success(first.latitude, first.longitude)
            } else {
                DeviceLocationResult.Unavailable(
                    "No GPS fix within ${FIX_TIMEOUT_MS / 1000} seconds. " +
                        "Check that location is enabled and try again."
                )
            }
        } catch (e: Exception) {
            DeviceLocationResult.Unavailable(
                "Could not get your location: ${e.message ?: "unknown error"}."
            )
        }
    }

    /**
     * First fix from either GMS fused or the platform GPS provider,
     * whichever arrives sooner.
     */
    @SuppressLint("MissingPermission")
    private suspend fun raceLocationSources(
        fused: com.google.android.gms.location.FusedLocationProviderClient
    ): android.location.Location? = coroutineScope {
        val fusedDeferred = async {
            callbackFlow {
                val callback = object : LocationCallback() {
                    override fun onLocationResult(result: LocationResult) {
                        result.lastLocation?.let { trySend(it) }
                    }
                }
                val request = LocationRequest.Builder(
                    Priority.PRIORITY_HIGH_ACCURACY, 1_000L
                )
                    .setMinUpdateIntervalMillis(1_000L)
                    .build()
                fused.requestLocationUpdates(request, callback, Looper.getMainLooper())
                awaitClose { fused.removeLocationUpdates(callback) }
            }.first()
        }

        val platformDeferred = async {
            callbackFlow {
                val listener = android.location.LocationListener { location ->
                    trySend(location)
                }
                val locationManager =
                    context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
                try {
                    locationManager.requestLocationUpdates(
                        LocationManager.GPS_PROVIDER,
                        1_000L,
                        0f,
                        listener,
                        Looper.getMainLooper()
                    )
                } catch (_: IllegalArgumentException) {
                    // GPS provider not present on this device.
                }
                awaitClose {
                    locationManager.removeUpdates(listener)
                }
            }.first()
        }

        try {
            select<android.location.Location?> {
                fusedDeferred.onAwait { it }
                platformDeferred.onAwait { it }
            }
        } finally {
            fusedDeferred.cancel()
            platformDeferred.cancel()
        }
    }

    private companion object {
        const val FIX_TIMEOUT_MS = 12_000L
    }
}
