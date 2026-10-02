package org.biorig.app.device

import android.annotation.SuppressLint
import android.content.Context
import android.location.GnssStatus
import android.location.LocationManager
import android.os.Handler
import android.os.Looper
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.tasks.await
import org.biorig.core.geo.Fix

/**
 * Fused location at high accuracy. The fix's own timestamp and its 68% accuracy radius are what go to the relay;
 * the 30 m gate in :core decides whether it may.
 */
class FixSource(context: Context) {
    private val fused = LocationServices.getFusedLocationProviderClient(context)
    private val lm = context.getSystemService(LocationManager::class.java)
    private val _satellites = MutableStateFlow<Int?>(null)
    /** Satellites used in the current GNSS fix, for the "3D fix · 9 satellites" line. */
    val satellites: StateFlow<Int?> = _satellites

    private val gnss = object : GnssStatus.Callback() {
        override fun onSatelliteStatusChanged(status: GnssStatus) {
            _satellites.value = (0 until status.satelliteCount).count { status.usedInFix(it) }
        }
    }

    @SuppressLint("MissingPermission") // the caller asks for ACCESS_FINE_LOCATION first
    fun startSatellites() {
        runCatching { lm.registerGnssStatusCallback(gnss, Handler(Looper.getMainLooper())) }
    }

    fun stopSatellites() {
        lm.unregisterGnssStatusCallback(gnss)
    }

    @SuppressLint("MissingPermission")
    suspend fun current(): Fix? {
        val cts = CancellationTokenSource()
        val loc = fused.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, cts.token).await() ?: return null
        if (!loc.hasAccuracy()) return null
        return Fix(loc.latitude, loc.longitude, loc.accuracy.toDouble(), loc.time / 1000)
    }
}
