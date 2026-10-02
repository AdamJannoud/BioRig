package org.biorig.core

/**
 * The relay's defaults, mirrored. relay/config.py is the source; GoldenVectorsTest fails if a value here drifts from
 * what tools/gen_golden.py reads out of it.
 */
object RelayDefaults {
    /**
     * The species picker's options. Defaults to the relay's own default allowlist (`RelayConfig.species`), which an
     * operator widens with RELAY_SPECIES. When a relay refuses with `species_not_allowed` the app offers the
     * `error.allowed` list it sent back instead of this one.
     */
    val SPECIES_OPTIONS: List<String> = listOf("unspecified")

    const val H3_RESOLUTION = 12
    const val MAX_ACCURACY_M = 30.0
    const val COLLISION_RADIUS_M = 20.0
    const val FIX_MAX_AGE_S = 600L
    const val FIX_MAX_FUTURE_S = 60L
    const val MAX_TREES_PER_CELL = 4
    const val REGISTRATIONS_PER_SESSION = 3
    const val SALT_PREFIX = "biorig:v1:"

    /** Transient failures (network, 5xx, 429) a queued capture survives before it asks the planter. */
    const val MAX_SEND_ATTEMPTS = 4
}
