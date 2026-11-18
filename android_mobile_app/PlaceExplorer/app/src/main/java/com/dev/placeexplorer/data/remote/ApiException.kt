package com.dev.placeexplorer.data.remote

import java.io.IOException

/**
 * A backend/API failure surfaced to the UI. Carries the backend's own
 * explanation when present (e.g. the HTTP 503 detail from /api/plan).
 */
class ApiException(
    val httpCode: Int?,
    message: String
) : IOException(message) {

    companion object {

        /** Map a Retrofit HttpException to an ApiException with the backend detail. */
        fun fromHttpException(http: retrofit2.HttpException): ApiException {
            val detail = extractDetail(http)
            return ApiException(
                httpCode = http.code(),
                message = when {
                    detail != null -> "Backend error ${http.code()}: $detail"
                    else -> "Backend request failed (HTTP ${http.code()})"
                }
            )
        }

        /** Parse {"detail": "..."} from an error response body, if any. */
        private fun extractDetail(http: retrofit2.HttpException): String? = try {
            val body = http.response()?.errorBody()?.string() ?: return null
            kotlinx.serialization.json.Json.decodeFromString<ApiError>(body).detail
        } catch (_: Exception) {
            null
        }
    }
}
