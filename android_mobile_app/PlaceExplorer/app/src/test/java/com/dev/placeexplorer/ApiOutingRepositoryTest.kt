package com.dev.placeexplorer

import com.dev.placeexplorer.data.remote.ApiClient
import com.dev.placeexplorer.data.remote.ApiItinerary
import com.dev.placeexplorer.data.remote.ApiMappers.toDomain
import com.dev.placeexplorer.data.remote.ApiMappers.toDto
import com.dev.placeexplorer.data.remote.ApiOutingRequest
import com.dev.placeexplorer.data.remote.ApiOutingRepository
import com.dev.placeexplorer.data.remote.ApiStartLocation
import com.dev.placeexplorer.domain.model.FoodPreference
import com.dev.placeexplorer.domain.model.Interest
import com.dev.placeexplorer.domain.model.Itinerary
import com.dev.placeexplorer.domain.model.OutingDuration
import com.dev.placeexplorer.domain.model.OutingRequest
import com.dev.placeexplorer.domain.model.StartLocation
import com.dev.placeexplorer.domain.model.TimeOfDay
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.encodeToString
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Unit tests for the Retrofit /api/plan integration.
 *
 * All HTTP traffic goes to a local MockWebServer; no live backend or
 * external API is ever contacted.
 */
class ApiOutingRepositoryTest {

    private lateinit var server: MockWebServer
    private lateinit var repository: ApiOutingRepository

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        repository = ApiOutingRepository(
            ApiClient.planApiService(server.url("/").toString())
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    // ------------------------------------------------------------------
    // Request DTO serialization
    // ------------------------------------------------------------------

    @Test
    fun `request DTO serializes to backend camelCase contract`() {
        val json = ApiClient.json.encodeToString(
            ApiOutingRequest(
                destination = "Pune, Maharashtra",
                duration = "FULL_DAY",
                timeOfDay = "MORNING",
                interests = listOf("TEMPLES", "HERITAGE"),
                foodPreference = "VEGETARIAN",
                startLocation = ApiStartLocation(
                    name = "Current Location",
                    isCurrentLocation = true,
                    latitude = 18.5204,
                    longitude = 73.8567
                )
            )
        )

        assertTrue(json.contains("\"timeOfDay\":\"MORNING\""))
        assertTrue(json.contains("\"foodPreference\":\"VEGETARIAN\""))
        assertTrue(json.contains("\"startLocation\""))
        assertTrue(json.contains("\"isCurrentLocation\":true"))
        assertTrue(json.contains("\"interests\":[\"TEMPLES\",\"HERITAGE\"]"))
    }

    @Test
    fun `domain request maps to DTO preserving enum names`() {
        val dto = OutingRequest(
            destination = "Pune, Maharashtra",
            duration = OutingDuration.FULL_DAY,
            timeOfDay = TimeOfDay.EVENING,
            interests = setOf(Interest.TEMPLES, Interest.NATURE),
            foodPreference = FoodPreference.VEGETARIAN,
            startLocation = StartLocation("Shaniwar Wada", false, 18.5195, 73.8553)
        ).toDto()

        assertEquals("FULL_DAY", dto.duration)
        assertEquals("EVENING", dto.timeOfDay)
        assertEquals(listOf("TEMPLES", "NATURE"), dto.interests)
        assertEquals("VEGETARIAN", dto.foodPreference)
        assertEquals("Shaniwar Wada", dto.startLocation.name)
        assertEquals(false, dto.startLocation.isCurrentLocation)
    }

    // ------------------------------------------------------------------
    // Response DTO deserialization + domain mapping
    // ------------------------------------------------------------------

    private val itineraryJson = """
        {
          "id": "itinerary_abc123",
          "title": "Royal Pune Heritage Walk",
          "destination": "Pune, Maharashtra",
          "request": {
            "destination": "Pune, Maharashtra",
            "duration": "FULL_DAY",
            "timeOfDay": "MORNING",
            "interests": ["TEMPLES", "HERITAGE"],
            "foodPreference": "VEGETARIAN",
            "startLocation": {
              "name": "Current Location",
              "isCurrentLocation": true,
              "latitude": 18.5204,
              "longitude": 73.8567
            }
          },
          "stops": [
            {
              "place": {
                "id": "live_123",
                "name": "Aga Khan Palace",
                "shortDescription": "Historic palace.",
                "fullDescription": "A historic palace built in 1892.",
                "address": "Aga Khan Palace Rd, Pune",
                "latitude": 18.5467,
                "longitude": 73.9006,
                "interests": ["HERITAGE"],
                "suggestedVisitMinutes": 60,
                "openingHours": "09:00-17:30",
                "imageUrl": null,
                "isOptionalAttraction": false
              },
              "arrivalTimeMinutes": 550,
              "visitDurationMinutes": 60,
              "travelToNext": {
                "distanceKm": 4.2,
                "durationMinutes": 15
              }
            }
          ],
          "totalDurationMinutes": 115,
          "optionalAttractions": [],
          "foodRecommendations": {
            "live_123": [
              {
                "name": "The Urban Kitchen",
                "cuisine": "North Indian",
                "mealType": "LUNCH",
                "isVegetarianFriendly": true,
                "distanceKm": 1.2,
                "priceLevel": 2
              }
            ]
          }
        }
    """.trimIndent()

    @Test
    fun `response DTO deserializes backend camelCase JSON`() {
        val dto = ApiClient.json.decodeFromString<ApiItinerary>(itineraryJson)

        assertEquals("itinerary_abc123", dto.id)
        assertEquals("Royal Pune Heritage Walk", dto.title)
        assertEquals(115, dto.totalDurationMinutes)
        val stop = dto.stops.single()
        assertEquals(550, stop.arrivalTimeMinutes)
        assertEquals(4.2, stop.travelToNext!!.distanceKm, 0.001)
        assertEquals("09:00-17:30", stop.place.openingHours)
        assertEquals("LUNCH", dto.foodRecommendations["live_123"]!!.single().mealType)
    }

    @Test
    fun `DTO maps to domain models correctly`() {
        val domain = ApiClient.json.decodeFromString<ApiItinerary>(itineraryJson).toDomain()

        assertTrue(domain is Itinerary)
        assertEquals(OutingDuration.FULL_DAY, domain.request.duration)
        assertEquals(TimeOfDay.MORNING, domain.request.timeOfDay)
        assertEquals(setOf(Interest.TEMPLES, Interest.HERITAGE), domain.request.interests)
        assertEquals(FoodPreference.VEGETARIAN, domain.request.foodPreference)
        assertTrue(domain.request.startLocation.isCurrentLocation)

        val stop = domain.stops.single()
        assertEquals("live_123", stop.place.id)
        assertEquals(Interest.HERITAGE, stop.place.interests.single())
        assertEquals(15, stop.travelToNext!!.durationMinutes)

        val rec = domain.foodRecommendations["live_123"]!!.single()
        assertEquals(com.dev.placeexplorer.domain.model.MealType.LUNCH, rec.mealType)
        assertTrue(rec.isVegetarianFriendly)
    }

    @Test
    fun `unknown JSON keys are ignored`() {
        val withExtra = itineraryJson.replace(
            "\"totalDurationMinutes\": 115,",
            "\"totalDurationMinutes\": 115, \"someFutureField\": 42,"
        )
        val dto = ApiClient.json.decodeFromString<ApiItinerary>(withExtra)
        assertEquals(115, dto.totalDurationMinutes)
    }

    // ------------------------------------------------------------------
    // Repository behaviour over mocked HTTP
    // ------------------------------------------------------------------

    @Test
    fun `repository success returns mapped itinerary and sends correct request`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(itineraryJson))

        val itinerary = repository.generateOuting(
            OutingRequest(
                duration = OutingDuration.FULL_DAY,
                interests = setOf(Interest.TEMPLES, Interest.HERITAGE)
            )
        )

        assertEquals("itinerary_abc123", itinerary.id)
        assertEquals(1, itinerary.stops.size)

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/plan", recorded.path)
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"timeOfDay\":\"MORNING\""))
        assertTrue(body.contains("\"interests\":[\"TEMPLES\",\"HERITAGE\"]"))
    }

    @Test
    fun `network failure surfaces as error`() = runTest {
        server.enqueue(
            MockResponse()
                .setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START)
        )

        val error = runCatching {
            repository.generateOuting(OutingRequest())
        }.exceptionOrNull()

        assertTrue(error is java.io.IOException)
        assertTrue(error !is com.dev.placeexplorer.data.remote.ApiException)
    }

    @Test
    fun `HTTP 503 surfaces backend explanation in message`() = runTest {
        val explanation =
            "Cannot generate a real itinerary: the connected place data source " +
                "provides only mock places without the coordinates required."
        server.enqueue(
            MockResponse()
                .setResponseCode(503)
                .setBody("""{"detail": "$explanation"}""")
        )

        val error = runCatching {
            repository.generateOuting(OutingRequest())
        }.exceptionOrNull()

        assertTrue(error is com.dev.placeexplorer.data.remote.ApiException)
        assertEquals(503, (error as com.dev.placeexplorer.data.remote.ApiException).httpCode)
        assertTrue(error.message!!.contains(explanation))
    }

    @Test
    fun `HTTP 503 with non-JSON body still surfaces the code`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(503).setBody("Service Unavailable")
        )

        val error = runCatching {
            repository.generateOuting(OutingRequest())
        }.exceptionOrNull()

        assertTrue(error is com.dev.placeexplorer.data.remote.ApiException)
        assertEquals(503, (error as com.dev.placeexplorer.data.remote.ApiException).httpCode)
    }

    @Test
    fun `HTTP 502 surfaces as ApiException`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(502).setBody("""{"detail": "upstream failed"}""")
        )

        val error = runCatching {
            repository.generateOuting(OutingRequest())
        }.exceptionOrNull()

        assertEquals(502, (error as com.dev.placeexplorer.data.remote.ApiException).httpCode)
        assertTrue(error.message!!.contains("upstream failed"))
    }
}
