package org.biorig.core.relay

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/** A refusal in the contract's shape: `{"error": {"code", "message", "field"?, ...}}`, plus the HTTP status. */
data class Refusal(
    val status: Int,
    val code: String,
    val message: String,
    val field: String? = null,
    val detail: JsonObject = JsonObject(emptyMap()),
    /** From the `Retry-After` header, falling back to `error.retry_after_s` (a 429 carries both). */
    val retryAfterS: Long? = null,
) {
    /** `species_not_allowed` carries the relay's allowlist in `error.allowed`. */
    val allowed: List<String>?
        get() = (detail["allowed"] as? JsonArray)?.mapNotNull { it.jsonPrimitive.contentOrNull }

    /** `rate_limited` names the limit that refused. */
    val limit: String? get() = detail["limit"]?.jsonPrimitive?.contentOrNull
    val distanceM: Double? get() = detail["distance_m"]?.jsonPrimitive?.doubleOrNull
    val relayValue: Double? get() = detail["relay_value"]?.jsonPrimitive?.doubleOrNull
    val existingTokenId: Long?
        get() = (detail["existing"] as? JsonObject)?.get("token_id")?.jsonPrimitive?.longOrNull
}

sealed interface RelayResult<out T> {
    data class Ok<T>(val value: T, val status: Int) : RelayResult<T>
    data class Refused(val refusal: Refusal) : RelayResult<Nothing>
    /** No HTTP answer at all: no signal, DNS, TLS, a timeout. Nothing reached the relay as far as we know. */
    data class Unreachable(val cause: IOException) : RelayResult<Nothing>
}

/**
 * The relay's client half: exactly the four non-admin routes of contract v1, nothing invented.
 *
 *     POST /v1/sessions               bootstrap a session token (no credential)
 *     POST /v1/registrations          Bearer <session_token>
 *     GET  /v1/registrations/{job_id} the reload / polling path
 *     GET  /v1/plots/{cell}           occupancy for the pre-check
 *
 * Given an [InstallId], every one of them carries `X-BioRig-Install-Id`, added by an interceptor on the client rather
 * than at each call site. Without one the relay counts the caller's address, as it did before the header existed.
 */
class RelayClient(
    baseUrl: String,
    http: OkHttpClient = OkHttpClient(),
    installId: InstallId? = null,
) {
    private val base: HttpUrl = baseUrl.trimEnd('/').toHttpUrl()
    private val http: OkHttpClient = if (installId == null) http else http.withInstallId(installId)

    companion object {
        val json = Json {
            ignoreUnknownKeys = true // the relay may add response fields; requests are built from our own types
            explicitNulls = false // an absent optional field, never `"photo_sha256": null`
            encodeDefaults = true
        }
        private val JSON_TYPE = "application/json".toMediaType()

        fun encode(request: RegistrationRequest): String = json.encodeToString(RegistrationRequest.serializer(), request)
    }

    suspend fun createSession(): RelayResult<SessionResponse> =
        execute(post("v1/sessions", null, null), SessionResponse.serializer())

    suspend fun submit(sessionToken: String, request: RegistrationRequest): RelayResult<RegistrationResponse> =
        execute(post("v1/registrations", encode(request), sessionToken), RegistrationResponse.serializer())

    suspend fun job(jobId: String): RelayResult<JobResponse> =
        execute(get("v1/registrations", jobId), JobResponse.serializer())

    suspend fun plot(cell: String): RelayResult<PlotOccupancy> =
        execute(get("v1/plots", cell), PlotOccupancy.serializer())

    private fun url(vararg segments: String): HttpUrl =
        base.newBuilder().apply { segments.forEach { s -> s.split('/').forEach { addPathSegment(it) } } }.build()

    private fun get(path: String, id: String): Request = Request.Builder().url(url(path, id)).get().build()

    private fun post(path: String, body: String?, bearer: String?): Request =
        Request.Builder().url(url(path))
            .post((body ?: "").toRequestBody(JSON_TYPE))
            .apply { if (bearer != null) header("Authorization", "Bearer $bearer") }
            .build()

    private suspend fun <T> execute(request: Request, serializer: KSerializer<T>): RelayResult<T> =
        withContext(Dispatchers.IO) {
            try {
                http.newCall(request).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    if (resp.isSuccessful) {
                        RelayResult.Ok(json.decodeFromString(serializer, text), resp.code)
                    } else {
                        RelayResult.Refused(parseRefusal(resp.code, text, resp.header("Retry-After")))
                    }
                }
            } catch (e: IOException) {
                RelayResult.Unreachable(e)
            }
        }

    internal fun parseRefusal(status: Int, text: String, retryAfterHeader: String?): Refusal {
        val error = runCatching { json.parseToJsonElement(text).jsonObject["error"]?.jsonObject }.getOrNull()
        val code = error?.get("code")?.jsonPrimitive?.contentOrNull ?: "http_$status"
        val message = error?.get("message")?.jsonPrimitive?.contentOrNull ?: text.take(200)
        val field = error?.get("field")?.jsonPrimitive?.contentOrNull
        val retryAfter = retryAfterHeader?.trim()?.toLongOrNull()
            ?: error?.get("retry_after_s")?.jsonPrimitive?.longOrNull
        return Refusal(status, code, message, field, error ?: JsonObject(emptyMap()), retryAfter)
    }
}
