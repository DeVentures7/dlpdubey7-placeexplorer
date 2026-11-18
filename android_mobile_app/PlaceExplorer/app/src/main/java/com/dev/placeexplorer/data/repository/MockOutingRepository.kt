package com.dev.placeexplorer.data.repository

import com.dev.placeexplorer.data.mock.PunePlaces
import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.ItineraryStop
import com.dev.placeexplorer.domain.model.MealType
import com.dev.placeexplorer.domain.model.NearbyFoodRecommendation
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.domain.model.PlaceDetails
import com.dev.placeexplorer.domain.model.TimeOfDay
import com.dev.placeexplorer.domain.model.TravelLeg
import com.dev.placeexplorer.domain.repository.OutingRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Mock implementation of [OutingRepository] backed by sample Pune data.
 *
 * The scheduling logic mimics what the AI backend will do: it filters
 * places by interest, orders them into a geographically sensible route
 * (nearest-neighbour from the start point), assigns arrival times based on
 * visit durations and simulated travel times, and attaches food
 * recommendations at meal-appropriate stops.
 *
 * Designed to be replaced 1:1 by a Retrofit implementation of the same
 * interface once the FastAPI + Gemini backend is ready.
 */
class MockOutingRepository : OutingRepository {

    override suspend fun generateOuting(request: OutingRequest): Itinerary = withContext(Dispatchers.Default) {
        delay(MOCK_LATENCY_MS) // simulate network latency of the real backend

        val startLat = if (request.startLocation.isCurrentLocation) CITY_CENTER.lat else request.startLocation.latitude
        val startLng = if (request.startLocation.isCurrentLocation) CITY_CENTER.lng else request.startLocation.longitude

        // 1. Filter candidate places by interest.
        val candidates = PunePlaces.all
            .filter { place -> place.interests.any { it in request.interests } }
            .filterNot { it.isOptionalAttraction }
            .toMutableList()

        // Always keep the outing interesting even for a single narrow interest.
        if (candidates.size < MIN_STOPS) {
            PunePlaces.all.filterNot { it.isOptionalAttraction }
                .shuffled()
                .take(MIN_STOPS - candidates.size)
                .forEach { if (it !in candidates) candidates.add(it) }
        }

        // 2. Nearest-neighbour route from the start point.
        val ordered = mutableListOf<Place>()
        var currentLat = startLat
        var currentLng = startLng
        while (candidates.isNotEmpty()) {
            val next = candidates.minByOrNull { distanceKm(currentLat, currentLng, it.latitude, it.longitude) }!!
            candidates.remove(next)
            ordered.add(next)
            currentLat = next.latitude
            currentLng = next.longitude
        }

        // 3. Cap the number of stops by available time.
        val totalMinutes = request.duration.totalHours * 60
        val maxStops = if (request.duration == com.dev.placeexplorer.domain.model.OutingDuration.FULL_DAY) 5 else 4
        val stops = ordered.take(maxStops)

        // 4. Assign arrival times and travel legs.
        var clockMinutes = request.timeOfDay.startHour * 60
        val itineraryStops = mutableListOf<ItineraryStop>()
        var prevLat = startLat
        var prevLng = startLng
        for (place in stops) {
            val travel = travelLeg(prevLat, prevLng, place.latitude, place.longitude)
            clockMinutes += travel.durationMinutes
            val visit = place.suggestedVisitMinutes
            itineraryStops += ItineraryStop(
                place = place,
                arrivalTimeMinutes = clockMinutes,
                visitDurationMinutes = visit,
                travelToNext = null // filled below
            )
            clockMinutes += visit
            prevLat = place.latitude
            prevLng = place.longitude
        }
        // Fill travel legs to the next stop.
        for (i in 0 until itineraryStops.size - 1) {
            val next = itineraryStops[i + 1]
            val leg = travelLeg(
                itineraryStops[i].place.latitude, itineraryStops[i].place.longitude,
                next.place.latitude, next.place.longitude
            )
            itineraryStops[i] = itineraryStops[i].copy(travelToNext = leg)
        }

        // 5. Food recommendations: attach to the stop whose visit window contains meal time.
        val mealRecs = foodRecommendationsFor(request, itineraryStops)

        // 6. Optional attractions: interesting places not in the route, near the route.
        val routePlaceIds = stops.map { it.id }.toSet()
        val optional = PunePlaces.all.filter { it.id !in routePlaceIds }
            .filter { place -> place.interests.any { it in request.interests } || request.interests.isEmpty() }
            .filter { distanceKm(it.latitude, it.longitude, startLat, startLng) < OPTIONAL_RADIUS_KM }
            .take(3)

        Itinerary(
            id = "mock-${System.currentTimeMillis()}",
            title = buildTitle(request, stops),
            destination = request.destination,
            request = request,
            stops = itineraryStops,
            totalDurationMinutes = totalMinutes,
            optionalAttractions = optional,
            foodRecommendations = mealRecs
        )
    }

    override suspend fun getPlaceDetails(
        placeId: String,
        foodPreference: FoodPreference
    ): PlaceDetails? = withContext(Dispatchers.Default) {
        delay(150)
        val place = PunePlaces.byId[placeId] ?: return@withContext null
        val restaurants = (PunePlaces.breakfastSpots + PunePlaces.lunchSpots + PunePlaces.snackSpots)
            .shuffled()
            .take(4)
        PlaceDetails(place = place, nearbyRestaurants = restaurants)
    }

    override suspend fun searchPlaces(query: String): List<Place> = withContext(Dispatchers.Default) {
        if (query.isBlank()) {
            // A few well-known start points.
            listOf(
                PunePlaces.shaniwarWada,
                PunePlaces.agaKhanPalace,
                PunePlaces.korumMall
            )
        } else {
            PunePlaces.all.filter {
                it.name.contains(query, ignoreCase = true) ||
                    it.address.contains(query, ignoreCase = true)
            }
        }
    }

    // ------------------------------------------------------------------

    private fun buildTitle(request: OutingRequest, stops: List<Place>): String {
        val interestLabel = when {
            request.interests.isEmpty() -> "City"
            request.interests.size == 1 -> request.interests.first().label
            else -> "Exploring"
        }
        return "$interestLabel ${request.timeOfDay.label.lowercase().replaceFirstChar { it.uppercase() }} in ${request.destination.substringBefore(",")}"
            .let { if (stops.isEmpty()) "$it" else it }
    }

    private fun travelLeg(fromLat: Double, fromLng: Double, toLat: Double, toLng: Double): TravelLeg {
        val km = distanceKm(fromLat, fromLng, toLat, toLng)
        // Pune city traffic: average effective speed ~22 km/h, min 10 min.
        val minutes = (km / 22.0 * 60).roundToInt().coerceAtLeast(10)
        return TravelLeg(distanceKm = (km * 10).roundToInt() / 10.0, durationMinutes = minutes)
    }

    private fun foodRecommendationsFor(
        request: OutingRequest,
        stops: List<ItineraryStop>
    ): Map<String, List<NearbyFoodRecommendation>> {
        val pools = mutableListOf<Pair<MealType, List<NearbyFoodRecommendation>>>()
        if (request.timeOfDay == TimeOfDay.MORNING) {
            pools += MealType.BREAKFAST to PunePlaces.breakfastSpots
            pools += MealType.SNACK to PunePlaces.snackSpots
            pools += MealType.LUNCH to PunePlaces.lunchSpots
        } else {
            pools += MealType.SNACK to PunePlaces.snackSpots
            pools += MealType.DINNER to PunePlaces.snackSpots
            pools += MealType.LUNCH to PunePlaces.lunchSpots
        }

        val result = mutableMapOf<String, List<NearbyFoodRecommendation>>()
        var poolIndex = 0
        for (stop in stops) {
            val windowEnd = stop.arrivalTimeMinutes + stop.visitDurationMinutes
            val matchingPool = pools.firstOrNull { (_, pool) ->
                pool.any { rec ->
                    rec.mealType.fits(request.timeOfDay, windowEnd)
                }
            }
            if (matchingPool != null) {
                val (mealType, pool) = matchingPool
                val filtered = pool.filter { fitsFoodPreference(it, request.foodPreference) }
                if (filtered.isNotEmpty()) {
                    result[stop.place.id] = filtered.take(2)
                    poolIndex++
                }
            }
        }
        return result
    }

    private fun fitsFoodPreference(
        rec: NearbyFoodRecommendation,
        preference: FoodPreference
    ): Boolean = when (preference) {
        FoodPreference.VEGETARIAN -> rec.isVegetarianFriendly
        else -> true
    }

    private fun MealType.fits(timeOfDay: TimeOfDay, visitWindowEndMinutes: Int): Boolean = when (this) {
        MealType.BREAKFAST -> timeOfDay == TimeOfDay.MORNING && visitWindowEndMinutes in 8 * 60..10 * 60 + 30
        MealType.LUNCH -> visitWindowEndMinutes in 11 * 60 + 30..14 * 60 + 30
        MealType.SNACK -> visitWindowEndMinutes in 15 * 60..17 * 60
        MealType.DINNER -> visitWindowEndMinutes >= 18 * 60
    }

    private fun distanceKm(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val r = 6371.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLng = Math.toRadians(lng2 - lng1)
        val a = sin(dLat / 2) * sin(dLat / 2) +
            cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) *
            sin(dLng / 2) * sin(dLng / 2)
        return r * 2 * atan2(sqrt(a), sqrt(1 - a))
    }

    companion object {
        private const val MOCK_LATENCY_MS = 900L
        private const val MIN_STOPS = 3
        private const val OPTIONAL_RADIUS_KM = 6.0
        private val CITY_CENTER = LatLng(18.5204, 73.8567)
    }

    private data class LatLng(val lat: Double, val lng: Double)
}
