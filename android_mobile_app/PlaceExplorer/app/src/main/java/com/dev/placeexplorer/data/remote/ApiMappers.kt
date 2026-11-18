package com.dev.placeexplorer.data.remote

import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.ItineraryStop
import com.dev.placeexplorer.domain.model.MealType
import com.dev.placeexplorer.domain.model.NearbyFoodRecommendation
import com.dev.placeexplorer.domain.model.OutingDuration
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.Place
import com.dev.placeexplorer.domain.model.PlaceDetails
import com.dev.placeexplorer.domain.model.StartLocation
import com.dev.placeexplorer.domain.model.TimeOfDay
import com.dev.placeexplorer.domain.model.TravelLeg

/**
 * Mapping between the API DTOs (backend JSON contract) and the domain models.
 *
 * Enum values are matched by their Kotlin enum entry names, which equal the
 * backend enum names (e.g. "HALF_DAY", "TEMPLES", "LUNCH"). Unknown values
 * fail fast instead of being silently mapped to a wrong category.
 */
object ApiMappers {

    // ------------------------------------------------------------------
    // Request: domain -> DTO
    // ------------------------------------------------------------------

    fun OutingRequest.toDto(): ApiOutingRequest = ApiOutingRequest(
        destination = destination,
        duration = duration.name,
        timeOfDay = timeOfDay.name,
        interests = interests.map { it.name },
        foodPreference = foodPreference.name,
        startLocation = startLocation.toDto()
    )

    fun StartLocation.toDto(): ApiStartLocation = ApiStartLocation(
        name = name,
        isCurrentLocation = isCurrentLocation,
        latitude = latitude,
        longitude = longitude
    )

    // ------------------------------------------------------------------
    // Response: DTO -> domain
    // ------------------------------------------------------------------

    fun ApiItinerary.toDomain(): Itinerary = Itinerary(
        id = id,
        title = title,
        destination = destination,
        request = request.toDomain(),
        stops = stops.map { it.toDomain() },
        totalDurationMinutes = totalDurationMinutes,
        optionalAttractions = optionalAttractions.map { it.toDomain() },
        foodRecommendations = foodRecommendations.mapValues { (_, recs) ->
            recs.map { it.toDomain() }
        }
    )

    fun ApiOutingRequest.toDomain(): OutingRequest = OutingRequest(
        destination = destination,
        duration = parseEnum<OutingDuration>(duration),
        timeOfDay = parseEnum<TimeOfDay>(timeOfDay),
        interests = interests.map { parseEnum<Interest>(it) }.toSet(),
        foodPreference = parseEnum<FoodPreference>(foodPreference),
        startLocation = startLocation.toDomain()
    )

    fun ApiStartLocation.toDomain(): StartLocation = StartLocation(
        name = name,
        isCurrentLocation = isCurrentLocation,
        latitude = latitude,
        longitude = longitude
    )

    fun ApiItineraryStop.toDomain(): ItineraryStop = ItineraryStop(
        place = place.toDomain(),
        arrivalTimeMinutes = arrivalTimeMinutes,
        visitDurationMinutes = visitDurationMinutes,
        travelToNext = travelToNext?.toDomain()
    )

    fun ApiPlace.toDomain(): Place = Place(
        id = id,
        name = name,
        shortDescription = shortDescription,
        fullDescription = fullDescription,
        address = address,
        latitude = latitude,
        longitude = longitude,
        interests = interests.map { parseEnum<Interest>(it) }.toSet(),
        suggestedVisitMinutes = suggestedVisitMinutes,
        openingHours = openingHours,
        imageUrl = imageUrl,
        isOptionalAttraction = isOptionalAttraction
    )

    fun ApiTravelLeg.toDomain(): TravelLeg = TravelLeg(
        distanceKm = distanceKm,
        durationMinutes = durationMinutes
    )

    fun ApiNearbyFoodRecommendation.toDomain(): NearbyFoodRecommendation =
        NearbyFoodRecommendation(
            name = name,
            cuisine = cuisine,
            mealType = parseEnum<MealType>(mealType),
            isVegetarianFriendly = isVegetarianFriendly,
            distanceKm = distanceKm,
            priceLevel = priceLevel
        )

    fun ApiPlaceDetails.toDomain(): PlaceDetails = PlaceDetails(
        place = place.toDomain(),
        nearbyRestaurants = nearbyRestaurants.map { it.toDomain() },
        nearbyAttractions = nearbyAttractions.map { it.toDomain() }
    )

    private inline fun <reified E : Enum<E>> parseEnum(raw: String): E =
        enumValues<E>().firstOrNull { it.name == raw }
            ?: throw IllegalArgumentException(
                "Unknown ${E::class.simpleName} value '$raw' from backend"
            )
}
