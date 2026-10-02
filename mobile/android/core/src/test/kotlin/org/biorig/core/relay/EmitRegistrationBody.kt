package org.biorig.core.relay

import org.biorig.core.queue.CaptureEntity
import org.biorig.core.chain.Sha256

/**
 * `./gradlew -q :core:emitRegistrationBody` prints the body :core builds for a capture taken now, so
 * tools/check_registration_body.py can hand the exact bytes to relay/validate.py. Test-only; nothing here is a key.
 */
fun main() {
    val now = System.currentTimeMillis() / 1000
    val capture = CaptureEntity(
        submissionId = RegistrationBuilder.newSubmissionId(),
        planterAddress = "0xD314e37FD8538fe66231EE670B74C9428d03feEa", // relay-api.md's example planter
        lat = 6.428093, lng = 3.421974, accuracyM = 4.2, fixCapturedAt = now - 30,
        species = "unspecified", dbhCm = 10,
        photoSha256 = Sha256.hex("trunk photo bytes".toByteArray()), photoPath = null, createdAt = now,
    )
    println(RelayClient.encode(RegistrationBuilder.build(capture)))
}
