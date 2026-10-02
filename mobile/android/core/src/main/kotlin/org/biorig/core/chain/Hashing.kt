package org.biorig.core.chain

import org.bouncycastle.jcajce.provider.digest.Keccak
import java.io.File
import java.io.InputStream
import java.security.MessageDigest

object Hex {
    private val DIGITS = "0123456789abcdef".toCharArray()

    fun encode(bytes: ByteArray): String {
        val out = CharArray(bytes.size * 2)
        bytes.forEachIndexed { i, b ->
            out[2 * i] = DIGITS[(b.toInt() shr 4) and 0xf]
            out[2 * i + 1] = DIGITS[b.toInt() and 0xf]
        }
        return String(out)
    }

    fun prefixed(bytes: ByteArray): String = "0x" + encode(bytes)

    fun decode(hex: String): ByteArray {
        val s = hex.removePrefix("0x").removePrefix("0X")
        require(s.length % 2 == 0) { "odd-length hex" }
        return ByteArray(s.length / 2) { i ->
            val hi = Character.digit(s[2 * i], 16)
            val lo = Character.digit(s[2 * i + 1], 16)
            require(hi >= 0 && lo >= 0) { "not hex: $hex" }
            ((hi shl 4) or lo).toByte()
        }
    }
}

/** Ethereum's keccak256 (the pre-NIST padding), via Bouncy Castle rather than a hand-rolled permutation. */
object Keccak256 {
    fun digest(input: ByteArray): ByteArray = Keccak.Digest256().digest(input)
    fun digest(text: String): ByteArray = digest(text.toByteArray(Charsets.UTF_8))
}

/** The photo digest the relay accepts as `photo_sha256`: 64 lowercase hex characters. The image itself stays here. */
object Sha256 {
    fun hex(input: InputStream): String {
        val md = MessageDigest.getInstance("SHA-256")
        val buf = ByteArray(64 * 1024)
        while (true) {
            val n = input.read(buf)
            if (n < 0) break
            md.update(buf, 0, n)
        }
        return Hex.encode(md.digest())
    }

    fun hex(file: File): String = file.inputStream().use(::hex)
    fun hex(bytes: ByteArray): String = Hex.encode(MessageDigest.getInstance("SHA-256").digest(bytes))
}

/** EIP-55 mixed-case checksums, the rule relay/validate.py applies to `planter_address`. */
object Eip55 {
    private val SHAPE = Regex("^0x[0-9a-fA-F]{40}$")

    fun checksum(address: String): String {
        require(SHAPE.matches(address)) { "not a 0x-prefixed 20-byte hex address" }
        val lower = address.substring(2).lowercase()
        val hash = Hex.encode(Keccak256.digest(lower))
        return "0x" + lower.mapIndexed { i, c -> if (c.isLetter() && Character.digit(hash[i], 16) >= 8) c.uppercaseChar() else c }
            .joinToString("")
    }

    sealed interface Check {
        data class Valid(val checksummed: String) : Check
        data class Invalid(val reason: String) : Check
    }

    /** The relay's acceptance rule: all-lower and all-upper pass unchecked, mixed case must match its checksum. */
    fun validate(input: String): Check {
        val address = input.trim()
        if (!SHAPE.matches(address)) return Check.Invalid("An address is 0x followed by 40 hex characters.")
        val body = address.substring(2)
        if (body != body.lowercase() && body != body.uppercase() && checksum(address) != address) {
            return Check.Invalid("This address fails its checksum: a character was mistyped.")
        }
        if (body.all { it == '0' }) return Check.Invalid("The zero address cannot hold a tree.")
        return Check.Valid(checksum(address))
    }
}
