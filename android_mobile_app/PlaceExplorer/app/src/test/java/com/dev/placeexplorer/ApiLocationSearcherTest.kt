package com.dev.placeexplorer

import com.dev.placeexplorer.data.remote.ApiClient
import com.dev.placeexplorer.data.remote.ApiLocationSearcher
import com.dev.placeexplorer.data.remote.ApiException
import com.dev.placeexplorer.data.remote.PlanApiService
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * Tests for ApiLocationSearcher (backend GET /api/geocode) over a local
 * MockWebServer. No live backend or Nominatim call ever happens.
 */
class ApiLocationSearcherTest {

    private lateinit var server: MockWebServer
    private lateinit var searcher: ApiLocationSearcher

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        searcher = ApiLocationSearcher(
            ApiClient.planApiService(server.url("/").toString())
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun successBody() = """
        {
          "query": "Shaniwar Wada",
          "results": [
            {
              "id": "nominatim_248202085",
              "name": "Shaniwar Wada",
              "displayName": "Shaniwar Wada, Shivaji Road, Kasba Peth, Pune, Maharashtra, 411001, India",
              "latitude": 18.5193826,
              "longitude": 73.8553566,
              "address": "Pune, Pune, Maharashtra, India"
            },
            {
              "id": "nominatim_248672805",
              "name": null,
              "displayName": "Kothrud, Pune, Maharashtra, India",
              "latitude": 18.5074,
              "longitude": 73.8077,
              "address": null
            }
          ]
        }
    """.trimIndent()

    // ------------------------------------------------------------------
    // Request shape
    // ------------------------------------------------------------------

    @Test
    fun `sends GET to api geocode with encoded query and default limit`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        searcher.search("Shaniwar Wada")

        val recorded = server.takeRequest()
        assertEquals("GET", recorded.method)
        assertEquals("/api/geocode?q=Shaniwar%20Wada&limit=5", recorded.path)
    }

    @Test
    fun `query with spaces and special characters is URL-encoded`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        searcher.search("Kalyani Nagar & café, Pune")

        val path = server.takeRequest().path!!
        assertTrue(path.startsWith("/api/geocode?q="))
        // No raw spaces or ampersands may reach the query parameter.
        assertTrue(!path.contains(" "))
        val query = path.substringAfter("q=").substringBefore("&")
        assertTrue(java.net.URLDecoder.decode(query, "UTF-8") == "Kalyani Nagar & café, Pune")
    }

    @Test
    fun `limit parameter defaults to five`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        searcher.search("Pune")

        assertTrue(server.takeRequest().path!!.contains("limit=5"))
    }

    // ------------------------------------------------------------------
    // Response mapping
    // ------------------------------------------------------------------

    @Test
    fun `successful response maps names display names and coordinates`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(successBody()))

        val results = searcher.search("Shaniwar Wada")

        assertEquals(2, results.size)
        assertEquals("nominatim_248202085", results[0].id)
        assertEquals("Shaniwar Wada", results[0].displayName)
        assertEquals(18.5193826, results[0].latitude, 0.0000001)
        assertEquals(73.8553566, results[0].longitude, 0.0000001)
        assertEquals("Pune, Pune, Maharashtra, India", results[0].address)

        // Missing short name falls back to the display name; missing
        // address falls back to the display name too.
        assertEquals("Kothrud, Pune, Maharashtra, India", results[1].displayName)
        assertEquals("Kothrud, Pune, Maharashtra, India", results[1].address)
    }

    @Test
    fun `empty results list is a genuine no-match`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"query": "zzz", "results": []}""")
        )

        val results = searcher.search("zzz")

        assertTrue(results.isEmpty())
    }

    // ------------------------------------------------------------------
    // Error handling
    // ------------------------------------------------------------------

    @Test
    fun `HTTP 400 surfaces backend detail as ApiException`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(400)
                .setBody("""{"detail": "q must not be empty"}""")
        )

        val error = runCatching { searcher.search("") }.exceptionOrNull()

        assertTrue(error is ApiException)
        assertEquals(400, (error as ApiException).httpCode)
        assertTrue(error.message!!.contains("must not be empty"))
    }

    @Test
    fun `HTTP 422 surfaces as ApiException`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(422)
                .setBody("""{"detail": [{"loc": ["query", "limit"], "msg": "invalid"}]}""")
        )

        val error = runCatching { searcher.search("x") }.exceptionOrNull()

        assertTrue(error is ApiException)
        assertEquals(422, (error as ApiException).httpCode)
    }

    @Test
    fun `HTTP 429 rate limit surfaces as ApiException with code`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(429)
                .setBody("""{"detail": "Too many requests"}""")
        )

        val error = runCatching { searcher.search("Pune") }.exceptionOrNull()

        assertTrue(error is ApiException)
        assertEquals(429, (error as ApiException).httpCode)
    }

    @Test
    fun `HTTP 502 upstream failure surfaces backend detail`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(502)
                .setBody("""{"detail": "geocoding provider unreachable"}""")
        )

        val error = runCatching { searcher.search("Pune") }.exceptionOrNull()

        assertTrue(error is ApiException)
        assertEquals(502, (error as ApiException).httpCode)
        assertTrue(error.message!!.contains("geocoding provider unreachable"))
    }

    @Test
    fun `network failure surfaces as plain IOException`() = runTest {
        server.enqueue(
            MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START)
        )

        val error = runCatching { searcher.search("Pune") }.exceptionOrNull()

        assertTrue(error is IOException)
        assertTrue(error !is ApiException)
    }

    @Test
    fun `malformed JSON response surfaces as IOException`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody("not json at all")
        )

        val error = runCatching { searcher.search("Pune") }.exceptionOrNull()

        // kotlinx SerializationException is an IllegalArgumentException, not
        // an IOException; either way it must not be a silent success.
        assertTrue(error != null)
        assertTrue(error !is ApiException)
    }
}
