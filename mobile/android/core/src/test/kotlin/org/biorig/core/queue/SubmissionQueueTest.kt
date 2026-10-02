package org.biorig.core.queue

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockWebServer
import org.biorig.core.relay.Fixtures
import org.biorig.core.relay.RelayClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MemoryCaptures : CaptureStore {
    val rows = linkedMapOf<String, CaptureEntity>()
    override suspend fun upsert(capture: CaptureEntity) { rows[capture.submissionId] = capture }
    override suspend fun get(submissionId: String) = rows[submissionId]
    override suspend fun all() = rows.values.toList()
}

class MemorySessions(var session: Session? = null) : SessionStore {
    override suspend fun load() = session
    override suspend fun save(session: Session?) { this.session = session }
}

/** Every refusal the brief names, plus the session and idempotency paths, driven through a fake relay. */
class SubmissionQueueTest {
    private val server = MockWebServer().apply { start() }
    private var now = 1_800_000_100L
    private val captures = MemoryCaptures()
    private val sessions = MemorySessions()
    private val queue = SubmissionQueue(RelayClient(server.url("/").toString()), captures, sessions, { now })

    @After fun stop() = server.shutdown()

    private suspend fun saved(id: String = "sub1", fixAt: Long = now - 60, species: String = "unspecified") =
        CaptureEntity(id, Fixtures.PLANTER, 6.428093, 3.421974, 4.2, fixAt, species, 10, null, null, now)
            .also { captures.upsert(it) }

    private fun paths() = (1..server.requestCount).map { server.takeRequest().path }

    @Test
    fun `created - session bootstrapped once, job recorded, then polled to minted`() = runTest {
        server.enqueue(Fixtures.session())
        server.enqueue(Fixtures.registration(202, "created"))
        server.enqueue(Fixtures.json(200, """{"job": ${Fixtures.job("minted", mint = Fixtures.MINT)}}"""))
        val c = queue.send(saved())
        assertEquals(CaptureState.SENT, c.state)
        assertEquals("0123456789abcdef0123456789abcdef", c.jobId)
        assertEquals("8c7a6e42ca207ff", c.cell)
        val m = queue.pollInFlight().single()
        assertEquals(CaptureState.MINTED, m.state)
        assertEquals(1L, m.tokenId)
        assertEquals(listOf("/v1/sessions", "/v1/registrations", "/v1/registrations/0123456789abcdef0123456789abcdef"), paths())
    }

    @Test
    fun `replayed and same_tree come back as the tree they already are`() = runTest {
        sessions.session = Session(Fixtures.TOKEN, now + 3600)
        server.enqueue(Fixtures.registration(200, "replayed"))
        server.enqueue(Fixtures.registration(200, "same_tree", extra = """, "distance_m": 3.1"""))
        assertEquals("replayed", queue.send(saved("a")).outcome)
        val b = queue.send(saved("b"))
        assertEquals("same_tree", b.outcome)
        assertEquals(3.1, b.distanceM!!, 0.0)
        assertEquals(CaptureState.SENT, b.state)
    }

    @Test
    fun `an expired session is renewed and the same submission id is sent again`() = runTest {
        sessions.session = Session("old", now + 3600)
        server.enqueue(Fixtures.refusal(401, "session_expired"))
        server.enqueue(Fixtures.session())
        server.enqueue(Fixtures.registration(200, "same_tree"))
        val c = queue.send(saved())
        assertEquals(CaptureState.SENT, c.state)
        val first = server.takeRequest(); server.takeRequest(); val third = server.takeRequest()
        assertEquals("Bearer old", first.getHeader("Authorization"))
        assertEquals("Bearer ${Fixtures.TOKEN}", third.getHeader("Authorization"))
        assertEquals(first.body.readUtf8(), third.body.readUtf8())
    }

    @Test
    fun `per_session limit opens a new session, other limits wait the Retry-After`() = runTest {
        sessions.session = Session("full", now + 3600)
        server.enqueue(Fixtures.refusal(429, "rate_limited", """, "limit": "per_session", "retry_after_s": 86000""", "Retry-After" to "86000"))
        server.enqueue(Fixtures.session())
        server.enqueue(Fixtures.registration(202, "created"))
        assertEquals(CaptureState.SENT, queue.send(saved("a")).state)

        server.enqueue(Fixtures.refusal(429, "rate_limited", """, "limit": "per_ip_hour", "retry_after_s": 1200""", "Retry-After" to "1200"))
        val b = queue.send(saved("b"))
        assertEquals(CaptureState.QUEUED, b.state)
        assertEquals(now + 1200, b.nextAttemptAt)
        assertEquals(0, b.attempts)
        assertEquals(emptyList<CaptureEntity>(), queue.due().filter { it.submissionId == "b" })
        now += 1200
        assertEquals("b", queue.due().single { it.submissionId == "b" }.submissionId)
    }

    @Test
    fun `species_not_allowed keeps error allowed, and a chosen species requeues it`() = runTest {
        sessions.session = Session(Fixtures.TOKEN, now + 3600)
        server.enqueue(Fixtures.refusal(422, "species_not_allowed", """, "field": "tree.species", "allowed": ["Mangifera indica", "Moringa oleifera"]"""))
        val c = queue.send(saved(species = "unspecified"))
        assertEquals(CaptureState.NEEDS_ATTENTION, c.state)
        assertEquals(listOf("Mangifera indica", "Moringa oleifera"), c.allowedSpeciesList)
        val again = queue.requeue(c.copy(species = c.allowedSpeciesList.first()))
        assertEquals(CaptureState.QUEUED, again.state)
        assertNull(again.allowedSpecies)
    }

    @Test
    fun `field refusals stop the queue and keep what the relay said`() = runTest {
        sessions.session = Session(Fixtures.TOKEN, now + 3600)
        val cases = listOf(
            Fixtures.refusal(422, "accuracy_too_coarse", """, "field": "fix.accuracy_m", "max_accuracy_m": 30.0"""),
            Fixtures.refusal(422, "fix_stale", """, "field": "fix.captured_at", "max_age_s": 600"""),
            Fixtures.refusal(409, "collision", """, "distance_m": 6.2, "collision_radius_m": 20.0, "existing": {"cell": "8c7a6e42ca207ff", "tree_ordinal": 0, "state": "minted", "token_id": 1}"""),
            Fixtures.refusal(422, "cell_full", """, "cell": "8c7a6e42ca207ff", "max_trees_per_cell": 4"""),
            Fixtures.refusal(422, "estimate_mismatch", """, "field": "client_estimate.biomass_kg", "relay_value": 19.902"""),
        )
        cases.forEach(server::enqueue)
        val codes = cases.indices.map { i -> queue.send(saved("s$i")) }
        assertEquals(List(5) { CaptureState.NEEDS_ATTENTION }, codes.map { it.state })
        assertEquals(listOf("accuracy_too_coarse", "fix_stale", "collision", "cell_full", "estimate_mismatch"), codes.map { it.lastErrorCode })
        assertEquals(6.2, codes[2].distanceM!!, 0.0)
        assertEquals(19.902, codes[4].relayValue!!, 0.0)
    }

    @Test
    fun `a fix past the relay's 600 s is not sent at all`() = runTest {
        val c = queue.send(saved(fixAt = now - 601))
        assertEquals(CaptureState.NEEDS_ATTENTION, c.state)
        assertEquals("fix_stale", c.lastErrorCode)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `no answer four times asks the planter, with backoff between`() = runTest {
        sessions.session = Session(Fixtures.TOKEN, now + 86_000)
        server.shutdown()
        var c = saved(fixAt = now)
        val waits = mutableListOf<Long?>()
        repeat(4) {
            c = queue.send(c)
            waits += c.nextAttemptAt?.minus(now)
        }
        assertEquals(4, c.attempts)
        assertEquals(CaptureState.NEEDS_ATTENTION, c.state)
        assertEquals(SubmissionQueue.UNREACHABLE, c.lastErrorCode)
        assertEquals(listOf(30L, 120L, 600L, null), waits)
    }

    @Test
    fun `a 503 chain_unavailable is retried, not shown as a refusal`() = runTest {
        sessions.session = Session(Fixtures.TOKEN, now + 3600)
        server.enqueue(Fixtures.refusal(503, "chain_unavailable"))
        val c = queue.send(saved())
        assertEquals(CaptureState.QUEUED, c.state)
        assertEquals(1, c.attempts)
        assertEquals(now + 30, c.nextAttemptAt)
    }
}
