package org.biorig.core.photo

import org.biorig.core.RelayDefaults
import org.biorig.core.geo.Fix
import org.biorig.core.geo.Haversine
import kotlin.math.abs

/**
 * Step 2's "photo checks out" line. The photo never leaves the phone, so this is the app's own sanity check before
 * its SHA-256 is put in the registration: the picture was taken at this tree, around the time of this fix.
 */
object PhotoCheck {
    const val MAX_CLOCK_SKEW_S = 2L // EXIF DateTimeOriginal has whole-second resolution
    const val MAX_DISTANCE_M = 3.0

    sealed interface Verdict {
        data object Ok : Verdict
        data class TimeMismatch(val fileTimeS: Long, val exifTimeS: Long) : Verdict
        data class TooFarFromFix(val distanceM: Double) : Verdict
        /** Taken so long after the fix that the fix would be stale before it is sent. */
        data class OutsideFixWindow(val secondsAfterFix: Long) : Verdict
        data object NoExifTime : Verdict
    }

    fun judge(fix: Fix, fileTimeS: Long, exifTimeS: Long?, exifLat: Double?, exifLng: Double?): Verdict {
        if (exifTimeS == null) return Verdict.NoExifTime
        if (abs(fileTimeS - exifTimeS) > MAX_CLOCK_SKEW_S) return Verdict.TimeMismatch(fileTimeS, exifTimeS)
        val after = exifTimeS - fix.capturedAt
        if (after < -RelayDefaults.FIX_MAX_FUTURE_S || after > RelayDefaults.FIX_MAX_AGE_S) {
            return Verdict.OutsideFixWindow(after)
        }
        if (exifLat != null && exifLng != null) {
            val d = Haversine.metres(fix.lat, fix.lng, exifLat, exifLng)
            if (d > MAX_DISTANCE_M) return Verdict.TooFarFromFix(d)
        }
        return Verdict.Ok
    }
}
