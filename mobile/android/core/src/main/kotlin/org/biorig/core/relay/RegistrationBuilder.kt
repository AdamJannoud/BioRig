package org.biorig.core.relay

import org.biorig.core.allometry.Allometry
import org.biorig.core.queue.CaptureEntity
import java.security.SecureRandom

/**
 * Builds the POST /v1/registrations body from a saved capture: the fix, the measurement, the photo digest and the
 * planter's public address. The client estimate is the ported allometry's, sent so the relay can catch a stale app
 * (estimate_mismatch); the relay never uses it.
 */
object RegistrationBuilder {
    private val SUBMISSION_ID = Regex("^[A-Za-z0-9_-]{1,64}$")
    private val rng = SecureRandom()

    /** Minted once, when a capture is saved, and kept across retries and sessions. 128 random bits. */
    fun newSubmissionId(): String = ByteArray(16).also(rng::nextBytes).joinToString("") { "%02x".format(it) }

    fun build(c: CaptureEntity): RegistrationRequest {
        require(SUBMISSION_ID.matches(c.submissionId)) { "submission id must be 1-64 of [A-Za-z0-9_-]" }
        val estimate = Allometry.estimate(c.dbhCm)
        return RegistrationRequest(
            submissionId = c.submissionId,
            planterAddress = c.planterAddress,
            fix = FixBody(c.lat, c.lng, c.accuracyM, c.fixCapturedAt),
            tree = TreeBody(c.species, c.dbhCm),
            clientEstimate = ClientEstimate(estimate.biomassKg, estimate.co2eKg),
            photoSha256 = c.photoSha256,
        )
    }
}
