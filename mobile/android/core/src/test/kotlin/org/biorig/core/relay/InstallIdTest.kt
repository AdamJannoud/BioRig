package org.biorig.core.relay

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockWebServer
import org.biorig.core.queue.CaptureEntity
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The same contract Prefs keeps: one string value, kept across reads and across instances built on it. */
private class MemoryStore(var value: String? = null) : InstallIdStore {
    var writes = 0
    override fun loadInstallId() = value
    override fun saveInstallId(id: String) { value = id; writes++ }
}

class InstallIdTest {
    private val server = MockWebServer().apply { start() }

    @After fun stop() = server.shutdown()

    @Test
    fun `a store with no value generates 128 random bits as lowercase hex and keeps them`() {
        val store = MemoryStore()
        val id = InstallId(store).get()
        assertTrue(id, InstallId.FORMAT.matches(id))
        assertEquals(32, id.length)
        assertEquals(id, store.value)
        assertEquals(1, store.writes)
    }

    @Test
    fun `the id is stable across reads and survives a fresh instance from the same store`() {
        val store = MemoryStore()
        val first = InstallId(store)
        val id = first.get()
        assertEquals(id, first.get())
        assertEquals(id, InstallId(store).get())
        assertEquals(1, store.writes)
    }

    @Test
    fun `a stored value is used as it is, and a malformed one is replaced rather than sent`() {
        val kept = "0123456789abcdef0123456789abcdef"
        assertEquals(kept, InstallId(MemoryStore(kept)).get())
        val bad = MemoryStore("not-an-id")
        val replaced = InstallId(bad).get()
        assertNotEquals("not-an-id", replaced)
        assertTrue(InstallId.FORMAT.matches(replaced))
        assertEquals(replaced, bad.value)
    }

    @Test
    fun `two installs get different ids`() {
        assertNotEquals(InstallId(MemoryStore()).get(), InstallId(MemoryStore()).get())
    }

    @Test
    fun `the header reaches the wire on every route through the normal client path`() = runTest {
        val store = MemoryStore()
        val client = RelayClient(server.url("/").toString(), installId = InstallId(store))
        server.enqueue(Fixtures.session())
        server.enqueue(Fixtures.json(200, """{"job": ${Fixtures.job("minted", mint = Fixtures.MINT)}}"""))
        server.enqueue(Fixtures.refusal(429, "rate_limited", """, "limit": "plot_reads_per_device_hour""""))
        server.enqueue(Fixtures.registration(202, "created"))
        val capture = CaptureEntity(
            "sub1", Fixtures.PLANTER, -1.2903, 36.8219, 8.0, 1_800_000_000, "unspecified", 10, null, null, 1_800_000_000,
        )
        client.createSession()
        client.job("0123456789abcdef0123456789abcdef")
        client.plot("8c7a6e42ca207ff")
        client.submit(Fixtures.TOKEN, RegistrationBuilder.build(capture))
        repeat(4) {
            assertEquals(store.value, server.takeRequest().getHeader(InstallId.HEADER))
        }
        assertTrue(InstallId.FORMAT.matches(store.value!!))
    }

    @Test
    fun `a client built without an install id sends no header, as the APK before it did`() = runTest {
        server.enqueue(Fixtures.session())
        RelayClient(server.url("/").toString()).createSession()
        assertNull(server.takeRequest().getHeader(InstallId.HEADER))
    }
}
