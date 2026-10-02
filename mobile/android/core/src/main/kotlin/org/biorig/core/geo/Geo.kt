package org.biorig.core.geo

import com.uber.h3core.H3Core
import com.uber.h3core.util.LatLng
import org.biorig.core.RelayDefaults
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** relay/plot_index.py's haversine_m, the distance the relay's 20 m collision rule is judged in. */
object Haversine {
    const val EARTH_RADIUS_M = 6_371_008.8 // IUGG mean radius

    fun metres(lat1: Double, lng1: Double, lat2: Double, lng2: Double): Double {
        val p1 = Math.toRadians(lat1)
        val p2 = Math.toRadians(lat2)
        val dp = p2 - p1
        val dl = Math.toRadians(lng2 - lng1)
        val a = sin(dp / 2).let { it * it } + cos(p1) * cos(p2) * sin(dl / 2).let { it * it }
        return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(a)))
    }
}

/**
 * H3 through Uber's own library (com.uber:h3), the same C core the relay's Python h3 binds, so the phone and the relay
 * cannot disagree about which cell a fix falls in. The cell is computed on the phone for the pre-check only; it is
 * never sent in a registration (the relay refuses `cell` with forbidden_field).
 */
class H3Index(private val core: H3Core = H3Core.newInstance()) {
    fun cellFor(lat: Double, lng: Double, resolution: Int = RelayDefaults.H3_RESOLUTION): String {
        require(lat in -90.0..90.0) { "latitude $lat out of range [-90, 90]" }
        require(lng in -180.0..180.0) { "longitude $lng out of range [-180, 180]" }
        require(resolution in 0..15) { "H3 resolution $resolution out of range [0, 15]" }
        return core.latLngToCellAddress(lat, lng, resolution)
    }

    fun isValidCell(cell: String): Boolean = core.isValidCell(cell)

    fun resolution(cell: String): Int = core.getResolution(cell)

    fun cellIndex(cell: String): Long = core.stringToH3(cell)

    fun centre(cell: String): LatLng = core.cellToLatLng(cell)

    fun gridDisk(cell: String, k: Int): List<String> = core.gridDisk(cell, k)

    /** relay/plot_index.py's ring_k: the smallest k whose disk holds every cell a point within radiusM can land in. */
    fun ringK(cell: String, radiusM: Double = RelayDefaults.COLLISION_RADIUS_M): Int {
        val c = core.cellToLatLng(cell)
        val e = core.cellToBoundary(cell).maxOf { Haversine.metres(c.lat, c.lng, it.lat, it.lng) }
        val reach = 2 * e * 1.1 + radiusM
        val spacing = 1.5 * e / 1.1
        return max(1, floor(reach / spacing).toInt())
    }

    /** The cells the relay's collision test searches for a fix in [cell]. */
    fun neighbourhood(cell: String, radiusM: Double = RelayDefaults.COLLISION_RADIUS_M): List<String> =
        gridDisk(cell, ringK(cell, radiusM))
}

/** A position fix as the phone took it. [capturedAt] is Unix seconds, UTC. */
data class Fix(val lat: Double, val lng: Double, val accuracyM: Double, val capturedAt: Long)

sealed interface FixVerdict {
    data class Usable(val fix: Fix, val cell: String) : FixVerdict
    /** Worse than the relay's MAX_ACCURACY_M: refused, never rounded (the relay's R4). */
    data class TooCoarse(val accuracyM: Double, val maxAccuracyM: Double) : FixVerdict
    data class Stale(val ageS: Long, val maxAgeS: Long) : FixVerdict
    data object InFuture : FixVerdict
    /** 0,0 or outside the coordinate ranges: a failed fix, not a place. */
    data object NotAPlace : FixVerdict
}

/**
 * Step 1's gate. It applies relay/validate.py's own fix rules before the planter walks on, so the button that says
 * "Use this fix" is only enabled for a fix the relay would accept.
 */
class FixGate(
    private val h3: H3Index,
    private val maxAccuracyM: Double = RelayDefaults.MAX_ACCURACY_M,
    private val maxAgeS: Long = RelayDefaults.FIX_MAX_AGE_S,
    private val maxFutureS: Long = RelayDefaults.FIX_MAX_FUTURE_S,
) {
    fun judge(fix: Fix, nowS: Long): FixVerdict {
        if (fix.lat !in -90.0..90.0 || fix.lng !in -180.0..180.0 || (fix.lat == 0.0 && fix.lng == 0.0)) {
            return FixVerdict.NotAPlace
        }
        if (!(fix.accuracyM > 0)) return FixVerdict.NotAPlace
        if (fix.accuracyM > maxAccuracyM) return FixVerdict.TooCoarse(fix.accuracyM, maxAccuracyM)
        if (fix.capturedAt > nowS + maxFutureS) return FixVerdict.InFuture
        if (fix.capturedAt < nowS - maxAgeS) return FixVerdict.Stale(nowS - fix.capturedAt, maxAgeS)
        return FixVerdict.Usable(fix, h3.cellFor(fix.lat, fix.lng))
    }
}

/** A tree this phone has already captured, for the local half of the collision pre-check. */
data class KnownTree(val submissionId: String, val lat: Double, val lng: Double)

sealed interface CollisionVerdict {
    data object Clear : CollisionVerdict
    /** Within the radius of a tree this phone already captured: the relay would answer `same_tree`. */
    data class SameTreeAsOwn(val submissionId: String, val distanceM: Double) : CollisionVerdict
    /** The relay's plot index says the neighbourhood holds active trees. It does not publish their coordinates, so
     * the relay makes the call in metres at submission; the planter is warned now. */
    data class NeighbourhoodOccupied(val neighbourhoodActive: Int) : CollisionVerdict
    data class CellFull(val active: Int, val max: Int) : CollisionVerdict
}

object CollisionCheck {
    fun nearestOwn(fix: Fix, own: List<KnownTree>): Pair<KnownTree, Double>? =
        own.map { it to Haversine.metres(fix.lat, fix.lng, it.lat, it.lng) }.minByOrNull { it.second }

    fun judge(
        fix: Fix,
        own: List<KnownTree>,
        cellActive: Int?,
        cellFull: Boolean?,
        neighbourhoodActive: Int?,
        maxTreesPerCell: Int = RelayDefaults.MAX_TREES_PER_CELL,
        radiusM: Double = RelayDefaults.COLLISION_RADIUS_M,
    ): CollisionVerdict {
        nearestOwn(fix, own)?.let { (tree, d) ->
            if (d <= radiusM) return CollisionVerdict.SameTreeAsOwn(tree.submissionId, d)
        }
        if (cellFull == true) return CollisionVerdict.CellFull(cellActive ?: maxTreesPerCell, maxTreesPerCell)
        if ((neighbourhoodActive ?: 0) > 0) return CollisionVerdict.NeighbourhoodOccupied(neighbourhoodActive!!)
        return CollisionVerdict.Clear
    }
}
