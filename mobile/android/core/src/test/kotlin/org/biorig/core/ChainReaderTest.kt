package org.biorig.core

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.biorig.core.chain.ChainError
import org.biorig.core.chain.ChainReader
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ChainReaderTest {
    private val server = MockWebServer().apply { start() }
    private val reader = ChainReader(server.url("/").toString(), "0x04db169ddf8abb80943161c01b2a71dc40384e64", retryDelayMs = 1)

    @After fun stop() = server.shutdown()

    private fun result(r: String) = MockResponse().setBody("""{"jsonrpc":"2.0","id":1,"result":"$r"}""")

    @Test
    fun `an empty answer is asked again rather than believed`() = runTest {
        server.enqueue(result("0x"))
        server.enqueue(result("0x" + "0".repeat(63) + "1"))
        assertTrue(reader.isNullifierActive("0x" + "ab".repeat(32)))
        assertEquals(2, server.requestCount)
        val body = server.takeRequest().body.readUtf8()
        assertTrue(body, body.contains("\"data\":\"0xa8cf33a9" + "ab".repeat(32) + "\""))
    }

    @Test
    fun `persistently empty is an error, not false`() = runTest {
        repeat(4) { server.enqueue(result("0x")) }
        try {
            reader.isNullifierActive("0x" + "ab".repeat(32)); fail("expected ChainError")
        } catch (e: ChainError) {
            assertEquals(4, server.requestCount)
        }
    }

    @Test
    fun `getTreeStats decodes the six-word tuple`() = runTest {
        val words = listOf(
            "a", "14", "68fd0000", "000000000000000000000000453e8952000000000000000000000000001256a0", "1", "ab".repeat(32),
        ).joinToString("") { it.padStart(64, '0') }
        server.enqueue(result("0x$words"))
        val s = reader.treeStats(1)
        assertEquals(10, s.dbh.toInt())
        assertEquals(20, s.biomass.toInt())
        assertTrue(s.isAlive)
        assertEquals("0x" + "ab".repeat(32), s.spatialNullifier)
        assertTrue(server.takeRequest().body.readUtf8().contains("0x8103dddd" + "0".repeat(63) + "1"))
    }
}
