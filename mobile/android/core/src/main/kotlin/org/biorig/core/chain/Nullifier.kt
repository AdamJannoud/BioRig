package org.biorig.core.chain

import org.biorig.core.RelayDefaults
import org.biorig.core.geo.H3Index
import java.nio.ByteBuffer

/**
 * The plot identity, as the relay derives it (relay/plot_index.py, dashboard/h3_nullifier.py):
 *
 *     salt      = "biorig:v1:" + cell + ":" + tree_ordinal
 *     nullifier = keccak256(uint64(cell) ++ utf8(salt))
 *
 * The phone never sends either. It re-derives them from a job the relay returns, to check that the identity the
 * relay chose is the pure function of (cell, ordinal) the contract says it is, and to read the chain for it.
 */
class Nullifier(private val h3: H3Index) {
    data class Derivation(val cell: String, val salt: String, val preimage: ByteArray, val nullifier: ByteArray) {
        val nullifierHex: String get() = Hex.prefixed(nullifier)
    }

    fun salt(cell: String, ordinal: Int): String {
        require(h3.isValidCell(cell)) { "'$cell' is not a valid H3 cell" }
        require(ordinal >= 0) { "tree ordinal must be non-negative, got $ordinal" }
        return "${RelayDefaults.SALT_PREFIX}$cell:$ordinal"
    }

    fun fromCell(cell: String, salt: String): Derivation {
        require(h3.isValidCell(cell)) { "'$cell' is not a valid H3 cell" }
        require(salt.isNotEmpty()) { "salt must be non-empty" }
        val saltBytes = salt.toByteArray(Charsets.UTF_8)
        val preimage = ByteBuffer.allocate(8 + saltBytes.size).putLong(h3.cellIndex(cell)).put(saltBytes).array()
        val digest = Keccak256.digest(preimage)
        check(digest.size == 32 && digest.any { it.toInt() != 0 }) { "nullifier must be a non-zero bytes32" }
        return Derivation(cell, salt, preimage, digest)
    }

    fun forOrdinal(cell: String, ordinal: Int): Derivation = fromCell(cell, salt(cell, ordinal))

    /** True when a job's salt and nullifier are what (cell, tree_ordinal) derive to. Seeded rows keep `plot-1`. */
    fun jobIsConsistent(cell: String, ordinal: Int, salt: String, nullifierHex: String): Boolean {
        val expectedSalt = if (salt == "plot-1") salt else salt(cell, ordinal)
        if (salt != expectedSalt) return false
        return fromCell(cell, salt).nullifierHex == nullifierHex.lowercase()
    }
}
