package org.biorig.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/** core/src/test/resources/golden/vectors.json, written by tools/gen_golden.py from the repository's own Python. */
object Golden {
    val root: JsonObject by lazy {
        val text = Golden::class.java.getResource("/golden/vectors.json")?.readText()
            ?: error("golden/vectors.json missing: run tools/gen_golden.py")
        Json.parseToJsonElement(text).jsonObject
    }

    fun obj(key: String): JsonObject = root.getValue(key).jsonObject
    fun rows(key: String): List<JsonObject> = root.getValue(key).jsonArray.map { it.jsonObject }
    fun strings(e: JsonElement): List<String> = (e as JsonArray).map { it.jsonPrimitive.content }

    fun JsonObject.d(key: String): Double = getValue(key).jsonPrimitive.double
    fun JsonObject.i(key: String): Int = getValue(key).jsonPrimitive.int
    fun JsonObject.l(key: String): Long = getValue(key).jsonPrimitive.long
    fun JsonObject.s(key: String): String = getValue(key).jsonPrimitive.content

    /** Relative comparison tight enough that any constant change shows, loose enough for a 1-ulp pow difference. */
    fun close(expected: Double, actual: Double, rel: Double = 1e-12): Boolean =
        expected == actual || Math.abs(expected - actual) <= rel * Math.max(Math.abs(expected), Math.abs(actual))
}
