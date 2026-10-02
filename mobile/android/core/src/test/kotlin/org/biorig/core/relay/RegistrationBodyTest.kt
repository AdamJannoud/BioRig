package org.biorig.core.relay

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.biorig.core.Golden
import org.biorig.core.queue.CaptureEntity
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The body against relay/validate.py's own field sets (via the golden file); tools/check_registration_body.py then
 * runs the real validator on it. */
class RegistrationBodyTest {
    private fun capture(photo: String? = "9f3c07" + "0".repeat(54) + "41d2") = CaptureEntity(
        submissionId = "7c41aa00bb11cc22dd33ee44ff55e209", planterAddress = "0xD314e37FD8538fe66231EE670B74C9428d03feEa",
        lat = 6.428093, lng = 3.421974, accuracyM = 4.2, fixCapturedAt = 1_800_000_000, species = "unspecified",
        dbhCm = 10, photoSha256 = photo, photoPath = "/data/user/0/org.biorig/files/x.jpg", createdAt = 1_800_000_010,
    )

    private fun keys(e: JsonElement, prefix: String = ""): List<String> = (e as? JsonObject)?.flatMap { (k, v) ->
        listOf(k) + keys(v, "$prefix$k.")
    }.orEmpty()

    @Test
    fun `the body uses only fields the relay defines and none it forbids, at any level`() {
        val body = RelayClient.json.parseToJsonElement(RelayClient.encode(RegistrationBuilder.build(capture()))).jsonObject
        val f = Golden.obj("fields")
        assertEquals(Golden.strings(f.getValue("top")).toSet(), body.keys)
        assertEquals(Golden.strings(f.getValue("fix")).toSet(), body.getValue("fix").jsonObject.keys)
        assertEquals(Golden.strings(f.getValue("tree")).toSet(), body.getValue("tree").jsonObject.keys)
        assertEquals(Golden.strings(f.getValue("client_estimate")).toSet(), body.getValue("client_estimate").jsonObject.keys)
        val forbidden = Golden.strings(f.getValue("forbidden")).toSet()
        // client_estimate.biomass_kg / co2e_kg are allowed there and only there (relay validate.ESTIMATE_FIELDS)
        val outsideEstimate = keys(body).toMutableList().apply { removeAll(listOf("biomass_kg", "co2e_kg")) }
        assertTrue(outsideEstimate.none { it in forbidden })
        assertFalse(body.containsKey("biomass_kg"))
    }

    @Test
    fun `exact wire form - integers stay integers, absent optionals are absent`() {
        val text = RelayClient.encode(RegistrationBuilder.build(capture(photo = null)))
        assertTrue(text, text.contains("\"dbh_cm\":10,") || text.contains("\"dbh_cm\":10}"))
        assertTrue(text, text.contains("\"captured_at\":1800000000"))
        assertFalse(text, text.contains("photo_sha256"))
        assertFalse(text, text.contains("null"))
    }

    @Test
    fun `submission ids are 32 hex and unique`() {
        val ids = (1..200).map { RegistrationBuilder.newSubmissionId() }.toSet()
        assertEquals(200, ids.size)
        assertTrue(ids.all { Regex("^[0-9a-f]{32}$").matches(it) })
    }
}
