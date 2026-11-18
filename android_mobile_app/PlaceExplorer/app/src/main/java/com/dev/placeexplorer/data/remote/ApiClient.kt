package com.dev.placeexplorer.data.remote

import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Builds the Retrofit + OkHttp stack for the FastAPI backend.
 *
 * The base URL comes from build configuration (BuildConfig.API_BASE_URL):
 * - Android Emulator: http://10.0.2.2:8000/ (10.0.2.2 maps to host localhost)
 * - Physical device: the host machine's LAN IP, e.g. http://192.168.1.5:8000/
 *
 * No production URL is hardcoded; it must be supplied per environment.
 */
object ApiClient {

    /** camelCase JSON matching the backend contract; unknown keys are ignored. */
    val json: Json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
        isLenient = true
        coerceInputValues = true
    }

    fun okHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(java.time.Duration.ofSeconds(20))
        // The plan pipeline queries Overpass and OSRM and can legitimately
        // take minutes when the public Overpass instance is slow; a 60s
        // timeout turned a working plan into an app-side SocketTimeout.
        .readTimeout(java.time.Duration.ofMinutes(4))
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        })
        .build()

    fun retrofit(baseUrl: String, client: OkHttpClient = okHttpClient()): Retrofit =
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

    fun planApiService(baseUrl: String, client: OkHttpClient = okHttpClient()): PlanApiService =
        retrofit(baseUrl, client).create(PlanApiService::class.java)
}
