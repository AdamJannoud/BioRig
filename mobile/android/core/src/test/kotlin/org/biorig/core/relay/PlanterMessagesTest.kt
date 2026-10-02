package org.biorig.core.relay

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class PlanterMessagesTest {
    private fun r(status: Int, code: String, vararg detail: Pair<String, Any>, retry: Long? = null) = Refusal(
        status, code, "m", detail.toMap()["field"] as String?,
        JsonObject(detail.associate { (k, v) -> k to (if (v is Number) JsonPrimitive(v) else JsonPrimitive(v.toString())) }),
        retry,
    )

    @Test
    fun `the refusals the app can receive each map to one next step`() {
        assertEquals(NextStep.Refix, PlanterMessages.forRefusal(r(422, "accuracy_too_coarse")).next)
        assertEquals(NextStep.Refix, PlanterMessages.forRefusal(r(422, "fix_stale")).next)
        assertEquals(NextStep.PickAnotherTree, PlanterMessages.forRefusal(r(409, "collision", "distance_m" to 6.2)).next)
        assertEquals(NextStep.PickAnotherTree, PlanterMessages.forRefusal(r(422, "cell_full")).next)
        assertEquals(NextStep.Remeasure, PlanterMessages.forRefusal(r(422, "estimate_mismatch", "relay_value" to 19.902)).next)
        assertEquals(NextStep.Wait(1800), PlanterMessages.forRefusal(r(429, "rate_limited", retry = 1800)).next)
        val species = Refusal(422, "species_not_allowed", "m", "tree.species",
            RelayClient.json.parseToJsonElement("""{"allowed": ["a", "b"]}""") as JsonObject)
        assertEquals(NextStep.ChooseSpecies(listOf("a", "b")), PlanterMessages.forRefusal(species).next)
    }

    @Test
    fun `sentences carry the relay's figures, not codes`() {
        val c = PlanterMessages.forRefusal(r(409, "collision", "distance_m" to 6.2))
        assertTrue(c.body, c.body.contains("6 m"))
        val e = PlanterMessages.forRefusal(r(422, "estimate_mismatch", "relay_value" to 19.902))
        assertTrue(e.body, e.body.contains("19.9 kg"))
        assertFalse(e.body.contains("estimate_mismatch"))
    }

    /** docs/relay-api.md is the contract. Every 409/422/429/503 code it lists for clients must have its own wording. */
    @Test
    fun `every client-facing code in the contract's error table is worded`() {
        val doc = File("../../../docs/relay-api.md").takeIf { it.isFile }
            ?: error("docs/relay-api.md not found from ${File(".").absolutePath}")
        val table = doc.readText().substringAfter("## Error codes").substringBefore("### Queue codes")
        val rows = Regex("""^\| (\d{3}) \| `([a-z_]+)` \|""", RegexOption.MULTILINE).findAll(table)
            .map { it.groupValues[1].toInt() to it.groupValues[2] }.toList()
        assertTrue("parsed ${rows.size} rows", rows.size >= 30)
        val adminOnly = setOf("invalid_transition", "broadcast_in_history")
        val generic = PlanterMessages.forRefusal(r(422, "no_such_code_xyz")).title
        val unworded = rows.filter { (status, code) -> status in setOf(409, 422, 429, 503) && code !in adminOnly }
            .filter { (status, code) -> PlanterMessages.forRefusal(r(status, code)).title == generic }
        assertEquals(emptyList<Pair<Int, String>>(), unworded)
    }
}
