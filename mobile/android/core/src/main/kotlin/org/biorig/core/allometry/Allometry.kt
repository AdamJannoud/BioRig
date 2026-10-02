package org.biorig.core.allometry

import kotlin.math.pow

/**
 * A 1:1 port of dashboard/allometry.py, the estimate relay/validate.py recomputes and compares the client's against.
 *
 *     AGB (kg) = 0.0673 * (rho * D^2 * H) ^ 0.976        Chave et al. 2014, pantropical model (eq. 4)
 *     H (m)    = 1.3 + 0.55 * D ^ 0.9                     height from diameter
 *
 * Carbon is 47% of dry biomass and CO2e is carbon times 44/12. A constant or a rounding step that differs from the
 * Python makes every submission come back `estimate_mismatch`, so AllometryTest holds this against vectors the
 * Python itself produced.
 */
object Allometry {
    const val CHAVE_A = 0.0673
    const val CHAVE_B = 0.976
    const val HEIGHT_A = 1.3
    const val HEIGHT_B = 0.55
    const val HEIGHT_C = 0.9
    const val DEFAULT_WOOD_DENSITY = 0.6 // g/cm3
    const val CARBON_FRACTION = 0.47
    const val CO2_PER_C = 44.0 / 12.0
    const val DBH_MIN_CM = 2
    const val DBH_MAX_CM = 120 // the planter's slider range

    fun heightM(dbhCm: Double): Double {
        require(dbhCm > 0) { "trunk diameter must be positive, got $dbhCm cm" }
        return HEIGHT_A + HEIGHT_B * dbhCm.pow(HEIGHT_C)
    }

    fun biomassKg(dbhCm: Double, woodDensity: Double = DEFAULT_WOOD_DENSITY, height: Double? = null): Double {
        require(dbhCm > 0) { "trunk diameter must be positive, got $dbhCm cm" }
        require(woodDensity > 0) { "wood density must be positive, got $woodDensity g/cm3" }
        val h = height ?: heightM(dbhCm)
        return CHAVE_A * (woodDensity * dbhCm.pow(2) * h).pow(CHAVE_B)
    }

    fun carbonKg(biomass: Double): Double = biomass * CARBON_FRACTION

    fun co2eKg(biomass: Double): Double = carbonKg(biomass) * CO2_PER_C

    fun estimate(dbhCm: Int, woodDensity: Double = DEFAULT_WOOD_DENSITY): Estimate {
        val b = biomassKg(dbhCm.toDouble(), woodDensity)
        return Estimate(dbhCm, heightM(dbhCm.toDouble()), b, carbonKg(b), co2eKg(b))
    }

    fun inSliderRange(dbhCm: Int): Boolean = dbhCm in DBH_MIN_CM..DBH_MAX_CM
}

data class Estimate(
    val dbhCm: Int,
    val heightM: Double,
    val biomassKg: Double,
    val carbonKg: Double,
    val co2eKg: Double,
) {
    /** mintTree's initialBiomass, whole kilograms. Python's round() is half-to-even, and so is rint. */
    val mintBiomassKg: Long get() = Math.rint(biomassKg).toLong()
}
