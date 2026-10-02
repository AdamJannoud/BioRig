package org.biorig.core.relay

import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonObject
import okhttp3.mockwebserver.MockWebServer
import org.biorig.core.queue.CaptureEntity
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RelayClientTest {
    private val server = MockWebServer().apply { start() }
    private val client = RelayClient(server.url("/").toString())

    @After fun stop() = server.shutdown()

    private val capture = CaptureEntity(
        "sub1", Fixtures.PLANTER, -1.2903, 36.8219, 8.0, 1_800_000_000, "unspecified", 10, null, null, 1_800_000_000,
    )

    @Test
    fun `sessions are bootstrapped with an empty POST and no credential`() = runTest {
        server.enqueue(Fixtures.session())
        val r = client.createSession() as RelayResult.Ok
        assertEquals(Fixtures.TOKEN, r.value.sessionToken)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/v1/sessions", req.path)
        assertEquals(null, req.getHeader("Authorization"))
    }

    @Test
    fun `registration carries the bearer token and the JSON body`() = runTest {
        server.enqueue(Fixtures.registration(202, "created"))
        val r = client.submit(Fixtures.TOKEN, RegistrationBuilder.build(capture)) as RelayResult.Ok
        assertEquals(202, r.status)
        assertEquals("created", r.value.outcome)
        assertEquals("submitted", r.value.job.state)
        val req = server.takeRequest()
        assertEquals("/v1/registrations", req.path)
        assertEquals("Bearer ${Fixtures.TOKEN}", req.getHeader("Authorization"))
        assertTrue(req.getHeader("Content-Type")!!.startsWith("application/json"))
        val body = RelayClient.json.parseToJsonElement(req.body.readUtf8()).jsonObject
        assertEquals("sub1", body["submission_id"].toString().trim('"'))
    }

    @Test
    fun `job and plot reads use the documented paths`() = runTest {
        server.enqueue(Fixtures.json(200, """{"job": ${Fixtures.job("minted", mint = Fixtures.MINT)}}"""))
        server.enqueue(
            Fixtures.json(
                200,
                """{"cell": "8c7a6e42ca207ff", "resolution": 12, "active": 1, "max_trees_per_cell": 4, "full": false,
                   "neighbourhood_active": 1, "collision_radius_m": 20.0,
                   "trees": [{"tree_ordinal": 0, "state": "minted", "token_id": 1}]}""",
            ),
        )
        val job = (client.job("0123456789abcdef0123456789abcdef") as RelayResult.Ok).value.job
        assertEquals(1L, job.mint!!.tokenId)
        val plot = (client.plot("8c7a6e42ca207ff") as RelayResult.Ok).value
        assertEquals(1, plot.neighbourhoodActive)
        assertEquals("/v1/registrations/0123456789abcdef0123456789abcdef", server.takeRequest().path)
        assertEquals("/v1/plots/8c7a6e42ca207ff", server.takeRequest().path)
    }

    @Test
    fun `a 429 takes Retry-After from the header and names the limit`() = runTest {
        server.enqueue(
            Fixtures.refusal(429, "rate_limited", """, "limit": "per_ip_hour", "retry_after_s": 1800""", "Retry-After" to "1800"),
        )
        val r = (client.submit(Fixtures.TOKEN, RegistrationBuilder.build(capture)) as RelayResult.Refused).refusal
        assertEquals(429, r.status)
        assertEquals(1800L, r.retryAfterS)
        assertEquals("per_ip_hour", r.limit)
    }

    @Test
    fun `species_not_allowed surfaces error allowed`() = runTest {
        server.enqueue(
            Fixtures.refusal(422, "species_not_allowed", """, "field": "tree.species", "allowed": ["unspecified", "Mangifera indica"]"""),
        )
        val r = (client.submit(Fixtures.TOKEN, RegistrationBuilder.build(capture)) as RelayResult.Refused).refusal
        assertEquals(listOf("unspecified", "Mangifera indica"), r.allowed)
        assertEquals("tree.species", r.field)
    }

    @Test
    fun `no server is Unreachable, not a refusal`() = runTest {
        server.shutdown()
        assertTrue(client.createSession() is RelayResult.Unreachable)
    }
}
