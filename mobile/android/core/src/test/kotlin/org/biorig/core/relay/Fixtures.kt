package org.biorig.core.relay

import okhttp3.mockwebserver.MockResponse

/** Response bodies in docs/relay-api.md's shapes. */
object Fixtures {
    const val PLANTER = "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
    const val TOKEN = "q3V0abcdefghijklmnopqrstuvwxyz0123456789ABC"

    fun json(status: Int, body: String, vararg headers: Pair<String, String>) = MockResponse()
        .setResponseCode(status).setHeader("Content-Type", "application/json").setHeader("Cache-Control", "no-store")
        .apply { headers.forEach { (k, v) -> setHeader(k, v) } }
        .setBody(body)

    fun session(expiresAt: Long = 1_800_086_400) = json(
        201,
        """{"session_token": "$TOKEN", "created_at": 1800000000, "expires_at": $expiresAt, "registrations_allowed": 3}""",
    )

    fun job(state: String = "submitted", submissionId: String = "sub1", mint: String = "null") = """
        {"job_id": "0123456789abcdef0123456789abcdef", "submission_id": "$submissionId", "state": "$state",
         "cell": "8c7a6e42ca207ff", "tree_ordinal": 0, "salt": "biorig:v1:8c7a6e42ca207ff:0",
         "nullifier": "0x${"ab".repeat(32)}", "planter_address": "$PLANTER",
         "tree": {"species": "unspecified", "dbh_cm": 10, "biomass_kg": 19.902, "co2e_kg": 34.298, "mint_biomass_kg": 20},
         "attempts": 0, "next_attempt_at": null, "last_error_code": null, "mint": $mint,
         "created_at": 1800000000, "updated_at": 1800000000, "verified_at": null, "minted_at": null}
    """.trimIndent()

    const val MINT = """{"token_id": 1, "tba": "0x453e8952000000000000000000000000001256A0", "tx_hash": "0x70476c", "block": 79000000}"""

    fun registration(status: Int, outcome: String, state: String = "submitted", extra: String = "") =
        json(status, """{"job": ${job(state)}, "outcome": "$outcome"$extra}""")

    fun refusal(status: Int, code: String, extra: String = "", vararg headers: Pair<String, String>) =
        json(status, """{"error": {"code": "$code", "message": "$code from the relay"$extra}}""", *headers)
}
