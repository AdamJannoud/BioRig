package org.biorig.core.chain

import kotlinx.coroutines.delay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.math.BigInteger

/** The three calls the status screen makes, ABI-encoded by hand: there is nothing here that needs a Web3 stack. */
object Abi {
    const val IS_NULLIFIER_ACTIVE = "isNullifierActive(bytes32)"
    const val GET_TREE_STATS = "getTreeStats(uint256)"
    const val OWNER_OF = "ownerOf(uint256)"

    fun selector(signature: String): String = Hex.prefixed(Keccak256.digest(signature).copyOfRange(0, 4))

    fun word(value: BigInteger): String {
        require(value.signum() >= 0) { "uint256 must be non-negative" }
        return value.toString(16).padStart(64, '0').also { require(it.length == 64) { "value exceeds 256 bits" } }
    }

    fun isNullifierActive(nullifierHex: String): String {
        val n = nullifierHex.removePrefix("0x").lowercase()
        require(n.length == 64) { "nullifier must be 32 bytes" }
        return selector(IS_NULLIFIER_ACTIVE) + n
    }

    fun getTreeStats(tokenId: Long): String = selector(GET_TREE_STATS) + word(BigInteger.valueOf(tokenId))
    fun ownerOf(tokenId: Long): String = selector(OWNER_OF) + word(BigInteger.valueOf(tokenId))

    fun words(data: String): List<String> {
        val s = data.removePrefix("0x")
        require(s.length % 64 == 0) { "return data is not whole 32-byte words" }
        return s.chunked(64)
    }

    fun address(word: String): String = Eip55.checksum("0x" + word.takeLast(40))
}

/** BioRigCoreV5's TreeStats tuple: (uint96 dbh, uint96 biomass, uint64 lastUpdated, address tba, bool alive, bytes32). */
data class TreeStats(
    val dbh: BigInteger,
    val biomass: BigInteger,
    val lastUpdated: Long,
    val tbaAddress: String,
    val isAlive: Boolean,
    val spatialNullifier: String,
) {
    companion object {
        fun decode(data: String): TreeStats {
            val w = Abi.words(data)
            require(w.size == 6) { "getTreeStats returned ${w.size} words, expected 6" }
            return TreeStats(
                BigInteger(w[0], 16), BigInteger(w[1], 16), BigInteger(w[2], 16).toLong(),
                Abi.address(w[3]), BigInteger(w[4], 16) != BigInteger.ZERO, "0x" + w[5],
            )
        }
    }
}

class ChainError(message: String) : IOException(message)

/**
 * A minimal JSON-RPC reader over the phone's own connection. Public Celo nodes intermittently answer an eth_call or a
 * log query with an empty result for data they hold (the dashboard's find_mint learned this), so an empty `0x` is
 * asked again, a bounded number of times, rather than believed on the first answer.
 */
class ChainReader(
    private val rpcUrl: String,
    private val proxyAddress: String,
    private val http: OkHttpClient = OkHttpClient(),
    private val emptyRetries: Int = 3,
    private val retryDelayMs: Long = 750,
) {
    private val json = Json { ignoreUnknownKeys = true }
    private var nextId = 1

    suspend fun blockNumber(): Long = BigInteger(rpc("eth_blockNumber", emptyList()).removePrefix("0x"), 16).toLong()

    suspend fun isNullifierActive(nullifierHex: String): Boolean =
        BigInteger(call(Abi.isNullifierActive(nullifierHex)).removePrefix("0x"), 16) != BigInteger.ZERO

    suspend fun treeStats(tokenId: Long): TreeStats = TreeStats.decode(call(Abi.getTreeStats(tokenId)))

    suspend fun ownerOf(tokenId: Long): String = Abi.address(Abi.words(call(Abi.ownerOf(tokenId))).single())

    private suspend fun call(data: String): String {
        var last = "0x"
        repeat(emptyRetries + 1) { attempt ->
            val params = listOf(
                buildJsonObject { put("to", proxyAddress); put("data", data) },
                JsonPrimitive("latest"),
            )
            last = rpc("eth_call", params)
            if (last != "0x" && last.isNotEmpty()) return last
            if (attempt < emptyRetries) delay(retryDelayMs)
        }
        throw ChainError("eth_call returned no data after ${emptyRetries + 1} attempts")
    }

    private suspend fun rpc(method: String, params: List<kotlinx.serialization.json.JsonElement>): String {
        val body = buildJsonObject {
            put("jsonrpc", "2.0")
            put("id", nextId++)
            put("method", method)
            put("params", buildJsonArray { params.forEach { add(it) } })
        }.toString()
        val request = Request.Builder().url(rpcUrl)
            .post(body.toRequestBody("application/json".toMediaType())).build()
        val text = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            http.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) throw ChainError("$method: HTTP ${resp.code}")
                resp.body?.string() ?: throw ChainError("$method: empty response")
            }
        }
        val obj: JsonObject = json.parseToJsonElement(text).jsonObject
        obj["error"]?.let { throw ChainError("$method: ${it.jsonObject["message"]?.jsonPrimitive?.contentOrNull ?: it}") }
        return obj["result"]?.jsonPrimitive?.contentOrNull ?: throw ChainError("$method: no result")
    }
}
