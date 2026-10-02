package org.biorig.core

import org.biorig.core.Golden.close
import org.biorig.core.Golden.d
import org.biorig.core.Golden.i
import org.biorig.core.Golden.l
import org.biorig.core.Golden.s
import org.biorig.core.allometry.Allometry
import org.biorig.core.chain.Abi
import org.biorig.core.chain.Eip55
import org.biorig.core.chain.Hex
import org.biorig.core.chain.Nullifier
import org.biorig.core.geo.H3Index
import org.biorig.core.geo.Haversine
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** :core against the numbers the relay's own Python produces. Each test fails if a constant moves on either side. */
class GoldenVectorsTest {
    private val h3 = H3Index()
    private val nullifier = Nullifier(h3)

    @Test
    fun `allometry constants are the Python's`() {
        val c = Golden.obj("constants")
        assertEquals(c.d("chave_a"), Allometry.CHAVE_A, 0.0)
        assertEquals(c.d("chave_b"), Allometry.CHAVE_B, 0.0)
        assertEquals(c.d("height_a"), Allometry.HEIGHT_A, 0.0)
        assertEquals(c.d("height_b"), Allometry.HEIGHT_B, 0.0)
        assertEquals(c.d("height_c"), Allometry.HEIGHT_C, 0.0)
        assertEquals(c.d("default_wood_density"), Allometry.DEFAULT_WOOD_DENSITY, 0.0)
        assertEquals(c.d("carbon_fraction"), Allometry.CARBON_FRACTION, 0.0)
        assertEquals(c.d("co2_per_c"), Allometry.CO2_PER_C, 0.0)
        assertEquals(c.i("dbh_min_cm"), Allometry.DBH_MIN_CM)
        assertEquals(c.i("dbh_max_cm"), Allometry.DBH_MAX_CM)
        assertEquals(c.i("h3_resolution"), RelayDefaults.H3_RESOLUTION)
        assertEquals(c.s("salt_prefix"), RelayDefaults.SALT_PREFIX)
        assertEquals(c.d("earth_radius_m"), Haversine.EARTH_RADIUS_M, 0.0)
    }

    @Test
    fun `relay limits and the species default are relay config's`() {
        val l = Golden.obj("limits")
        assertEquals(l.d("max_accuracy_m"), RelayDefaults.MAX_ACCURACY_M, 0.0)
        assertEquals(l.d("collision_radius_m"), RelayDefaults.COLLISION_RADIUS_M, 0.0)
        assertEquals(l.l("fix_max_age_s"), RelayDefaults.FIX_MAX_AGE_S)
        assertEquals(l.l("fix_max_future_s"), RelayDefaults.FIX_MAX_FUTURE_S)
        assertEquals(l.i("max_trees_per_cell"), RelayDefaults.MAX_TREES_PER_CELL)
        assertEquals(l.i("per_session"), RelayDefaults.REGISTRATIONS_PER_SESSION)
        assertEquals(Golden.strings(Golden.root.getValue("default_species")), RelayDefaults.SPECIES_OPTIONS)
    }

    @Test
    fun `every DBH on the slider gives the Python's height, biomass, carbon, CO2e and mint figure`() {
        val rows = Golden.rows("allometry")
        assertEquals(119, rows.size)
        for (row in rows) {
            val e = Allometry.estimate(row.i("dbh_cm"))
            val at = "dbh ${row.i("dbh_cm")}"
            assertTrue("$at height ${e.heightM} vs ${row.d("height_m")}", close(row.d("height_m"), e.heightM))
            assertTrue("$at biomass ${e.biomassKg} vs ${row.d("biomass_kg")}", close(row.d("biomass_kg"), e.biomassKg))
            assertTrue("$at carbon", close(row.d("carbon_kg"), e.carbonKg))
            assertTrue("$at co2e", close(row.d("co2e_kg"), e.co2eKg))
            assertEquals(at, row.l("mint_biomass_kg"), e.mintBiomassKg)
        }
    }

    @Test
    fun `the pilot tree's 10 cm gives 19_9 kg and mints 20`() {
        val e = Allometry.estimate(10)
        assertEquals(19.9, e.biomassKg, 0.01)
        assertEquals(20L, e.mintBiomassKg)
    }

    @Test
    fun `wood density is applied as the Python applies it`() {
        for (row in Golden.rows("allometry_density")) {
            val b = Allometry.biomassKg(row.d("dbh_cm"), row.d("wood_density"))
            assertTrue("$row -> $b", close(row.d("biomass_kg"), b))
        }
    }

    @Test
    fun `H3 res-12 cells, k-rings and neighbourhoods match the relay's`() {
        for (row in Golden.rows("cells")) {
            val cell = h3.cellFor(row.d("lat"), row.d("lng"))
            assertEquals(row.s("name"), row.s("cell"), cell)
            assertEquals(row.i("resolution"), h3.resolution(cell))
            assertEquals("${row.s("name")} ring_k", row.i("ring_k"), h3.ringK(cell))
            assertEquals(Golden.strings(row.getValue("neighbourhood")), h3.neighbourhood(cell).sorted())
        }
    }

    @Test
    fun `salts, preimages and nullifiers match dashboard h3_nullifier`() {
        val rows = Golden.rows("nullifiers")
        assertEquals(18, rows.size)
        for (row in rows) {
            val d = nullifier.forOrdinal(row.s("cell"), row.i("ordinal"))
            assertEquals(row.s("salt"), d.salt)
            assertEquals(row.s("preimage"), Hex.prefixed(d.preimage))
            assertEquals(row.s("nullifier"), d.nullifierHex)
            assertTrue(nullifier.jobIsConsistent(row.s("cell"), row.i("ordinal"), row.s("salt"), row.s("nullifier")))
        }
        val legacy = Golden.obj("legacy_pilot_nullifier")
        assertEquals(legacy.s("nullifier"), nullifier.fromCell(legacy.s("cell"), legacy.s("salt")).nullifierHex)
    }

    @Test
    fun `a job whose nullifier is not its cell and ordinal's is caught`() {
        val row = Golden.rows("nullifiers")[1]
        val other = Golden.rows("nullifiers")[0]
        assertTrue(!nullifier.jobIsConsistent(row.s("cell"), row.i("ordinal"), row.s("salt"), other.s("nullifier")))
        assertTrue(!nullifier.jobIsConsistent(row.s("cell"), row.i("ordinal") + 1, row.s("salt"), row.s("nullifier")))
    }

    @Test
    fun `haversine is relay plot_index's`() {
        for (row in Golden.rows("haversine")) {
            val m = Haversine.metres(row.d("lat1"), row.d("lng1"), row.d("lat2"), row.d("lng2"))
            assertEquals(row.toString(), row.d("metres"), m, 1e-9)
        }
    }

    @Test
    fun `EIP-55 checksums are eth_utils'`() {
        for (row in Golden.rows("eip55")) {
            assertEquals(row.s("checksummed"), Eip55.checksum(row.s("lower")))
            assertEquals(Eip55.Check.Valid(row.s("checksummed")), Eip55.validate(row.s("checksummed")))
        }
    }

    @Test
    fun `function selectors are keccak of the ABI signature`() {
        for (row in Golden.rows("selectors")) assertEquals(row.s("signature"), row.s("selector"), Abi.selector(row.s("signature")))
    }
}
