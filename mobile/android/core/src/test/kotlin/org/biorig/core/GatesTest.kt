package org.biorig.core

import org.biorig.core.Golden.d
import org.biorig.core.chain.Eip55
import org.biorig.core.geo.CollisionCheck
import org.biorig.core.geo.CollisionVerdict
import org.biorig.core.geo.Fix
import org.biorig.core.geo.FixGate
import org.biorig.core.geo.FixVerdict
import org.biorig.core.geo.H3Index
import org.biorig.core.geo.KnownTree
import org.biorig.core.photo.PhotoCheck
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The 30 m accuracy gate, the fix age window and the 20 m collision rule, at their boundaries. */
class GatesTest {
    private val gate = FixGate(H3Index())
    private val now = 1_800_000_000L
    private fun fix(acc: Double, at: Long = now, lat: Double = 6.428093, lng: Double = 3.421974) = Fix(lat, lng, acc, at)

    @Test
    fun `accuracy exactly 30 m passes, anything worse is refused not rounded`() {
        assertTrue(gate.judge(fix(30.0), now) is FixVerdict.Usable)
        assertEquals(FixVerdict.TooCoarse(30.000001, 30.0), gate.judge(fix(30.000001), now))
        assertEquals(FixVerdict.TooCoarse(62.0, 30.0), gate.judge(fix(62.0), now))
        assertEquals(FixVerdict.NotAPlace, gate.judge(fix(0.0), now))
    }

    @Test
    fun `a usable fix carries its res-12 cell`() {
        val v = gate.judge(fix(4.2), now) as FixVerdict.Usable
        assertEquals(H3Index().cellFor(6.428093, 3.421974), v.cell)
        assertEquals(12, H3Index().resolution(v.cell))
    }

    @Test
    fun `fix age window is the relay's 600 s back and 60 s ahead`() {
        assertTrue(gate.judge(fix(5.0, now - 600), now) is FixVerdict.Usable)
        assertEquals(FixVerdict.Stale(601, 600), gate.judge(fix(5.0, now - 601), now))
        assertTrue(gate.judge(fix(5.0, now + 60), now) is FixVerdict.Usable)
        assertEquals(FixVerdict.InFuture, gate.judge(fix(5.0, now + 61), now))
    }

    @Test
    fun `0,0 and out-of-range coordinates are not a place`() {
        assertEquals(FixVerdict.NotAPlace, gate.judge(fix(5.0, lat = 0.0, lng = 0.0), now))
        assertEquals(FixVerdict.NotAPlace, gate.judge(fix(5.0, lat = 90.5), now))
        assertEquals(FixVerdict.NotAPlace, gate.judge(fix(5.0, lng = -180.5), now))
    }

    @Test
    fun `own trees within 20 m are the same tree, beyond are clear (golden boundary points)`() {
        val pairs = Golden.rows("haversine")
        val origin = fix(4.0, lat = pairs[1].d("lat1"), lng = pairs[1].d("lng1"))
        fun at(i: Int) = listOf(KnownTree("t$i", pairs[i].d("lat2"), pairs[i].d("lng2")))
        // pairs[1..3] sit 19.9 m, 20.000027 m and 20.1 m north of the origin, by relay plot_index.haversine_m
        assertTrue(CollisionCheck.judge(origin, at(1), 0, false, 0) is CollisionVerdict.SameTreeAsOwn)
        assertEquals(CollisionVerdict.Clear, CollisionCheck.judge(origin, at(2), 0, false, 0))
        assertEquals(CollisionVerdict.Clear, CollisionCheck.judge(origin, at(3), 0, false, 0))
        val exactly20 = KnownTree("e", origin.lat + 20.0 / (Math.toRadians(1.0) * 6_371_008.8), origin.lng)
        assertTrue(CollisionCheck.judge(origin, listOf(exactly20), 0, false, 0) is CollisionVerdict.SameTreeAsOwn)
    }

    @Test
    fun `the relay's occupancy decides the rest`() {
        val f = fix(4.0)
        assertEquals(CollisionVerdict.CellFull(4, 4), CollisionCheck.judge(f, emptyList(), 4, true, 4))
        assertEquals(CollisionVerdict.NeighbourhoodOccupied(2), CollisionCheck.judge(f, emptyList(), 0, false, 2))
        assertEquals(CollisionVerdict.Clear, CollisionCheck.judge(f, emptyList(), null, null, null))
    }

    @Test
    fun `photo check - EXIF time, fix window and distance`() {
        val f = fix(4.0, at = now)
        assertEquals(PhotoCheck.Verdict.Ok, PhotoCheck.judge(f, now + 111, now + 111, f.lat, f.lng))
        assertTrue(PhotoCheck.judge(f, now + 120, now + 111, null, null) is PhotoCheck.Verdict.TimeMismatch)
        assertTrue(PhotoCheck.judge(f, now + 700, now + 700, null, null) is PhotoCheck.Verdict.OutsideFixWindow)
        assertTrue(PhotoCheck.judge(f, now, now, f.lat + 0.0001, f.lng) is PhotoCheck.Verdict.TooFarFromFix)
        assertEquals(PhotoCheck.Verdict.NoExifTime, PhotoCheck.judge(f, now, null, null, null))
    }

    @Test
    fun `planter address follows the relay's EIP-55 acceptance rule`() {
        val good = "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
        assertEquals(Eip55.Check.Valid(good), Eip55.validate(good))
        assertEquals(Eip55.Check.Valid(good), Eip55.validate(good.lowercase()))
        assertTrue(Eip55.validate("0xd314e37FD8538fe66231EE670B74C9428d03feEa") is Eip55.Check.Invalid)
        assertTrue(Eip55.validate("0x" + "0".repeat(40)) is Eip55.Check.Invalid)
        assertTrue(Eip55.validate("0x1234") is Eip55.Check.Invalid)
    }
}
